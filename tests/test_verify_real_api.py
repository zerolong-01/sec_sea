from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.config import Settings
from backend.app.batch import BatchRunner
from backend.app.batch_budget import BatchCallBudget
from backend.testing.fixture_model import FixtureModelServer
from scripts.data_contract import ROOT
from scripts.verify_real_api import VerificationError, _inspect, main, verify


class RealApiPilotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.output = self.folder / "pilot"
        self.fixture = FixtureModelServer(ROOT / "data/week2").__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        pricing = self.folder / "pricing.json"
        pricing.write_text(json.dumps({"version": "test-price-v1", "currency": "USD", "models": [
            {"model_id": model, "input_usd_per_million": 0.4, "output_usd_per_million": 1.6,
             "source_url": "https://example.invalid/test-only", "effective_date": "2026-10-20", "verified": True}
            for model in ("fixture-generation", "fixture-classifier")]}), encoding="utf-8")
        self.settings = Settings(project_root=ROOT, data_dir=ROOT / "data/week2", runs_dir=self.folder / "unused",
            model_provider="fixture_http", model_id="fixture-generation", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=self.fixture.base_url,
            model_api_key="pilot-private-test-value", d2_model_id="fixture-classifier", pricing_path=pricing)

    def test_partial_resume_reuses_checkpoint_and_read_refresh_never_calls_provider(self):
        first = verify(self.output, settings=self.settings, max_items=1, allow_fixture=True)
        self.assertEqual(first["status"], "paused")
        self.assertEqual(first["planned_runs"], 108)
        self.assertEqual(first["refresh_model_calls"], 0)
        self.assertFalse(first["real_model_verified"])
        self.assertEqual(first["recommendation_status"], "deferred")
        checkpoint = json.loads((self.output / "checkpoint.json").read_text(encoding="utf-8"))
        initial_traces = set((self.output / "runs").glob("*.trace.json"))
        self.assertEqual(len(initial_traces), 1)
        second = verify(self.output, settings=self.settings, max_items=1, allow_fixture=True)
        self.assertEqual(second["batch_id"], checkpoint["batch_id"])
        self.assertEqual(len(set((self.output / "runs").glob("*.trace.json")) - initial_traces), 1)
        self.assertEqual(second["reconciled_calls"], len(self.fixture.requests))
        self.assertEqual(second["refresh_model_calls"], 0)
        self.assertEqual(second["execution_scope"], "fixture")
        self.assertFalse(second["holdout_executed"])
        self.assertEqual(second["team_agreement"], "pending")
        for path in (self.output / "public-samples").glob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("CANARY_", text)
            self.assertNotIn("pilot-private-test-value", text)

    def test_invalid_detector_output_stops_remaining_batch_without_implicit_paid_retry(self):
        self.fixture.fail_detection = "malformed"
        failed = verify(self.output, settings=self.settings, allow_fixture=True)
        self.assertEqual(failed["status"], "failed")
        self.assertGreater(failed["status_counts"]["failed"], 0)
        self.assertFalse(failed["real_model_verified"])
        self.assertTrue(failed["error_counts"])
        before = len(self.fixture.requests)
        self.fixture.fail_detection = None
        resumed = verify(self.output, settings=self.settings, allow_fixture=True)
        self.assertEqual(len(self.fixture.requests), before)
        self.assertEqual(resumed, failed)

    def test_cancelled_before_transport_resumes_without_missing_trace_or_hidden_calls(self):
        with patch("backend.app.batch.RunService.execute", side_effect=KeyboardInterrupt):
            interrupted = verify(self.output, settings=self.settings, max_items=1, allow_fixture=True)
        self.assertEqual((interrupted["status"], interrupted["reconciled_calls"],
                          interrupted["unreconciled_calls"]), ("paused", 0, 0))
        self.assertEqual(self.fixture.requests, [])
        runner = BatchRunner(replace(self.settings, runs_dir=self.output / "runs"))
        state = runner.store.get(interrupted["batch_id"])
        entry = next(e for e in state.plan if e["attempts"])
        cancelled = entry["attempts"][0]
        self.assertEqual(cancelled["status"], "cancelled_before_transport")
        self.assertFalse((self.output / "runs" / (cancelled["run_id"] + ".trace.json")).exists())

        resumed = verify(self.output, settings=self.settings, max_items=1, allow_fixture=True)
        self.assertEqual(resumed["batch_id"], interrupted["batch_id"])
        self.assertEqual(resumed["reconciled_calls"], len(self.fixture.requests))
        self.assertGreater(resumed["reconciled_calls"], 0)
        self.assertEqual(resumed["unreconciled_calls"], 0)
        self.assertEqual(len(list((self.output / "runs").glob("*.trace.json"))), 1)
        state = runner.store.get(resumed["batch_id"])
        entry = next(e for e in state.plan if e["attempts"])
        self.assertEqual(len(entry["attempts"]), 2)
        self.assertEqual(entry["attempts"][0], cancelled)
        report_text = (self.output / "verification-report.json").read_text(encoding="utf-8")
        self.assertNotIn("CANARY_", report_text)
        self.assertNotIn(self.settings.model_api_key, report_text)

        state.calls[0]["attempt_id"] = cancelled["attempt_id"]
        with self.assertRaisesRegex(VerificationError, "CANCELLED_ATTEMPT_HAS_LEDGER_CALLS"):
            _inspect(runner, state, (self.settings.model_api_key,))

    def test_fixture_opt_in_and_cli_error_output_never_reveal_exception_text(self):
        with self.assertRaises(VerificationError):
            verify(self.output, settings=self.settings, max_items=1)
        self.assertFalse(self.output.exists())
        stream = io.StringIO()
        with patch("scripts.verify_real_api.verify", side_effect=RuntimeError("pilot-private-test-value")), contextlib.redirect_stdout(stream):
            code = main(["--output", str(self.output)])
        self.assertEqual(code, 1)
        self.assertNotIn("pilot-private-test-value", stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())["error"], "RuntimeError")

    def test_mid_detector_crash_reports_settled_and_reserved_calls_without_retry(self):
        original_before = BatchCallBudget.before

        def crash_after_second_detector_reservation(guard, call):
            ticket = original_before(guard, call)
            detections = [saved for saved in guard.state.calls
                          if saved["attempt_id"] == guard.attempt_id and saved["purpose"] == "detection"]
            if call.purpose == "detection" and len(detections) == 2:
                raise KeyboardInterrupt
            return ticket

        with patch.object(BatchCallBudget, "before", crash_after_second_detector_reservation):
            result = verify(self.output, settings=self.settings, allow_fixture=True)
        self.assertEqual((result["status"], result["batch_status"]), ("failed", "uncertain"))
        self.assertEqual((result["unreconciled_calls"], result["unreconciled_settled_calls"]), (2, 1))
        self.assertGreater(result["unreconciled_known_cost_usd"], 0)
        self.assertGreater(result["unreconciled_committed_usd"], result["unreconciled_known_cost_usd"])
        self.assertIsNone(result["budget"]["total_cost_usd"])
        self.assertEqual(result["budget"]["unresolved_calls"], 1)
        self.assertFalse(result["real_model_verified"])
        runner = BatchRunner(replace(self.settings, runs_dir=self.output / "runs"))
        state = runner.store.get(result["batch_id"])
        entry = next(entry for entry in state.plan if entry["status"] == "uncertain")
        self.assertEqual(entry["condition_id"], "D2-both")
        attempt = entry["attempts"][-1]
        paid = [call for call in state.calls if call["attempt_id"] == attempt["attempt_id"]]
        self.assertEqual([call["status"] for call in paid], ["settled", "reserved"])
        self.assertFalse((self.output / "runs" / (attempt["run_id"] + ".trace.json")).exists())
        before = len(self.fixture.requests)
        resumed = verify(self.output, settings=self.settings, allow_fixture=True)
        self.assertEqual(len(self.fixture.requests), before)
        self.assertEqual(resumed, result)
        self.assertEqual(json.loads((self.output / "verification-report.json").read_text(encoding="utf-8")), result)


if __name__ == "__main__":
    unittest.main()
