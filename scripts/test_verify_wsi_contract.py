#!/usr/bin/env python3
"""Dependency-free contract tests for the stack WSI release gates."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from builtins import ValueError
from argparse import Namespace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent
E2E_SCRIPT = (ROOT / "verify-databricks-wsi-e2e.sh").read_text()
STACK_SCRIPT = (ROOT / "verify-stack-release.sh").read_text()


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = _load("verify_study_load", ROOT / "verify-study-load.py")
STACK = _load("verify_stack_release", ROOT / "verify-stack-release.py")
EXPORT = _load("export_databricks_wsi_snapshot", ROOT / "export_databricks_wsi_snapshot.py")
RECONCILE = _load(
    "reconcile_pathology_timeline_capabilities",
    ROOT / "reconcile_pathology_timeline_capabilities.py",
)


class PortalTileContractTests(unittest.TestCase):
    def test_release_verifiers_use_dev_tables_and_bound_event_requests(self):
        self.assertIn('databricks_target="${DATABRICKS_TARGET:-dev}"', E2E_SCRIPT)
        self.assertIn(
            'canonical_default="cdsi_prod.pathology_data_mining_dev.canonical_slide_associations"',
            E2E_SCRIPT,
        )
        self.assertIn("s3://ocra/", E2E_SCRIPT)
        self.assertIn(
            '--timeline-patient-sample "${TIMELINE_PATIENT_SAMPLE:-24}"',
            E2E_SCRIPT,
        )
        self.assertIn(
            'args+=(--timeline-patient-sample "${TIMELINE_PATIENT_SAMPLE:-24}")',
            STACK_SCRIPT,
        )

    def test_portal_config_is_authoritative_and_cross_origin_is_preflighted(self):
        args = Namespace(cookie="", expected_tile_url="https://tiles.example.test/")
        with mock.patch.object(
            VERIFY, "_request_json", return_value={"msk_wsi_tile_server_url": "https://tiles.example.test"}
        ), mock.patch.object(VERIFY, "_request_cors_preflight") as preflight:
            tile_url, origin = VERIFY._portal_tile_server(args, "https://portal.example.test")

        self.assertEqual(tile_url, "https://tiles.example.test")
        self.assertEqual(origin, "https://portal.example.test")
        self.assertEqual(
            [call.args for call in preflight.call_args_list],
            [
                ("https://tiles.example.test/thumbnails", "https://portal.example.test"),
                ("https://tiles.example.test/tiles/zxy/0/0/0", "https://portal.example.test"),
            ],
        )

    def test_portal_config_mismatch_fails_even_when_legacy_tile_url_is_set(self):
        args = Namespace(
            cookie="", expected_tile_url="https://wrong.example.test", tile_url="https://wrong.example.test"
        )
        with mock.patch.object(
            VERIFY, "_request_json", return_value={"msk_wsi_tile_server_url": "https://tiles.example.test"}
        ):
            with self.assertRaisesRegex(VERIFY.VerificationError, "differs from the expected"):
                VERIFY._portal_tile_server(args, "https://portal.example.test")

    def test_sample_selection_spans_patients_and_is_stable(self):
        wsi = {
            "servable_image_ids": {
                "patient-b": {"slide-b2", "slide-b1"},
                "patient-a": {"slide-a1"},
            }
        }
        slides = [
            {"imageId": "slide-b2", "canServeTiles": True},
            {"imageId": "slide-a1", "canServeTiles": True},
            {"imageId": "slide-b1", "canServeTiles": True},
            {"imageId": "not-servable", "canServeTiles": False},
        ]
        sample = VERIFY._select_wsi_sample(wsi, slides, 2)
        self.assertEqual([slide["imageId"] for slide in sample], ["slide-a1", "slide-b1"])

    def test_timeline_patient_sampling_is_bounded_and_event_focused(self):
        patients = ["patient-a", "patient-b", "patient-c", "patient-d"]
        metrics = {
            "patient-a": {"events": 1},
            "patient-c": {"events": 2},
            "patient-d": {"events": 3},
        }
        self.assertEqual(
            VERIFY._select_timeline_patients(patients, metrics, 2),
            ["patient-a", "patient-d"],
        )
        self.assertEqual(
            VERIFY._select_timeline_patients(patients, metrics, 0),
            ["patient-a", "patient-c", "patient-d"],
        )

    def test_timeline_capability_check_rejects_non_servable_linkout(self):
        event = {
            "attributes": [
                {"key": "IMAGE_COUNT", "value": "2"},
                {"key": "NON_SERVABLE_IMAGE_COUNT", "value": "0"},
                {"key": "TOTAL_IMAGE_COUNT", "value": "2"},
                {
                    "key": "LINKOUT",
                    "value": (
                        "/patient/wsiHESlides?caseId=P-1&sampleId=S-1&"
                        "stainFilter=hne&matchLevel=BLOCK&specimenKey=block::part:1::block:A1"
                    ),
                },
            ]
        }
        slides = [
            {
                "imageId": "slide-1",
                "sampleId": "S-1",
                "matchLevel": "BLOCK",
                "specimenKey": "block::part:1::block:A1",
                "isHne": True,
                "isIhc": False,
                "canServeTiles": False,
            },
            {
                "imageId": "slide-2",
                "sampleId": "S-1",
                "matchLevel": "BLOCK",
                "specimenKey": "block::part:1::block:A1",
                "isHne": True,
                "isIhc": False,
                "canServeTiles": False,
            },
        ]
        with self.assertRaisesRegex(
            VERIFY.VerificationError, "non-servable WSI group"
        ):
            VERIFY._validate_pathology_timeline_capability(
                [event], {"P-1": slides}
            )

    def test_timeline_capability_check_accepts_non_servable_event_without_linkout(self):
        event = {
            "attributes": [
                {"key": "IMAGE_COUNT", "value": "0"},
                {"key": "NON_SERVABLE_IMAGE_COUNT", "value": "2"},
                {"key": "TOTAL_IMAGE_COUNT", "value": "2"},
            ]
        }
        self.assertEqual(
            VERIFY._validate_pathology_timeline_capability([event], {"P-1": []}),
            1,
        )

    def test_timeline_capability_check_rejects_unaccounted_slides_without_linkout(self):
        event = {
            "attributes": [
                {"key": "IMAGE_COUNT", "value": "0"},
                {"key": "NON_SERVABLE_IMAGE_COUNT", "value": "0"},
                {"key": "TOTAL_IMAGE_COUNT", "value": "1"},
            ]
        }
        with self.assertRaisesRegex(VERIFY.VerificationError, "inconsistent"):
            VERIFY._validate_pathology_timeline_capability([event], {"P-1": []})


class DatabricksExportContractTests(unittest.TestCase):
    @staticmethod
    def _study_fixture(root: Path) -> Path:
        study_dir = root / "study_a"
        study_dir.mkdir()
        (study_dir / "meta_study.txt").write_text(
            "cancer_study_identifier: study_a\n", encoding="utf-8"
        )
        (study_dir / "data_clinical_sample.txt").write_text(
            "PATIENT_ID\tSAMPLE_ID\nP-1\tS-1\n", encoding="utf-8"
        )
        return study_dir

    def test_export_rejects_a_cohort_row_that_would_be_filtered(self):
        with tempfile.TemporaryDirectory() as temporary:
            study_dir = self._study_fixture(Path(temporary))
            record = {
                "patient_id": "P-1",
                "sample_id": "",
                "match_level": "INVALID",
                "image_id": "slide-1",
                "can_serve_tiles": False,
            }
            with mock.patch.object(EXPORT, "_run_external_query", return_value=[record]):
                with self.assertRaisesRegex(ValueError, "filtered 1 rows"):
                    with mock.patch.object(
                        EXPORT.sys, "argv", ["export", "--study-dir", str(study_dir)]
                    ):
                        EXPORT.main()

    def test_export_rejects_a_study_with_no_servable_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            study_dir = self._study_fixture(Path(temporary))
            record = {
                "patient_id": "P-1",
                "match_level": "UNMATCHED",
                "image_id": "slide-1",
                "can_serve_tiles": False,
            }
            with mock.patch.object(EXPORT, "_run_external_query", return_value=[record]):
                with self.assertRaisesRegex(ValueError, "no servable WSI assets"):
                    with mock.patch.object(
                        EXPORT.sys, "argv", ["export", "--study-dir", str(study_dir)]
                    ):
                        EXPORT.main()

    def test_tile_metadata_accepts_date_like_sha256_fingerprint(self):
        metadata = {
            "dimensions": {"width": 100, "height": 80},
            "levels": 1,
            "level_dimensions": [{"width": 100, "height": 80}],
            "max_zoom": 0,
            "tile_size": 256,
            # Contains the date-like substring 20395333, which is valid
            # inside a digest and must not be treated as PHI.
            "source_fingerprint": "a" * 10 + "20395333" + "b" * 46,
        }
        self.assertTrue(EXPORT._metadata_is_safe_and_valid(metadata))

    def test_export_preserves_a_matched_row_marked_non_servable(self):
        with tempfile.TemporaryDirectory() as temporary:
            study_dir = self._study_fixture(Path(temporary))
            record = {
                "patient_id": "P-1",
                "sample_id": "S-1",
                "match_level": "PART",
                "image_id": "slide-1",
                "can_serve_tiles": False,
            }
            values = EXPORT._row(
                record,
                {"P-1"},
                {"S-1"},
                {"S-1": "P-1"},
                require_complete_assets=True,
                asset_stats={"canonical_servable": 0, "incomplete": 0},
            )
            self.assertIsNotNone(values)
            self.assertEqual(values[EXPORT.DATA_COLUMNS.index("CAN_SERVE_TILES")], "FALSE")
            self.assertEqual(values[EXPORT.DATA_COLUMNS.index("SOURCE_URL")], "")

    def test_export_downgrades_sample_outside_study_to_unmatched(self):
        record = {
            "patient_id": "P-1",
            "sample_id": "S-not-in-study",
            "match_level": "PART",
            "image_id": "slide-1",
            "can_serve_tiles": False,
        }
        values = EXPORT._row(
            record,
            {"P-1"},
            {"S-1"},
            {"S-1": "P-1"},
            require_complete_assets=True,
            asset_stats={"canonical_servable": 0, "incomplete": 0},
        )
        self.assertIsNotNone(values)
        self.assertEqual(values[EXPORT.DATA_COLUMNS.index("MATCH_LEVEL")], "UNMATCHED")
        self.assertEqual(values[EXPORT.DATA_COLUMNS.index("SAMPLE_ID")], "")

    def test_export_fails_closed_for_canonical_servable_row_without_metadata(self):
        record = {
            "patient_id": "P-1",
            "match_level": "UNMATCHED",
            "image_id": "slide-1",
            "can_serve_tiles": True,
            "slide_path": "s3://mskmind-bkt/reef-slides/slide-1.svs",
            "serving_artifact_uri": "s3://mskmind-bkt/wsi-thumbnails/slide-1.jpg",
            "tile_metadata_json": "",
        }
        with self.assertRaisesRegex(ValueError, "asset contract is incomplete"):
            EXPORT._row(
                record,
                {"P-1"},
                set(),
                {},
                require_complete_assets=True,
                asset_stats={"canonical_servable": 0, "incomplete": 0},
            )

    def test_export_diagnostic_escape_hatch_keeps_the_association_non_servable(self):
        record = {
            "patient_id": "P-1",
            "match_level": "UNMATCHED",
            "image_id": "slide-1",
            "can_serve_tiles": True,
            "slide_path": "s3://mskmind-bkt/reef-slides/slide-1.svs",
            "serving_artifact_uri": "s3://mskmind-bkt/wsi-thumbnails/slide-1.jpg",
            "tile_metadata_json": "",
        }
        values = EXPORT._row(
            record,
            {"P-1"},
            set(),
            {},
            require_complete_assets=False,
            asset_stats={"canonical_servable": 0, "incomplete": 0},
        )
        self.assertIsNotNone(values)
        self.assertEqual(values[EXPORT.DATA_COLUMNS.index("CAN_SERVE_TILES")], "FALSE")

    def test_export_accepts_all_configured_s3_source_prefixes(self):
        record = {
            "patient_id": "P-1",
            "match_level": "UNMATCHED",
            "image_id": "slide-pathology",
            "can_serve_tiles": True,
            "slide_path": "s3://pathology/CRC_21-167/slides/slide-pathology.svs",
            "artifact_uri": "s3://mskmind-bkt/wsi-thumbnails/slide-pathology.jpg",
            "tile_metadata_json": json.dumps(
                {
                    "dimensions": {"width": 1024, "height": 1024},
                    "levels": 1,
                    "level_dimensions": [{"width": 1024, "height": 1024}],
                    "max_zoom": 0,
                    "tile_size": 256,
                }
            ),
            "width": 1024,
            "height": 1024,
            "content_type": "image/jpeg",
        }
        prefixes = EXPORT._source_prefixes(
            [
                "s3://mskmind-bkt/reef-slides/",
                "s3://pathology/CRC_21-167/slides/",
            ]
        )
        values = EXPORT._row(
            record,
            {"P-1"},
            set(),
            {},
            require_complete_assets=True,
            asset_stats={"canonical_servable": 0, "incomplete": 0},
            allowed_source_prefixes=prefixes,
        )
        self.assertIsNotNone(values)
        self.assertEqual(values[EXPORT.DATA_COLUMNS.index("CAN_SERVE_TILES")], "TRUE")

    def test_source_prefixes_reject_invalid_s3_prefixes(self):
        with self.assertRaisesRegex(ValueError, "invalid S3 prefix"):
            EXPORT._source_prefixes(["s3://"])

    def test_timeline_record_uses_final_wsi_capability(self):
        values = [""] * len(EXPORT.DATA_COLUMNS)
        for name, value in {
            "PATIENT_ID": "P-1",
            "SAMPLE_ID": "S-1",
            "IMAGE_ID": "slide-1",
            "MATCH_LEVEL": "BLOCK",
            "SPECIMEN_KEY": "block::part:1::block:A1",
            "IS_HNE": "TRUE",
            "IS_IHC": "FALSE",
            "CAN_SERVE_TILES": "FALSE",
        }.items():
            values[EXPORT.DATA_COLUMNS.index(name)] = value
        values.extend(("-5", "AVAILABLE", "source"))

        record = EXPORT._timeline_record(values)

        self.assertFalse(record["can_serve_tiles"])


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_requires_pixel_snapshot_and_complete_timeline_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            study_dir = Path(temporary) / "study"
            study_dir.mkdir()
            (study_dir / "meta_wsi.txt").write_text(
                "cancer_study_identifier: study_a\ndata_filename: data_wsi.txt\n", encoding="utf-8"
            )
            (study_dir / "data_wsi.txt").write_text("PATIENT_ID\tIMAGE_ID\nP\tI\n", encoding="utf-8")
            (study_dir / "wsi_snapshot_manifest.json").write_text(
                json.dumps(
                    {
                        "study_id": "study_a",
                        "association_row_count": 1,
                        "servable_row_count": 1,
                        "patient_count": 1,
                        "incomplete_asset_count": 0,
                        "filtered_row_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text(
                json.dumps({"version": 1, "studies": [{"study_id": "study_a", "study_dir": str(study_dir)}]}),
                encoding="utf-8",
            )
            self.assertEqual(STACK._read_manifest(manifest)[0]["study_id"], "study_a")

            timeline_dir = Path(temporary) / "timeline"
            timeline_dir.mkdir()
            (timeline_dir / "meta_clinical_timeline_pathology_slides.txt").write_text("", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "studies": [
                            {
                                "study_id": "study_a",
                                "study_dir": str(study_dir),
                                "timeline_dir": str(timeline_dir),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(STACK.VerificationError, "incomplete pathology timeline"):
                STACK._read_manifest(manifest)

    def test_manifest_rejects_incomplete_wsi_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            study_dir = Path(temporary) / "study"
            study_dir.mkdir()
            (study_dir / "meta_wsi.txt").write_text(
                "cancer_study_identifier: study_a\ndata_filename: data_wsi.txt\n",
                encoding="utf-8",
            )
            (study_dir / "data_wsi.txt").write_text("PATIENT_ID\tIMAGE_ID\nP\tI\n", encoding="utf-8")
            (study_dir / "wsi_snapshot_manifest.json").write_text(
                json.dumps(
                    {
                        "study_id": "study_a",
                        "association_row_count": 1,
                        "servable_row_count": 1,
                        "patient_count": 1,
                        "incomplete_asset_count": 1,
                        "filtered_row_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {"version": 1, "studies": [{"study_id": "study_a", "study_dir": str(study_dir)}]}
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(STACK.VerificationError, "incomplete WSI assets"):
                STACK._read_manifest(manifest)

    def test_manifest_rejects_duplicate_studies(self):
        with tempfile.TemporaryDirectory() as temporary:
            study_dir = Path(temporary) / "study"
            study_dir.mkdir()
            (study_dir / "meta_wsi.txt").write_text(
                "cancer_study_identifier: study_a\ndata_filename: data_wsi.txt\n", encoding="utf-8"
            )
            (study_dir / "data_wsi.txt").write_text("PATIENT_ID\tIMAGE_ID\nP\tI\n", encoding="utf-8")
            (study_dir / "wsi_snapshot_manifest.json").write_text(
                json.dumps(
                    {
                        "study_id": "study_a",
                        "association_row_count": 1,
                        "servable_row_count": 1,
                        "patient_count": 1,
                        "incomplete_asset_count": 0,
                        "filtered_row_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            manifest = Path(temporary) / "manifest.json"
            entry = {"study_id": "study_a", "study_dir": str(study_dir)}
            manifest.write_text(json.dumps({"version": 1, "studies": [entry, entry]}), encoding="utf-8")
            with self.assertRaisesRegex(STACK.VerificationError, "duplicates study"):
                STACK._read_manifest(manifest)

    def test_manifest_rejects_a_study_id_mismatch_in_meta_wsi(self):
        with tempfile.TemporaryDirectory() as temporary:
            study_dir = Path(temporary) / "study"
            study_dir.mkdir()
            (study_dir / "meta_wsi.txt").write_text(
                "cancer_study_identifier: source_id\ndata_filename: data_wsi.txt\n",
                encoding="utf-8",
            )
            (study_dir / "data_wsi.txt").write_text("PATIENT_ID\tIMAGE_ID\nP\tI\n", encoding="utf-8")
            (study_dir / "wsi_snapshot_manifest.json").write_text(
                json.dumps(
                    {
                        "study_id": "source_id",
                        "association_row_count": 1,
                        "servable_row_count": 1,
                        "patient_count": 1,
                        "incomplete_asset_count": 0,
                        "filtered_row_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text(
                json.dumps({"version": 1, "studies": [{"study_id": "portal_id", "study_dir": str(study_dir)}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(STACK.VerificationError, "different cancer_study_identifier"):
                STACK._read_manifest(manifest)

    def test_manifest_rejects_a_declared_source_without_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            study_dir = Path(temporary) / "study"
            study_dir.mkdir()
            (study_dir / "meta_wsi.txt").write_text(
                "cancer_study_identifier: study_a\ndata_filename: data_wsi.txt\n", encoding="utf-8"
            )
            (study_dir / "data_wsi.txt").write_text("PATIENT_ID\tIMAGE_ID\nP\tI\n", encoding="utf-8")
            (study_dir / "meta_mutations.txt").write_text(
                "cancer_study_identifier: study_a\ndata_filename: data_mutations.txt\n", encoding="utf-8"
            )
            (study_dir / "wsi_snapshot_manifest.json").write_text(
                json.dumps(
                    {
                        "study_id": "study_a",
                        "association_row_count": 1,
                        "servable_row_count": 1,
                        "patient_count": 1,
                        "incomplete_asset_count": 0,
                        "filtered_row_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text(
                json.dumps({"version": 1, "studies": [{"study_id": "study_a", "study_dir": str(study_dir)}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(STACK.VerificationError, "references missing or unsafe data"):
                STACK._read_manifest(manifest)


class TimelineRepairTests(unittest.TestCase):
    def test_reconcile_removes_linkout_for_a_non_servable_slide(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wsi = root / "data_wsi.txt"
            wsi.write_text(
                "PATIENT_ID\tSAMPLE_ID\tIMAGE_ID\tMATCH_LEVEL\tSPECIMEN_KEY\tIS_HNE\tIS_IHC\tCAN_SERVE_TILES\n"
                "P-1\tS-1\tslide-1\tBLOCK\tblock::part:1::block:A1\tTRUE\tFALSE\tFALSE\n",
                encoding="utf-8",
            )
            timeline = root / "data_clinical_timeline_pathology_slides.txt"
            timeline.write_text(
                "PATIENT_ID\tSTART_DATE\tEVENT_TYPE\tIMAGE_COUNT\tNON_SERVABLE_IMAGE_COUNT\tTOTAL_IMAGE_COUNT\tLINKOUT\n"
                "P-1\t0\tPATHOLOGY SLIDES\t1\t0\t1\t"
                "/patient/wsiHESlides?caseId=P-1&sampleId=S-1&stainFilter=hne&"
                "matchLevel=BLOCK&specimenKey=block%3A%3Apart%3A1%3A%3Ablock%3AA1\n",
                encoding="utf-8",
            )

            result = RECONCILE.reconcile(wsi, timeline)

            self.assertEqual(result["rows_changed"], 1)
            row = next(iter(RECONCILE._rows(timeline)))
            self.assertEqual(row["IMAGE_COUNT"], "0")
            self.assertEqual(row["NON_SERVABLE_IMAGE_COUNT"], "1")
            self.assertEqual(row["TOTAL_IMAGE_COUNT"], "1")
            self.assertEqual(row["LINKOUT"], "")

    def test_reconcile_can_drop_an_association_absent_from_the_wsi_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wsi = root / "data_wsi.txt"
            wsi.write_text(
                "PATIENT_ID\tSAMPLE_ID\tIMAGE_ID\tMATCH_LEVEL\tSPECIMEN_KEY\tIS_HNE\tIS_IHC\tCAN_SERVE_TILES\n",
                encoding="utf-8",
            )
            timeline = root / "data_clinical_timeline_pathology_slides.txt"
            timeline.write_text(
                "PATIENT_ID\tSTART_DATE\tEVENT_TYPE\tIMAGE_COUNT\tNON_SERVABLE_IMAGE_COUNT\tTOTAL_IMAGE_COUNT\tLINKOUT\n"
                "P-1\t0\tPATHOLOGY SLIDES\t1\t0\t1\t"
                "/patient/wsiHESlides?caseId=P-1&stainFilter=hne&matchLevel=BLOCK&"
                "specimenKey=block%3A%3Apart%3A1%3A%3Ablock%3AA1\n",
                encoding="utf-8",
            )

            result = RECONCILE.reconcile(wsi, timeline, drop_unresolved=True)

            self.assertEqual(result["rows_changed"], 1)
            self.assertEqual(list(RECONCILE._rows(timeline)), [])


if __name__ == "__main__":
    unittest.main()
