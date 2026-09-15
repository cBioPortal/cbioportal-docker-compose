#!/usr/bin/env python3
"""Verify every study admitted to a running WSI stack.

The per-study verifier is intentionally strict about one study at a time. This
entry point supplies the missing catalog boundary: the portal's complete study
set must match an explicit release manifest, and every listed study must have
its own source snapshot, WSI hierarchy, clinical WSI counts, and real pixel
smoke checks.

The manifest is host-local and must not contain credentials. Accepted releases
use the version 2 schema in ``release-manifest.schema.json`` and pin every code,
image, data-producer, database, and per-study snapshot identity.

The referenced snapshot must contain a valid ``wsi_snapshot_manifest.json``
with non-zero association, servable, and patient counts and
``incomplete_asset_count=0``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class VerificationError(RuntimeError):
    """A user-actionable stack verification failure."""


ROOT_DIR = Path(__file__).resolve().parent
PER_STUDY_VERIFIER = ROOT_DIR / "verify-study-load.py"
REQUIRED_SOURCE_PREFIXES = {
    "s3://pathology/",
    "s3://mskmind-bkt/",
    "s3://ocra/",
}
REQUIRED_THUMBNAIL_PREFIXES = {"s3://mskmind-bkt/wsi-thumbnails/"}
WSI_SERVING_CONTRACT_VERSION = "wsi-serving-v2"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_text(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VerificationError(f"{context} needs non-empty {key}")
    return value.strip()


def _validate_release_identity(value: dict[str, Any]) -> dict[str, str]:
    if value.get("version") != 2:
        raise VerificationError("immutable stack release manifest must have version 2")
    release_id = _required_text(value, "release_id", "stack release manifest")
    _required_text(value, "created_at_utc", "stack release manifest")
    components = value.get("components")
    if not isinstance(components, dict):
        raise VerificationError("stack release manifest needs components")
    for name in ("frontend", "backend", "tile_server", "pdm", "clickhouse"):
        if not isinstance(components.get(name), dict):
            raise VerificationError(f"stack release manifest needs component {name}")
    for name in ("frontend", "backend", "tile_server", "pdm"):
        sha = _required_text(components[name], "git_sha", f"component {name}")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise VerificationError(f"component {name} git_sha must be a full commit")
    frontend_url = _required_text(components["frontend"], "artifact_url", "frontend")
    parsed_frontend = urllib.parse.urlparse(frontend_url)
    if parsed_frontend.scheme != "https" or not parsed_frontend.netloc:
        raise VerificationError("frontend artifact_url must be an absolute HTTPS URL")
    if "deploy-preview" in parsed_frontend.netloc:
        raise VerificationError("frontend artifact_url must not be a mutable PR preview alias")
    for name in ("backend", "tile_server"):
        digest = _required_text(components[name], "image_digest", f"component {name}")
        if not re.search(r"@sha256:[0-9a-fA-F]{64}$", digest):
            raise VerificationError(f"component {name} image_digest must pin a sha256 digest")
    pdm = components["pdm"]
    if _required_text(pdm, "contract_version", "component pdm") != WSI_SERVING_CONTRACT_VERSION:
        raise VerificationError("PDM contract version is not supported by this verifier")
    _required_text(pdm, "databricks_job_run_id", "component pdm")
    clickhouse = components["clickhouse"]
    _required_text(clickhouse, "schema_version", "component clickhouse")
    _required_text(clickhouse, "source_database", "component clickhouse")
    if set(value.get("allowed_source_prefixes") or []) != REQUIRED_SOURCE_PREFIXES:
        raise VerificationError("release source-prefix policy differs from the approved policy")
    if set(value.get("allowed_thumbnail_prefixes") or []) != REQUIRED_THUMBNAIL_PREFIXES:
        raise VerificationError("release thumbnail-prefix policy differs from the approved policy")
    return {"release_id": release_id, "frontend_artifact_url": frontend_url}


def _validate_live_release_identity(
    portal_url: str, cookie: str, manifest: dict[str, Any]
) -> None:
    """Prove the running portal and tile service match the immutable manifest."""
    components = manifest["components"]
    release_id = manifest["release_id"]
    config = _request_json(f"{portal_url.rstrip('/')}/config_service", cookie)
    if not isinstance(config, dict):
        raise VerificationError("portal config_service response is not an object")
    expected_config = {
        "frontendUrl": components["frontend"]["artifact_url"],
        "wsi_release_id": release_id,
        "wsi_backend_git_sha": components["backend"]["git_sha"],
        "wsi_serving_contract_version": WSI_SERVING_CONTRACT_VERSION,
    }
    for key, expected in expected_config.items():
        actual = config.get(key)
        if key == "frontendUrl" and isinstance(actual, str):
            actual = actual.rstrip("/") + "/"
            expected = str(expected).rstrip("/") + "/"
        if actual != expected:
            raise VerificationError(
                f"running portal {key} does not match release manifest "
                f"(expected {expected!r}, got {actual!r})"
            )

    tile_value = config.get("msk_wsi_tile_server_url")
    if not isinstance(tile_value, str) or not tile_value.strip():
        raise VerificationError("running portal has no WSI tile-server URL")
    tile_parsed = urllib.parse.urlparse(
        urllib.parse.urljoin(portal_url.rstrip("/") + "/", tile_value)
    )
    if tile_parsed.scheme not in ("http", "https") or not tile_parsed.netloc:
        raise VerificationError("running portal has an invalid WSI tile-server URL")
    ready_url = urllib.parse.urlunparse(
        (tile_parsed.scheme, tile_parsed.netloc, "/ready", "", "", "")
    )
    ready = _request_json(ready_url, cookie)
    if not isinstance(ready, dict):
        raise VerificationError("tile-server readiness response is not an object")
    expected_ready = {
        "release_id": release_id,
        "image_git_sha": components["tile_server"]["git_sha"],
        "serving_contract_version": WSI_SERVING_CONTRACT_VERSION,
    }
    for key, expected in expected_ready.items():
        if ready.get(key) != expected:
            raise VerificationError(
                f"running tile server {key} does not match release manifest "
                f"(expected {expected!r}, got {ready.get(key)!r})"
            )


def _request_json(url: str, cookie: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if cookie:
        request.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise VerificationError(f"HTTP {error.code} from portal catalog") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise VerificationError(f"portal catalog request failed: {type(error).__name__}") from None


def _read_manifest(path: Path, *, require_immutable: bool = False) -> list[dict[str, Any]]:
    if not path.is_file():
        raise VerificationError(f"stack release manifest does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise VerificationError("stack release manifest is not valid JSON") from None
    if not isinstance(value, dict) or value.get("version") not in (1, 2):
        raise VerificationError("stack release manifest must have version 1 or 2")
    if require_immutable:
        _validate_release_identity(value)
    studies = value.get("studies")
    if not isinstance(studies, list) or not studies:
        raise VerificationError("stack release manifest must contain a non-empty studies array")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in studies:
        if not isinstance(item, dict):
            raise VerificationError("stack release manifest contains a non-object study")
        study_id = item.get("study_id")
        study_dir = item.get("study_dir")
        if not isinstance(study_id, str) or not study_id.strip():
            raise VerificationError("every manifest study needs a non-empty study_id")
        if study_id in seen:
            raise VerificationError(f"stack release manifest duplicates study {study_id}")
        if not isinstance(study_dir, str) or not study_dir.strip():
            raise VerificationError(f"manifest study {study_id} needs study_dir")
        directory = Path(study_dir).expanduser().resolve()
        if not directory.is_dir():
            raise VerificationError(f"study directory does not exist for {study_id}: {directory}")
        if not (directory / "meta_wsi.txt").is_file():
            raise VerificationError(f"study {study_id} is missing meta_wsi.txt")
        if not (directory / "wsi_snapshot_manifest.json").is_file():
            raise VerificationError(f"study {study_id} is missing wsi_snapshot_manifest.json")
        wsi_values: dict[str, str] = {}
        for line in (directory / "meta_wsi.txt").read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#") and ":" in line:
                key, value = line.split(":", 1)
                wsi_values[key.strip()] = value.strip()
        if wsi_values.get("cancer_study_identifier") != study_id:
            raise VerificationError(
                f"study {study_id} meta_wsi.txt has a different cancer_study_identifier"
            )
        try:
            wsi_manifest = json.loads(
                (directory / "wsi_snapshot_manifest.json").read_text(encoding="utf-8")
            )
        except json.JSONDecodeError:
            raise VerificationError(f"study {study_id} has an invalid WSI snapshot manifest") from None
        if not isinstance(wsi_manifest, dict):
            raise VerificationError(f"study {study_id} WSI snapshot manifest is not an object")
        if require_immutable:
            if wsi_manifest.get("snapshot_version") != 2:
                raise VerificationError(f"study {study_id} WSI snapshot must have version 2")
            if wsi_manifest.get("contract_version") != WSI_SERVING_CONTRACT_VERSION:
                raise VerificationError(f"study {study_id} WSI contract version is incompatible")
            expected_hash = _required_text(
                item, "snapshot_manifest_sha256", f"manifest study {study_id}"
            )
            actual_hash = _sha256_file(directory / "wsi_snapshot_manifest.json")
            if expected_hash.lower() != actual_hash:
                raise VerificationError(f"study {study_id} WSI snapshot manifest hash differs")
            producer = wsi_manifest.get("producer")
            if not isinstance(producer, dict):
                raise VerificationError(f"study {study_id} WSI snapshot has no producer identity")
            if _required_text(producer, "pdm_git_sha", f"study {study_id} producer").lower() != str(
                value["components"]["pdm"]["git_sha"]
            ).lower():
                raise VerificationError(f"study {study_id} was produced by a different PDM commit")
            if _required_text(
                producer, "databricks_job_run_id", f"study {study_id} producer"
            ) != str(value["components"]["pdm"]["databricks_job_run_id"]):
                raise VerificationError(f"study {study_id} came from a different Databricks run")
            source_tables = wsi_manifest.get("source_tables")
            if not isinstance(source_tables, dict):
                raise VerificationError(f"study {study_id} WSI snapshot has no source tables")
            for source_name in ("canonical", "thumbnail_registry"):
                source = source_tables.get(source_name)
                if not isinstance(source, dict):
                    raise VerificationError(
                        f"study {study_id} WSI snapshot has no {source_name} source identity"
                    )
                _required_text(source, "name", f"study {study_id} {source_name} source")
                _required_text(source, "version", f"study {study_id} {source_name} source")
            files_sha256 = wsi_manifest.get("files_sha256")
            if not isinstance(files_sha256, dict) or not files_sha256:
                raise VerificationError(f"study {study_id} WSI snapshot has no file checksums")
            for file_name, expected_file_hash in files_sha256.items():
                if not isinstance(file_name, str) or Path(file_name).name != file_name:
                    raise VerificationError(f"study {study_id} has an unsafe checksum filename")
                file_path = directory / file_name
                if not file_path.is_file():
                    raise VerificationError(f"study {study_id} checksum file is missing: {file_name}")
                if not isinstance(expected_file_hash, str) or not re.fullmatch(
                    r"[0-9a-fA-F]{64}", expected_file_hash
                ):
                    raise VerificationError(f"study {study_id} has an invalid checksum: {file_name}")
                if _sha256_file(file_path).lower() != expected_file_hash.lower():
                    raise VerificationError(f"study {study_id} file checksum differs: {file_name}")
        if wsi_manifest.get("study_id") not in (None, study_id):
            raise VerificationError(f"study {study_id} WSI snapshot manifest has a different study_id")
        for key in ("association_row_count", "servable_row_count", "patient_count"):
            try:
                count = int(wsi_manifest[key])
            except (KeyError, TypeError, ValueError):
                raise VerificationError(
                    f"study {study_id} WSI snapshot manifest is missing integer {key}"
                ) from None
            if count <= 0:
                raise VerificationError(
                    f"study {study_id} WSI snapshot manifest has invalid {key}"
                )
        try:
            incomplete_assets = int(wsi_manifest["incomplete_asset_count"])
        except (KeyError, TypeError, ValueError):
            raise VerificationError(
                f"study {study_id} WSI snapshot manifest is missing integer "
                "incomplete_asset_count"
            ) from None
        if incomplete_assets != 0:
            raise VerificationError(
                f"study {study_id} has {incomplete_assets} incomplete WSI assets"
            )
        try:
            filtered_rows = int(wsi_manifest["filtered_row_count"])
        except (KeyError, TypeError, ValueError):
            raise VerificationError(
                f"study {study_id} WSI snapshot manifest is missing integer "
                "filtered_row_count"
            ) from None
        if filtered_rows != 0:
            raise VerificationError(
                f"study {study_id} filtered {filtered_rows} WSI association rows"
            )
        declared_files = _validate_declared_sources(directory, study_id)
        timeline_dir = item.get("timeline_dir", study_dir)
        if not isinstance(timeline_dir, str) or not timeline_dir.strip():
            raise VerificationError(f"manifest timeline_dir is invalid for {study_id}")
        timeline_path = Path(timeline_dir).expanduser().resolve()
        timeline_files = [
            timeline_path / "meta_clinical_timeline_pathology_slides.txt",
            timeline_path / "data_clinical_timeline_pathology_slides.txt",
        ]
        if any(path.is_file() for path in timeline_files) and not all(
            path.is_file() for path in timeline_files
        ):
            raise VerificationError(f"study {study_id} has an incomplete pathology timeline")
        if timeline_path != directory and all(path.is_file() for path in timeline_files):
            _validate_declared_sources(timeline_path, study_id)
        seen.add(study_id)
        normalized.append(
            {
                **item,
                "study_id": study_id,
                "study_dir": str(directory),
                "timeline_dir": str(timeline_path),
                "declared_files": declared_files,
            }
        )
    return normalized


def _validate_declared_sources(directory: Path, study_id: str) -> list[str]:
    """Ensure every imported metadata declaration has its source data file.

    ``meta_study.txt`` is study-level metadata and intentionally has no data
    file. Every other ``meta_*.txt`` file is an importer declaration and must
    resolve to a regular file inside the same snapshot. This catches partial
    bundles before any portal/API checks are attempted.
    """
    declared: list[str] = []
    for meta_path in sorted(directory.glob("meta_*.txt")):
        if meta_path.name == "meta_study.txt":
            continue
        values: dict[str, str] = {}
        for line in meta_path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#") and ":" in line:
                key, value = line.split(":", 1)
                values[key.strip()] = value.strip()
        data_name = values.get("data_filename")
        if not data_name:
            raise VerificationError(
                f"study {study_id} metadata {meta_path.name} is missing data_filename"
            )
        data_path = (directory / data_name).resolve()
        if data_path.parent != directory.resolve() or not data_path.is_file():
            raise VerificationError(
                f"study {study_id} metadata {meta_path.name} references missing or unsafe data"
            )
        declared.append(meta_path.name)
    return declared


def _catalog_ids(value: Any) -> set[str]:
    if not isinstance(value, list):
        raise VerificationError("portal studies response is not an array")
    ids = {
        str(item["studyId"])
        for item in value
        if isinstance(item, dict) and item.get("studyId")
    }
    if not ids:
        raise VerificationError("portal study catalog is empty")
    return ids


def _has_complete_molecular_snapshot(study_dir: Path) -> bool:
    """Use the strict molecular verifier when the study declares those files."""
    candidates = (
        ("meta_mutations.txt", "meta_mutations_extended.txt"),
        ("meta_cna.txt", "meta_CNA.txt"),
        ("meta_sv.txt",),
        ("meta_cna_hg19_seg.txt", "mskimpact_meta_cna_hg19_seg.txt"),
        ("meta_gene_panel_matrix.txt", "meta_gene_matrix.txt"),
    )
    return all(any((study_dir / name).is_file() for name in names) for names in candidates) and all(
        (study_dir / name).is_file()
        for name in ("meta_clinical_patient.txt", "meta_clinical_sample.txt")
    )


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        raise VerificationError(f"{name} must be an integer") from None


def _verify_study(
    args: argparse.Namespace, study: dict[str, Any], *, check_all_tiles: bool
) -> dict[str, Any]:
    study_id = str(study["study_id"])
    study_dir = str(study["study_dir"])
    command = [
        sys.executable,
        str(PER_STUDY_VERIFIER),
        "--portal-url",
        args.portal_url,
        "--study-id",
        study_id,
        "--study-dir",
        study_dir,
        "--timeline-dir",
        str(study["timeline_dir"]),
        "--clickhouse-container",
        args.clickhouse_container,
        "--clickhouse-user",
        args.clickhouse_user,
        "--clickhouse-database",
        args.clickhouse_database,
        "--check-study-view",
        "--require-wsi",
        "--check-all-wsi",
        "--timeline-patient-sample",
        str(args.timeline_patient_sample),
        "--check-wsi-clinical-counts",
        "--check-access",
        "--wsi-sample-size",
        str(args.wsi_sample_size),
        "--expected-tile-url",
        args.expected_tile_url,
    ]
    timeline_meta = Path(study["timeline_dir"]) / "meta_clinical_timeline_pathology_slides.txt"
    if timeline_meta.is_file():
        command.append("--check-timeline")
    if _has_complete_molecular_snapshot(Path(study_dir)):
        command.append("--check-all-data")
    if check_all_tiles:
        command.extend(["--check-all-access", "--check-all-tiles"])
    if args.cookie:
        command.extend(["--cookie", args.cookie])

    environment = os.environ.copy()
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=args.study_timeout_seconds,
            env=environment,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "per-study verification failed"
        raise VerificationError(f"{study_id}: {message}") from None
    except subprocess.TimeoutExpired:
        raise VerificationError(f"{study_id}: verification exceeded its timeout") from None
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise VerificationError(f"{study_id}: verifier returned invalid JSON") from None
    if not isinstance(value, dict):
        raise VerificationError(f"{study_id}: verifier returned an invalid result")
    value["declared_source_metadata"] = len(study.get("declared_files", []))
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=os.environ.get("STACK_STUDY_MANIFEST", ""),
        help="host-local JSON release manifest (or STACK_STUDY_MANIFEST)",
    )
    parser.add_argument(
        "--portal-url",
        default=os.environ.get("PORTAL_URL", "http://localhost:8080"),
        help="browser-reachable cBioPortal URL",
    )
    parser.add_argument(
        "--clickhouse-container",
        default=os.environ.get("CLICKHOUSE_CONTAINER", ""),
        help="ClickHouse container name",
    )
    parser.add_argument("--clickhouse-user", default=os.environ.get("CLICKHOUSE_USER", "cbio_user"))
    parser.add_argument(
        "--clickhouse-database", default=os.environ.get("CLICKHOUSE_DB", "cbioportal")
    )
    parser.add_argument("--cookie", default=os.environ.get("VERIFY_COOKIE", ""))
    parser.add_argument(
        "--expected-tile-url",
        default=os.environ.get(
            "EXPECTED_WSI_TILE_SERVER_URL", os.environ.get("WSI_TILE_SERVER_URL", "")
        ),
        help="optional assertion for the portal-advertised WSI tile URL",
    )
    parser.add_argument(
        "--wsi-sample-size",
        type=int,
        default=_env_int("WSI_SAMPLE_SIZE", 3),
    )
    parser.add_argument(
        "--study-timeout-seconds",
        type=int,
        default=_env_int("VERIFY_STUDY_TIMEOUT_SECONDS", 1800),
    )
    parser.add_argument(
        "--timeline-patient-sample",
        type=int,
        default=_env_int("TIMELINE_PATIENT_SAMPLE", 24),
        help="event-bearing patients checked per study when --check-all-wsi is enabled",
    )
    parser.add_argument(
        "--all-tiles",
        action="store_true",
        default=os.environ.get("VERIFY_ALL_TILES", "1") == "1",
        help="validate every servable slide's access, thumbnail, and tile (default: enabled)",
    )
    args = parser.parse_args()

    if not args.manifest:
        parser.error("--manifest or STACK_STUDY_MANIFEST is required")
    if not args.clickhouse_container:
        parser.error("--clickhouse-container or CLICKHOUSE_CONTAINER is required")
    if args.wsi_sample_size <= 0:
        parser.error("--wsi-sample-size must be positive")
    if args.study_timeout_seconds <= 0:
        parser.error("--study-timeout-seconds must be positive")
    if args.timeline_patient_sample < 0:
        parser.error("--timeline-patient-sample must not be negative")

    try:
        raw_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        release_identity = _validate_release_identity(raw_manifest)
        studies = _read_manifest(args.manifest, require_immutable=True)
        _validate_live_release_identity(args.portal_url, args.cookie, raw_manifest)
        encoded = urllib.parse.urlencode(
            {"projection": "DETAILED", "pageSize": "10000000", "pageNumber": "0"}
        )
        catalog = _catalog_ids(_request_json(f"{args.portal_url.rstrip('/')}/api/studies?{encoded}", args.cookie))
        expected = {str(study["study_id"]) for study in studies}
        missing = sorted(expected - catalog)
        unexpected = sorted(catalog - expected)
        if missing or unexpected:
            details = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if unexpected:
                details.append("unexpected=" + ",".join(unexpected))
            raise VerificationError("portal study catalog does not match release manifest: " + " ".join(details))

        results = [
            _verify_study(args, study, check_all_tiles=args.all_tiles)
            for study in sorted(studies, key=lambda item: str(item["study_id"]))
        ]
        print(
            json.dumps(
                {
                    "catalog_studies": len(catalog),
                    "release_id": release_identity["release_id"],
                    "release_manifest_sha256": _sha256_file(args.manifest),
                    "release_studies": len(studies),
                    "studies": results,
                    "status": "accepted",
                },
                sort_keys=True,
            )
        )
    except VerificationError as error:
        print(f"verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
