"""Transferred artifacts retain identity, target observations and null semantics."""
from __future__ import annotations

import copy
import csv
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from backend.app.batch import file_hash
from backend.app.research_models import ResearchFilters, ResearchReport
from backend.app.research_reports import ROOT, research_csv, research_report
from backend.app.storage import atomic_json
from scripts.week4_package import release_evidence, replay, tree_hashes, verify_package
from tests.test_batch_dashboard import batch_core

QUOTE = "batch-8fb19849d67c"


def change_csv(content, change):
    reader = csv.DictReader(io.StringIO(content))
    fields, rows = reader.fieldnames, list(reader)
    change(rows)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class ResearchExportIntegrityTests(unittest.TestCase):
    def test_every_target_gold_distribution_is_exported_without_detector_rates(self):
        for batch in (QUOTE, "batch-bd093a919251", "batch-fb671ff629f0"):
            report = research_report(batch)
            rows = list(csv.DictReader(io.StringIO(research_csv(report))))
            observed = [r for r in rows if r["row_kind"] == "target_gold_count"]
            actual = {(r["group_id"], r["gold_label"]): int(r["gold_count"]) for r in observed}
            expected = {(g["group_id"], label): count for g in report.target_gold_groups
                        for label, count in g["fresh_ai_gold_counts"].items()}
            self.assertTrue(expected)
            self.assertEqual(actual, expected)
            self.assertEqual(sum(actual.values()), report.counts["target_observations"])
            for row in observed:
                self.assertEqual((row["value"], row["numerator"], row["denominator"]), ("", "", ""))
                self.assertEqual(row["ci95"], "null")
                self.assertEqual(row["metric_source"], "ai_research_target_gold")
            self.assertIsNone(batch_core.research_csv_report_error(research_csv(report).encode(), report.model_dump(mode="json")))

    def test_empty_selection_keeps_filter_report_identity_and_unsupported_dimensions(self):
        for selected in ({"language": "en"}, {"condition_id": ""}):
            with self.subTest(selected=selected):
                report = research_report(QUOTE, ResearchFilters(**selected))
                rows = list(csv.DictReader(io.StringIO(research_csv(report))))
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row["row_kind"], "report_metadata")
                self.assertEqual(row["report_sha256"], report.report_sha256)
                self.assertTrue(selected.items() <= json.loads(row["filters"]).items())
                self.assertEqual(json.loads(row["counts"]), report.counts)
                self.assertEqual(json.loads(row["capabilities"]), report.capabilities)
                self.assertTrue(all(c["value"] is None for c in json.loads(row["capabilities"]).values()))
                self.assertIsNone(batch_core.research_csv_report_error(research_csv(report).encode("utf-8-sig"), report.model_dump(mode="json")))

    def test_consumer_rejects_missing_duplicate_or_changed_gold_rows_and_stale_identity(self):
        report = research_report(QUOTE)
        original = research_csv(report)
        def remove_gold(rows):
            rows.pop(next(i for i, r in enumerate(rows) if r["row_kind"] == "target_gold_count"))
        def duplicate(rows):
            rows.append(dict(rows[-1]))
        def change_gold(rows):
            next(r for r in rows if r["row_kind"] == "target_gold_count")["gold_count"] = "999"
        def invent_rate(rows):
            next(r for r in rows if r["row_kind"] == "target_gold_count")["value"] = "0"
        def stale(rows):
            rows[-1]["report_sha256"] = "a" * 64
        def wrong_metric(rows):
            next(r for r in rows if r["row_kind"] == "final_output_metric")["denominator"] = "999"
        def wrong_counts(rows):
            rows[0]["counts"] = "{}"
        for mutation in (remove_gold, duplicate, change_gold, invent_rate, stale, wrong_metric, wrong_counts):
            with self.subTest(mutation=mutation.__name__):
                content = change_csv(original, mutation).encode()
                self.assertEqual(batch_core.research_csv_report_error(content, report.model_dump(mode="json"))["code"], "SNAPSHOT_MISMATCH")

    def test_v1_samples_remain_readable_and_new_schema_accepts_both_versions(self):
        archived = ROOT / "docs/examples/week4"
        report = ResearchReport.model_validate_json((archived / "research-report.example.json").read_text())
        self.assertEqual(report.report_version, "week4-public-overlay-v0.1")
        self.assertEqual(research_csv(report).replace("\r\n", "\n"), (archived / "research-metrics.example.csv").read_text(encoding="utf-8-sig"))
        schema = json.loads((ROOT / "contracts/research-overlay-v0.2.schema.json").read_text())
        validator = Draft202012Validator(schema)
        validator.validate(report.model_dump(mode="json"))
        validator.validate(research_report(QUOTE).model_dump(mode="json"))


class TransferredPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "transferred"
        self.manifest = replay(QUOTE, self.package, source="overlay")

    def rehash_artifact(self, name):
        self.manifest["artifacts"][name] = file_hash(self.package / name)
        atomic_json(self.package / "reproduction-manifest.json", self.manifest)

    def test_verification_uses_no_keys_sources_git_or_models_and_preserves_package(self):
        before = tree_hashes(self.package)
        with patch("backend.app.config.Settings.from_environment", side_effect=AssertionError("settings read")), \
             patch("scripts.week4_package.load_evidence", side_effect=AssertionError("source read")), \
             patch("scripts.week4_package.subprocess.check_output", side_effect=AssertionError("git called")), \
             patch("backend.app.providers.OpenAICompatibleProvider.complete", side_effect=AssertionError("paid call")):
            result = verify_package(self.package, expected_report_sha256=self.manifest["report_sha256"],
                                    expected_source_inventory_sha256=self.manifest["source_inventory_sha256"])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["model_calls"], 0)
        self.assertFalse(result["source_evidence_revalidated"])
        self.assertTrue(result["expected_report_hash_matched"] and result["expected_source_hash_matched"])
        self.assertEqual(tree_hashes(self.package), before)

    def test_byte_corruption_is_detected_before_deserialization(self):
        (self.package / "report.json").write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "artifact hashes"):
            verify_package(self.package)

    def test_rehashed_csv_cannot_silently_drop_gold_observations(self):
        path = self.package / "metrics.csv"
        changed = change_csv(path.read_text(encoding="utf-8-sig"), lambda rows: rows.pop())
        path.write_text(changed, encoding="utf-8-sig", newline="")
        self.rehash_artifact("metrics.csv")
        with self.assertRaisesRegex(ValueError, "CSV differs"):
            verify_package(self.package)

    def test_rehashed_decision_cannot_claim_an_approved_recommendation(self):
        path = self.package / "decision-record.json"
        decision = json.loads(path.read_text())
        decision["status"] = "recommended_candidate"
        atomic_json(path, decision)
        self.rehash_artifact("decision-record.json")
        with self.assertRaisesRegex(ValueError, "decision record"):
            verify_package(self.package)

    def test_rehashed_report_still_needs_its_canonical_report_hash(self):
        path = self.package / "report.json"
        report = json.loads(path.read_text())
        report["counts"]["members"] = 999
        atomic_json(path, report)
        self.rehash_artifact("report.json")
        with self.assertRaisesRegex(ValueError, "canonical hash"):
            verify_package(self.package)

    def test_wrong_trusted_hash_or_manifest_identity_is_rejected(self):
        for key in ("expected_report_sha256", "expected_source_inventory_sha256"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "expected hash"):
                verify_package(self.package, **{key: "0" * 64})
        self.manifest["filters"] = {"language": "en"}
        atomic_json(self.package / "reproduction-manifest.json", self.manifest)
        with self.assertRaisesRegex(ValueError, "identity"):
            verify_package(self.package)

    def test_unexpected_files_and_external_artifact_paths_are_rejected(self):
        unexpected = self.package / ".env"
        unexpected.write_text("private sentinel")
        with self.assertRaisesRegex(ValueError, "unexpected files"):
            verify_package(self.package)
        unexpected.unlink()
        self.manifest["artifacts"]["../.env"] = "0" * 64
        atomic_json(self.package / "reproduction-manifest.json", self.manifest)
        with self.assertRaisesRegex(ValueError, "artifact hashes"):
            verify_package(self.package)

    def test_symlink_artifacts_are_not_followed(self):
        # Windows CI may not grant the symlink privilege; missing/extra/hash
        # validation is covered independently on every OS.
        path = self.package / "metrics.csv"
        path.unlink()
        try:
            path.symlink_to(self.root / "outside-private.csv")
        except OSError:
            self.skipTest("OS does not allow creating symlinks")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            verify_package(self.package)

    def test_archive_v1_package_can_be_verified_without_rewriting_it(self):
        old = ROOT / "docs/examples/week4"
        for source, target in (("research-report.example.json", "report.json"),
                               ("research-metrics.example.csv", "metrics.csv"),
                               ("decision-record.example.json", "decision-record.json")):
            shutil.copyfile(old / source, self.package / target)
        report = json.loads((self.package / "report.json").read_text())
        for key in ("batch_id", "report_version", "report_sha256", "evaluation_snapshot_sha256", "filters"):
            self.manifest[key] = report[key]
        self.manifest["version"] = "week4-reproduction-package-v0.1"
        self.manifest["artifacts"] = {name: file_hash(self.package / name) for name in self.manifest["artifacts"]}
        atomic_json(self.package / "reproduction-manifest.json", self.manifest)
        before = tree_hashes(self.package)
        self.assertEqual(verify_package(self.package)["status"], "passed")
        self.assertEqual(tree_hashes(self.package), before)

    def test_verification_detects_concurrent_package_changes(self):
        from scripts.week4_package import research_csv as render
        def changed(report):
            with (self.package / "metrics.csv").open("ab") as stream:
                stream.write(b"\n")
            return render(report)
        with patch("scripts.week4_package.research_csv", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "CSV differs|changed during"):
                verify_package(self.package)


class ReleaseEvidenceTests(unittest.TestCase):
    def test_completed_smoke_and_audit_index_are_pinned_too(self):
        index = json.loads((ROOT / "configs/week4-release-index.v0.1.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = release_evidence(ROOT, index)
            for name in expected:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, root / name)
            self.assertEqual(release_evidence(root, index), expected)
            for ref in (index["new_dev_reproduction_completed"], index["exploratory_audit"]["source_index"]):
                path = root / ref["path"]
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                with self.assertRaisesRegex(ValueError, "release index"):
                    release_evidence(root, index)
                path.write_bytes(original)
            bad = copy.deepcopy(index)
            bad["public_result_summary"]["path"] = "../private.env"
            with self.assertRaisesRegex(ValueError, "public project path"):
                release_evidence(root, bad)


if __name__ == "__main__":
    unittest.main()
