from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.batch import BatchRunner, batch_lock, atomic_json
from app.batch_models import BatchCondition, BatchSource, BatchSpec
from app.batch_budget import BatchCallBudget
from app.accounting import Accounting
from app.models import ModelCall, ChatMessage
from app.providers import ProviderError
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

    def test_http_failure_keeps_its_admitted_call_and_unknown_usage(self):
        self.fixture.fail_detection = "http_error"
        state = self.runner.execute(self.runner.create(self.one("D2")).batch_id)
        self.assertEqual(state.status, "partial")
        self.assertEqual(len(state.calls), 1)
        self.assertEqual(state.calls[0]["error_code"], "MODEL_PROVIDER_ERROR")
        self.assertIsNone(state.calls[0]["input_tokens"])
        self.assertIsNone(self.runner.store.summary(state)["budget"]["total_cost_usd"])

    def test_token_and_verified_dollar_reservations_stop_before_transport(self):
        token_spec = self.one(budget={"max_calls": 10, "max_reserved_tokens": 100, "max_seconds": 60,
                                     "unknown_price_policy": "calls_tokens"})
        state = self.runner.execute(self.runner.create(token_spec).batch_id)
        self.assertEqual(state.reason, "BATCH_TOKEN_BUDGET_EXCEEDED")
        self.assertEqual(self.fixture.requests, [])
        price_path = self.folder / "prices.json"
        price_path.write_text(json.dumps({"version": "test-only-price", "currency": "USD", "models": [
            {"model_id": "fixture-generation", "input_usd_per_million": 1, "output_usd_per_million": 1,
             "source_url": "https://example.com/test-fixture-not-a-real-price", "effective_date": "2026-10-13", "verified": True}]}), encoding="utf-8")
        runner = BatchRunner(replace(self.settings, pricing_path=price_path))
        usd_spec = self.one(budget={"max_calls": 10, "max_reserved_tokens": 1000000, "max_seconds": 60,
                                   "per_call_input_token_ceiling": 10000, "max_usd": .005})
        state = runner.execute(runner.create(usd_spec).batch_id)
        self.assertEqual(state.reason, "BATCH_USD_BUDGET_EXCEEDED")
        self.assertEqual(self.fixture.requests, [])
        usd_spec.budget.max_usd = .02
        state = runner.execute(runner.create(usd_spec).batch_id)
        self.assertEqual(state.status, "completed")
        self.assertAlmostEqual(state.calls[0]["known_cost_usd"], .000022)
        self.assertAlmostEqual(state.calls[0]["committed_usd"], .000022)
        self.fixture.missing_usage = True
        usd_spec.repeats = 2
        usd_spec.budget.max_usd = .015
        calls_before = len(self.fixture.requests)
        state = runner.execute(runner.create(usd_spec).batch_id)
        self.assertEqual(state.reason, "BATCH_USD_BUDGET_EXCEEDED")
        self.assertEqual(len(self.fixture.requests) - calls_before, 1)
        self.assertIsNone(state.calls[0]["known_cost_usd"])
        self.assertEqual(state.calls[0]["committed_usd"], state.calls[0]["reserved_usd"])

    def test_expired_wall_budget_prevents_new_attempts(self):
        state = self.runner.create(self.one())
        state.elapsed_seconds = state.spec.budget.max_seconds
        self.runner.store.save(state)
        state = self.runner.execute(state.batch_id)
        self.assertEqual(state.reason, "BATCH_TIME_BUDGET_EXCEEDED")
        self.assertEqual(state.plan[0]["status"], "pending")
        self.assertEqual(self.fixture.requests, [])

    def test_writer_lock_blocks_a_second_runner(self):
        state = self.runner.create(self.one())
        with batch_lock(self.runner.store.folder(state.batch_id)):
            with self.assertRaisesRegex(ValueError, "active writer"):
                self.runner.execute(state.batch_id)
        self.assertEqual(self.fixture.requests, [])

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

    def test_plan_case_or_family_cannot_change_after_snapshot_freeze(self):
        state = self.runner.create(self.one())
        state.plan[0]["metadata"]["family_id"] = "different-family"
        self.runner.store.save(state)
        with self.assertRaisesRegex(ValueError, "plan metadata changed"):
            self.runner.execute(state.batch_id)
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

    def test_holdout_inventory_does_not_authorize_execution_and_selection_is_frozen(self):
        raw = self.spec().model_dump(mode="json")
        raw["sources"] = [{"source_id": "holdout-rag", "data_dir": "data/week2", "split": "holdout"}]
        raw["repeats"] = 3
        inventory_only = BatchSpec.model_validate(raw, context={"inventory_only": True})
        hashes = self.runner.inspect_inputs(inventory_only)[-1]
        self.assertIn("selection", hashes)
        with self.assertRaises(ValueError):
            self.runner.create(inventory_only)
        # Changing a reviewed selection must alter the freeze inventory even
        # when the underlying files and runtime model settings are identical.
        changed = inventory_only.model_copy(deep=True)
        changed.sources[0].languages = ["en"]
        with self.assertRaisesRegex(ValueError, "selects no cases"):
            self.runner.inspect_inputs(changed)
        self.assertEqual(self.fixture.requests, [])

    def test_comparison_cannot_change_threshold_and_effective_duplicates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "D2 overrides"):
            self.one(conditions=[{"condition_id": "invalid-none", "defense_mode": "none",
                                  "d2_threshold": .9, "comparisons": ["technique"]}])
        spec = self.spec(conditions=[
            {"condition_id": "D2", "defense_mode": "D2", "comparisons": ["technique"], "d2_threshold": .5},
            {"condition_id": "D1-D2", "defense_mode": "D1+D2", "comparisons": ["technique"], "d2_threshold": .9}])
        with self.assertRaisesRegex(ValueError, "more than the intended"):
            self.runner.create(spec)
        spec = self.spec(conditions=[
            {"condition_id": "default", "defense_mode": "D2", "comparisons": ["technique"]},
            {"condition_id": "explicit", "defense_mode": "D2", "comparisons": ["technique"], "d2_threshold": .5}])
        with self.assertRaisesRegex(ValueError, "Duplicate effective"):
            self.runner.create(spec)

    def test_planning_rejects_credential_bearing_endpoint_before_persisting_it(self):
        bad = BatchRunner(replace(self.settings, model_base_url="https://user:private-password@example.com/v1"))
        with self.assertRaisesRegex(ValueError, "without credentials"):
            bad.create(self.one())
        self.assertEqual(bad.store.list(), [])

    def test_status_replace_survives_a_concurrent_windows_reader(self):
        target = self.folder / "state.json"
        atomic_json(target, {"status": "old"})
        handle = target.open("r", encoding="utf-8")
        release = threading.Thread(target=lambda: (time.sleep(.05), handle.close()))
        release.start()
        try:
            atomic_json(target, {"status": "new"})
        finally:
            release.join()
            handle.close()
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"status": "new"})
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_reservation_write_delay_cannot_send_a_call_after_deadline(self):
        spec = self.one()
        spec.budget.max_seconds = 1
        state = self.runner.create(spec)
        elapsed = [0]
        def slow_save(_):
            elapsed[0] += .6
        budget = BatchCallBudget(state, slow_save, Accounting(), "delayed-attempt", clock=lambda: elapsed[0])
        call = ModelCall(purpose="generation", model_id="fixture-generation", parameters={"max_tokens": 512},
                         messages=[ChatMessage(role="user", content="test")], latency_ms=0)
        with self.assertRaises(ProviderError) as raised:
            budget.before(call)
        self.assertEqual(raised.exception.code, "BATCH_TIME_BUDGET_EXCEEDED")
        self.assertEqual(state.calls, [])


if __name__ == "__main__":
    unittest.main()
