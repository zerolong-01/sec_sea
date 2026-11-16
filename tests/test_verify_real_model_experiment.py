from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.config import Settings
from backend.testing.fixture_model import FixtureModelServer
from scripts.data_contract import ROOT
from scripts.pipeline_state import VerificationError
from scripts.verify_real_model_experiment import verify


class RealModelExperimentVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.output = self.folder / "verification"
        self.fixture = FixtureModelServer(ROOT / "data").__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        self.settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=self.output / "runs",
            model_provider="fixture_http", model_id="fixture-a", model_base_url=self.fixture.base_url,
            model_api_key=None, system_prompt_version="v0.1", retrieval_config_version="lexical-v0.1")
        self.prices = self.folder / "prices.json"
        self.prices.write_text(json.dumps({"version": "test-only-price-v1", "models": [
            {"model_id": model, "input_usd_per_million": rate, "output_usd_per_million": rate,
             "source_url": "https://example.invalid/synthetic-prices", "effective_date": "2026-10-25",
             "verified": True} for model, rate in (("fixture-a", 1), ("fixture-b", 2), ("fixture-detector", 1))]}), encoding="utf-8")
        self.payload = {"models": [{"model_key": key, "provider": "fixture_http", "model_id": "fixture-" + key,
            "base_url": self.fixture.base_url, "api_key_env": "FIXTURE_GENERATION_KEY"} for key in ("a", "b")],
            "detector": {"model_key": "shared", "provider": "fixture_http", "model_id": "fixture-detector",
                         "base_url": self.fixture.base_url, "api_key_env": "FIXTURE_DETECTOR_KEY"},
            "pricing_file": str(self.prices), "evaluation_rules_file": "configs/evaluation-starter.json",
            "batch": {"sources": [{"source_id": "rag", "data_dir": "data", "split": "dev", "case_ids": ["a006", "b006"]}],
                "conditions": [{"condition_id": mode, "defense_mode": mode, "comparisons": ["technique"]}
                               for mode in ("none", "D2")], "repeats": 1,
                "budget": {"max_calls": 20, "max_reserved_tokens": 200000, "max_seconds": 60,
                           "max_usd": 0.1, "per_call_input_token_ceiling": 8192, "unknown_price_policy": "stop"},
                "statistics": {"bootstrap_samples": 100}}}
        self.spec = self.folder / "spec.json"
        self.save_spec()
        environment = patch.dict(os.environ, {"FIXTURE_GENERATION_KEY": "private-fixture-generation-key",
                                              "FIXTURE_DETECTOR_KEY": "private-fixture-detector-key"})
        environment.start()
        self.addCleanup(environment.stop)

    def save_spec(self):
        self.spec.write_text(json.dumps(self.payload), encoding="utf-8")

    def verify(self, **kwargs):
        return verify(self.spec, self.output, settings=self.settings, allow_fixture=True, **kwargs)

    def test_plan_is_nonexecuting_and_resume_and_keyless_refresh_reconcile_actual_calls(self):
        planned = self.verify()
        self.assertEqual(planned["status"], "incomplete")
        self.assertEqual(self.fixture.requests, [])
        paused = self.verify(execute=True, max_items=2)
        self.assertEqual(paused["attempt_count"], 2)
        done = self.verify(execute=True)
        self.assertEqual(done["status"], "passed")
        self.assertEqual(done["planned_runs"], 8)
        self.assertEqual(done["budget_usage"]["admitted_calls"], len(self.fixture.requests))
        self.assertGreater(done["compared_transmitted_calls"], 0)
        self.assertTrue(all(audit["http_status_counts"] == {"200": audit["reconciled_calls"]}
                            for audit in done["audits"].values()))
        before = len(self.fixture.requests)
        with patch.dict(os.environ, {"FIXTURE_GENERATION_KEY": "", "FIXTURE_DETECTOR_KEY": ""}):
            refreshed = self.verify()
        self.assertEqual(refreshed["status"], "passed")
        self.assertEqual(refreshed["report_sha256"], done["report_sha256"])
        self.assertEqual(len(self.fixture.requests), before)
        self.assertNotIn("private-fixture", json.dumps(done))

    def test_missing_later_price_and_over_budget_fail_before_paid_transport(self):
        with self.assertRaises(VerificationError):
            self.verify(execute=True, max_total_usd=0.1)
        prices = json.loads(self.prices.read_text(encoding="utf-8"))
        prices["models"] = [row for row in prices["models"] if row["model_id"] != "fixture-b"]
        self.prices.write_text(json.dumps(prices), encoding="utf-8")
        with self.assertRaises(VerificationError):
            self.verify(execute=True)
        self.assertEqual(self.fixture.requests, [])

    def test_changed_spec_cannot_silently_create_another_paid_experiment(self):
        initial = self.verify()
        self.payload["batch"]["repeats"] = 2
        self.save_spec()
        with self.assertRaises(VerificationError):
            self.verify(execute=True)
        self.assertEqual(self.fixture.requests, [])
        self.assertEqual(len(list((self.output / "runs/model-experiments").glob("*/manifest.json"))), 1)
        self.assertEqual(json.loads((self.output / "checkpoint.json").read_text(encoding="utf-8"))["experiment_id"], initial["experiment_id"])

    def test_real_only_default_does_not_accept_fixture_or_invalid_limits(self):
        with self.assertRaises(VerificationError):
            verify(self.spec, self.output, settings=self.settings, execute=True)
        with self.assertRaises(VerificationError):
            self.verify(execute=True, max_items=0)
        self.assertEqual(self.fixture.requests, [])
