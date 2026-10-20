"""Public redaction must never alter private execution/evaluation evidence."""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.batch import BatchRunner
from app.batch_models import BatchReview, BatchSpec
from app.config import Settings
from app.evaluation import RuleEvaluator
from app.models import (DefenseEvent, DetectorGoldUpdate, EvaluationUpdate,
                        ModelCall, RunRequest, RunTrace)
from app.providers import DemoRagProvider, OpenAICompatibleProvider, ProviderResponse
from app.repository import ArtifactValidationError, ExperimentRepository, RunTraceStore
from app.service import RunService, TraceableRunError


class ProtectedTracePrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.data = self.folder / "data"
        self.data.mkdir()
        self.secret = "vault-test-48/Z"
        self.unicode_secret = "시험값_73"
        self.canary = "CANARY_PRIVACY_FIXTURE_882"
        self.variants = []
        for value in (self.secret, self.unicode_secret, self.canary):
            mixed_url = "".join(character if index % 2 else
                "".join(f"%{byte:02x}" for byte in character.encode())
                for index, character in enumerate(value))
            encoded = base64.b64encode(value.encode()).decode()
            self.variants.extend([value, encoded, mixed_url, " \t".join(value),
                                  "\n".join(encoded)])
        self.text = " / ".join(self.variants)
        # Only a dev case/document is inspected; no holdout content is used.
        case = next(json.loads(line) for line in (ROOT / "data/cases.v0.1.jsonl").read_text(
            encoding="utf-8").splitlines() if json.loads(line)["case_id"] == "a006")
        document = next(json.loads(line) for line in (ROOT / "data/corpus.v0.1.jsonl").read_text(
            encoding="utf-8").splitlines() if json.loads(line)["document_id"] == "doc006")
        case["user_input"] = "fixture input " + self.text
        document["content"] = "fixture context " + self.text
        self._write(self.data / "cases.v0.1.jsonl", case)
        self._write(self.data / "corpus.v0.1.jsonl", document)
        self.rules = self.folder / "rules.json"
        self._write(self.rules, {"version": "privacy-fixture-v1", "policy_version": "test-only-v1",
            "dataset_versions": [case["source_version"]], "rules": [
                {"case_id": "a006", "canary": self.canary,
                 "protected_values": [self.secret, self.unicode_secret]},
                {"case_id": "b006", "protected_values": ["OTHER_CASE_TARGET"]}]})
        self.settings = Settings(project_root=ROOT, data_dir=self.data, runs_dir=self.folder / "runs",
            model_provider="demo", model_id="demo-rag-v0.1", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None,
            evaluation_rules_path=self.rules)
        self.request = RunRequest(schema_version="0.3", artifact_type="run_request", case_id="a006",
            scenario="rag_chat", defense_mode="none", dataset_version=case["source_version"],
            corpus_version=document["source_version"], requested_by=self.secret)
        self.store = RunTraceStore(self.settings.runs_dir)
        self.provider_messages = []
        outer = self

        class CapturingProvider:
            def generate_prepared(self, prompt, parameters):
                outer.provider_messages.append([message.model_dump() for message in prompt.messages])
                output = outer.text + " OTHER_CASE_TARGET"
                call = ModelCall(purpose="generation", model_id="fixture", messages=prompt.messages,
                    parameters={"nested": [{outer.secret: outer.text}]}, latency_ms=0, response_text=output)
                return ProviderResponse(output, None, None, None, call)

        class CapturingEvaluator(RuleEvaluator):
            def evaluate(self, context):
                outer.evaluated_output = context.raw_output
                return super().evaluate(context)

        self.service = RunService(self.settings, ExperimentRepository(self.data), self.store,
                                  CapturingProvider(), evaluator=CapturingEvaluator(self.rules))

    @staticmethod
    def _write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")

    @staticmethod
    def _hash(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _assert_safe(self, value):
        serialized = json.dumps(value.model_dump(mode="json") if isinstance(value, RunTrace) else value,
                                ensure_ascii=False)
        for variant in self.variants:
            self.assertNotIn(variant, serialized)
        self.assertIn("[MASKED_PROTECTED]", serialized)

    def _legacy_batch(self, *, run_id=None):
        # Planning freezes rules only; it performs no generation/model calls.
        runner = BatchRunner(self.settings)
        spec = BatchSpec.model_validate({"sources": [{"source_id": "rag", "data_dir": "data",
            "split": "dev", "case_ids": ["a006"]}], "repeats": 1,
            "conditions": [{"condition_id": "none", "defense_mode": "none", "comparisons": ["technique"]}],
            "budget": {"max_calls": 10, "max_reserved_tokens": 100000, "max_seconds": 60,
                       "unknown_price_policy": "calls_tokens"}})
        state = runner.create(spec)
        run_id = run_id or "run-" + state.batch_id[6:] + "-entry-000000-attempt-1"
        trace = self.service.execute(self.request, run_id=run_id)
        raw = self.store.get_raw(run_id)
        # Reproduce an old public file that contains unmasked non-CANARY fields.
        legacy = trace.model_dump(mode="json")
        legacy["input"] = raw["input"]
        legacy["prompt_assembly"] = raw["prompt_assembly"]
        legacy["model_calls"] = raw["model_calls"]
        legacy["output"].update(display_text=raw["provider_output"], is_masked=False)
        legacy["evaluation"]["reason"] = self.text
        legacy["defense_events"] = [DefenseEvent(defense_id="D2", defense_version="fixture",
            stage="input", decision="allow", score=.1, threshold=.5,
            reason_code="fixture", reason=self.text).model_dump(mode="json")]
        legacy["detector_evaluation"] = [{"stage": "input", "target_ref": None,
            "gold_label": "malicious", "gold_version": "fixture", "reason": self.text,
            "reviewer": self.text}]
        self.store.save(RunTrace.model_validate(legacy))
        state.plan[0]["attempts"] = [{"run_id": run_id, "attempt_id": "fixture", "status": "completed"}]
        state.plan[0]["status"] = state.status = "completed"
        runner.store.save(state)
        current_rules = self.folder / "different-current-rules.json"
        self._write(current_rules, {"version": "different", "policy_version": "different",
            "rules": [{"case_id": "a006", "protected_values": ["UNRELATED_CURRENT_SECRET"]}]})
        reader_settings = replace(self.settings, evaluation_rules_path=current_rules)
        reader = RunService(reader_settings, ExperimentRepository(self.data), self.store, DemoRagProvider())
        return runner, state, run_id, reader_settings, reader

    def test_fresh_trace_masks_all_public_fields_and_variants_after_raw_evaluation(self):
        trace = self.service.execute(self.request)
        self._assert_safe(trace)
        self._assert_safe(json.loads((self.settings.runs_dir / (trace.run_id + ".trace.json")).read_text(
            encoding="utf-8")))
        self.assertEqual(trace.evaluation.attack_success, "success")
        self.assertEqual(trace.evaluation.normal_task_success, "failure")
        self.assertEqual(self.evaluated_output, self.text + " OTHER_CASE_TARGET")
        self.assertTrue(trace.output.is_masked)
        raw = self.store.get_raw(trace.run_id)
        for original, component in zip(raw["prompt_assembly"], trace.prompt_assembly):
            self.assertEqual(component.is_masked, original["display_text"] != component.display_text)
        self.assertEqual(trace.request.requested_by, "[MASKED_PROTECTED]")
        self.assertIn("OTHER_CASE_TARGET", trace.output.display_text)
        self.assertIn(self.secret, raw["input"]["user_input"])
        self.assertEqual(raw["model_calls"][0]["messages"], self.provider_messages[0])
        self.assertIn(self.secret, json.dumps(self.provider_messages, ensure_ascii=False))
        self.assertNotIn("[MASKED_PROTECTED]", json.dumps(raw, ensure_ascii=False))
        self.assertEqual(self.service.get_trace(trace.run_id), trace)

    def test_legacy_get_uses_frozen_rules_without_writing_or_calling_a_provider(self):
        runner, state, run_id, settings, reader = self._legacy_batch()
        watched = list(settings.runs_dir.glob(run_id + ".*.json")) + [runner.store.folder(state.batch_id) / "manifest.json"]
        before = {path: self._hash(path) for path in watched}
        with patch.object(Settings, "from_environment", return_value=settings):
            from app.main import create_app
        with patch.object(DemoRagProvider, "generate_prepared", side_effect=AssertionError("GET generated")), \
             patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("GET called API")):
            response = TestClient(create_app(settings)).get("/api/v1/runs/" + run_id)
            self.assertEqual(response.status_code, 200, response.text)
            self._assert_safe(response.json())
            trace = reader.get_trace(run_id)
        self.assertTrue(trace.output.is_masked)
        self.assertTrue(any(component.is_masked for component in trace.prompt_assembly))
        self.assertEqual(before, {path: self._hash(path) for path in watched})
        self.assertIn(self.secret, (settings.runs_dir / (run_id + ".trace.json")).read_text(encoding="utf-8"))

    def test_arbitrary_legacy_run_id_finds_frozen_membership(self):
        _, _, run_id, _, reader = self._legacy_batch(run_id="run-legacy-independent")
        self._assert_safe(reader.get_trace(run_id))

    def test_invalid_frozen_rules_or_membership_fail_closed_instead_of_using_current_rules(self):
        runner, state, run_id, _, reader = self._legacy_batch()
        snapshot = runner.store.folder(state.batch_id) / "evaluation_rules.snapshot"
        snapshot.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ArtifactValidationError, "hash mismatch"):
            reader.get_trace(run_id)
        state.plan[0]["attempts"] = []
        runner.store.save(state)
        with self.assertRaisesRegex(ArtifactValidationError, "membership"):
            reader.get_trace(run_id)

    def test_traceable_error_uses_the_redacted_public_message(self):
        with patch.object(self.service._repository, "get_case", side_effect=ArtifactValidationError(self.text)):
            with self.assertRaises(TraceableRunError) as captured:
                self.service.execute(self.request)
        self._assert_safe({"error": str(captured.exception)})
        self.assertEqual(str(captured.exception), captured.exception.trace.error.message)
        self.assertEqual(self.store.get_raw(captured.exception.trace.run_id)["provider_error"], self.text)

    def test_public_reviews_mask_frozen_targets_and_private_audit_history_stays_original(self):
        runner, state, run_id, settings, reader = self._legacy_batch()
        raw_path = settings.runs_dir / (run_id + ".raw.json")
        before = self._hash(raw_path)
        trace = reader.update_evaluation(run_id, EvaluationUpdate(attack_success="success",
            normal_task_success="failure", evaluator_version="review-fixture", reviewer="fixture",
            reason=self.text))
        self._assert_safe(trace)
        gold_trace = reader.update_detector_gold(run_id, DetectorGoldUpdate(stage="input",
            gold_label="malicious", gold_version="fixture", reviewer="fixture", reason=self.text))
        self._assert_safe(gold_trace)
        for suffix in ("evaluation", "detector-gold"):
            history = json.loads((settings.runs_dir / (run_id + "." + suffix + ".json")).read_text(encoding="utf-8"))
            self.assertEqual(history[-1]["reason"], self.text)
        batch_review = BatchRunner(settings).review(state.batch_id, run_id, BatchReview(
            reviewer="fixture", reason=self.text, policy_version="fixture", target_exposed=True))
        self._assert_safe(batch_review)
        history = json.loads((runner.store.folder(state.batch_id) / "reviews.json").read_text(encoding="utf-8"))
        self._assert_safe(history)
        self.assertEqual(before, self._hash(raw_path))
        self._assert_safe(reader.get_trace(run_id))


if __name__ == "__main__":
    unittest.main()
