from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.batch import BatchRunner, batch_lock
from app.batch_models import BatchCondition, BatchSource, BatchSpec
from app.config import Settings
from app.repository import RunTraceStore
from backend.testing.fixture_model import FixtureModelServer


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.fixture = FixtureModelServer(ROOT / "data").__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        self.settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=self.folder / "runs",
            model_provider="fixture_http", model_id="fixture-generation", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=self.fixture.base_url,
            model_api_key="test-only-private-key", d2_model_id="fixture-classifier",
            evaluation_rules_path=ROOT / "configs/evaluation-starter.json")
        self.runner = BatchRunner(self.settings)

    def spec(self, **updates):
        data = {"sources": [{"source_id": "rag", "data_dir": "data", "split": "dev",
                             "case_ids": ["a006", "b006", "h007"]}], "repeats": 1,
                "budget": {"max_calls": 1000, "max_reserved_tokens": 10_000_000, "max_seconds": 60,
                           "unknown_price_policy": "calls_tokens"}}
        data.update(updates)
        return BatchSpec.model_validate(data)

    def one(self, mode="none", case_id="b006", **updates):
        data = {"sources": [{"source_id": "rag", "data_dir": "data", "split": "dev", "case_ids": [case_id]}],
                "conditions": [{"condition_id": "one", "defense_mode": mode, "comparisons": ["technique"]}]}
        data.update(updates)
        return self.spec(**data)

    def test_six_unique_conditions_snapshot_and_resume_without_duplicate_calls(self):
        state = self.runner.create(self.spec())
        self.assertEqual(len(state.plan), 18)
        shared = [c for c in state.spec.conditions if len(c.comparisons) == 2]
        self.assertEqual([c.condition_id for c in shared], ["D2-both"])
        state = self.runner.execute(state.batch_id, max_items=2)
        self.assertEqual(state.status, "paused")
        self.assertEqual(sum(len(e["attempts"]) for e in state.plan), 2)
        state = self.runner.execute(state.batch_id)
        self.assertEqual(state.status, "completed")
        sent = len(self.fixture.requests)
        state = self.runner.execute(state.batch_id)
        self.assertEqual(len(self.fixture.requests), sent)
        self.assertEqual(len(state.calls), sent)
        self.assertEqual(sum(len(e["attempts"]) for e in state.plan), 18)
        serialized = json.dumps(self.runner.store.summary(state), ensure_ascii=False)
        self.assertNotIn("test-only-private-key", serialized)
        self.assertNotIn("CANARY_EDU_SECRET_2026", serialized)
        self.assertIsNone(self.runner.store.summary(state)["budget"]["total_cost_usd"])

    def test_before_call_limit_cannot_be_bypassed_by_detector_fail_open(self):
        runner = BatchRunner(replace(self.settings, d2_error_policy="fail_open"))
        spec = self.one("D2", budget={"max_calls": 1, "max_reserved_tokens": 100000, "max_seconds": 60,
                                     "unknown_price_policy": "calls_tokens"})
        state = runner.execute(runner.create(spec).batch_id)
        self.assertEqual(len(self.fixture.requests), 1)
        self.assertEqual(state.reason, "BATCH_CALL_BUDGET_EXCEEDED")
        trace = RunTraceStore(self.settings.runs_dir).get(state.plan[0]["attempts"][0]["run_id"])
        self.assertEqual(trace.status, "failed")
        self.assertEqual(trace.metrics.generation_call_count, 0)

    def test_unknown_prices_stop_before_transport_when_usd_cap_is_requested(self):
        spec = self.one(budget={"max_calls": 10, "max_reserved_tokens": 100000, "max_seconds": 60,
                                "max_usd": .1})
        state = self.runner.execute(self.runner.create(spec).batch_id)
        self.assertEqual(state.reason, "BATCH_VERIFIED_PRICE_REQUIRED")
        self.assertEqual(self.fixture.requests, [])
        self.assertEqual(state.calls, [])

    def test_durable_reservation_on_interrupt_is_not_silently_replayed(self):
        state = self.runner.create(self.one())
        with patch("app.batch_budget.BatchCallBudget.after", side_effect=KeyboardInterrupt):
            state = self.runner.execute(state.batch_id)
        self.assertEqual(state.status, "uncertain")
        self.assertEqual(len(self.fixture.requests), 1)
        self.assertEqual(state.calls[0]["status"], "reserved")
        state = self.runner.execute(state.batch_id)
        self.assertEqual(state.reason, "uncertain_attempt_requires_explicit_retry")
        self.assertEqual(len(self.fixture.requests), 1)
        state = self.runner.execute(state.batch_id, retry_uncertain=True)
        self.assertEqual(state.status, "completed")
        self.assertEqual(len(self.fixture.requests), 2)
        self.assertEqual(len(state.plan[0]["attempts"]), 2)
        self.assertEqual(state.calls[0]["status"], "abandoned_unknown")

    def test_failed_attempt_is_only_retried_explicitly_and_both_calls_remain(self):
        self.fixture.fail_detection = "malformed"
        state = self.runner.execute(self.runner.create(self.one("D2")).batch_id)
        self.assertEqual(state.status, "partial")
        sent = len(self.fixture.requests)
        state = self.runner.execute(state.batch_id)
        self.assertEqual(len(self.fixture.requests), sent)
        self.fixture.fail_detection = None
        state = self.runner.execute(state.batch_id, retry_failed=True)
        self.assertEqual(state.status, "completed")
        self.assertEqual(len(state.plan[0]["attempts"]), 2)
        self.assertEqual(len(state.calls), len(self.fixture.requests))

    def test_tampered_snapshot_and_runtime_configuration_stop_before_any_call(self):
        state = self.runner.create(self.one())
        path = self.runner.store.folder(state.batch_id) / "inputs/rag/corpus.v0.1.jsonl"
        path.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.runner.execute(state.batch_id)
        other = BatchRunner(replace(self.settings, temperature=.2))
        with self.assertRaisesRegex(ValueError, "settings changed"):
            other.execute(state.batch_id)
        self.assertEqual(self.fixture.requests, [])

    def test_common_policy_identical_in_actual_none_and_d1_requests(self):
        spec = self.one(conditions=[{"condition_id": name, "defense_mode": name, "comparisons": ["technique"]}
                                   for name in ("none", "D1")])
        state = self.runner.execute(self.runner.create(spec).batch_id)
        self.assertEqual(state.status, "completed")
        self.assertEqual(len(self.fixture.requests), 2)
        for request in self.fixture.requests:
            self.assertIn("공통 애플리케이션 보안 정책 v0.1", request["messages"][0]["content"])
            self.assertNotIn("family_id", json.dumps(request))
            self.assertNotIn("attack_goal", json.dumps(request))
        prompts = [p["messages"][0]["content"] for p in self.fixture.requests]
        self.assertEqual(sum("신뢰 경계" in p for p in prompts), 1)

    def test_duplicate_conditions_split_mix_and_unfrozen_holdout_rejected(self):
        condition = {"condition_id": "one", "defense_mode": "none", "comparisons": ["technique"]}
        with self.assertRaises(ValueError):
            self.spec(conditions=[condition, {**condition, "condition_id": "two"}])
        with self.assertRaises(ValueError):
            self.spec(sources=[{"source_id": "rag", "data_dir": "data", "split": "holdout"}])
        with self.assertRaises(ValueError):
            self.spec(sources=[{"source_id": "a", "data_dir": "data", "split": "dev"},
                               {"source_id": "b", "data_dir": "data", "split": "holdout"}])


if __name__ == "__main__":
    unittest.main()
