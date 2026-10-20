"""Failure-slice scope, unknown denominators, safe export, immutable sources."""
from __future__ import annotations

import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from backend.app.batch import digest, file_hash
from scripts.week3_failure_slices import Profile, analyze, rates, write_reports
from tests.test_week3_research_report import STATISTICS, row


def evidence(number=1, **kwargs):
    value = row(number, **kwargs)
    value["review"].update(version="test-ai-review-v1", raw_output_sha256=digest([number, "output"]),
                           source_facts_sha256=digest([number, "facts"]), expected_normal_task_sha256=digest("task"))
    return value


class FailureSlicesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "saved/runs"
        self.batch_id = "batch-000000000001"
        folder = self.runs / "batches" / self.batch_id
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text("{}", encoding="utf-8")
        self.raw = self.runs / "run-1.raw.json"
        self.raw.write_text('{"output":"PRIVATE_BODY_SHOULD_NEVER_APPEAR"}', encoding="utf-8")
        self.reviews = self.root / "reviews.jsonl"
        self.reviews.write_text("{}\n", encoding="utf-8")
        self.profile = Profile("fixture", self.runs, self.batch_id, self.reviews)
        self.policy = {"statistics": STATISTICS, "source_files": [], "decision": {"holdout_authorized": False}}
        for name in ("rubric.json", "scripts/week3_research_report.py", "backend/app/batch_analysis.py"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        self.rubric = self.root / "rubric.json"

    def state(self, rows):
        return NS(batch_id=self.batch_id, plan=[r["entry"] for r in rows], configuration_hashes={},
                  spec=NS(statistics=NS(model_dump=lambda **_: {"version": "original-frozen-statistics"})))

    def test_normal_and_attack_denominators_are_separate_and_versions_do_not_merge(self):
        rows = [evidence(1), evidence(2, label="hard_negative", verdict="failure"),
                evidence(3, label="attack", goal="marker", verdict="failure")]
        result = rates(rows, STATISTICS)
        self.assertEqual((result["normal_task_success"]["numerator"], result["normal_task_success"]["denominator"]), (1, 2))
        self.assertEqual((result["attack_task_utility"]["numerator"], result["attack_task_utility"]["denominator"]), (0, 1))
        self.assertEqual((result["legacy_asr"]["numerator"], result["legacy_asr"]["denominator"]), (1, 1))
        rows.append(evidence(4, label="attack", goal="marker", model="model-v2"))
        before = copy.deepcopy([r["entry"] for r in rows])
        report = analyze(self.profile, self.state(rows), rows, self.policy)
        attack_slices = [s for s in report["failure_slices"] if s["metrics"]["legacy_asr"]["selected_count"]]
        self.assertEqual(len(attack_slices), 2)
        self.assertEqual({s["cohort"]["model_id"] for s in attack_slices}, {"model-v1", "model-v2"})
        self.assertEqual([r["entry"] for r in rows], before)
        self.assertTrue(all(s["cohort"]["severity"] == "unspecified" for s in report["failure_slices"]))

    def test_unknown_empty_scope_and_execution_failure_are_not_zero_success_rates(self):
        rows = [evidence(1, verdict="review_needed"), evidence(2, verdict="failure")]
        rows[1]["trace"].status, rows[1]["trace"].error = "failed", NS(code="test-error")
        report = analyze(self.profile, self.state(rows), rows, self.policy)
        group = report["failure_slices"][0]
        metric = group["metrics"]["normal_task_success"]
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["denominator"], 0)
        self.assertEqual(metric["excluded"], {"execution_invalid_or_detector_only": 1, "review_needed": 1})
        self.assertEqual(group["failure_counts"]["normal_task_failures"], 0)
        self.assertEqual(group["failure_counts"]["invalid_or_detector_only_runs"], 1)
        english = next(v for v in report["axes"]["language"] if v["value"] == "en")
        self.assertEqual((english["status"], english["sample_counts"]["run_count"]), ("not_observed", 0))
        self.assertTrue(all(gap["denominator"] == 0 and gap["value_estimate"] is None for gap in report["scope_gaps"]))

    def test_missing_or_duplicate_membership_is_rejected(self):
        rows = [evidence(1)]
        with self.assertRaisesRegex(ValueError, "Complete profile membership"):
            analyze(self.profile, self.state(rows * 2), rows, self.policy)
        with self.assertRaisesRegex(ValueError, "Duplicate analysis run ID"):
            analyze(self.profile, self.state(rows * 2), rows * 2, self.policy)

    def test_new_json_csv_preserve_sources_and_never_export_raw_or_review_text(self):
        rows = [evidence(1)]
        rows[0]["review"]["reason"] = "PRIVATE_BODY_SHOULD_NEVER_APPEAR"
        before = {p: file_hash(p) for p in self.runs.rglob("*") if p.is_file()}
        output = self.root / "runs/failure-slices"
        with patch("scripts.week3_failure_slices.load_rows", return_value=(self.state(rows), rows)), \
                patch("scripts.week3_failure_slices.research_policy", return_value=self.policy):
            report = write_reports(output, profiles=[self.profile], rubric=self.rubric, root=self.root)
            with self.assertRaisesRegex(ValueError, "new ignored"):
                write_reports(output, profiles=[self.profile], rubric=self.rubric, root=self.root)
        self.assertEqual(report["source_integrity"]["status"], "unchanged")
        self.assertEqual(report["additional_model_calls"], 0)
        self.assertEqual({p: file_hash(p) for p in before}, before)
        text = (output / "failure-slices.json").read_text(encoding="utf-8")
        csv_text = (output / "failure-slices.csv").read_text(encoding="utf-8-sig")
        self.assertNotIn("PRIVATE_BODY_SHOULD_NEVER_APPEAR", text + csv_text)
        records = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(len([r for r in records if r["row_type"] == "slice_metric"]), 5)
        gaps = [r for r in records if r["row_type"] == "scope_gap"]
        self.assertEqual(len(gaps), 3)
        self.assertTrue(all(r["value"] == "" and r["denominator"] == "0" and r["coverage_status"] == "not_assessed" for r in gaps))
        asr = next(r for r in records if r["metric"] == "legacy_asr")
        self.assertEqual((asr["value"], asr["denominator"]), ("", "0"))

    def test_source_mutation_during_read_prevents_publication(self):
        rows = [evidence(1)]
        def changed(*args):
            self.raw.write_text("modified", encoding="utf-8")
            return self.state(rows), rows
        output = self.root / "runs/failure-slices"
        with patch("scripts.week3_failure_slices.load_rows", side_effect=changed), \
                patch("scripts.week3_failure_slices.research_policy", return_value=self.policy):
            with self.assertRaisesRegex(ValueError, "Source artifacts changed"):
                write_reports(output, profiles=[self.profile], rubric=self.rubric, root=self.root)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
