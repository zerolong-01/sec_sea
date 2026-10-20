"""Research decisions stay schema-compatible without fabricating review/freeze."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from backend.app.batch_analysis import statistic
from backend.app.batch_models import BatchSpec, StatisticsPolicy

ROOT = Path(__file__).resolve().parents[1]


class StatisticalPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads((ROOT / "configs/week3-statistical-policy.json").read_text(encoding="utf-8"))
        cls.runtime = StatisticsPolicy.model_validate(cls.policy["runtime_statistics"])

    def test_runtime_is_separate_from_research_authority_and_fake_review(self):
        self.assertEqual(self.policy["decision_status"], "adopted_for_dev")
        self.assertEqual(self.policy["authority"]["kind"], "user_delegated_research_decision")
        self.assertEqual(self.policy["authority"]["decision_date"], "2026-10-20")
        self.assertEqual(self.policy["authority"]["external_review_status"], "pending")
        self.assertEqual(self.policy["authority"]["human_reviewers"], [])
        self.assertEqual(self.runtime.reviewed_by, [])
        self.assertEqual(self.runtime.status, "draft")
        with self.assertRaises(ValidationError):
            StatisticsPolicy.model_validate(self.policy)

    def test_sample_floor_and_resampling_choices_are_consistent(self):
        floor = self.policy["sample_floor"]
        repeats = self.policy["execution_plan"]["repeats_per_case_condition"]
        self.assertEqual(self.runtime.minimum_families, floor["minimum_independent_families"])
        self.assertEqual(self.runtime.minimum_evaluated_runs, floor["minimum_evaluated_runs_or_pairs"])
        self.assertEqual(repeats, floor["minimum_planned_repeats_per_case_condition"])
        self.assertEqual(self.runtime.minimum_evaluated_runs, repeats * self.runtime.minimum_families)
        self.assertEqual(self.runtime.bootstrap_samples, self.policy["confidence_intervals"]["bootstrap_samples"])
        self.assertEqual(self.runtime.bootstrap_samples, 10000)
        self.assertFalse(self.policy["confidence_intervals"]["coverage_guaranteed_by_sample_floor"])

    def test_repeated_one_family_never_satisfies_independent_sample_gate(self):
        many_repeats = [("one-original-family", value % 2) for value in range(600)]
        result = statistic(many_repeats, self.runtime)
        self.assertEqual(result["denominator"], 600)
        self.assertEqual(result["family_count"], 1)
        self.assertEqual(result["value"], .5)
        self.assertIsNone(result["ci95"])
        self.assertEqual(result["inference_status"], "insufficient_sample")

    def test_both_family_and_evaluated_run_gates_apply(self):
        insufficient_runs = [(f"family-{i}", i % 2) for i in range(self.runtime.minimum_families)]
        result = statistic(insufficient_runs, self.runtime)
        self.assertIsNone(result["ci95"])
        self.assertEqual(result["inference_status"], "insufficient_sample")
        enough = [(family, value) for family, value in insufficient_runs for _ in range(3)]
        available = statistic(enough, self.runtime)
        self.assertEqual(available["inference_status"], "available")
        self.assertEqual(available["denominator"], 60)
        self.assertIsNotNone(available["ci95"])
        self.assertLessEqual(available["ci95"][0], available["value"])
        self.assertGreaterEqual(available["ci95"][1], available["value"])

    def test_policy_cannot_authorize_holdout_or_unadjusted_superiority(self):
        plan = self.policy["execution_plan"]
        self.assertEqual(plan["split"], "dev")
        self.assertFalse(plan["holdout_execution_authorized"])
        self.assertTrue(plan["preserve_existing_manifest_statistics"])
        for key in ("confirmatory_tests_enabled", "statistical_superiority_claims_allowed",
                    "simultaneous_coverage_claims_allowed", "ci_overlap_implies_equivalence"):
            self.assertFalse(self.policy["multiplicity"][key])
        self.assertFalse(self.policy["abstention"]["zero_events_prove_zero_risk"])
        spec = {"sources": [{"source_id": "test", "data_dir": "data/week2", "split": "holdout"}],
                "statistics": self.runtime.model_dump(mode="json"), "repeats": plan["repeats_per_case_condition"],
                "budget": {"max_calls": 1, "max_reserved_tokens": 1, "max_seconds": 1}}
        with self.assertRaisesRegex(ValidationError, "Holdout requires"):
            BatchSpec.model_validate(spec)

    def test_parameter_sources_resolve_to_recorded_primary_references_without_network(self):
        sources = {s["id"]: s for s in self.policy["sources"]}
        self.assertEqual(len(sources), len(self.policy["sources"]))
        allowed = {"aclanthology.org", "www.econ.ucdavis.edu", "arxiv.org", "www.ime.usp.br", "jamanetwork.com"}
        for source in sources.values():
            parsed = urlsplit(source["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, allowed)
            self.assertTrue(source["supports"])
            self.assertTrue(source["does_not_supply"])
        for decision in self.policy["parameter_rationale"].values():
            self.assertTrue(decision["source_ids"])
            self.assertTrue(set(decision["source_ids"]) <= sources.keys())
            self.assertTrue(decision["choice_kind"].startswith("project_"))


if __name__ == "__main__":
    unittest.main()
