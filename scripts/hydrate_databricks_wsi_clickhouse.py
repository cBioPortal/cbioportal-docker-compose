#!/usr/bin/env python3
"""Hydrate cBioPortal ClickHouse WSI tables from the Databricks contract.

This is deliberately a database-to-database loader rather than a study-file
shortcut.  It resolves every de-identified Databricks association against the
target portal's patient/sample tables, keeps explicit non-servable provenance,
loads the five WSI tables and the six WSI count attributes, and materializes
the pathology timeline in ``clinical_event``/``clinical_event_data``.

The loader is idempotent for studies represented by the current Databricks
snapshot.  It only replaces WSI rows, WSI count attributes, and pathology
timeline events for those studies; unrelated clinical events and studies are
left untouched.  No PHI table is queried.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import export_databricks_wsi_snapshot as exporter  # noqa: E402

_TIMELINE_MODULE = None
try:
    from tools import generate_pathology_timeline_files as _TIMELINE_MODULE  # type: ignore
except ImportError:  # pragma: no cover - only possible in an incomplete checkout
    pass

WSI_ATTRS = (
    ("WSI_SAMPLE_SLIDE_COUNT", "WSI Slides per Sample", "Associated pathology slide count for the sample.", 0),
    ("WSI_SAMPLE_PART_MATCHED_SLIDE_COUNT", "WSI Slides per Sample, Part-matched", "Associated pathology slides matched to a specimen part.", 0),
    ("WSI_SAMPLE_BLOCK_MATCHED_SLIDE_COUNT", "WSI Slides per Sample, Block-matched", "Associated pathology slides matched to a specimen block.", 0),
    ("WSI_PATIENT_SLIDE_COUNT", "WSI Slides per Patient", "Associated pathology slide count for the patient.", 1),
    ("WSI_PATIENT_PART_MATCHED_SLIDE_COUNT", "WSI Slides per Patient, Part-matched", "Associated pathology slides matched to a specimen part for the patient.", 1),
    ("WSI_PATIENT_BLOCK_MATCHED_SLIDE_COUNT", "WSI Slides per Patient, Block-matched", "Associated pathology slides matched to a specimen block for the patient.", 1),
)

DATA_COLUMNS = exporter.DATA_COLUMNS


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--clickhouse-config", type=Path, required=True,
                   help="0600-mode clickhouse-client YAML config")
    p.add_argument("--clickhouse-bin", default="clickhouse")
    p.add_argument("--database", required=True)
    p.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_WAREHOUSE_ID", "0b49b7d78734ad5c"))
    p.add_argument("--canonical-table", default="cdsi_prod.pathology_data_mining.canonical_slide_associations")
    p.add_argument("--registry-table", default="cdsi_prod.pathology_data_mining.slide_thumbnail_registry")
    p.add_argument("--allowed-source-prefix", dest="allowed_source_prefixes", action="append",
                   help="repeat for each approved S3 source prefix")
    p.add_argument("--keep-staging", action="store_true",
                   help="keep the temporary SQLite staging database for diagnosis")
    p.add_argument("--staging-db", type=Path,
                   help="reuse a completed SQLite staging database (skips Databricks scan)")
    return p.parse_args()


def _run_client(args: argparse.Namespace, query: str, *, multiquery: bool = False,
                capture: bool = True) -> str:
    command = [args.clickhouse_bin, "client", "--config-file", str(args.clickhouse_config),
               "--database", args.database, "--mutations_sync", "2"]
    if multiquery:
        command.append("--multiquery")
        input_text = query
    else:
        command.extend(["--query", query])
        input_text = None
    result = subprocess.run(command, input=input_text, text=True,
                            capture_output=capture, check=False)
    if result.returncode:
        raise RuntimeError(f"clickhouse query failed (exit {result.returncode}): {result.stderr[-4000:]}")
    return result.stdout if capture else ""


def _query_rows(args: argparse.Namespace, query: str) -> list[list[str]]:
    output = _run_client(args, query).strip("\n")
    if not output:
        return []
    rows: list[list[str]] = []
    for line in output.splitlines():
        values = []
        for value in line.split("\t"):
            values.append("" if value == r"\N" else value)
        rows.append(values)
    return rows


def _sql_ids(values: Iterable[int]) -> str:
    unique = sorted({int(value) for value in values})
    if not unique:
        return "0"
    return ",".join(str(value) for value in unique)


def _tsv(value: Any, *, nullable: bool = False) -> str:
    if value is None or (nullable and value == ""):
        return r"\N"
    if isinstance(value, bool):
        return "1" if value else "0"
    text = str(value)
    # ClickHouse TSV escaping; all published free text has already had tabs and
    # newlines normalized by the exporter, but metadata JSON can contain '\\'.
    return (text.replace("\\", "\\\\").replace("\t", "\\t")
            .replace("\n", "\\n").replace("\r", "\\r"))


def _insert_stream(args: argparse.Namespace, table: str, columns: list[str],
                   rows: Iterable[Iterable[Any]], nullable: set[int] | None = None) -> int:
    nullable = nullable or set()
    command = [args.clickhouse_bin, "client", "--config-file", str(args.clickhouse_config),
               "--database", args.database, "--mutations_sync", "2", "--query",
               f"INSERT INTO {table} ({', '.join(columns)}) FORMAT TSV"]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    count = 0
    assert process.stdin is not None
    broken_pipe = False
    try:
        for row in rows:
            try:
                process.stdin.write("\t".join(_tsv(value, nullable=index in nullable)
                                              for index, value in enumerate(row)) + "\n")
            except BrokenPipeError:
                broken_pipe = True
                break
            count += 1
        if not broken_pipe:
            process.stdin.close()
        stderr = process.stderr.read() if process.stderr is not None else ""
        code = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise
    if code or broken_pipe:
        raise RuntimeError(f"insert into {table} failed (exit {code}): {stderr[-4000:]}")
    return count


def _load_target_maps(args: argparse.Namespace) -> tuple[dict[str, list[tuple[int, int]]],
                                                          dict[str, list[tuple[int, int, int, str]]],
                                                          dict[int, str]]:
    patient_rows = _query_rows(args, "SELECT stable_id, internal_id, cancer_study_id FROM patient FORMAT TSV")
    patient_stable_by_internal: dict[int, str] = {}
    patient_study_by_internal: dict[int, int] = {}
    patient_targets: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for stable, internal, study in patient_rows:
        if not stable:
            continue
        internal_id, study_id = int(internal), int(study)
        patient_stable_by_internal[internal_id] = stable
        patient_study_by_internal[internal_id] = study_id
        patient_targets[stable].append((study_id, internal_id))

    # cBioPortal's sample table stores the owning patient, not a study column;
    # resolve the study through the already-loaded patient map.
    sample_rows = _query_rows(args, "SELECT stable_id, internal_id, patient_id FROM sample FORMAT TSV")
    sample_targets: dict[str, list[tuple[int, int, int, str]]] = defaultdict(list)
    for stable, internal, patient_internal in sample_rows:
        if not stable:
            continue
        sample_internal, patient_internal_id = int(internal), int(patient_internal)
        patient_stable = patient_stable_by_internal.get(patient_internal_id, "")
        # A sample belongs to exactly the study owning its internal patient.
        # Do not fan it out to every study that happens to reuse the same
        # de-identified patient stable identifier (study aliases/clones are
        # common in the portal database).
        study_id = patient_study_by_internal.get(patient_internal_id)
        if study_id is not None:
            sample_targets[stable].append((study_id, sample_internal, patient_internal_id, patient_stable))
    return patient_targets, sample_targets, patient_stable_by_internal


def _candidate_targets(record: dict[str, Any], patient_targets, sample_targets):
    patient = exporter._text(record.get("patient_id"))
    sample = exporter._text(record.get("sample_id"))
    candidates = []
    if sample:
        candidates.extend(item for item in sample_targets.get(sample, [])
                         if item[3] == patient)
    # A canonical sample can be absent from a study's sample table.  Retain it
    # as an unmatched slide in every study containing the patient rather than
    # dropping valid pathology provenance.
    if not candidates:
        candidates.extend((study, 0, patient_internal, patient)
                          for study, patient_internal in patient_targets.get(patient, []))
    seen = set()
    for item in candidates:
        key = (item[0], item[2])
        if key not in seen:
            seen.add(key)
            yield item


def _rank(values: list[str]) -> str:
    levels = {"BLOCK": "0", "PART": "1", "UNMATCHED": "2"}
    return "{}|{}|{}|{}".format(
        levels.get(values[DATA_COLUMNS.index("MATCH_LEVEL")], "3"),
        "0" if values[DATA_COLUMNS.index("SAMPLE_ID")] else "1",
        "0" if values[DATA_COLUMNS.index("CAN_SERVE_TILES")] == "TRUE" else "1",
        values[DATA_COLUMNS.index("SAMPLE_ID")],
    )


def _stage(args: argparse.Namespace, db: sqlite3.Connection, patient_targets, sample_targets,
           patient_stable_by_internal, prefixes) -> dict[str, int]:
    stats = defaultdict(int)
    asset_stats: dict[str, int] = {}
    selected = 0
    for record in exporter._run_export_query(args.canonical_table, args.registry_table, args.warehouse_id):
        stats["databricks_rows"] += 1
        patient = exporter._text(record.get("patient_id"))
        targets = list(_candidate_targets(record, patient_targets, sample_targets))
        if not targets:
            stats["unmatched_patient_rows"] += 1
            continue
        for study_id, sample_internal, patient_internal, patient_stable in targets:
            canonical_sample = exporter._text(record.get("sample_id"))
            valid_sample = canonical_sample and sample_internal and sample_targets.get(canonical_sample)
            if valid_sample:
                valid_sample = any(item[0] == study_id and item[1] == sample_internal and item[2] == patient_internal
                                   for item in sample_targets[canonical_sample])
            normalized = dict(record)
            normalized["sample_id"] = canonical_sample if valid_sample else None
            reference = exporter._text(record.get("reference_sample_id"))
            reference_internal = None
            if reference:
                for item in sample_targets.get(reference, []):
                    if item[0] == study_id and item[2] == patient_internal:
                        reference_internal = item[1]
                        break
            normalized["reference_sample_id"] = reference if reference_internal is not None else None
            values = exporter._row(
                normalized,
                {patient_stable},
                {canonical_sample} if valid_sample else set(),
                {canonical_sample: patient_stable} if valid_sample else {},
                require_complete_assets=False,
                asset_stats=asset_stats,
                allowed_source_prefixes=prefixes,
            )
            if values is None:
                stats["filtered_rows"] += 1
                continue
            row_key = (study_id, patient_internal, values[DATA_COLUMNS.index("IMAGE_ID")])
            rank_key = _rank(values)
            payload = json.dumps(values, separators=(",", ":"))
            timing = [str(record.get(name) or "") for name in exporter.TIMELINE_COLUMNS]
            timing_json = json.dumps(timing, separators=(",", ":"))
            db.execute(
                """INSERT INTO slides(study_id,patient_internal,image_id,sample_internal,
                   reference_internal,rank_key,values_json,timing_json)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(study_id,patient_internal,image_id) DO UPDATE SET
                   sample_internal=excluded.sample_internal,
                   reference_internal=excluded.reference_internal,
                   rank_key=excluded.rank_key, values_json=excluded.values_json,
                   timing_json=excluded.timing_json
                   WHERE excluded.rank_key < slides.rank_key""",
                (study_id, patient_internal, row_key[2], sample_internal or None,
                 reference_internal, rank_key, payload, timing_json),
            )
            selected += 1
        if stats["databricks_rows"] % 100_000 == 0:
            print(f"scanned {stats['databricks_rows']:,} Databricks rows; selected attempts {selected:,}", file=sys.stderr, flush=True)
        if stats["databricks_rows"] % 10_000 == 0:
            db.commit()
    db.commit()
    stats.update(asset_stats)
    stats["selected_rows"] = db.execute("SELECT count(*) FROM slides").fetchone()[0]
    stats["study_count"] = db.execute("SELECT count(DISTINCT study_id) FROM slides").fetchone()[0]
    return dict(stats)


def _cleanup(args: argparse.Namespace, study_ids: list[int]) -> None:
    ids = _sql_ids(study_ids)
    for table in ("wsi_slide_placement", "wsi_slide", "wsi_block", "wsi_part", "wsi_patient"):
        _run_client(args, f"ALTER TABLE {table} DELETE WHERE cancer_study_id IN ({ids})")
    # ReplacingMergeTree does not remove old versions immediately, so remove
    # WSI count attributes before inserting this snapshot.  The subqueries are
    # constrained to the selected studies and cannot affect other attributes.
    attr_ids = ",".join("'" + attr[0] + "'" for attr in WSI_ATTRS)
    sample_entity = ("SELECT s.internal_id FROM sample s INNER JOIN patient p "
                     "ON s.patient_id = p.internal_id WHERE p.cancer_study_id IN "
                     f"({ids})")
    for table, entity_query in (("clinical_sample", sample_entity),
                                ("clinical_patient", f"SELECT internal_id FROM patient WHERE cancer_study_id IN ({ids})")):
        query = (f"ALTER TABLE {table} DELETE WHERE attr_id IN ({attr_ids}) "
                 f"AND internal_id IN ({entity_query})")
        existing_query = query.replace(
            f"ALTER TABLE {table} DELETE WHERE ",
            f"SELECT count() FROM {table} WHERE ",
            1,
        )
        existing = _query_rows(args, existing_query)
        if existing and existing[0] and int(existing[0][0]) > 0:
            _run_client(args, query)
    meta_query = (f"ALTER TABLE clinical_attribute_meta DELETE WHERE attr_id IN ({attr_ids}) "
                  f"AND cancer_study_id IN ({ids})")
    meta_count = _query_rows(args, meta_query.replace(
        "ALTER TABLE clinical_attribute_meta DELETE WHERE ",
        "SELECT count() FROM clinical_attribute_meta WHERE ",
        1,
    ))
    if meta_count and int(meta_count[0][0]) > 0:
        _run_client(args, meta_query)

    old_event_ids = _query_rows(args, f"SELECT e.clinical_event_id FROM clinical_event e INNER JOIN patient p ON e.patient_id=p.internal_id WHERE e.event_type='PATHOLOGY SLIDES' AND p.cancer_study_id IN ({ids}) FORMAT TSV")
    event_ids = [int(row[0]) for row in old_event_ids if row and row[0]]
    for offset in range(0, len(event_ids), 5000):
        chunk = _sql_ids(event_ids[offset:offset + 5000])
        _run_client(args, f"ALTER TABLE clinical_event_data DELETE WHERE clinical_event_id IN ({chunk})")
        _run_client(args, f"ALTER TABLE clinical_event DELETE WHERE clinical_event_id IN ({chunk})")


def _iter_slides(db: sqlite3.Connection):
    return db.execute("SELECT study_id,patient_internal,image_id,sample_internal,reference_internal,values_json,timing_json FROM slides ORDER BY study_id,patient_internal,image_id")


def _populate_tables(args: argparse.Namespace, db: sqlite3.Connection, study_ids: list[int]) -> None:
    # Build patient rows and counts in a compact dictionary; hierarchy metadata
    # is bounded by distinct parts/blocks, not the number of image pixels.
    patients: dict[tuple[int, int], tuple[int | None, int, int, int]] = {}
    parts: dict[tuple[int, int, str], tuple[str, ...]] = {}
    blocks: dict[tuple[int, int, str, str], tuple[str, ...]] = {}
    sample_counts: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0, 0])
    patient_counts: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0, 0])

    def slide_rows(*, count_rows: bool):
        for study, patient, image, sample, reference, values_json, timing_json in _iter_slides(db):
            values = json.loads(values_json)
            sample = int(sample) if sample is not None else None
            reference = int(reference) if reference is not None else None
            level = values[DATA_COLUMNS.index("MATCH_LEVEL")]
            patients.setdefault((study, patient), (reference, 0, 0, 0))
            current = patients[(study, patient)]
            if current[0] is None and reference is not None:
                patients[(study, patient)] = (reference, current[1], current[2], current[3])
            part_key = values[DATA_COLUMNS.index("PART_KEY")]
            block_key = values[DATA_COLUMNS.index("BLOCK_KEY")]
            # part_key is the map key and is supplied separately to the
            # insert row; retain only the six nullable metadata columns here.
            parts.setdefault((study, patient, part_key), tuple(values[index] or None for index in (5, 6, 7, 8, 9, 10)))
            blocks.setdefault((study, patient, part_key, block_key), tuple(values[index] or None for index in (12, 13)))
            if count_rows and sample is not None:
                counts = sample_counts[(study, sample)]
                counts[0] += 1
                if level == "PART": counts[1] += 1
                if level == "BLOCK": counts[2] += 1
            if count_rows:
                counts = patient_counts[(study, patient)]
                counts[0] += 1
                if level == "PART": counts[1] += 1
                if level == "BLOCK": counts[2] += 1
            yield study, patient, image, sample, values, json.loads(timing_json)

    # Materialize the compact hierarchy/count dictionaries before opening any
    # ClickHouse insert stream.  ``slide_rows`` is intentionally a generator;
    # creating it alone does not populate ``patients`` or ``parts``.
    for _ in slide_rows(count_rows=True):
        pass
    slides_for_insert = slide_rows(count_rows=False)
    _insert_stream(args, "wsi_patient", ["cancer_study_id", "patient_id", "reference_sample_id"],
                   ((study, patient, data[0]) for (study, patient), data in sorted(patients.items())), {2})
    _insert_stream(args, "wsi_part", ["cancer_study_id", "patient_id", "part_key", "part_number", "part_designator", "part_type", "part_description", "subspecialty", "path_dx_title"],
                   ((study, patient, part_key, *data) for (study, patient, part_key), data in sorted(parts.items())), {3, 4, 5, 6, 7, 8})
    _insert_stream(args, "wsi_block", ["cancer_study_id", "patient_id", "part_key", "block_key", "block_number", "block_label"],
                   ((study, patient, part_key, block_key, *data) for (study, patient, part_key, block_key), data in sorted(blocks.items())), {4, 5})
    _insert_stream(args, "wsi_slide", ["cancer_study_id", "patient_id", "image_id", "stain_name", "stain_group", "is_hne", "is_ihc", "magnification", "file_size_bytes", "can_serve_tiles", "barcode", "slide_type", "source_url", "tile_metadata_json", "thumbnail_url", "thumbnail_width", "thumbnail_height", "thumbnail_content_type"],
                   ((study, patient, image, values[16] or None, values[17] or None, values[18] == "TRUE", values[19] == "TRUE", values[20] or None, int(values[21]) if values[21] else None, values[24] == "TRUE", values[22] or None, values[23] or None, values[25] or None, values[26] or None, values[27] or None, int(values[28]) if values[28] else None, int(values[29]) if values[29] else None, values[30] or None) for study, patient, image, sample, values, timing in slides_for_insert), {3, 4, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17})
    # The generator above is exhausted after wsi_slide; rescan for placements
    # and timeline aggregation.
    placements = ((study, patient, image, values[4], values[11], sample, values[14], values[15])
                  for study, patient, image, sample, values, timing in slide_rows(count_rows=False))
    _insert_stream(args, "wsi_slide_placement", ["cancer_study_id", "patient_id", "image_id", "part_key", "block_key", "sample_id", "match_level", "specimen_key"], placements, {5})

    # Attributes are inserted after old rows were removed.  Counts include all
    # selected associations, including explicitly non-servable slides.
    _insert_stream(args, "clinical_attribute_meta", ["attr_id", "display_name", "description", "datatype", "patient_attribute", "priority", "cancer_study_id"],
                   ((attr_id, display, description, "NUMBER", patient_attribute, "1", study)
                    for study in study_ids for attr_id, display, description, patient_attribute in WSI_ATTRS))
    _insert_stream(args, "clinical_sample", ["internal_id", "attr_id", "attr_value"],
                   ((sample, attr_id, str(value)) for (study, sample), values in sorted(sample_counts.items())
                    for attr_id, value in zip((WSI_ATTRS[0][0], WSI_ATTRS[1][0], WSI_ATTRS[2][0]), values)))
    _insert_stream(args, "clinical_patient", ["internal_id", "attr_id", "attr_value"],
                   ((patient, attr_id, str(value)) for (study, patient), values in sorted(patient_counts.items())
                    for attr_id, value in zip((WSI_ATTRS[3][0], WSI_ATTRS[4][0], WSI_ATTRS[5][0]), values)))


def _timeline_from_slides(db: sqlite3.Connection, study_stable_by_id: dict[int, str]) -> list[tuple[int, int, int | None, str, list[tuple[str, str]]]]:
    """Build timeline events with the shared pathology grouping semantics."""
    if _TIMELINE_MODULE is None:
        raise RuntimeError("shared pathology timeline formatter is unavailable")
    groups: dict[tuple[int, str, int, str, str, str, str], dict[str, Any]] = {}
    for study, patient_internal, image, sample_internal, _reference, values_json, timing_json in _iter_slides(db):
        values = json.loads(values_json)
        timing = json.loads(timing_json)
        start, status, source = timing
        if not start or (status and status.upper() != "AVAILABLE"):
            continue
        try:
            start_int = int(start)
        except ValueError:
            continue
        subtype = _TIMELINE_MODULE._infer_slide_type(values[17] or None, values[16] or None,
                                                      values[18] == "TRUE", values[19] == "TRUE")
        if subtype is None:
            continue
        raw_match = values[14].upper()
        match = _TIMELINE_MODULE._match_level_display_value(raw_match)
        sample_display = values[2] if values[2] else _TIMELINE_MODULE._sample_display_value(None, raw_match)
        specimen_key = values[15]
        specimen = _TIMELINE_MODULE._format_specimen_label(
            raw_match,
            int(values[5]) if values[5] and values[5].isdigit() else None,
            values[8] or None,
            values[13] or None,
            values[12] or "",
        )
        servable = values[24] == "TRUE"
        grouping_token = specimen_key if servable else specimen
        key = (study, values[0], start_int, sample_display, match, specimen, grouping_token, subtype)
        group = groups.setdefault(key, {"images": set(), "servable": set(), "sources": set(), "patient": patient_internal})
        group["images"].add(image)
        (group["servable"] if servable else group.setdefault("nonservable", set())).add(image)
        timepoint_source = ("Procedure date relative to first ICD-O diagnosis" if status.upper() == "AVAILABLE" else status or source)
        if timepoint_source:
            group["sources"].add(_TIMELINE_MODULE._clean_timeline_text(str(timepoint_source)))
    events = []
    for key, group in sorted(groups.items()):
        study, patient_stable, start, sample_display, match, specimen, _token, subtype = key
        study_stable = study_stable_by_id[study]
        servable_count = len(group["servable"])
        nonservable_count = len(group.get("nonservable", set()))
        linkout = _TIMELINE_MODULE._build_linkout(study_stable, patient_stable, sample_display, subtype, match, key[6], servable_count)
        data = [("SAMPLE_ID", sample_display), ("SUBTYPE", subtype), ("MATCH_LEVEL", match),
                ("SPECIMEN", specimen), ("IMAGE_COUNT", str(servable_count)),
                ("NON_SERVABLE_IMAGE_COUNT", str(nonservable_count)),
                ("TOTAL_IMAGE_COUNT", str(servable_count + nonservable_count)),
                ("TIMEPOINT_SOURCE", ", ".join(sorted(group["sources"]))), ("LINKOUT", linkout)]
        events.append((study, group["patient"], start, None, "PATHOLOGY SLIDES", data))
    return events


def _insert_timeline(args: argparse.Namespace, db: sqlite3.Connection, study_stable_by_id: dict[int, str]) -> int:
    events = _timeline_from_slides(db, study_stable_by_id)
    max_id_rows = _query_rows(args, "SELECT coalesce(max(clinical_event_id), 0) FROM clinical_event FORMAT TSV")
    next_id = int(max_id_rows[0][0]) if max_id_rows else 0
    event_rows = []
    data_rows = []
    for offset, (_study, patient, start, stop, event_type, data) in enumerate(events, start=1):
        event_id = next_id + offset
        event_rows.append((event_id, patient, start, stop, event_type))
        data_rows.extend((event_id, key, value) for key, value in data if value != "")
    _insert_stream(args, "clinical_event", ["clinical_event_id", "patient_id", "start_date", "stop_date", "event_type"], event_rows, {3})
    _insert_stream(args, "clinical_event_data", ["clinical_event_id", "key", "value"], data_rows)
    return len(events)


def main() -> int:
    args = _args()
    if not args.clickhouse_config.is_file() or (args.clickhouse_config.stat().st_mode & 0o077):
        raise RuntimeError("ClickHouse config must exist and be mode 0600")
    if shutil.which(args.clickhouse_bin) is None and not Path(args.clickhouse_bin).is_file():
        raise RuntimeError(f"ClickHouse client not found: {args.clickhouse_bin}")
    prefixes = exporter._source_prefixes(args.allowed_source_prefixes)
    patient_targets, sample_targets, patient_stable_by_internal = _load_target_maps(args)
    study_rows = _query_rows(args, "SELECT cancer_study_id, cancer_study_identifier FROM cancer_study FORMAT TSV")
    study_stable_by_id = {int(row[0]): row[1] for row in study_rows if row[1]}
    staging_path = args.staging_db.resolve() if args.staging_db else Path(tempfile.mkstemp(prefix="wsi_hydration_", suffix=".sqlite")[1])
    owns_staging = args.staging_db is None
    try:
        db = sqlite3.connect(staging_path)
        if args.staging_db:
            table_check = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='slides'").fetchone()
            if not table_check:
                raise RuntimeError(f"staging database has no slides table: {staging_path}")
            stats = {"selected_rows": db.execute("SELECT count(*) FROM slides").fetchone()[0],
                     "study_count": db.execute("SELECT count(DISTINCT study_id) FROM slides").fetchone()[0],
                     "resumed_from_staging": 1}
        else:
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("PRAGMA synchronous=OFF")
            db.execute("CREATE TABLE slides (study_id INTEGER NOT NULL, patient_internal INTEGER NOT NULL, image_id TEXT NOT NULL, sample_internal INTEGER, reference_internal INTEGER, rank_key TEXT NOT NULL, values_json TEXT NOT NULL, timing_json TEXT NOT NULL, PRIMARY KEY(study_id, patient_internal, image_id))")
            stats = _stage(args, db, patient_targets, sample_targets, patient_stable_by_internal, prefixes)
        if stats.get("selected_rows", 0) == 0:
            raise RuntimeError("Databricks WSI data did not overlap any target patient/sample; refusing to mutate ClickHouse")
        study_ids = [row[0] for row in db.execute("SELECT DISTINCT study_id FROM slides ORDER BY study_id")]
        print(json.dumps({"stage": stats, "study_ids": study_ids, "allowed_source_prefixes": prefixes}, sort_keys=True), flush=True)
        _cleanup(args, study_ids)
        _populate_tables(args, db, study_ids)
        timeline_count = _insert_timeline(args, db, study_stable_by_id)
        db.close()
        # Rebuild all derived tables after WSI clinical attributes/events.
        print(f"inserted {timeline_count:,} pathology timeline events; rebuilding derived tables", flush=True)
        migrate = Path(__file__).resolve().parents[2] / "cbioportal-prod-migration-rehearsal/src/main/resources/db-scripts/clickhouse/migrate/migrate_db.py"
        env = os.environ.copy()
        env["CLICKHOUSE_DB"] = args.database
        # The migration runner uses the same config-file convention but takes
        # its credentials from env; invoke its SQL population script directly.
        populate = migrate.parent.parent / "populate_derived_tables.sql"
        command = [args.clickhouse_bin, "client", "--config-file", str(args.clickhouse_config),
                   "--database", args.database, "--mutations_sync", "2", "--multiquery",
                   "--queries-file", str(populate), "--param_optimize_backoff_secs", "0"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(f"derived-table rebuild failed: {result.stderr[-4000:]}")
        print(json.dumps({"hydrated": True, "selected_rows": stats["selected_rows"], "study_count": len(study_ids), "timeline_event_count": timeline_count}, sort_keys=True), flush=True)
    finally:
        db_path_exists = staging_path.exists()
        try:
            db.close()
        except Exception:
            pass
        if owns_staging and not args.keep_staging and db_path_exists:
            staging_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"WSI hydration failed: {exc}", file=sys.stderr)
        raise
