from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import BatchRunner
from backend.app.config import Settings
from backend.testing.fixture_model import FixtureModelServer
from scripts.data_contract import ROOT, DataContractError
from scripts.verify_real_detector import _summarize, main, verify


class RealDetectorDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.output = self.folder / "diagnostic"
        self.fixture = FixtureModelServer(ROOT / "data/week2").__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        pricing = self.folder / "pricing.json"
        pricing.write_text(json.dumps({"version": "test-verified-v1", "currency": "USD", "models": [
            {"model_id": model, "input_usd_per_million": 0.4, "output_usd_per_million": 1.6,
             "source_url": "https://example.invalid/test-only", "effective_date": "2026-10-20", "verified": True}
            for model in ("fixture-generation", "fixture-classifier")]}), encoding="utf-8")
        self.settings = Settings(project_root=ROOT, data_dir=ROOT / "data/week2", runs_dir=self.folder / "unused",
            model_provider="fixture_http", model_id="fixture-generation", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=self.fixture.base_url,
            model_api_key="test-private-secret", d2_model_id="fixture-classifier", pricing_path=pricing)

    def run_diagnostic(self, **options):
        return verify(self.output, settings=self.settings, allow_fixture=True, **options)

    def test_complete_dev_diagnostic_keeps_gold_pending_and_resume_makes_no_calls(self):
        partial = self.run_diagnostic(max_items=2)
        self.assertEqual((partial["status"], partial["saved_runs"], partial["model_call_count"]), ("incomplete", 2, 4))
        checkpoint = json.loads((self.output / "checkpoint.json").read_text(encoding="utf-8"))
        complete = self.run_diagnostic()
        self.assertEqual(complete["batch_id"], checkpoint["batch_id"])
        self.assertEqual((complete["status"], complete["saved_runs"], complete["model_call_count"]), ("passed", 18, 36))
        self.assertEqual((complete["expected_target_count"], complete["inspected_target_count"]), (36, 36))
        self.assertFalse(complete["real_model_verified"])
        self.assertEqual(complete["execution_scope"], "fixture")
        self.assertFalse(complete["holdout_executed"])
        self.assertEqual(complete["gold_exclusions"], {"team_review_pending": 36})
        self.assertEqual(complete["gold_updates_applied"], 0)
        self.assertEqual(complete["team_agreement"], "pending")
        self.assertTrue(complete["usage_complete"] and complete["cost_complete"])
        self.assertEqual(sum(group["eligible_target_count"] for group in complete["detector_report"]["groups"]), 0)
        self.assertNotIn("a025", {row["case_id"] for row in complete["runs"]})
        before = len(self.fixture.requests)
        resumed = self.run_diagnostic()
        self.assertEqual(len(self.fixture.requests), before)
        self.assertEqual(resumed, complete)
        for path in self.output.glob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("test-private-secret", text)
            self.assertNotIn("CANARY_", text)

    def test_detector_error_stops_and_is_never_implicitly_retried(self):
        self.fixture.fail_detection = "malformed"
        result = self.run_diagnostic()
        self.assertEqual((result["status"], result["saved_runs"]), ("incomplete", 1))
        self.assertEqual(result["runs"][0]["status"], "failed")
        before = len(self.fixture.requests)
        self.fixture.fail_detection = None
        resumed = self.run_diagnostic()
        self.assertEqual(resumed, result)
        self.assertEqual(len(self.fixture.requests), before)

    def test_cancelled_before_transport_resumes_without_missing_trace_or_hidden_calls(self):
        with patch("backend.app.batch.RunService.execute", side_effect=KeyboardInterrupt):
            interrupted = self.run_diagnostic(max_items=1)
        self.assertEqual((interrupted["status"], interrupted["saved_runs"],
                          interrupted["model_call_count"]), ("incomplete", 0, 0))
        self.assertEqual(self.fixture.requests, [])
        runner = BatchRunner(replace(self.settings, runs_dir=self.output / "runs"))
        state = runner.store.get(interrupted["batch_id"])
        entry = next(e for e in state.plan if e["attempts"])
        cancelled = entry["attempts"][0]
        self.assertEqual(cancelled["status"], "cancelled_before_transport")
        self.assertFalse((self.output / "runs" / (cancelled["run_id"] + ".trace.json")).exists())

        resumed = self.run_diagnostic(max_items=1)
        self.assertEqual(resumed["batch_id"], interrupted["batch_id"])
        self.assertEqual((resumed["saved_runs"], resumed["reconciled_calls"]), (1, 2))
        self.assertEqual(len(self.fixture.requests), 2)
        self.assertTrue(resumed["usage_complete"] and resumed["cost_complete"])
        state = runner.store.get(resumed["batch_id"])
        entry = next(e for e in state.plan if e["attempts"])
        self.assertEqual(len(entry["attempts"]), 2)
        self.assertEqual(entry["attempts"][0], cancelled)
        report_text = (self.output / "verification-report.json").read_text(encoding="utf-8")
        self.assertNotIn("CANARY_", report_text)
        self.assertNotIn(self.settings.model_api_key, report_text)

        state.calls[0]["attempt_id"] = cancelled["attempt_id"]
        with self.assertRaisesRegex(DataContractError, "cancelled-before-transport"):
            _summarize(self.output, runner, state)

    def test_fixture_needs_explicit_opt_in_and_cli_errors_never_echo_settings(self):
        with self.assertRaises(DataContractError):
            verify(self.output, settings=self.settings)
        self.assertFalse(self.output.exists())
        stream = io.StringIO()
        with patch("scripts.verify_real_detector._settings", side_effect=ValueError("test-private-secret")), contextlib.redirect_stdout(stream):
            code = main(["--output", str(self.output)])
        self.assertEqual(code, 1)
        self.assertNotIn("test-private-secret", stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())["status"], "error")

    def test_crash_without_saved_trace_keeps_paid_reservation_uncertain(self):
        partial = self.run_diagnostic(max_items=1)
        runner = BatchRunner(replace(self.settings, runs_dir=self.output / "runs"))
        state = runner.store.get(partial["batch_id"])
        entry = next(entry for entry in state.plan if entry["attempts"])
        run_id = entry["attempts"][0]["run_id"]
        (self.output / "runs" / (run_id + ".trace.json")).unlink()
        entry["status"] = entry["attempts"][0]["status"] = "running"
        state.status = "running"
        for call in state.calls:
            call.update(status="reserved", known_cost_usd=None, input_tokens=None, output_tokens=None)
        runner.store.save(state)
        before = len(self.fixture.requests)
        recovered = self.run_diagnostic()
        self.assertEqual(len(self.fixture.requests), before)
        self.assertEqual(recovered["batch_status"], "uncertain")
        self.assertEqual(recovered["model_call_count"], before)
        self.assertEqual(recovered["reconciled_calls"], 0)
        self.assertIsNone(recovered["total_cost_usd"])
        self.assertFalse(recovered["usage_complete"] or recovered["cost_complete"])

    def test_changed_settings_cannot_resume_even_a_completed_diagnostic(self):
        complete = self.run_diagnostic()
        before = len(self.fixture.requests)
        with self.assertRaises(DataContractError):
            verify(self.output, settings=replace(self.settings, temperature=0.25), allow_fixture=True)
        self.assertEqual(len(self.fixture.requests), before)
        state = BatchRunner(replace(self.settings, runs_dir=self.output / "runs")).store.get(complete["batch_id"])
        self.assertEqual(state.status, "completed")
        record = json.loads((self.output / "verification-report.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertNotIn(self.settings.model_api_key, json.dumps(record))


if __name__ == "__main__":
    unittest.main()
