from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.batch_models import BatchSpec, RecommendationPolicy
from scripts.data_contract import ROOT, DataContractError
from scripts.week3_policy import research_policy
from scripts.week3_prepare import prepare, validate


class ResearchPolicyTests(unittest.TestCase):
    def test_adopted_numbers_do_not_fabricate_final_approval(self):
        loaded = research_policy()
        policy = RecommendationPolicy.model_validate_json((ROOT / loaded["evaluation_policy_file"]).read_text(encoding="utf-8"))
        self.assertTrue(all(value is not None for value in policy.thresholds.model_dump().values()))
        self.assertEqual(len(policy.priority), 6)
        self.assertFalse(policy.final_recommendation_allowed)
        self.assertEqual(policy.reviewed_by, [])
        self.assertEqual(loaded["decision"]["status"], "adopted_for_dev")
        self.assertFalse(loaded["decision"]["holdout_authorized"])

    def test_new_preparation_freezes_research_statistics_and_review_inputs(self):
        with tempfile.TemporaryDirectory() as temp, patch(
                "backend.app.providers.OpenAICompatibleProvider.complete", side_effect=AssertionError("No model calls")):
            output = Path(temp) / "new"
            prepared = prepare(output)
            spec = BatchSpec.model_validate_json((output / "batch-spec.json").read_text(encoding="utf-8"))
            self.assertEqual(spec.statistics.bootstrap_samples, 10000)
            self.assertEqual(spec.statistics.minimum_families, 20)
            self.assertEqual(spec.statistics.minimum_evaluated_runs, 60)
            self.assertEqual(spec.repeats, 3)
            self.assertTrue(all(source.split == "dev" for source in spec.sources))
            rag, email = spec.sources
            self.assertEqual(rag.metadata["w3_a001_original"].severity, "critical")
            self.assertEqual(rag.metadata["w3_a006_original"].goal_kind, "marker")
            self.assertEqual(email.metadata["email-attack-001"].goal_kind, "marker")
            self.assertEqual(email.metadata["email-hard-negative-001"].goal_kind, "normal")
            self.assertTrue(all(item.severity != "unspecified" for source in spec.sources for item in source.metadata.values()))
            self.assertIn("data/week2/target-gold.v0.1.jsonl", prepared["source_sha256"])
            self.assertIn("data/week3/research-evaluation-spec.v0.4.json", prepared["source_sha256"])
            self.assertIn("configs/week3-statistical-policy.json", prepared["source_sha256"])
            self.assertEqual(validate(output), prepared)
            with patch("scripts.week3_prepare.file_hash", return_value="changed"):
                with self.assertRaises(DataContractError):
                    validate(output)

    def test_conflicting_thresholds_or_holdout_authority_are_rejected(self):
        for name in ("threshold", "holdout", "fake_freeze"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for source in research_policy()["source_files"]:
                    destination = root / source
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / source, destination)
                target = root / ("configs/week3-evaluation-policy.json" if name == "threshold" else "configs/week3-statistical-policy.json")
                data = json.loads(target.read_text(encoding="utf-8"))
                if name == "threshold":
                    data["thresholds"]["ASR_MAX"] = .9
                elif name == "holdout":
                    data["execution_plan"]["holdout_execution_authorized"] = True
                else:
                    data["runtime_statistics"]["status"] = "frozen"
                target.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(DataContractError):
                    research_policy(root)
