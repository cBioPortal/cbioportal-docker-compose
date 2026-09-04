#!/usr/bin/env python3
"""Verify that a study import is visible and usable through the portal API.

The importer validates files before writing ClickHouse, but a successful process
exit does not prove that the running portal is serving the expected study.  This
small, dependency-free check is intended to run immediately after an import (or
as a deployment smoke test). It reports counts and HTTP statuses, and only
echoes a patient identifier when an explicit ``--wsi-patient-id`` target is
provided; source URLs, slide identifiers, and access tokens are never printed.
Use ``--check-all-data`` as the release gate when the source study directory is
available; that mode compares every supported clinical and molecular data
category with ClickHouse rather than checking service health alone.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


class VerificationError(RuntimeError):
    """A user-actionable release verification failure."""


def _http_timeout_seconds() -> float:
    """Use a generous portal timeout for large studies, without hanging forever."""
    try:
        return max(1.0, float(os.environ.get("VERIFY_HTTP_TIMEOUT_SECONDS", "120")))
    except ValueError:
        return 120.0


def _safe_tile_level(metadata: dict[str, Any]) -> int:
    """Choose the lowest-cost ZXY level that stays under the decode budget.

    Older access metadata may not contain ``safe_min_level``.  Recompute it
    from the slide pyramid in that case so a smoke request does not ask the
    tile service to decode an oversized overview (HTTP 422) or a full-
    resolution region unnecessarily.
    """
    try:
        provided = metadata.get("safe_min_level")
        if isinstance(provided, int) and not isinstance(provided, bool) and provided >= 0:
            return provided
        dimensions = metadata["dimensions"]
        width = int(dimensions["width"])
        height = int(dimensions["height"])
        level_dimensions = [
            (int(level["width"]), int(level["height"]))
            for level in metadata["level_dimensions"]
        ]
        level_downsamples = [float(value) for value in metadata["level_downsamples"]]
        tile_size = int(metadata.get("tile_size") or 256)
        max_zoom_value = metadata.get("max_zoom")
        if max_zoom_value is None:
            max_zoom = max(0, int(metadata.get("levels") or 1) - 1)
        else:
            max_zoom = int(max_zoom_value)
        max_decode_pixels = int(metadata.get("max_decode_pixels") or 16 * 1024 * 1024)
        if (
            width <= 0
            or height <= 0
            or tile_size <= 0
            or max_zoom < 0
            or max_decode_pixels <= 0
            or len(level_dimensions) != len(level_downsamples)
            or not level_dimensions
        ):
            return max(0, max_zoom)

        def best_level(target_downsample: float) -> int:
            if target_downsample <= 1:
                return 0
            for index, level_downsample in enumerate(level_downsamples):
                if level_downsample > target_downsample:
                    return max(0, index - 1)
            return len(level_downsamples) - 1

        for z in range(max_zoom + 1):
            target_downsample = 2 ** (max_zoom - z)
            tiles_x = max(1, math.ceil(width / (tile_size * target_downsample)))
            tiles_y = max(1, math.ceil(height / (tile_size * target_downsample)))
            level = best_level(target_downsample)
            level_width, level_height = level_dimensions[level]
            level_downsample = max(1.0, level_downsamples[level])
            worst_pixels = 0
            for x in {0, tiles_x - 1}:
                for y in {0, tiles_y - 1}:
                    x0 = x * tile_size * target_downsample
                    y0 = y * tile_size * target_downsample
                    source_width = min(tile_size * target_downsample, width - x0)
                    source_height = min(tile_size * target_downsample, height - y0)
                    read_width = min(
                        math.ceil(source_width / level_downsample),
                        level_width - math.floor(x0 / level_downsample),
                    )
                    read_height = min(
                        math.ceil(source_height / level_downsample),
                        level_height - math.floor(y0 / level_downsample),
                    )
                    worst_pixels = max(worst_pixels, max(0, read_width) * max(0, read_height))
            if worst_pixels <= max_decode_pixels:
                return z
        return max_zoom
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError):
        try:
            max_zoom_value = metadata.get("max_zoom")
            if max_zoom_value is None:
                return max(0, int(metadata.get("levels") or 1) - 1)
            return max(0, int(max_zoom_value))
        except (TypeError, ValueError):
            return 0


def _request_json(url: str, cookie: str = "") -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if cookie:
        request.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(request, timeout=_http_timeout_seconds()) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise VerificationError(f"HTTP {error.code} from portal API") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise VerificationError(f"portal API request failed: {type(error).__name__}") from None


def _request_json_post(url: str, body: Any, cookie: str = "") -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    if cookie:
        request.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(request, timeout=_http_timeout_seconds()) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise VerificationError(f"HTTP {error.code} from portal API") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise VerificationError(f"portal API request failed: {type(error).__name__}") from None


def _request_bytes(
    url: str,
    *,
    cookie: str = "",
    bearer: str = "",
    source: str = "",
    origin: str = "",
) -> int:
    headers = {"Accept": "image/jpeg"}
    if source:
        headers["X-WSI-Source"] = source
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(url, headers=headers)
    if cookie:
        request.add_header("Cookie", cookie)
    if bearer:
        request.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get_content_type()
            if not content_type.startswith("image/"):
                raise VerificationError(
                    f"tile service returned non-image content type {content_type}"
                )
            if origin and response.headers.get("Access-Control-Allow-Origin") not in {
                origin,
                "*",
            }:
                raise VerificationError("tile service response is missing CORS origin")
            response.read(1)
            return response.status
    except urllib.error.HTTPError as error:
        raise VerificationError(f"HTTP {error.code} from tile service") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise VerificationError(f"tile service request failed: {type(error).__name__}") from None


def _request_cors_preflight(url: str, origin: str) -> None:
    """Verify the browser preflight needed for authenticated WSI requests."""
    request = urllib.request.Request(
        url,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-wsi-source",
        },
        method="OPTIONS",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status < 200 or response.status >= 300:
                raise VerificationError("tile service CORS preflight failed")
            if response.headers.get("Access-Control-Allow-Origin") not in {origin, "*"}:
                raise VerificationError("tile service CORS preflight has no matching origin")
            allowed_headers = {
                value.strip().lower()
                for value in (response.headers.get("Access-Control-Allow-Headers") or "").split(",")
            }
            if not {"authorization", "x-wsi-source"}.issubset(allowed_headers):
                raise VerificationError("tile service CORS preflight omits WSI headers")
    except urllib.error.HTTPError as error:
        raise VerificationError(f"HTTP {error.code} from tile service CORS preflight") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise VerificationError(
            f"tile service CORS preflight failed: {type(error).__name__}"
        ) from None


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


def _portal_tile_server(args: argparse.Namespace, portal_url: str) -> tuple[str, str]:
    """Resolve the browser tile endpoint from the portal's live config."""
    config = _request_json(f"{portal_url}/config_service", args.cookie)
    configured = config.get("msk_wsi_tile_server_url") if isinstance(config, dict) else None
    if not isinstance(configured, str) or not configured.strip():
        raise VerificationError("portal config does not advertise a WSI tile server URL")
    tile_url = urllib.parse.urljoin(f"{portal_url}/", configured.strip())
    parsed_tile = urllib.parse.urlparse(tile_url)
    parsed_portal = urllib.parse.urlparse(portal_url)
    if parsed_tile.scheme not in {"http", "https"} or not parsed_tile.netloc:
        raise VerificationError("portal WSI tile server URL is not an absolute HTTP(S) URL")
    expected = getattr(args, "expected_tile_url", "") or getattr(args, "tile_url", "")
    if expected and _normalize_url(tile_url) != _normalize_url(expected):
        raise VerificationError(
            "portal WSI tile server URL differs from the expected deployment endpoint"
        )
    origin = f"{parsed_portal.scheme}://{parsed_portal.netloc}"
    cross_origin = parsed_tile.netloc != parsed_portal.netloc
    if cross_origin:
        _request_cors_preflight(f"{tile_url.rstrip('/')}/thumbnails", origin)
        _request_cors_preflight(f"{tile_url.rstrip('/')}/tiles/zxy/0/0/0", origin)
    return tile_url.rstrip("/"), origin if cross_origin else ""


def _parse_wsi_file(study_dir: Path) -> dict[str, Any]:
    meta_path = study_dir / "meta_wsi.txt"
    if not meta_path.is_file():
        raise VerificationError("study directory is missing meta_wsi.txt")

    metadata: dict[str, str] = {}
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    data_name = metadata.get("data_filename")
    if not data_name:
        raise VerificationError("meta_wsi.txt is missing data_filename")
    data_path = (study_dir / data_name).resolve()
    if data_path.parent != study_dir.resolve():
        raise VerificationError("data_filename must stay inside the study directory")
    if not data_path.is_file():
        raise VerificationError("WSI data file referenced by meta_wsi.txt is missing")

    lines = data_path.read_text(encoding="utf-8").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line and not line.startswith("#")),
        None,
    )
    if header_index is None:
        raise VerificationError("WSI data file has no header")
    header = lines[header_index].split("\t")
    required = {"PATIENT_ID", "IMAGE_ID", "CAN_SERVE_TILES"}
    missing = sorted(required.difference(header))
    if missing:
        raise VerificationError(f"WSI data header is missing: {', '.join(missing)}")

    index = {name: position for position, name in enumerate(header)}
    rows = [line.split("\t") for line in lines[header_index + 1 :] if line.strip()]
    if any(len(row) != len(header) for row in rows):
        raise VerificationError("WSI data contains a row with the wrong column count")
    image_ids = [row[index["IMAGE_ID"]].strip() for row in rows]
    if not rows:
        raise VerificationError("WSI data file contains no rows")
    if any(not image_id for image_id in image_ids):
        raise VerificationError("WSI data contains a row without IMAGE_ID")
    if len(image_ids) != len(set(image_ids)):
        raise VerificationError("WSI data contains duplicate IMAGE_ID values")

    serving_fields = (
        "SOURCE_URL",
        "TILE_METADATA_JSON",
        "THUMBNAIL_URL",
        "THUMBNAIL_WIDTH",
        "THUMBNAIL_HEIGHT",
        "THUMBNAIL_CONTENT_TYPE",
    )
    missing_serving_fields = [
        image_id
        for row, image_id in zip(rows, image_ids)
        if row[index["CAN_SERVE_TILES"]].strip().upper() in {"TRUE", "1", "YES"}
        and any(not row[index[field]].strip() for field in serving_fields if field in index)
    ]
    if missing_serving_fields:
        raise VerificationError(
            f"{len(missing_serving_fields)} servable WSI rows are missing pixel bundle fields"
        )

    manifest_path = study_dir / "wsi_snapshot_manifest.json"
    manifest_timeline_events: int | None = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise VerificationError("wsi_snapshot_manifest.json is not valid JSON") from None
        if manifest.get("study_id") and manifest["study_id"] != metadata.get(
            "cancer_study_identifier"
        ):
            raise VerificationError("WSI snapshot manifest study_id does not match meta_wsi.txt")
        try:
            incomplete_assets = int(manifest["incomplete_asset_count"])
        except (KeyError, TypeError, ValueError):
            raise VerificationError(
                "wsi_snapshot_manifest.json is missing integer incomplete_asset_count"
            ) from None
        if incomplete_assets != 0:
            raise VerificationError(
                f"WSI snapshot contains {incomplete_assets} incomplete asset(s)"
            )
        try:
            filtered_rows = int(manifest["filtered_row_count"])
        except (KeyError, TypeError, ValueError):
            raise VerificationError(
                "wsi_snapshot_manifest.json is missing integer filtered_row_count"
            ) from None
        if filtered_rows != 0:
            raise VerificationError(
                f"WSI snapshot filtered {filtered_rows} association row(s)"
            )
        expected_rows = manifest.get("association_row_count")
        if expected_rows is not None:
            try:
                manifest_row_count = int(expected_rows)
            except (TypeError, ValueError):
                raise VerificationError(
                    "WSI snapshot manifest association_row_count is not an integer"
                ) from None
            if manifest_row_count != len(rows):
                raise VerificationError(
                    "WSI snapshot manifest row count does not match data_wsi.txt"
                )
        if manifest.get("timeline_event_count") is not None:
            try:
                manifest_timeline_events = int(manifest["timeline_event_count"])
            except (TypeError, ValueError):
                raise VerificationError(
                    "wsi_snapshot_manifest.json timeline_event_count is not an integer"
                ) from None

    servable_values = {"TRUE", "1", "YES"}
    patient_image_ids: dict[str, set[str]] = {}
    servable_image_ids: dict[str, set[str]] = {}
    for row in rows:
        patient_id = row[index["PATIENT_ID"]].strip()
        image_id = row[index["IMAGE_ID"]].strip()
        patient_image_ids.setdefault(patient_id, set()).add(image_id)
        if row[index["CAN_SERVE_TILES"]].strip().upper() in servable_values:
            servable_image_ids.setdefault(patient_id, set()).add(image_id)

    patients = list(patient_image_ids)
    servable = sum(len(image_ids) for image_ids in servable_image_ids.values())
    if not patients:
        raise VerificationError("WSI data contains no patient identifier for hierarchy smoke test")

    # The file is not required to be ordered by serving capability.  Select a
    # patient that actually has a servable slide so the hierarchy/access smoke
    # checks exercise the tile path instead of failing on an unrelated patient
    # whose rows are retained for provenance but have no complete pixel bundle.
    servable_patient = next(
        (
            row[index["PATIENT_ID"]].strip()
            for row in rows
            if len(row) > index["CAN_SERVE_TILES"]
            and row[index["CAN_SERVE_TILES"]].strip().upper() in servable_values
            and len(row) > index["PATIENT_ID"]
            and row[index["PATIENT_ID"]].strip()
        ),
        patients[0],
    )

    return {
        "rows": len(rows),
        "servable": servable,
        "patient_image_ids": patient_image_ids,
        "servable_image_ids": servable_image_ids,
        "patients": patients,
        # Keep the identifier internal to the request; it is never printed.
        "smoke_patient": servable_patient,
        "timeline_events": manifest_timeline_events,
    }


def _all_slides(value: Any) -> list[dict[str, Any]]:
    slides: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "imageId" in value:
            slides.append(value)
        for child in value.values():
            slides.extend(_all_slides(child))
    elif isinstance(value, list):
        for child in value:
            slides.extend(_all_slides(child))
    return slides


def _pathology_linkout_candidates(
    linkout: str, slides_by_patient: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Return hierarchy slides addressed by one pathology linkout.

    Linkouts are the only stable association key exposed by the public
    timeline.  Matching them against the served hierarchy makes the release
    check exercise the same capability gate as the browser: a retained
    metadata row is not a viewable slide unless ``canServeTiles`` is true.
    """
    parsed = urllib.parse.urlparse(linkout)
    query = urllib.parse.parse_qs(parsed.query)
    if parsed.path != "/patient/wsiHESlides":
        return []
    patient_id = query.get("caseId", [""])[0]
    sample_id = query.get("sampleId", [""])[0]
    specimen_key = query.get("specimenKey", [""])[0]
    match_level = query.get("matchLevel", [""])[0].upper()
    stain_filter = query.get("stainFilter", [""])[0].lower()
    candidates: list[dict[str, Any]] = []
    for slide in slides_by_patient.get(patient_id, []):
        slide_sample = str(slide.get("sampleId") or "")
        slide_match = str(slide.get("matchLevel") or "").upper()
        if sample_id and slide_sample != sample_id:
            continue
        if not sample_id and slide_sample:
            continue
        if specimen_key and slide.get("specimenKey") != specimen_key:
            continue
        if match_level and slide_match != match_level:
            continue
        if stain_filter == "hne" and slide.get("isHne") is not True:
            continue
        if stain_filter == "ihc" and slide.get("isIhc") is not True:
            continue
        candidates.append(slide)
    return candidates


def _validate_pathology_timeline_capability(
    pathology_events: list[dict[str, Any]],
    slides_by_patient: dict[str, list[dict[str, Any]]],
) -> int:
    """Reject timeline claims that cannot be served by the WSI hierarchy.

    The old release verifier compared the timeline file only with the
    clinical-events API.  That allowed both layers to agree on a stale
    ``IMAGE_COUNT=2`` while the hierarchy correctly exposed two
    ``canServeTiles=false`` rows.  This check closes that gap and is deliberately
    based on the live hierarchy, not just the source TSV.
    """
    checked = 0
    for event in pathology_events:
        attributes = {
            attribute.get("key"): attribute.get("value")
            for attribute in event.get("attributes", [])
            if isinstance(attribute, dict)
        }
        linkout = str(attributes.get("LINKOUT") or "").strip()
        try:
            image_count = int(attributes.get("IMAGE_COUNT") or 0)
            non_servable = int(attributes.get("NON_SERVABLE_IMAGE_COUNT") or 0)
            total = int(attributes.get("TOTAL_IMAGE_COUNT") or 0)
        except (TypeError, ValueError):
            raise VerificationError(
                "pathology timeline has a non-numeric capability count"
            ) from None

        if not linkout:
            if image_count or non_servable != total:
                raise VerificationError(
                    "pathology timeline has inconsistent non-servable counts without a WSI linkout"
                )
            checked += 1
            continue

        candidates = _pathology_linkout_candidates(linkout, slides_by_patient)
        servable = sum(slide.get("canServeTiles") is True for slide in candidates)
        actual_non_servable = len(candidates) - servable
        if not candidates:
            raise VerificationError(
                "pathology timeline linkout does not resolve to a WSI hierarchy slide"
            )
        if servable == 0:
            raise VerificationError(
                "pathology timeline contains a linkout for a non-servable WSI group"
            )
        # A group may contain the same specimen on more than one timeline date,
        # so the hierarchy can legitimately contain additional rows.  It may
        # never contain fewer capable/non-capable rows than the event claims,
        # and a linkout is forbidden when the addressed group has no servable
        # pixels at all.
        if image_count > servable or non_servable > actual_non_servable or total > len(candidates):
            raise VerificationError(
                "pathology timeline counts exceed the live WSI capability for a linkout: "
                f"event={image_count}/{non_servable}/{total} "
                f"hierarchy={servable}/{actual_non_servable}/{len(candidates)}"
            )
        if image_count == 0:
            raise VerificationError(
                "pathology timeline contains a linkout with zero servable slides"
            )
        checked += 1
    return checked


def _select_wsi_sample(
    wsi: dict[str, Any], slides: list[dict[str, Any]], sample_size: int
) -> list[dict[str, Any]]:
    """Select stable servable slides across distinct patients."""
    if sample_size <= 0:
        raise VerificationError("--wsi-sample-size must be positive")
    by_image_id = {
        str(slide.get("imageId")): slide
        for slide in slides
        if slide.get("imageId") and slide.get("canServeTiles") is True
    }
    patient_candidates: list[dict[str, Any]] = []
    for patient_id in sorted(wsi["servable_image_ids"]):
        image_ids = sorted(wsi["servable_image_ids"][patient_id])
        for image_id in image_ids:
            slide = by_image_id.get(str(image_id))
            if slide is not None:
                patient_candidates.append(slide)
                break
    candidates = patient_candidates
    if len(candidates) < sample_size:
        remaining = [
            by_image_id[image_id]
            for image_id in sorted(by_image_id)
            if by_image_id[image_id] not in candidates
        ]
        candidates = candidates + remaining
    if not candidates:
        return []
    if len(candidates) <= sample_size:
        return candidates
    if sample_size == 1:
        return candidates[:1]
    indexes = [
        round(index * (len(candidates) - 1) / (sample_size - 1))
        for index in range(sample_size)
    ]
    return [candidates[index] for index in indexes]


def _parse_timeline_file(study_dir: Path) -> dict[str, Any]:
    meta_path = study_dir / "meta_clinical_timeline_pathology_slides.txt"
    data_path = study_dir / "data_clinical_timeline_pathology_slides.txt"
    if not meta_path.is_file() or not data_path.is_file():
        raise VerificationError("timeline directory is missing the pathology timeline files")

    rows = []
    patient_total_image_counts: Counter[str] = Counter()
    patient_metrics: dict[str, Counter[str]] = defaultdict(Counter)
    with data_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {
            "PATIENT_ID",
            "EVENT_TYPE",
            "IMAGE_COUNT",
            "NON_SERVABLE_IMAGE_COUNT",
            "TOTAL_IMAGE_COUNT",
            "LINKOUT",
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise VerificationError("pathology timeline is missing required columns")
        for row in reader:
            if not row.get("PATIENT_ID") or row.get("EVENT_TYPE") != "PATHOLOGY SLIDES":
                raise VerificationError("pathology timeline contains an invalid event")
            try:
                image_count = int(row.get("IMAGE_COUNT") or 0)
                non_servable = int(row.get("NON_SERVABLE_IMAGE_COUNT") or 0)
                total = int(row.get("TOTAL_IMAGE_COUNT") or 0)
            except ValueError:
                raise VerificationError("pathology timeline contains a non-numeric image count") from None
            if image_count < 0 or non_servable < 0 or total != image_count + non_servable:
                raise VerificationError("pathology timeline image counts are inconsistent")
            rows.append((image_count, non_servable, total, bool(row.get("LINKOUT"))))
            patient_id = str(row["PATIENT_ID"])
            patient_total_image_counts[patient_id] += total
            metrics = patient_metrics[patient_id]
            metrics["events"] += 1
            metrics["image_count"] += image_count
            metrics["non_servable_image_count"] += non_servable
            metrics["total_image_count"] += total
            metrics["linkouts"] += bool(row.get("LINKOUT"))
    if not rows:
        raise VerificationError("pathology timeline contains no events")
    return {
        "events": len(rows),
        "image_count": sum(row[0] for row in rows),
        "non_servable_image_count": sum(row[1] for row in rows),
        "total_image_count": sum(row[2] for row in rows),
        "linkouts": sum(row[3] for row in rows),
        "patient_total_image_counts": dict(patient_total_image_counts),
        "patient_metrics": {
            patient_id: dict(metrics)
            for patient_id, metrics in patient_metrics.items()
        },
    }


def _select_timeline_patients(
    patients: list[str], patient_metrics: dict[str, dict[str, int]], sample_size: int
) -> list[str]:
    """Select deterministic event-bearing patients for bounded API checks."""
    candidates = [patient_id for patient_id in patients if patient_id in patient_metrics]
    candidates = candidates or list(patients)
    if sample_size <= 0 or sample_size >= len(candidates):
        return candidates
    if sample_size == 1:
        return candidates[:1]
    indexes = [
        round(index * (len(candidates) - 1) / (sample_size - 1))
        for index in range(sample_size)
    ]
    return [candidates[index] for index in indexes]


def _study_record(studies: Any, study_id: str) -> dict[str, Any]:
    if not isinstance(studies, list):
        raise VerificationError("portal studies response is not an array")
    record = next(
        (item for item in studies if isinstance(item, dict) and item.get("studyId") == study_id),
        None,
    )
    if record is None:
        raise VerificationError("study is not present in the portal catalog")
    return record


def _clickhouse_wsi_counts(args: argparse.Namespace, study_id: str) -> tuple[int, int]:
    """Return imported WSI row/servable counts when a local DB container is supplied."""
    query = (
        "SELECT count(), countIf(can_serve_tiles) FROM wsi_slide "
        "WHERE cancer_study_id = (SELECT cancer_study_id FROM cancer_study "
        "WHERE cancer_study_identifier = '"
        + study_id.replace("'", "''")
        + "') FORMAT TabSeparatedRaw"
    )
    command = [
        "docker",
        "exec",
        args.clickhouse_container,
        "clickhouse-client",
        "--user",
        args.clickhouse_user,
        "--database",
        args.clickhouse_database,
        "--query",
        query,
    ]
    if args.clickhouse_password:
        command[2:2] = ["-e", f"CLICKHOUSE_PASSWORD={args.clickhouse_password}"]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        values = completed.stdout.strip().split("\t")
        if len(values) != 2:
            raise ValueError
        return int(values[0]), int(values[1])
    except (OSError, subprocess.SubprocessError, ValueError):
        raise VerificationError("ClickHouse WSI count query failed") from None


def _clickhouse_wsi_clinical_counts(
    args: argparse.Namespace, study_id: str
) -> tuple[int, int, int, int, int, int]:
    """Check that imported WSI associations have matching clinical attributes.

    Study View renders sample- and patient-level WSI columns from the six
    attributes emitted by the WSI importer. Checking hierarchy rows alone
    cannot catch a missing clinical-data load, which otherwise renders every
    value as an em dash in the Clinical Data tab.
    """
    escaped_study_id = study_id.replace("'", "''")
    query = f"""
WITH expected AS (
    SELECT placement.sample_id AS sample_id, count() AS expected_count
    FROM wsi_slide_placement placement
    INNER JOIN cancer_study study
        ON study.cancer_study_id = placement.cancer_study_id
    WHERE study.cancer_study_identifier = '{escaped_study_id}'
      AND placement.sample_id IS NOT NULL
    GROUP BY placement.sample_id
), actual AS (
    SELECT internal_id AS sample_id,
        maxIf(toInt64OrNull(attr_value), attr_id = 'WSI_SAMPLE_SLIDE_COUNT') AS actual_count
    FROM clinical_sample
    WHERE attr_id = 'WSI_SAMPLE_SLIDE_COUNT'
    GROUP BY internal_id
), expected_patients AS (
    SELECT placement.patient_id AS patient_id, count() AS expected_count
    FROM wsi_slide_placement placement
    INNER JOIN cancer_study study
        ON study.cancer_study_id = placement.cancer_study_id
    WHERE study.cancer_study_identifier = '{escaped_study_id}'
    GROUP BY placement.patient_id
), actual_patients AS (
    SELECT internal_id AS patient_id,
        maxIf(toInt64OrNull(attr_value), attr_id = 'WSI_PATIENT_SLIDE_COUNT') AS actual_count
    FROM clinical_patient
    WHERE attr_id = 'WSI_PATIENT_SLIDE_COUNT'
    GROUP BY internal_id
)
SELECT count() AS expected_samples,
    countIf(isNull(actual.actual_count)) AS missing_samples,
    countIf(NOT isNull(actual.actual_count) AND actual.actual_count != expected.expected_count) AS mismatched_samples,
    (SELECT count() FROM expected_patients) AS expected_patients,
    (SELECT count() FROM expected_patients AS e
        LEFT JOIN actual_patients AS a ON a.patient_id = e.patient_id
        WHERE isNull(a.actual_count)) AS missing_patients,
    (SELECT count() FROM expected_patients AS e
        LEFT JOIN actual_patients AS a ON a.patient_id = e.patient_id
        WHERE NOT isNull(a.actual_count)
          AND a.actual_count != e.expected_count) AS mismatched_patients
FROM expected
LEFT JOIN actual ON actual.sample_id = expected.sample_id
SETTINGS join_use_nulls = 1
FORMAT TabSeparatedRaw
"""
    command = [
        "docker",
        "exec",
        args.clickhouse_container,
        "clickhouse-client",
        "--user",
        args.clickhouse_user,
        "--database",
        args.clickhouse_database,
        "--query",
        query,
    ]
    if args.clickhouse_password:
        command[2:2] = ["-e", f"CLICKHOUSE_PASSWORD={args.clickhouse_password}"]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        values = completed.stdout.strip().split("\t")
        if len(values) != 6:
            raise ValueError
        return tuple(int(value) for value in values)  # type: ignore[return-value]
    except (OSError, subprocess.SubprocessError, ValueError):
        raise VerificationError("ClickHouse WSI clinical count query failed") from None


def _portal_wsi_clinical_counts(
    args: argparse.Namespace, study_id: str
) -> tuple[int, int]:
    """Confirm the portal API exposes at least one patient WSI count.

    The ClickHouse check catches missing or stale rows, while this API check
    catches metadata mistakes (for example, marking a patient attribute as a
    sample attribute) that would leave the Clinical Data column blank.
    """
    portal_url = args.portal_url.rstrip("/")
    response = _request_json_post(
        f"{portal_url}/api/clinical-data-table/fetch?"
        "pageSize=500&pageNumber=0&sortBy=WSI_PATIENT_SLIDE_COUNT&direction=DESC",
        {"studyIds": [study_id]},
        args.cookie,
    )
    rows = response.get("byUniqueSampleKey") if isinstance(response, dict) else None
    if not isinstance(rows, dict):
        raise VerificationError("clinical-data-table response is missing sample rows")

    patients: set[str] = set()
    for attributes in rows.values():
        if not isinstance(attributes, list):
            continue
        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            if attribute.get("clinicalAttributeId") != "WSI_PATIENT_SLIDE_COUNT":
                continue
            patient_id = attribute.get("patientId")
            value = attribute.get("value")
            try:
                numeric_value = int(value)
            except (TypeError, ValueError):
                continue
            if patient_id and numeric_value >= 0:
                patients.add(str(patient_id))
    if not patients:
        raise VerificationError(
            "clinical-data-table does not expose any patient-level WSI slide counts"
        )
    return len(rows), len(patients)


def _clickhouse_query(
    args: argparse.Namespace, query: str, *, timeout: int = 120
) -> list[list[str]]:
    """Run a bounded, tab-separated ClickHouse query without leaking credentials."""
    command = [
        "docker",
        "exec",
        args.clickhouse_container,
        "clickhouse-client",
        "--user",
        args.clickhouse_user,
        "--database",
        args.clickhouse_database,
        "--format",
        "TabSeparatedRaw",
        "--query",
        query,
    ]
    if args.clickhouse_password:
        command[2:2] = ["-e", f"CLICKHOUSE_PASSWORD={args.clickhouse_password}"]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        raise VerificationError("ClickHouse study-data query failed") from None
    return [line.split("\t") for line in completed.stdout.splitlines() if line.strip()]


def _data_file(study_dir: Path, name: str) -> Path:
    """Resolve a study data file while preventing metadata path traversal."""
    meta_path = study_dir / name
    if not meta_path.is_file():
        raise VerificationError(f"study directory is missing {name}")
    metadata: dict[str, str] = {}
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    filename = metadata.get("data_filename")
    if not filename:
        raise VerificationError(f"{name} is missing data_filename")
    path = (study_dir / filename).resolve()
    if path.parent != study_dir.resolve() or not path.is_file():
        raise VerificationError(f"data file referenced by {name} is missing or unsafe")
    return path


def _resolve_meta(study_dir: Path, *names: str) -> Path:
    """Resolve a metadata file across importer-supported naming variants.

    Public cBioPortal studies use both ``meta_mutations.txt`` and the more
    explicit ``meta_mutations_extended.txt`` spelling.  Gene-panel matrices
    likewise appear as ``meta_gene_panel_matrix.txt`` or
    ``meta_gene_matrix.txt``.  The importer accepts both forms, so the
    release verifier must not reject a valid study solely because of the
    filename variant.
    """
    for name in names:
        candidate = study_dir / name
        if candidate.is_file():
            return candidate
    raise VerificationError(f"study directory is missing {' or '.join(names)}")


def _meta_value(meta_path: Path, key: str) -> str | None:
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and ":" in line:
            name, value = line.split(":", 1)
            if name.strip() == key:
                return value.strip()
    return None


def _tabular_rows(path: Path) -> Iterable[dict[str, str]]:
    """Yield non-comment rows from a cBioPortal tab-delimited data file."""
    handle = path.open(encoding="utf-8", newline="")
    try:
        lines = (line for line in handle if line.strip() and not line.startswith("#"))
        reader = csv.DictReader(lines, delimiter="\t")
        if not reader.fieldnames:
            raise VerificationError(f"{path.name} has no tabular header")
        yield from reader
    finally:
        handle.close()


def _gene_symbol_map(args: argparse.Namespace) -> dict[str, set[int]]:
    """Return canonical and alias symbols mapped to all known Entrez IDs."""
    rows = _clickhouse_query(
        args,
        "SELECT toString(entrez_gene_id), hugo_gene_symbol FROM gene "
        "UNION ALL SELECT toString(entrez_gene_id), gene_alias FROM gene_alias",
        timeout=120,
    )
    symbols: dict[str, set[int]] = {}
    for row in rows:
        if len(row) != 2:
            continue
        try:
            entrez = int(row[0])
        except ValueError:
            continue
        symbols.setdefault(row[1].upper(), set()).add(entrez)
    return symbols


def _profile_id(args: argparse.Namespace, study_id: str, alteration_type: str) -> int:
    escaped = study_id.replace("'", "''")
    rows = _clickhouse_query(
        args,
        "SELECT toString(genetic_profile_id) FROM genetic_profile "
        f"WHERE cancer_study_id = (SELECT cancer_study_id FROM cancer_study "
        f"WHERE cancer_study_identifier = '{escaped}') "
        f"AND genetic_alteration_type = '{alteration_type}' LIMIT 1",
    )
    if not rows or not rows[0]:
        raise VerificationError(f"study is missing its {alteration_type} molecular profile")
    try:
        return int(rows[0][0])
    except ValueError:
        raise VerificationError(f"invalid {alteration_type} molecular profile id") from None


def _study_data_snapshot(args: argparse.Namespace, study_id: str, study_dir: Path) -> dict[str, Any]:
    """Count every source data category and its ClickHouse representation.

    The expected counts intentionally model importer semantics: any explicitly
    configured mutation filter, zero-width segments, and duplicate structural
    variants are called out rather than silently counted as missing data.
    """
    mutation_meta = _resolve_meta(study_dir, "meta_mutations.txt", "meta_mutations_extended.txt")
    cna_meta = _resolve_meta(study_dir, "meta_cna.txt", "meta_CNA.txt")
    sv_meta = _resolve_meta(study_dir, "meta_sv.txt")
    seg_meta = _resolve_meta(
        study_dir, "meta_cna_hg19_seg.txt", "mskimpact_meta_cna_hg19_seg.txt"
    )
    panel_meta = _resolve_meta(study_dir, "meta_gene_panel_matrix.txt", "meta_gene_matrix.txt")
    mutation_path = _data_file(study_dir, mutation_meta.name)
    cna_path = _data_file(study_dir, cna_meta.name)
    sv_path = _data_file(study_dir, sv_meta.name)
    seg_path = _data_file(study_dir, seg_meta.name)
    panel_path = _data_file(study_dir, panel_meta.name)

    configured_filter = _meta_value(mutation_meta, "variant_classification_filter")
    if configured_filter is None:
        raise VerificationError(
            f"{mutation_meta.name} must explicitly set variant_classification_filter; "
            "use __NONE__ to require every source mutation row or list intentional exclusions"
        )
    mutation_filter = (
        set()
        if configured_filter.strip() == "__NONE__"
        else {value.strip() for value in configured_filter.split(",") if value.strip()}
    )

    mutation_rows = 0
    mutation_filtered = 0
    mutation_samples: set[str] = set()
    mutation_symbols: set[str] = set()
    mutation_classifications: Counter[str] = Counter()
    for row in _tabular_rows(mutation_path):
        mutation_rows += 1
        mutation_symbols.add((row.get("Hugo_Symbol") or "").strip().upper())
        classification = (row.get("Variant_Classification") or "").strip()
        if classification in mutation_filter:
            mutation_filtered += 1
        else:
            mutation_classifications[classification] += 1
            sample = (row.get("Tumor_Sample_Barcode") or "").strip()
            if sample:
                mutation_samples.add(sample)

    cna_rows = 0
    cna_events = 0
    cna_samples: set[str] = set()
    cna_symbols: set[str] = set()
    with cna_path.open(encoding="utf-8", newline="") as handle:
        lines = (line for line in handle if line.strip() and not line.startswith("#"))
        reader = csv.reader(lines, delimiter="\t")
        try:
            header = next(reader)
        except StopIteration:
            raise VerificationError("CNA file has no header") from None
        if len(header) < 2 or header[0] != "Hugo_Symbol":
            raise VerificationError("CNA file has an invalid header")
        cna_sample_ids = [sample.strip() for sample in header[1:]]
        for row in reader:
            if not row:
                continue
            cna_rows += 1
            cna_symbols.add(row[0].strip().upper())
            for index, value in enumerate(row[1:]):
                value = value.strip()
                if value and value.upper() != "NA" and value not in {"0", "0.0"}:
                    cna_events += 1
                    if index < len(cna_sample_ids) and cna_sample_ids[index]:
                        cna_samples.add(cna_sample_ids[index])

    gene_symbols = _gene_symbol_map(args)
    missing_mutation_symbols = sorted(symbol for symbol in mutation_symbols if symbol and symbol not in gene_symbols)
    missing_cna_symbols = sorted(symbol for symbol in cna_symbols if symbol and symbol not in gene_symbols)

    sv_rows = 0
    sv_samples: set[str] = set()
    sv_keys: set[tuple[str, ...]] = set()
    sv_unresolved_rows = 0
    sv_unresolved_symbols: set[str] = set()
    for row in _tabular_rows(sv_path):
        sv_rows += 1
        sample = (row.get("Sample_Id") or "").strip()
        site1 = (row.get("Site1_Hugo_Symbol") or "").strip()
        site2 = (row.get("Site2_Hugo_Symbol") or "").strip()
        site1_ids = gene_symbols.get(site1.upper(), set())
        site2_ids = gene_symbols.get(site2.upper(), set())
        if not site1_ids and not site2_ids:
            sv_unresolved_rows += 1
            sv_unresolved_symbols.update(symbol for symbol in (site1, site2) if symbol)
            continue
        if sample:
            sv_samples.add(sample)

        def normalized_site(symbol: str, key: str) -> str:
            ids = gene_symbols.get(symbol.upper(), set())
            # ImportStructuralVariantData resolves an unambiguous symbol to
            # its canonical Entrez ID before constructing its duplicate key.
            return str(next(iter(ids))) if len(ids) == 1 else key

        sv_keys.add(
            (
                sample,
                normalized_site(site1, "null"),
                (row.get("Site1_Chromosome") or "").strip(),
                (row.get("Site1_Position") or "").strip() or "NA",
                (row.get("Site1_Region_Number") or "").strip() or "NA",
                (row.get("Site1_Ensembl_Transcript_Id") or "").strip() or "NA",
                normalized_site(site2, "null"),
                (row.get("Site2_Chromosome") or "").strip(),
                (row.get("Site2_Position") or "").strip() or "NA",
                (row.get("Site2_Region_Number") or "").strip() or "NA",
                (row.get("Site2_Ensembl_Transcript_Id") or "").strip() or "NA",
                (row.get("Event_Info") or "").strip() or "NA",
            )
        )

    seg_rows = 0
    seg_samples: set[str] = set()
    for row in _tabular_rows(seg_path):
        try:
            start = int((row.get("loc.start") or row.get("start") or "").strip())
            end = int((row.get("loc.end") or row.get("end") or "").strip())
        except ValueError:
            raise VerificationError("segment file contains a non-numeric interval") from None
        if start >= end:
            continue
        seg_rows += 1
        sample = (row.get("ID") or "").strip()
        if sample:
            seg_samples.add(sample)

    panel_rows = 0
    panel_mappings = 0
    panel_samples: set[str] = set()
    for row in _tabular_rows(panel_path):
        panel_rows += 1
        sample = (row.get("SAMPLE_ID") or "").strip()
        if sample:
            panel_samples.add(sample)
        for key, value in row.items():
            if key != "SAMPLE_ID" and value and value.strip() not in {"", "NA"}:
                panel_mappings += 1

    patient_path = _data_file(study_dir, "meta_clinical_patient.txt")
    sample_path = _data_file(study_dir, "meta_clinical_sample.txt")
    patient_ids = {(row.get("PATIENT_ID") or "").strip() for row in _tabular_rows(patient_path)}
    sample_ids = {(row.get("SAMPLE_ID") or "").strip() for row in _tabular_rows(sample_path)}
    patient_ids.discard("")
    sample_ids.discard("")

    resource_definition_meta = study_dir / "meta_resource_definition.txt"
    resource_patient_meta = study_dir / "meta_resource_patient.txt"
    source_resource_definitions = 0
    source_resource_patients = 0
    if resource_definition_meta.is_file() and resource_patient_meta.is_file():
        source_resource_definitions = sum(
            1 for _ in _tabular_rows(_data_file(study_dir, resource_definition_meta.name))
        )
        source_resource_patients = sum(
            1 for _ in _tabular_rows(_data_file(study_dir, resource_patient_meta.name))
        )

    mutation_profile = _profile_id(args, study_id, "MUTATION_EXTENDED")
    cna_profile = _profile_id(args, study_id, "COPY_NUMBER_ALTERATION")
    sv_profile = _profile_id(args, study_id, "STRUCTURAL_VARIANT")
    profile_ids = f"{mutation_profile},{cna_profile},{sv_profile}"
    db_rows = _clickhouse_query(
        args,
        "SELECT 'mutations', toString(count()), toString(uniqExact(sample_id)), '0' "
        f"FROM mutation WHERE genetic_profile_id = {mutation_profile} "
        "UNION ALL SELECT 'cna', toString(count()), toString(uniqExact(sample_id)), '0' "
        f"FROM sample_cna_event WHERE genetic_profile_id = {cna_profile} "
        "UNION ALL SELECT 'structural_variants', toString(count()), toString(uniqExact(sample_id)), '0' "
        f"FROM structural_variant WHERE genetic_profile_id = {sv_profile} "
        "UNION ALL SELECT 'segments', toString(count()), toString(uniqExact(sample_id)), '0' "
        "FROM copy_number_seg WHERE cancer_study_id = (SELECT cancer_study_id FROM cancer_study "
        f"WHERE cancer_study_identifier = '{study_id.replace(chr(39), chr(39) * 2)}') "
        "UNION ALL SELECT 'panel_mappings', toString(count()), toString(uniqExact(sample_id)), "
        f"toString(uniqExact(genetic_profile_id)) FROM sample_profile WHERE genetic_profile_id IN ({profile_ids})",
    )
    actual: dict[str, tuple[int, int, int]] = {}
    for row in db_rows:
        if len(row) != 4:
            raise VerificationError("ClickHouse study-data query returned an invalid row")
        try:
            actual[row[0]] = (int(row[1]), int(row[2]), int(row[3]))
        except ValueError:
            raise VerificationError("ClickHouse study-data query returned a non-numeric value") from None

    db_mutation_classifications = _clickhouse_query(
        args,
        "SELECT coalesce(me.mutation_type, ''), toString(count()) "
        "FROM mutation m INNER JOIN mutation_event me "
        "ON m.mutation_event_id = me.mutation_event_id "
        f"WHERE m.genetic_profile_id = {mutation_profile} "
        "GROUP BY me.mutation_type",
    )
    actual_mutation_classifications: Counter[str] = Counter()
    for row in db_mutation_classifications:
        if len(row) != 2:
            raise VerificationError("ClickHouse mutation classification query returned an invalid row")
        try:
            actual_mutation_classifications[row[0]] = int(row[1])
        except ValueError:
            raise VerificationError("ClickHouse mutation classification query returned a non-numeric value") from None

    expected = {
        "mutations": (mutation_rows - mutation_filtered, len(mutation_samples), 0),
        "cna": (cna_events, len(cna_samples), 0),
        "structural_variants": (len(sv_keys), len(sv_samples), 0),
        "segments": (seg_rows, len(seg_samples), 0),
        "panel_mappings": (panel_mappings, len(panel_samples), 3),
    }
    mismatches = []
    for category, values in expected.items():
        if actual.get(category) != values:
            mismatches.append(f"{category} expected {values}, loaded {actual.get(category)}")
    if actual_mutation_classifications != mutation_classifications:
        mismatches.append(
            "mutation classifications expected "
            f"{dict(sorted(mutation_classifications.items()))}, loaded "
            f"{dict(sorted(actual_mutation_classifications.items()))}"
        )
    if missing_mutation_symbols or missing_cna_symbols:
        mismatches.append(
            "unresolved mutation/CNA symbols: "
            + ", ".join((missing_mutation_symbols + missing_cna_symbols)[:20])
        )
    if sv_unresolved_rows:
        mismatches.append(f"{sv_unresolved_rows} SV rows have no recognized gene")
    if mismatches:
        raise VerificationError("study data completeness failed: " + "; ".join(mismatches))

    clinical_rows = _clickhouse_query(
        args,
        "SELECT toString(uniqExact(internal_id)) FROM patient WHERE cancer_study_id = "
        f"(SELECT cancer_study_id FROM cancer_study WHERE cancer_study_identifier = '{study_id.replace(chr(39), chr(39) * 2)}')",
    )
    clinical_sample_rows = _clickhouse_query(
        args,
        "SELECT toString(uniqExact(sample.internal_id)) FROM sample INNER JOIN patient "
        "ON sample.patient_id = patient.internal_id WHERE patient.cancer_study_id = "
        f"(SELECT cancer_study_id FROM cancer_study WHERE cancer_study_identifier = '{study_id.replace(chr(39), chr(39) * 2)}')",
    )
    resource_definition_rows = _clickhouse_query(
        args,
        "SELECT toString(count()) FROM resource_definition WHERE cancer_study_id = "
        f"(SELECT cancer_study_id FROM cancer_study WHERE cancer_study_identifier = '{study_id.replace(chr(39), chr(39) * 2)}')",
    )
    resource_patient_rows = _clickhouse_query(
        args,
        "SELECT toString(count()) FROM resource_patient r INNER JOIN patient p "
        "ON r.internal_id = p.internal_id WHERE p.cancer_study_id = "
        f"(SELECT cancer_study_id FROM cancer_study WHERE cancer_study_identifier = '{study_id.replace(chr(39), chr(39) * 2)}')",
    )
    try:
        loaded_patients = int(clinical_rows[0][0])
        loaded_samples = int(clinical_sample_rows[0][0])
        loaded_resource_definitions = int(resource_definition_rows[0][0])
        loaded_resource_patients = int(resource_patient_rows[0][0])
    except (IndexError, ValueError):
        raise VerificationError("clinical study counts could not be read from ClickHouse") from None
    if loaded_patients != len(patient_ids) or loaded_samples != len(sample_ids):
        raise VerificationError(
            "clinical study counts do not match the source: "
            f"patients {len(patient_ids)} vs {loaded_patients}, "
            f"samples {len(sample_ids)} vs {loaded_samples}"
        )
    if (
        source_resource_definitions != loaded_resource_definitions
        or source_resource_patients != loaded_resource_patients
    ):
        raise VerificationError(
            "resource data counts do not match the source: "
            f"definitions {source_resource_definitions} vs {loaded_resource_definitions}, "
            f"patients {source_resource_patients} vs {loaded_resource_patients}"
        )

    return {
        "source_mutation_rows": mutation_rows,
        "source_mutation_filtered_rows": mutation_filtered,
        "source_mutation_classifications": dict(sorted(mutation_classifications.items())),
        "database_mutation_classifications": dict(sorted(actual_mutation_classifications.items())),
        "database_mutation_rows": actual["mutations"][0],
        "source_cna_events": cna_events,
        "database_cna_events": actual["cna"][0],
        "source_sv_rows": sv_rows,
        "source_sv_duplicate_rows": sv_rows - len(sv_keys) - sv_unresolved_rows,
        "source_sv_unresolved_rows": sv_unresolved_rows,
        "database_sv_rows": actual["structural_variants"][0],
        "source_segment_rows": seg_rows,
        "database_segment_rows": actual["segments"][0],
        "source_gene_panel_mappings": panel_mappings,
        "database_gene_panel_mappings": actual["panel_mappings"][0],
        "source_patient_count": len(patient_ids),
        "database_patient_count": loaded_patients,
        "source_sample_count": len(sample_ids),
        "database_sample_count": loaded_samples,
        "source_resource_definition_count": source_resource_definitions,
        "database_resource_definition_count": loaded_resource_definitions,
        "source_resource_patient_count": source_resource_patients,
        "database_resource_patient_count": loaded_resource_patients,
        "gene_catalog_count": len(gene_symbols),
    }


def verify(args: argparse.Namespace) -> dict[str, Any]:
    portal_url = args.portal_url.rstrip("/")
    study_id = args.study_id
    encoded_study_id = urllib.parse.quote(study_id, safe="")
    if args.wsi_patient_id and not args.study_dir:
        raise VerificationError("--wsi-patient-id needs --study-dir")
    if args.wsi_patient_id and args.check_all_wsi:
        raise VerificationError("--wsi-patient-id cannot be combined with --check-all-wsi")
    if args.check_wsi_clinical_counts and not args.clickhouse_container:
        raise VerificationError(
            "--check-wsi-clinical-counts needs --clickhouse-container"
        )

    studies = _request_json(
        f"{portal_url}/api/studies?projection=DETAILED&pageSize=10000000&pageNumber=0",
        args.cookie,
    )
    record = _study_record(studies, study_id)
    sample_count = int(record.get("allSampleCount") or 0)
    if sample_count < args.min_samples:
        raise VerificationError(
            f"study catalog reports {sample_count} samples; expected at least {args.min_samples}"
        )
    catalog_status = record.get("status")
    if catalog_status not in (None, 1, "1"):
        raise VerificationError("study is present in the catalog but is not available")

    result: dict[str, Any] = {
        "study_id": study_id,
        "catalog_samples": sample_count,
    }

    if args.check_study_view:
        filtered_samples = _request_json_post(
            f"{portal_url}/api/filtered-samples/fetch",
            {"studyIds": [study_id]},
            args.cookie,
        )
        if not isinstance(filtered_samples, list):
            raise VerificationError("study-view sample response is not an array")
        if len(filtered_samples) != sample_count:
            raise VerificationError(
                "study-view sample count does not match the study catalog; "
                "derived tables may be missing or stale"
            )
        result["study_view_samples"] = len(filtered_samples)

    # Parse the WSI snapshot before timeline checks so a large study can be
    # queried patient-by-patient.  The study-wide clinical-events endpoint
    # materializes every event attribute in one response and can exhaust the
    # portal heap for cohorts with hundreds of thousands of events.
    wsi: dict[str, Any] | None = _parse_wsi_file(args.study_dir) if args.study_dir else None

    if args.check_timeline:
        timeline_dir = args.timeline_dir or args.study_dir
        if timeline_dir is None:
            raise VerificationError("--check-timeline needs --timeline-dir or --study-dir")
        timeline = _parse_timeline_file(timeline_dir)
        timeline_sampled = False
        if wsi is not None:
            if (
                wsi.get("timeline_events") is not None
                and wsi["timeline_events"] != timeline["events"]
            ):
                raise VerificationError(
                    "WSI snapshot manifest timeline event count does not match the "
                    "pathology timeline file"
                )
            def patient_events(patient_id: str) -> list[dict[str, Any]]:
                encoded_patient_id = urllib.parse.quote(patient_id, safe="")
                value = _request_json(
                    f"{portal_url}/api/studies/{encoded_study_id}/patients/"
                    f"{encoded_patient_id}/clinical-events?projection=SUMMARY"
                    "&pageSize=100000&pageNumber=0",
                    args.cookie,
                )
                return value if isinstance(value, list) else []

            # A focused patient run must remain focused.  Expanding a
            # ``--wsi-patient-id`` check to every patient defeats the purpose
            # of the option and can overwhelm the portal with tens of
            # thousands of requests (and hide the result behind an OOM).
            if args.wsi_patient_id:
                event_patients = [args.wsi_patient_id]
            elif args.timeline_patient_sample and args.check_all_wsi:
                # A full WSI hierarchy check can cover every patient without
                # issuing one clinical-events request per patient. Sample
                # event-bearing patients deterministically and compare the API
                # counts with the corresponding release rows.
                event_patients = _select_timeline_patients(
                    wsi["patients"],
                    timeline["patient_metrics"],
                    args.timeline_patient_sample,
                )
                timeline_sampled = True
            else:
                event_patients = wsi["patients"]
            with ThreadPoolExecutor(max_workers=24) as executor:
                event_batches = list(executor.map(patient_events, event_patients))
            events = [event for batch in event_batches for event in batch]
        else:
            events = _request_json(
                f"{portal_url}/api/studies/{encoded_study_id}/clinical-events",
                args.cookie,
            )
        if not isinstance(events, list):
            raise VerificationError("clinical-events response is not an array")
        pathology_events = [
            event
            for event in events
            if isinstance(event, dict) and event.get("eventType") == "PATHOLOGY SLIDES"
        ]
        expected_timeline = {
            "events": timeline["events"],
            "image_count": timeline["image_count"],
            "non_servable_image_count": timeline["non_servable_image_count"],
            "total_image_count": timeline["total_image_count"],
            "linkouts": timeline["linkouts"],
        }
        if args.wsi_patient_id:
            patient_metrics = timeline["patient_metrics"].get(args.wsi_patient_id)
            if patient_metrics is None:
                raise VerificationError(
                    f"pathology timeline has no events for {args.wsi_patient_id}"
                )
            expected_timeline = {
                "events": patient_metrics["events"],
                "image_count": patient_metrics["image_count"],
                "non_servable_image_count": patient_metrics["non_servable_image_count"],
                "total_image_count": patient_metrics["total_image_count"],
                "linkouts": patient_metrics["linkouts"],
            }
        elif args.timeline_patient_sample and args.check_all_wsi and wsi is not None:
            sampled_metrics = [
                timeline["patient_metrics"].get(patient_id, {})
                for patient_id in event_patients
            ]
            expected_timeline = {
                key: sum(int(metrics.get(key, 0)) for metrics in sampled_metrics)
                for key in (
                    "events",
                    "image_count",
                    "non_servable_image_count",
                    "total_image_count",
                    "linkouts",
                )
            }
        if len(pathology_events) != expected_timeline["events"]:
            raise VerificationError(
                "pathology timeline event count mismatch: "
                f"release={expected_timeline['events']} portal={len(pathology_events)}"
            )
        api_counts = {"image_count": 0, "non_servable_image_count": 0, "total_image_count": 0, "linkouts": 0}
        for event in pathology_events:
            attributes = {
                attribute.get("key"): attribute.get("value")
                for attribute in event.get("attributes", [])
                if isinstance(attribute, dict)
            }
            try:
                api_counts["image_count"] += int(attributes.get("IMAGE_COUNT") or 0)
                api_counts["non_servable_image_count"] += int(
                    attributes.get("NON_SERVABLE_IMAGE_COUNT") or 0
                )
                api_counts["total_image_count"] += int(attributes.get("TOTAL_IMAGE_COUNT") or 0)
            except (TypeError, ValueError):
                raise VerificationError("pathology timeline has a non-numeric API image count") from None
            api_counts["linkouts"] += bool(attributes.get("LINKOUT"))
        if api_counts != {
            "image_count": expected_timeline["image_count"],
            "non_servable_image_count": expected_timeline["non_servable_image_count"],
            "total_image_count": expected_timeline["total_image_count"],
            "linkouts": expected_timeline["linkouts"],
        }:
            raise VerificationError(
                "pathology timeline count mismatch: "
                f"release={expected_timeline['image_count']}/"
                f"{expected_timeline['non_servable_image_count']}/"
                f"{expected_timeline['total_image_count']}/"
                f"{expected_timeline['linkouts']} portal="
                f"{api_counts['image_count']}/"
                f"{api_counts['non_servable_image_count']}/"
                f"{api_counts['total_image_count']}/"
                f"{api_counts['linkouts']}"
            )
        timeline_linkout_urls: list[str] = []
        for event in pathology_events:
            attributes = {
                attribute.get("key"): attribute.get("value")
                for attribute in event.get("attributes", [])
                if isinstance(attribute, dict)
            }
            if attributes.get("LINKOUT"):
                timeline_linkout_urls.append(str(attributes["LINKOUT"]))
        result["timeline_events"] = expected_timeline["events"]
        result["timeline_linkouts"] = expected_timeline["linkouts"]
        if timeline_sampled:
            result["timeline_patients_checked"] = len(event_patients)
    else:
        timeline_linkout_urls = []

    if wsi is not None:
        result["wsi_file_rows"] = wsi["rows"]
        result["wsi_file_servable"] = wsi["servable"]
        if args.check_timeline and args.wsi_patient_id:
            patient_wsi_rows = len(wsi["patient_image_ids"].get(args.wsi_patient_id, set()))
            patient_timeline_rows = timeline["patient_total_image_counts"].get(
                args.wsi_patient_id, 0
            )
            # Date-less associations remain in the WSI hierarchy but are
            # intentionally absent from the date-based timeline.  Reject an
            # over-count (which indicates duplicate/unrelated events), while
            # allowing the validated undated remainder.
            if patient_timeline_rows > patient_wsi_rows:
                raise VerificationError(
                    "pathology timeline represents more slides than the WSI hierarchy for "
                    f"{args.wsi_patient_id}; timeline has {patient_timeline_rows} "
                    f"slides but the WSI snapshot has {patient_wsi_rows}"
                )
            result["wsi_patient_undated_timeline_slides"] = patient_wsi_rows - patient_timeline_rows
        if args.wsi_patient_id:
            if args.wsi_patient_id not in wsi["patient_image_ids"]:
                raise VerificationError(
                    f"WSI snapshot does not contain patient {args.wsi_patient_id}"
                )
            result["wsi_patient_id"] = args.wsi_patient_id
    if args.clickhouse_container:
        db_rows, db_servable = _clickhouse_wsi_counts(args, study_id)
        result["database_wsi_rows"] = db_rows
        result["database_wsi_servable"] = db_servable
        if wsi is not None and (db_rows != wsi["rows"] or db_servable != wsi["servable"]):
            raise VerificationError(
                "database WSI count mismatch: "
                f"release={wsi['rows']}/{wsi['servable']} "
                f"database={db_rows}/{db_servable}"
            )
        if args.check_wsi_clinical_counts:
            (
                expected_samples,
                missing_samples,
                mismatched_samples,
                expected_patients,
                missing_patients,
                mismatched_patients,
            ) = (
                _clickhouse_wsi_clinical_counts(args, study_id)
            )
            if expected_samples == 0:
                raise VerificationError("WSI clinical count check found no matched samples")
            if missing_samples or mismatched_samples or missing_patients or mismatched_patients:
                raise VerificationError(
                    "WSI clinical counts are missing or stale for "
                    f"{missing_samples + mismatched_samples} of {expected_samples} samples and "
                    f"{missing_patients + mismatched_patients} of {expected_patients} patients"
                )
            result["wsi_clinical_count_samples"] = expected_samples
            result["wsi_clinical_count_patients"] = expected_patients
            api_rows, api_patients = _portal_wsi_clinical_counts(args, study_id)
            result["wsi_clinical_api_rows"] = api_rows
            result["wsi_clinical_api_patient_values_on_first_page"] = api_patients
    if getattr(args, "check_all_data", False):
        if not args.study_dir:
            raise VerificationError("--check-all-data needs --study-dir")
        if not args.clickhouse_container:
            raise VerificationError("--check-all-data needs --clickhouse-container")
        result.update(_study_data_snapshot(args, study_id, args.study_dir))
    if args.require_wsi and wsi is None:
        raise VerificationError("--require-wsi needs --study-dir")
    if args.require_wsi and wsi is not None and wsi["servable"] == 0:
        raise VerificationError("WSI snapshot contains no servable slides")

    if wsi is not None or args.require_wsi:
        if wsi is None:
            raise VerificationError("WSI hierarchy check requires a study directory")
        portal_tile_url, portal_origin = _portal_tile_server(args, portal_url)
        result["wsi_tile_server"] = "configured"
        if args.check_all_access and not (args.check_all_wsi or args.wsi_patient_id):
            raise VerificationError(
                "--check-all-access requires --check-all-wsi or --wsi-patient-id"
            )
        if args.check_all_tiles and not (args.check_all_wsi or args.wsi_patient_id):
            raise VerificationError(
                "--check-all-tiles requires --check-all-wsi or --wsi-patient-id"
            )
        if args.check_all_tiles and not args.check_all_access:
            raise VerificationError("--check-all-tiles requires --check-all-access")
        if args.max_tile_checks is not None and args.max_tile_checks <= 0:
            raise VerificationError("--max-tile-checks must be positive")
        if args.max_tile_checks is not None and not args.check_all_tiles:
            raise VerificationError("--max-tile-checks requires --check-all-tiles")
        if args.timeline_patient_sample < 0:
            raise VerificationError("--timeline-patient-sample must not be negative")

        all_hierarchy_slides: list[dict[str, Any]] = []
        if args.check_all_wsi:
            expected_images = wsi["patient_image_ids"]
            expected_servable = wsi["servable_image_ids"]

            def check_patient(patient_id: str) -> tuple[list[dict[str, Any]] | None, bool]:
                try:
                    hierarchy = _request_json(
                        f"{portal_url}/api/wsi/v2/hierarchy/{encoded_study_id}/"
                        f"{urllib.parse.quote(patient_id, safe='')}",
                        args.cookie,
                    )
                    slides = _all_slides(hierarchy)
                    actual_images = {
                        str(slide.get("imageId")) for slide in slides if slide.get("imageId")
                    }
                    actual_servable = {
                        str(slide.get("imageId"))
                        for slide in slides
                        if slide.get("imageId") and slide.get("canServeTiles") is True
                    }
                    expected = expected_images.get(patient_id, set())
                    expected_serves = expected_servable.get(patient_id, set())
                    valid = (
                        len(actual_images) == len(slides)
                        and actual_images == expected
                        and actual_servable == expected_serves
                    )
                    return slides, valid
                except (VerificationError, TypeError, ValueError):
                    return None, False

            with ThreadPoolExecutor(max_workers=24) as executor:
                hierarchy_results = list(executor.map(check_patient, wsi["patients"]))
            invalid_hierarchies = sum(not valid for _, valid in hierarchy_results)
            if invalid_hierarchies:
                raise VerificationError(
                    f"{invalid_hierarchies} of {len(hierarchy_results)} WSI hierarchies "
                    "did not match the release snapshot"
                )
            slides_by_patient: dict[str, list[dict[str, Any]]] = {}
            for patient_id, (patient_slides, _) in zip(wsi["patients"], hierarchy_results):
                slide_list = patient_slides or []
                slides_by_patient[patient_id] = slide_list
                all_hierarchy_slides.extend(slide_list)
            if args.check_timeline:
                overcounted_patients = [
                    patient_id
                    for patient_id, patient_slides in slides_by_patient.items()
                    if timeline["patient_total_image_counts"].get(patient_id, 0)
                    > len(patient_slides)
                ]
                if overcounted_patients:
                    raise VerificationError(
                        "pathology timeline represents more slides than the WSI hierarchy "
                        f"for {len(overcounted_patients)} patient(s)"
                    )
            slides = all_hierarchy_slides
            servable_slides = [
                slide for slide in slides if slide.get("canServeTiles") is True
            ]
            result["hierarchy_patients"] = len(hierarchy_results)
        else:
            smoke_patient = args.wsi_patient_id or wsi["smoke_patient"]
            hierarchy = _request_json(
                f"{portal_url}/api/wsi/v2/hierarchy/{encoded_study_id}/"
                f"{urllib.parse.quote(smoke_patient, safe='')}",
                args.cookie,
            )
            slides = _all_slides(hierarchy)
            servable_slides = [
                slide for slide in slides if slide.get("canServeTiles") is True
            ]
            slides_by_patient = {smoke_patient: slides}
            if args.wsi_patient_id:
                actual_images = {
                    str(slide.get("imageId"))
                    for slide in slides
                    if slide.get("imageId")
                }
                actual_servable = {
                    str(slide.get("imageId"))
                    for slide in servable_slides
                    if slide.get("imageId")
                }
                expected_images = wsi["patient_image_ids"][args.wsi_patient_id]
                expected_servable = wsi["servable_image_ids"].get(
                    args.wsi_patient_id, set()
                )
                if (
                    actual_images != expected_images
                    or actual_servable != expected_servable
                ):
                    raise VerificationError(
                        "target WSI hierarchy does not match the release snapshot"
                    )

        if not slides:
            raise VerificationError("WSI hierarchy returned no slides")
        if args.require_wsi and not servable_slides:
            raise VerificationError("WSI hierarchy contains no servable slides")
        result["hierarchy_slides"] = len(slides)
        result["hierarchy_servable"] = len(servable_slides)
        if args.check_all_wsi and (
            len(slides) != wsi["rows"] or len(servable_slides) != wsi["servable"]
        ):
            raise VerificationError("WSI hierarchy totals differ from the release snapshot")
        if (
            args.expected_hierarchy_slides is not None
            and len(slides) != args.expected_hierarchy_slides
        ):
            raise VerificationError("WSI hierarchy slide count differs from the release expectation")
        if (
            args.expected_hierarchy_servable is not None
            and len(servable_slides) != args.expected_hierarchy_servable
        ):
            raise VerificationError(
                "WSI hierarchy servable count differs from the release expectation"
            )

        if args.check_timeline and args.check_all_wsi:
            result["timeline_linkouts_validated"] = _validate_pathology_timeline_capability(
                pathology_events, slides_by_patient
            )
        elif args.check_timeline and args.wsi_patient_id:
            result["timeline_linkouts_validated"] = _validate_pathology_timeline_capability(
                pathology_events, slides_by_patient
            )

        if args.check_access or args.check_all_access:
            if not servable_slides:
                raise VerificationError("WSI hierarchy has no servable slide for access smoke test")
            access_targets = (
                servable_slides
                if args.check_all_access
                else _select_wsi_sample(wsi, servable_slides, args.wsi_sample_size)
            )
            if not access_targets:
                raise VerificationError("WSI hierarchy has no selectable servable slide")
            if args.check_all_tiles and args.max_tile_checks is not None:
                if args.max_tile_checks >= len(access_targets):
                    tile_targets = access_targets
                elif args.max_tile_checks == 1:
                    tile_targets = access_targets[:1]
                else:
                    # Spread bounded checks across the deterministic hierarchy
                    # order so a large study is not represented by one patient.
                    tile_targets = [
                        access_targets[round(index * (len(access_targets) - 1) / (args.max_tile_checks - 1))]
                        for index in range(args.max_tile_checks)
                    ]
            else:
                tile_targets = access_targets
            tile_target_ids = {
                str(slide.get("imageId")) for slide in tile_targets if slide.get("imageId")
            }

            def check_access(slide: dict[str, Any]) -> tuple[bool, bool, bool]:
                try:
                    image_id = str(slide["imageId"])
                    access_url = (
                        f"{portal_url}/api/wsi/v2/slides/{encoded_study_id}/"
                        f"{urllib.parse.quote(image_id, safe='')}/access"
                    )
                    access = _request_json(access_url, args.cookie)
                    token = access.get("accessToken") if isinstance(access, dict) else None
                    source = access.get("sourceUrl") if isinstance(access, dict) else None
                    metadata = access.get("tileMetadata") if isinstance(access, dict) else None
                    thumbnail = access.get("thumbnail") if isinstance(access, dict) else None
                    complete = (
                        bool(token)
                        and bool(source)
                        and isinstance(metadata, dict)
                        and bool(metadata.get("dimensions"))
                        and isinstance(thumbnail, dict)
                        and bool(thumbnail.get("sourceUrl"))
                    )
                    if not complete:
                        return False, False, False
                    if not portal_tile_url:
                        return True, True, True
                    thumbnail_url = (
                        f"{portal_tile_url.rstrip('/')}/thumbnails?"
                        + urllib.parse.urlencode(
                            {
                                "source": thumbnail["sourceUrl"],
                                "width": thumbnail.get("width", 256),
                                "height": thumbnail.get("height", 256),
                            }
                        )
                    )
                    thumbnail_ok = (
                        _request_bytes(
                            thumbnail_url, bearer=token, origin=portal_origin
                        )
                        == 200
                    )
                    if not thumbnail_ok:
                        return True, False, False
                    tile_ok = True
                    should_check_tile = args.check_access or (
                        args.check_all_tiles and image_id in tile_target_ids
                    )
                    if should_check_tile:
                        metadata_level = _safe_tile_level(metadata)
                        tile_url = (
                            f"{portal_tile_url.rstrip('/')}/tiles/zxy/"
                            f"{max(0, metadata_level)}/0/0"
                        )
                        tile_ok = (
                            _request_bytes(
                                tile_url,
                                bearer=token,
                                source=source,
                                origin=portal_origin,
                            )
                            == 200
                        )
                    return True, True, tile_ok
                except (VerificationError, KeyError, TypeError, ValueError):
                    return False, False, False

            # Keep the verifier below the tile server's image-operation gate.
            # Sending hundreds of cache-miss tile requests at once only adds
            # queueing (and can exhaust memory) without increasing coverage.
            access_workers = 2 if args.check_all_tiles else 8
            with ThreadPoolExecutor(max_workers=access_workers) as executor:
                access_results = list(executor.map(check_access, access_targets))
            incomplete = sum(not bundle for bundle, _, _ in access_results)
            thumbnail_failures = sum(
                bundle and not thumbnail for bundle, thumbnail, _ in access_results
            )
            tile_failures = sum(
                bundle and thumbnail and not tile
                for bundle, thumbnail, tile in access_results
            )
            if incomplete or thumbnail_failures or tile_failures:
                raise VerificationError(
                    f"WSI access validation failed for {incomplete} slide bundles and "
                    f"{thumbnail_failures} thumbnails and {tile_failures} tiles"
                )
            if args.check_all_access:
                result["access_bundles"] = len(access_targets)
            else:
                result["access_bundle"] = "ok"
            if args.check_all_access:
                result["thumbnails"] = len(access_targets)
                if args.check_all_tiles:
                    result["tiles"] = len(tile_targets)
            else:
                result["thumbnail"] = "ok"
                if args.check_access:
                    result["tile"] = "ok"
            result["wsi_access_sample"] = len(access_targets)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portal-url",
        default=os.environ.get("PORTAL_URL", "http://localhost:8080"),
        help="cBioPortal base URL (default: PORTAL_URL or http://localhost:8080)",
    )
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--study-dir", type=Path)
    parser.add_argument(
        "--timeline-dir",
        type=Path,
        help="directory containing the pathology timeline files (defaults to --study-dir)",
    )
    parser.add_argument(
        "--cookie",
        default=os.environ.get("VERIFY_COOKIE", ""),
        help="optional portal session cookie for authenticated smoke checks",
    )
    parser.add_argument("--min-samples", type=int, default=1)
    parser.add_argument(
        "--clickhouse-container",
        default=os.environ.get("CLICKHOUSE_CONTAINER", ""),
        help="optional local ClickHouse container for an imported-row count check",
    )
    parser.add_argument(
        "--clickhouse-user",
        default=os.environ.get("CLICKHOUSE_USER", "cbio_user"),
    )
    parser.add_argument(
        "--clickhouse-database",
        default=os.environ.get("CLICKHOUSE_DB", "cbioportal"),
    )
    parser.add_argument("--expected-wsi-rows", type=int)
    parser.add_argument("--expected-wsi-servable", type=int)
    parser.add_argument("--expected-hierarchy-slides", type=int)
    parser.add_argument("--expected-hierarchy-servable", type=int)
    parser.add_argument(
        "--check-study-view",
        action="store_true",
        help="verify the unfiltered study-view sample query matches the catalog",
    )
    parser.add_argument(
        "--check-timeline",
        action="store_true",
        help="verify pathology timeline event counts and linkouts through the portal API",
    )
    parser.add_argument(
        "--timeline-patient-sample",
        type=int,
        default=int(os.environ.get("TIMELINE_PATIENT_SAMPLE", "0")),
        help=(
            "when checking every WSI hierarchy, cap clinical-event requests to a "
            "deterministic sample of event-bearing patients (0 means all)"
        ),
    )
    parser.add_argument(
        "--check-all-wsi",
        action="store_true",
        help="verify every patient hierarchy and compare every slide to the snapshot",
    )
    parser.add_argument(
        "--wsi-patient-id",
        help="target one patient for hierarchy/access smoke checks (requires --study-dir)",
    )
    parser.add_argument(
        "--check-all-access",
        action="store_true",
        help="verify access bundles and thumbnail requests for every servable slide",
    )
    parser.add_argument(
        "--check-all-tiles",
        action="store_true",
        help="also issue an authenticated tile request for every servable slide (slow/heavy)",
    )
    parser.add_argument(
        "--max-tile-checks",
        type=int,
        help="cap tile requests while retaining full access/thumbnail coverage",
    )
    parser.add_argument("--require-wsi", action="store_true")
    parser.add_argument(
        "--check-wsi-clinical-counts",
        action="store_true",
        help="verify sample- and patient-level WSI counts used by the Study View Clinical Data tab",
    )
    parser.add_argument(
        "--check-all-data",
        action="store_true",
        help=(
            "compare all source clinical, mutation, CNA, SV, segment, and gene-panel "
            "rows with their ClickHouse representations"
        ),
    )
    parser.add_argument("--check-access", action="store_true")
    parser.add_argument(
        "--wsi-sample-size",
        type=int,
        default=int(os.environ.get("WSI_SAMPLE_SIZE", "1")),
        help="number of distinct servable slides to exercise when --check-access is used",
    )
    parser.add_argument(
        "--tile-url",
        default="",
        help=(
            "deprecated expected tile URL assertion; the actual URL is always read "
            "from the portal config_service"
        ),
    )
    parser.add_argument(
        "--expected-tile-url",
        default=os.environ.get("EXPECTED_WSI_TILE_SERVER_URL", ""),
        help="assert the portal-advertised tile URL matches this deployment endpoint",
    )
    # Keep credentials out of argv (and therefore out of process listings).
    parser.set_defaults(clickhouse_password=os.environ.get("CLICKHOUSE_PASSWORD", ""))
    args = parser.parse_args()

    try:
        result = verify(args)
        if args.expected_wsi_rows is not None and result.get("wsi_file_rows") != args.expected_wsi_rows:
            raise VerificationError("WSI row count differs from the release expectation")
        if (
            args.expected_wsi_servable is not None
            and result.get("wsi_file_servable") != args.expected_wsi_servable
        ):
            raise VerificationError("WSI servable count differs from the release expectation")
        print(json.dumps(result, sort_keys=True))
    except VerificationError as error:
        print(f"verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
