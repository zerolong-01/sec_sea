from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.experiment_models import ExperimentSpec
from app.experiments import ExperimentRunner
from app.repository import ArtifactValidationError


class ExperimentPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runs = Path(self.temporary.name) / "runs"
        self.runner = ExperimentRunner(ROOT, self.runs)
        self.settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=self.runs,
            model_provider="demo", model_id="demo", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None)

    def spec(self, **updates):
        payload = {"models": [{"model_key": key, "provider": "demo", "model_id": "demo-" + key}
                               for key in ("first", "second")],
            "batch": {"sources": [{"source_id": "rag", "data_dir": "data", "split": "dev",
                                   "case_ids": ["a006", "b006", "h007"]}],
                "conditions": [{"condition_id": mode, "defense_mode": mode, "comparisons": ["technique"]}
                               for mode in ("none", "D1")], "repeats": 1,
                "budget": {"max_calls": 100, "max_reserved_tokens": 10000000,
                           "max_seconds": 60, "unknown_price_policy": "calls_tokens"}}}
        payload.update(updates)
        return ExperimentSpec.model_validate(payload)

    def test_planning_freezes_equal_inputs_and_never_calls_models(self):
        with patch("app.providers.DemoRagProvider.generate_prepared", side_effect=AssertionError("No model calls")):
            state = self.runner.create(self.spec(), settings=self.settings)
        children = self.runner.validate_members(self.runner.store.get(state.experiment_id))
        self.assertEqual(len(children), 2)
        self.assertNotEqual(children[0].batch_id, children[1].batch_id)
        self.assertEqual(children[0].plan, children[1].plan)
        self.assertEqual(children[0].source_snapshots, children[1].source_snapshots)
        self.assertNotEqual(children[0].execution_settings["model_id"], children[1].execution_settings["model_id"])
        self.assertTrue(all(not child.calls for child in children))

    def test_invalid_profiles_and_missing_shared_detector_are_rejected(self):
        payload = self.spec().model_dump(mode="json")
        for change in ("duplicate_key", "duplicate_model", "mixed_scope", "missing_detector", "inline_key"):
            data = json.loads(json.dumps(payload))
            if change == "duplicate_key":
                data["models"][1]["model_key"] = "first"
            elif change == "duplicate_model":
                data["models"][1]["model_id"] = "demo-first"
            elif change == "mixed_scope":
                data["models"][1].update(provider="openai_compatible", base_url="http://localhost:8000/v1")
            elif change == "missing_detector":
                data["batch"]["conditions"][1]["defense_mode"] = "D2"
            else:
                data["models"][1]["api_key"] = "must-not-be-stored"
            with self.subTest(change=change), self.assertRaises(ValueError):
                ExperimentSpec.model_validate(data)

    def test_swapped_members_and_changed_data_fail_validation(self):
        state = self.runner.create(self.spec(), settings=self.settings)
        path = self.runner.store.folder(state.experiment_id) / "manifest.json"
        original = path.read_bytes()
        payload = json.loads(original)
        payload["members"].reverse()
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ArtifactValidationError):
            self.runner.store.get(state.experiment_id)
        path.write_bytes(original)
        child = self.runner.validate_members(state)[1]
        frozen = self.runner.batches.folder(child.batch_id) / "inputs/rag/cases.v0.1.jsonl"
        frozen.write_bytes(frozen.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            self.runner.validate_members(state)
