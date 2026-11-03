"""The final-report table is reproducible through the AI API, CSV and CI."""
from __future__ import annotations

import copy
import csv
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from backend.app.batch import digest, file_hash
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.research_comparison import BATCH_ID, CASE_IDS, comparison_csv, original_attack_comparison
from backend.app.research_models import ResearchFilters
from backend.app.research_reports import ROOT, research_report
from backend.app.shared_variables import RESEARCH_API_PATHS
from scripts.week4_report_comparison import DOCUMENT_TABLES, document_errors, main


class ReportComparisonTests(unittest.TestCase):
    def test_selected_ai_results_include_a11_and_preserve_goal_and_utility_scope(self):
        with patch("backend.app.config.Settings.from_environment", side_effect=AssertionError("live settings read")):
            report = original_attack_comparison()
        self.assertEqual(report.selection["output_runs"], 72)
        self.assertEqual({m["case_id"] for m in report.members}, set(CASE_IDS))
        expected = {"none": (3, 8), "D1": (1, 9), "D2-input": (4, 4),
                    "D2-retrieval": (2, 3), "D2-both": (3, 0), "D1-D2": (1, 0)}
        for row in report.rows:
            metrics = row["metrics"]
            self.assertEqual(tuple(metrics[k]["numerator"] for k in
                ("fresh_ai_attack_success", "fresh_ai_attack_task_utility")), expected[row["condition_id"]])
            self.assertEqual({m["denominator"] for m in metrics.values()}, {12})
            self.assertEqual({g["goal_kind"] for g in row["goal_groups"]}, {"marker", "secret_leak"})
            for key, metric in metrics.items():
                self.assertEqual(sum(g["metrics"][key]["numerator"] for g in row["goal_groups"]), metric["numerator"])
                self.assertIsNone(metric["ci95"])
                self.assertEqual(metric["recorded_family_count"], 4)
            self.assertNotIn("fresh_ai_normal_task_success", metrics)
        self.assertEqual(report.decisions["status"], "deferred")
        self.assertFalse(report.decisions["holdout_authorized"])
        self.assertEqual(report.provenance["human_review"], "not_performed")
        self.assertIn("mixed_goals", report.selection["inference_status"])
        self.assertTrue(all("source_sha256" in m and "task_id" in m and "unit_id" in m for m in report.members))
        self.assertFalse(any(k in m for m in report.members for k in ("reason", "votes", "consensus", "response")))
        payload = report.model_dump(mode="json")
        self.assertEqual(payload.pop("report_sha256"), digest(payload))
        schema = json.loads((ROOT / "contracts/week4-original-attack-comparison-v0.1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(report.model_dump(mode="json"))

    def test_http_json_and_csv_share_identity_and_never_call_models_or_modify_sources(self):
        report = original_attack_comparison()
        before = {name: file_hash(ROOT / name) for name in report.provenance["source_files"]}
        with tempfile.TemporaryDirectory() as temporary:
            settings = replace(Settings.from_environment(ROOT), runs_dir=Path(temporary), model_provider="demo")
            with patch("backend.app.providers.OpenAICompatibleProvider.complete", side_effect=AssertionError("paid call")) as paid, \
                 patch("backend.app.providers.DemoRagProvider.generate_prepared", side_effect=AssertionError("model call")) as demo:
                client = TestClient(create_app(settings))
                response = client.get(RESEARCH_API_PATHS["ORIGINAL_ATTACKS"])
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), report.model_dump(mode="json"))
                exported = client.get(RESEARCH_API_PATHS["ORIGINAL_ATTACKS_CSV"])
                self.assertEqual(exported.status_code, 200, exported.text)
                self.assertEqual(exported.headers["X-Report-SHA256"], report.report_sha256)
                self.assertEqual(exported.headers["X-Evaluation-Source"], "ai_research_overlay")
                self.assertEqual(exported.text, comparison_csv(report))
                for route in ("ORIGINAL_ATTACKS", "ORIGINAL_ATTACKS_CSV"):
                    rejected = client.get(RESEARCH_API_PATHS[route], params={"condition_id": "none"})
                    self.assertEqual(rejected.status_code, 422)
                    self.assertEqual(rejected.json()["detail"]["code"], "UNSUPPORTED_COMPARISON_FILTER")
                paid.assert_not_called()
                demo.assert_not_called()
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        self.assertEqual(len(rows), 36)  # 6 conditions x 2 metrics x (combined, marker, secret leak)
        for row in rows:
            self.assertEqual(row["report_sha256"], report.report_sha256)
            self.assertEqual(row["source_report_sha256"], report.provenance["source_report_sha256"])
            self.assertEqual(json.loads(row["selection"]), report.selection)
            self.assertEqual(row["decision_status"], "deferred")
            self.assertEqual(row["ci95"], "null")
            condition = next(r for r in report.rows if r["condition_id"] == row["condition_id"])
            section = condition if row["goal_kind"] == "combined_descriptive" else next(
                g for g in condition["goal_groups"] if g["goal_kind"] == row["goal_kind"])
            metric = section["metrics"][row["metric"]]
            self.assertEqual((int(row["numerator"]), int(row["denominator"])), (metric["numerator"], metric["denominator"]))
            self.assertEqual(json.loads(row["run_ids"]), section["run_ids"])
            self.assertEqual(json.loads(row["source_group_ids"]), section["source_group_ids"])
        self.assertEqual({name: file_hash(ROOT / name) for name in before}, before)

    def test_missing_duplicate_or_inconsistent_source_links_fail_closed(self):
        original = research_report(BATCH_ID, ResearchFilters(source_id="week3"))
        def missing(source):
            source.members.remove(next(m for m in source.members if m["case_id"] == "w3pv_a11" and m["kind"] == "final_output"))
        def duplicate(source):
            source.members.append(copy.deepcopy(next(m for m in source.members if m["case_id"] == "w3pv_a11" and m["kind"] == "final_output")))
        def metric_changed(source):
            next(g for g in source.groups if g["cohort"]["ablation_variant"] == "A11")["metrics"]["fresh_ai_attack_success"]["denominator"] = 0
        for mutate in (missing, duplicate, metric_changed):
            source = original.model_copy(deep=True)
            mutate(source)
            with self.subTest(mutate=mutate.__name__), patch("backend.app.research_comparison.research_report", return_value=source):
                with self.assertRaises(ValueError):
                    original_attack_comparison()

    def test_unresolved_attacks_stay_excluded_and_null_instead_of_becoming_failures(self):
        source = research_report(BATCH_ID, ResearchFilters(source_id="week3"))
        ids = {m["run_id"] for m in source.members if m["kind"] == "final_output" and
               m["case_id"] in CASE_IDS and m["condition_id"] == "none"}
        for member in source.members:
            if member["kind"] == "final_output" and member["run_id"] in ids:
                member["fresh_ai_attack_success"] = "review_needed"
        for group in source.groups:
            if set(group["run_ids"]).intersection(ids):
                group["metrics"]["fresh_ai_attack_success"].update(value=None, numerator=0, denominator=0,
                    excluded={"review_needed": len(group["run_ids"])}, unique_case_count=0,
                    recorded_family_count=0, coverage_status="unavailable")
        with patch("backend.app.research_comparison.research_report", return_value=source):
            report = original_attack_comparison()
        metric = report.rows[0]["metrics"]["fresh_ai_attack_success"]
        self.assertIsNone(metric["value"])
        self.assertEqual((metric["denominator"], metric["selected_count"], metric["excluded"]), (0, 12, {"review_needed": 12}))
        row = next(r for r in csv.DictReader(io.StringIO(comparison_csv(report))) if r["condition_id"] == "none" and
                   r["goal_kind"] == "combined_descriptive" and r["metric"] == "fresh_ai_attack_success")
        self.assertEqual((row["value"], row["denominator"], row["ci95"]), ("", "0", "null"))

    def test_document_and_cli_checks_detect_stale_counts_scope_and_metric_labels(self):
        report = original_attack_comparison()
        self.assertEqual(document_errors(report), [])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in DOCUMENT_TABLES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / name).read_bytes())
            name = next(iter(DOCUMENT_TABLES))
            path = root / name
            original = path.read_text(encoding="utf-8")
            for old, new in (("| none | 3/12 | 8/12 |", "| none | 2/12 | 9/12 |"),
                             ("`w3pv_a11` 4개 case", "`w3pv_a10` 4개 case"),
                             ("| 공격 상황 업무 성공 |", "| 정상 업무 성공 |")):
                path.write_text(original.replace(old, new), encoding="utf-8")
                with self.subTest(new=new):
                    self.assertTrue(document_errors(report, root=root))
                    with patch("sys.stdout", new=io.StringIO()):
                        # Pass the copied documents explicitly; source evidence still comes from the backend.
                        with patch("scripts.week4_report_comparison.document_errors", wraps=lambda r: document_errors(r, root=root)):
                            self.assertEqual(main(["--check-docs"]), 1)
                path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
