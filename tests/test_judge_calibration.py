"""Published labels, held-back splits and automated judge quality gates cannot be faked."""
import copy
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.config import Settings
from backend.app.judge_reference import ROOT, REFERENCE, load_reference, select_pairs, summarize, units_for
from backend.app.storage import file_sha256
from backend.testing.fixture_model import FixtureModelServer
from scripts.judge_calibration import messages_for, prepare, report, run


class HumanReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = load_reference()

    def test_published_gold_is_pinned_and_splits_do_not_share_instructions(self):
        reference = self.reference
        self.assertEqual(len(reference["pairs"]), 419)
        dev = select_pairs(reference, "development")
        validation = select_pairs(reference)
        self.assertEqual((len(dev), len(validation)), (20, 80))
        self.assertFalse({p["family_id"] for p in dev} & {p["family_id"] for p in validation})
        self.assertEqual(select_pairs(reference), validation)
        units = units_for(validation)
        self.assertEqual(sum(u["expected"] == "success" for u in units), 80)
        for unit in units:
            payload = json.loads(messages_for(unit)[1].content)
            self.assertNotIn("expected", payload)
            self.assertNotIn("source_label", payload)
            self.assertEqual(payload["saved_answer"], unit["answer"])
            self.assertEqual(unit["expected"] == "success", unit["side"] == unit["source_label"])

    def test_source_label_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "reference"
            shutil.copytree(REFERENCE, folder)
            path = folder / "source/Natural.json"
            content = json.loads(path.read_text())
            content[0]["label"] = 3-content[0]["label"]
            path.write_text(json.dumps(content))
            with self.assertRaises(ValueError):
                load_reference(folder)

    def test_false_success_abstention_and_missing_predictions_do_not_pass(self):
        units = units_for(select_pairs(self.reference))
        perfect = {u["unit_id"]:{"verdict":u["expected"]} for u in units}
        self.assertTrue(summarize(self.reference, units, perfect)["external_reference_gate"]["passed"])
        always_success = {u["unit_id"]:{"verdict":"success"} for u in units}
        result = summarize(self.reference, units, always_success)
        self.assertEqual(result["overall"]["accuracy"], .5)
        self.assertEqual(result["overall"]["false_success_rate"], 1)
        self.assertFalse(result["external_reference_gate"]["passed"])
        abstain = {u["unit_id"]:{"verdict":"review_needed"} for u in units}
        self.assertEqual(summarize(self.reference, units, abstain)["overall"]["accuracy"], 0)
        del perfect[units[0]["unit_id"]]
        self.assertIn("missing_or_failed_predictions", summarize(self.reference, units, perfect)["external_reference_gate"]["reasons"])


class CalibrationExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "calibration"
        self.fixture = FixtureModelServer(ROOT / "data/week2").__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        self.settings = Settings(project_root=ROOT, data_dir=ROOT / "data/week2", runs_dir=self.output / "unused",
            model_provider="demo", model_id="offline", model_base_url=None, model_api_key=None,
            system_prompt_version="v0.1", retrieval_config_version="lexical-v0.1",
            judge_provider="fixture_http", judge_base_url=self.fixture.base_url, judge_model_id="fixture-judge")

    def test_resume_and_report_reuse_settled_results_without_model_calls(self):
        first = run(self.output, self.settings, max_items=2)
        self.assertEqual(len(self.fixture.requests), 2)
        self.assertEqual(first["budget"]["admitted_calls"], 2)
        source = file_sha256(self.output / "ledger.json")
        with patch("scripts.judge_calibration.OpenAICompatibleProvider.complete", side_effect=AssertionError("Read called a model")):
            repeated = report(self.output)
        self.assertEqual(first, repeated)
        self.assertEqual(file_sha256(self.output / "ledger.json"), source)
        second = run(self.output, self.settings, max_items=2)
        self.assertEqual(second["budget"]["admitted_calls"], 4)
        self.assertEqual(len(self.fixture.requests), 4)

    def test_changed_configuration_cannot_mix_evaluations(self):
        run(self.output, self.settings, max_items=1)
        with self.assertRaises(ValueError):
            run(self.output, replace(self.settings, judge_max_tokens=512), max_items=1)
        self.assertEqual(len(self.fixture.requests), 1)

    def test_unresolved_reservation_is_not_retried(self):
        run(self.output, self.settings, max_items=1)
        path = self.output / "ledger.json"
        state = json.loads(path.read_text())
        state["predictions"] = {}
        path.write_text(json.dumps(state))
        result = run(self.output, self.settings, max_items=1)
        self.assertEqual(result["stopped_reason"], "UNRESOLVED_PAID_CALL_NO_AUTOMATIC_RETRY")
        self.assertEqual(len(self.fixture.requests), 1)

    def test_gold_file_cannot_be_replaced_after_preparation(self):
        prepare(self.output)
        path = self.output / "human-reference-labels.json"
        labels = json.loads(path.read_text())
        labels[0]["expected"] = "failure" if labels[0]["expected"] == "success" else "success"
        path.write_text(json.dumps(labels))
        with self.assertRaises(ValueError):
            run(self.output, self.settings, max_items=1)
        self.assertEqual(len(self.fixture.requests), 0)

    def test_lowered_dollar_cap_is_frozen_and_cannot_be_raised_on_resume(self):
        run(self.output, self.settings, max_items=1, max_usd=.5)
        with self.assertRaises(ValueError):
            run(self.output, self.settings, max_items=1)
        result = run(self.output, self.settings, max_items=1, max_usd=.5)
        self.assertEqual(result["budget"]["admitted_calls"], 2)

    def test_three_consecutive_schema_errors_stop_spending(self):
        self.fixture.judge_response = "not JSON"
        result = run(self.output, self.settings)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["stopped_reason"], "INVALID_JUDGE_RESPONSE")
        self.assertEqual(len(self.fixture.requests), 3)


if __name__ == "__main__":
    unittest.main()
