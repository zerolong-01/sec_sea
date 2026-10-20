"""Saved Week3 reports use frozen evidence without live API configuration."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.config import Settings
from backend.app.providers import OpenAICompatibleProvider
from backend.testing.fixture_model import FixtureModelServer
from scripts.data_contract import ROOT
from scripts.verify_real_api import VerificationError
from scripts.week3_pipeline import verify


class Week3OfflineReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        cls.original = cls.folder / "original"
        pricing = cls.folder / "pricing.json"
        pricing.write_text(json.dumps({"version": "frozen-test-price", "currency": "USD", "models": [
            {"model_id": model, "input_usd_per_million": .4, "output_usd_per_million": 1.6,
             "source_url": "https://example.invalid/test-only", "effective_date": "2026-10-20", "verified": True}
            for model in ("fixture-generation", "fixture-classifier")]}), encoding="utf-8")
        with FixtureModelServer(ROOT / "data/week2") as fixture:
            cls.settings = Settings(project_root=ROOT, data_dir=ROOT / "data/week2", runs_dir=cls.folder / "unused",
                model_provider="fixture_http", model_id="fixture-generation", system_prompt_version="v0.1",
                retrieval_config_version="lexical-v0.1", model_base_url=fixture.base_url,
                model_api_key="offline-private-fixture-key", d2_model_id="fixture-classifier", pricing_path=pricing)
            cls.initial = verify(cls.original, settings=cls.settings, max_items=2, allow_fixture=True)
        cls.batch_id = cls.initial["batch_id"]

    def setUp(self):
        self.output = self.folder / self.id().rsplit(".", 1)[-1]
        shutil.copytree(self.original, self.output)
        self.batch = self.output / "runs/batches" / self.batch_id

    def test_replay_ignores_live_credentials_settings_price_and_environment(self):
        manifest = (self.batch / "manifest.json").read_bytes()
        checkpoint = (self.output / "checkpoint.json").read_bytes()
        changed = replace(self.settings, model_id="unavailable-current-model", model_api_key=None,
                          d2_api_key=None, pricing_path=self.folder / "absent-current-price.json")
        with patch.dict(os.environ, {"MODEL_PROVIDER": "invalid-current-provider", "MODEL_TEMPERATURE": "not-a-number"}), \
             patch("scripts.week3_pipeline._settings", side_effect=AssertionError("read live settings")), \
             patch("scripts.week3_pipeline.public_settings", side_effect=AssertionError("read current platform")), \
             patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("model called")) as calls:
            result = verify(self.output, settings=changed, report_only=True)
        calls.assert_not_called()
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["batch_id"], self.batch_id)
        self.assertEqual(result["budget"], self.initial["budget"])
        self.assertEqual(result["refresh_model_calls"], 0)
        self.assertEqual(result["code_commit"], self.initial["code_commit"])
        self.assertEqual((self.batch / "manifest.json").read_bytes(), manifest)
        self.assertEqual((self.output / "checkpoint.json").read_bytes(), checkpoint)

    def test_replay_without_checkpoint_does_not_create_one(self):
        (self.output / "checkpoint.json").unlink()
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("model called")) as calls:
            result = verify(self.output, report_only=True)
        self.assertEqual(result["batch_id"], self.batch_id)
        self.assertFalse((self.output / "checkpoint.json").exists())
        calls.assert_not_called()

    def test_replay_requires_existing_preparation_and_never_creates_execution_inputs(self):
        (self.output / "prepared/preparation.json").unlink()
        with patch("scripts.week3_pipeline.prepare") as prepare, \
             patch("scripts.week3_pipeline.BatchRunner.create") as create:
            with self.assertRaisesRegex(VerificationError, "PREPARED_DATA_NOT_CREATED"):
                verify(self.output, report_only=True)
            missing = self.folder / "missing-pipeline"
            with self.assertRaisesRegex(VerificationError, "PIPELINE_NOT_CREATED"):
                verify(missing, report_only=True)
        prepare.assert_not_called()
        create.assert_not_called()
        self.assertFalse(missing.exists())

    def test_replay_still_rejects_frozen_configuration_tampering(self):
        price = self.batch / "pricing.snapshot"
        price.write_text(price.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("model called")) as calls:
            with self.assertRaisesRegex(ValueError, "Frozen configuration hash mismatch"):
                verify(self.output, report_only=True)
        calls.assert_not_called()

    def test_replay_still_checks_raw_usage_against_trace_and_ledger(self):
        path = next((self.output / "runs").glob("*.raw.json"))
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["model_calls"][0]["input_tokens"] += 1
        path.write_text(json.dumps(raw), encoding="utf-8")
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("model called")) as calls:
            with self.assertRaisesRegex(VerificationError, "PUBLIC_USAGE_MISMATCH"):
                verify(self.output, report_only=True)
        calls.assert_not_called()

    def test_paid_resume_still_rejects_changed_execution_settings(self):
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("model called")) as calls:
            with self.assertRaisesRegex(VerificationError, "EXECUTION_SETTINGS_CHANGED"):
                verify(self.output, settings=replace(self.settings, temperature=.6), allow_fixture=True)
        calls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
