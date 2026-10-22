"""Public AI evidence and private saved-result replay keep distinct provenance."""
from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from backend.app.batch import BatchRunner, digest
from backend.app.batch_analysis import aggregate, export_report
from backend.app.batch_models import BatchSpec
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.research_models import ResearchFilters
from backend.app.research_reports import ROOT, load_evidence, research_csv, research_report
from backend.app.storage import atomic_json
from scripts.week4_package import replay, tree_hashes

LEGACY = "batch-bd093a919251"
QUOTE = "batch-8fb19849d67c"


class ResearchContractTests(unittest.TestCase):
    def test_membership_counts_and_published_metrics_are_preserved(self):
        summary, records, _ = load_evidence()
        reports = [research_report(b) for b in (LEGACY, QUOTE, "batch-fb671ff629f0")]
        self.assertEqual(sum(r.counts["output_runs"] for r in reports), 648)
        self.assertEqual(sum(r.counts["target_observations"] for r in reports), 621)
        self.assertEqual(sum(r.counts["members"] for r in reports), 1269)
        self.assertEqual(sum(len(r.groups) + len(r.target_gold_groups) for r in reports), 168)
        published = {r["group_id"]: r for r in records["metrics"]}
        for report in reports:
            self.assertEqual(report.provenance["human_review"], "not_performed")
            self.assertEqual(report.decisions["status"], "deferred")
            for row in report.groups + report.target_gold_groups:
                self.assertEqual(row, published[row["group_id"]])
            self.assertTrue(all(cap["value"] is None and cap["reason"] for cap in report.capabilities.values()))
            self.assertTrue(all(m["source_sha256"] and m["task_id"] and "consensus" in m for m in report.members))
        self.assertFalse(summary["holdout_authorized"])

    def test_filters_change_report_hash_and_do_not_reuse_other_cohorts(self):
        full = research_report(QUOTE)
        selected = research_report(QUOTE, ResearchFilters(condition_id="none", goal_kind="secret_leak"))
        self.assertNotEqual(full.report_sha256, selected.report_sha256)
        self.assertEqual(full.evaluation_snapshot_sha256, selected.evaluation_snapshot_sha256)
        self.assertTrue(selected.groups)
        self.assertTrue(all(g["cohort"]["condition_id"] == "none" and g["cohort"]["goal_kind"] == "secret_leak" for g in selected.groups))
        self.assertEqual(selected.target_gold_groups, [])  # goal is not published on target cohorts
        self.assertTrue(all(m["kind"] == "final_output" and m["run_id"] in {r for g in selected.groups for r in g["run_ids"]} for m in selected.members))
        empty = research_report(QUOTE, ResearchFilters(language="en"))
        self.assertEqual(empty.counts["members"], 0)
        self.assertEqual(empty.groups, [])
        with self.assertRaises(ValueError):
            ResearchFilters(label="attack")  # unsupported subset cannot retain original denominator
        with self.assertRaises(ValueError):
            ResearchFilters(evaluation_version="unknown")

    def test_json_csv_hash_denominators_and_unknowns_match(self):
        report = research_report(LEGACY)
        content = research_csv(report)
        rows = list(csv.DictReader(io.StringIO(content)))
        groups = {g["group_id"]: g for g in report.groups}
        saw_unresolved = False
        for row in rows:
            metric = groups[row["group_id"]]["metrics"][row["metric"]]
            self.assertEqual(row["report_sha256"], report.report_sha256)
            self.assertEqual(int(row["denominator"]), metric["denominator"])
            self.assertEqual(json.loads(row["excluded"]), metric["excluded"])
            self.assertEqual(float(row["value"]) if row["value"] else None, metric["value"])
            self.assertEqual(row["ci95"], "null")
            saw_unresolved |= bool(metric["excluded"].get("review_needed"))
        self.assertTrue(saw_unresolved)
        payload = report.model_dump(mode="json")
        payload.pop("report_sha256")
        self.assertEqual(digest(payload), report.report_sha256)
        schema = json.loads((ROOT / "contracts/research-overlay-v0.1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(report.model_dump(mode="json"))
        self.assertNotIn('"votes"', json.dumps(payload))
        self.assertNotIn('"reason"', json.dumps(report.members))
        self.assertNotIn("CANARY_", content)

    def test_evidence_byte_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "configs").mkdir()
            shutil.copy(ROOT / "configs/week4-release-index.v0.1.json", root / "configs")
            shutil.copy(ROOT / "configs/week3-ai-dev-review-policy.v0.1.json", root / "configs")
            shutil.copytree(ROOT / "docs/examples/week3-completion", root / "docs/examples/week3-completion")
            for filename in ("ai-dev-review.v0.1.json", "ai-dev-review.members.v0.1.jsonl", "ai-dev-review.units.v0.1.jsonl", "ai-dev-review.metrics.v0.1.jsonl"):
                path = root / "docs/examples/week3-completion" / filename
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, "hash mismatch"):
                    research_report(LEGACY, root=root)
                path.write_bytes(original)

    def test_http_explicit_selection_never_falls_back_or_calls_a_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = replace(Settings.from_environment(), runs_dir=Path(temporary))
            with patch("backend.app.providers.OpenAICompatibleProvider.complete", side_effect=AssertionError("model called")) as paid, \
                 patch("backend.app.providers.DemoRagProvider.generate_prepared", side_effect=AssertionError("model called")) as demo:
                client = TestClient(create_app(settings))
                base = f"/api/v1/batches/{QUOTE}"
                self.assertTrue(client.get(base + "/evaluation-sources").json()["research"]["available"])
                report = client.post(base + "/research/report", json={})
                self.assertEqual(report.status_code, 200, report.text)
                exported = client.post(base + "/research/export.csv", json={})
                self.assertEqual(exported.headers["X-Report-SHA256"], report.json()["report_sha256"])
                self.assertEqual(client.post(base + "/report", json={}).status_code, 404)
                for body in ({"label": "attack"}, {"evaluation_version": "original"}):
                    self.assertEqual(client.post(base + "/research/report", json=body).status_code, 422)
                self.assertEqual(client.post("/api/v1/batches/batch-000000000000/research/report", json={}).status_code, 404)
                paid.assert_not_called()
                demo.assert_not_called()


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_public_replay_is_identical_without_live_settings_and_never_overwrites(self):
        first, second = self.root / "first", self.root / "second"
        with patch("backend.app.config.Settings.from_environment", side_effect=AssertionError("live settings read")):
            a = replay(QUOTE, first, source="overlay")
            b = replay(QUOTE, second, source="overlay")
        self.assertEqual(a["report_sha256"], b["report_sha256"])
        self.assertEqual(a["artifacts"], b["artifacts"])
        self.assertEqual(a["source_inventory_sha256"], b["source_inventory_sha256"])
        self.assertEqual(a["model_calls"], 0)
        self.assertTrue(a["source_unchanged"])
        with self.assertRaises(ValueError):
            replay(QUOTE, first, source="overlay")

    def test_original_replay_preserves_raw_ledger_reviews_and_prior_exports(self):
        settings = replace(Settings.from_environment(), model_provider="demo", model_id="demo-rag-v0.1",
                           runs_dir=self.root / "runs", evaluation_rules_path=None)
        runner = BatchRunner(settings)
        spec = BatchSpec.model_validate({"sources": [{"source_id": "rag", "data_dir": "data", "split": "dev", "case_ids": ["a006", "b006", "h007"]}],
            "conditions": [{"condition_id": "none", "defense_mode": "none", "comparisons": ["technique"]}],
            "repeats": 1, "budget": {"max_calls": 10, "max_reserved_tokens": 500000, "max_seconds": 60, "unknown_price_policy": "calls_tokens"},
            "statistics": {"bootstrap_samples": 100}})
        state = runner.execute(runner.create(spec).batch_id)
        report = aggregate(settings.runs_dir, state.batch_id)
        export_report(report, settings.runs_dir / "historical-export")
        before = tree_hashes(settings.runs_dir)
        with patch("backend.app.config.Settings.from_environment", side_effect=AssertionError("live settings read")):
            manifest = replay(state.batch_id, self.root / "derived", runs_dir=settings.runs_dir)
        self.assertEqual(tree_hashes(settings.runs_dir), before)
        self.assertEqual(manifest["report_sha256"], report.provenance["report_sha256"])
        self.assertEqual(json.loads((self.root / "derived/report.json").read_text()), report.model_dump(mode="json"))
        decision = json.loads((self.root / "derived/decision-record.json").read_text())
        self.assertEqual(decision["report_sha256"], manifest["report_sha256"])
        self.assertEqual(decision["status"], "deferred")
        with self.assertRaisesRegex(ValueError, "overlaps"):
            replay(state.batch_id, settings.runs_dir / "derived", runs_dir=settings.runs_dir)

    def test_concurrent_input_change_does_not_publish_partial_result(self):
        original = self.root / "source"
        original.mkdir()
        sentinel = original / "evidence.json"
        sentinel.write_text("original")
        report = research_report(QUOTE)
        report.provenance["report_sha256"] = report.report_sha256
        def changed(*args, **kwargs):
            sentinel.write_text("changed")
            return atomic_json(*args, **kwargs)
        with patch("scripts.week4_package.aggregate", return_value=report), \
             patch("scripts.week4_package.export_report", side_effect=lambda r, p: (p.mkdir(), changed(p / "report.json", {}))):
            with self.assertRaisesRegex(ValueError, "Source artifacts changed"):
                replay("batch-000000000000", self.root / "rejected", runs_dir=original)
        self.assertFalse((self.root / "rejected").exists())
        self.assertFalse(list(self.root.glob(".rejected-*")))


if __name__ == "__main__":
    unittest.main()
