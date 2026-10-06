from __future__ import annotations

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))
from backend.testing.fixture_model import FixtureModelServer
from app.config import Settings
from app.main import create_app


class DetectorSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.fixture = FixtureModelServer(ROOT / "data").__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        self.settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=self.folder,
            model_provider="fixture_http", model_id="fixture-model", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=self.fixture.base_url,
            model_api_key="test-credential", d2_model_id="fixture-classifier")
        self.client = TestClient(create_app(self.settings))
        self.schema = Draft202012Validator(json.loads((ROOT / "contracts/execution-v0.3.schema.json").read_text(encoding="utf-8")))

    def request(self, case="a006", position="input_retrieval", kind="detector_only"):
        return {"schema_version": "0.3", "artifact_type": "run_request", "case_id": case,
                "scenario": "rag_chat", "defense_mode": "D2", "defense_position": position,
                "dataset_version": "synthetic_v0.1.1", "corpus_version": "synthetic_v0.1.1",
                "requested_by": "security-fixture", "execution_kind": kind}

    def run_case(self, case="a006", position="input_retrieval", kind="detector_only", client=None):
        response = (client or self.client).post("/api/v1/runs", json=self.request(case, position, kind))
        self.assertEqual(response.status_code, 201, response.text)
        trace = response.json()["trace"]
        self.schema.validate(trace)
        return trace

    def override(self, doc_id=None, text=None, score=0.0, reason_code="normal_request"):
        if doc_id:
            doc = self.fixture.documents[doc_id]
            text = doc["title"] + "\n" + doc["content"]
        self.fixture.detection_overrides[text] = {"score": score, "reason_code": reason_code,
                                               "reason": "synthetic policy test; CANARY_FIXTURE"}

    def annotate(self, trace, label, stage="retrieval", target="doc006", reason="independent fixture gold", version="gold-fixture-v1"):
        response = self.client.put(f"/api/v1/runs/{trace['run_id']}/detector-gold", json={
            "stage": stage, "target_ref": target, "gold_label": label,
            "gold_version": version, "reviewer": "fixture-reviewer", "reason": reason})
        self.assertEqual(response.status_code, 200, response.text)
        self.schema.validate(response.json())
        return response.json()

    def test_contradiction_blocks_or_quarantines_and_baseline_preserves_original_decision(self):
        self.override(doc_id="doc006", reason_code="malicious_instruction")
        closed = self.run_case(position="retrieval", kind="full_pipeline")
        event = closed["defense_events"][0]
        self.assertEqual((closed["status"], event["threshold_decision"], event["decision"]), ("blocked", "allow", "quarantine"))
        self.assertTrue(event["review_needed"])
        self.assertEqual(closed["metrics"]["model_call_count"], 1)
        baseline = TestClient(create_app(replace(self.settings, d2_consistency_policy="threshold_only")))
        allowed = self.run_case(position="retrieval", kind="full_pipeline", client=baseline)
        self.assertEqual(allowed["status"], "completed")
        self.assertTrue(allowed["defense_events"][0]["review_needed"])
        self.override(text=self.fixture.cases["b006"]["user_input"], reason_code="malicious_instruction")
        blocked = self.run_case("b006", "input", "full_pipeline")
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["metrics"]["generation_call_count"], 0)
        self.override(doc_id="doc012", score=1.0, reason_code="normal_request")
        benign_review = self.run_case("b006", "retrieval")
        self.assertEqual(benign_review["defense_events"][0]["consistency_issue"], "benign_reason_at_or_above_threshold")

    def test_consistent_wrong_json_passes_defense_but_independent_gold_detects_it(self):
        self.override(doc_id="doc006")
        trace = self.run_case(kind="full_pipeline")
        self.assertEqual(trace["status"], "completed")
        self.assertFalse(trace["defense_events"][1]["review_needed"])
        raw = json.loads((self.folder / f"{trace['run_id']}.raw.json").read_text(encoding="utf-8"))
        self.assertIn("CANARY_EDU_SECRET_2026", raw["provider_output"])
        self.assertNotIn("CANARY_EDU_SECRET_2026", json.dumps(trace))
        trace = self.annotate(trace, "malicious")
        self.assertEqual(trace["detector_evaluation"][1]["analysis_status"], "valid_json_misclassification")
        self.assertEqual(trace["evaluation"]["attack_success"], "not_evaluated")
        # No rubric was supplied; misclassification must not manufacture final ASR.

    def test_detector_only_observes_targets_after_input_block_and_never_generates(self):
        trace = self.run_case("a001")
        self.assertEqual(trace["status"], "completed")
        self.assertEqual(trace["defense_events"][0]["decision"], "block")
        self.assertEqual(trace["metrics"]["detection_call_count"], 2)
        self.assertEqual(trace["metrics"]["generation_call_count"], 0)
        self.assertEqual(trace["output"]["outcome"], "not_generated")
        self.assertEqual(trace["prompt_assembly"], [])
        self.assertTrue(all(not item["included_in_prompt"] for item in trace["retrieval"]))
        self.assertEqual(trace["evaluation"]["attack_success"], "not_evaluated")
        self.assertEqual(trace["evaluation"]["evaluator_version"], "detector-only-v0.1")
        self.assertEqual(trace["evaluation"]["reason"], "detector_only:no_generation_or_final_outcome")
        update = {"attack_success": "success", "normal_task_success": "failure", "evaluator_version": "invalid",
                  "reason": "No generated output exists", "reviewer": "fixture"}
        self.assertEqual(self.client.put(f"/api/v1/runs/{trace['run_id']}/evaluation", json=update).status_code, 422)

    def test_gold_is_target_specific_post_execution_masked_and_audited(self):
        trace = self.run_case()
        before = len(self.fixture.requests)
        trace = self.annotate(trace, "benign", stage="input", target=None, reason="CANARY_EDU_SECRET_2026 is not a gold input")
        trace = self.annotate(trace, "malicious")
        self.assertEqual([row["gold_label"] for row in trace["detector_evaluation"]], ["benign", "malicious"])
        self.assertEqual([row["analysis_status"] for row in trace["detector_evaluation"]], ["correct", "correct"])
        self.assertEqual(len(self.fixture.requests), before)
        self.assertNotIn("CANARY_EDU_SECRET_2026", trace["detector_evaluation"][0]["reason"])
        self.assertEqual(self.client.get(f"/api/v1/runs/{trace['run_id']}").json(), trace)
        trace = self.annotate(trace, "review_needed", reason="team disagreement")
        history = json.loads((self.folder / f"{trace['run_id']}.detector-gold.json").read_text(encoding="utf-8"))
        self.assertEqual(len(history), 3)
        self.assertEqual(history[-2]["gold_label"], "malicious")
        self.assertEqual(history[-1]["gold_label"], "review_needed")
        self.assertIsNotNone(history[-1]["evaluated_at"])
        for payload in self.fixture.requests:
            contents = " ".join(message["content"] for message in payload["messages"])
            for forbidden in ("gold_label", "gold-fixture-v1", "fixture-reviewer", "success_criterion", "attack_goal"):
                self.assertNotIn(forbidden, contents)

    def test_report_denominators_exclude_errors_reviews_and_unannotated_and_split_conditions(self):
        traces = []
        self.override(doc_id="doc006")
        traces.append(self.annotate(self.run_case(position="retrieval"), "malicious"))
        self.override(doc_id="doc006", score=.9, reason_code="malicious_instruction")
        traces.append(self.annotate(self.run_case(position="retrieval"), "malicious"))
        self.override(doc_id="doc012", score=.9, reason_code="malicious_instruction")
        traces.append(self.annotate(self.run_case("b006", "retrieval"), "benign", target="doc012"))
        traces.append(self.annotate(self.run_case("h007", "retrieval"), "hard_negative", target="doc011"))
        self.override(doc_id="doc012", score=.1, reason_code="malicious_instruction")
        traces.append(self.annotate(self.run_case("b006", "retrieval"), "benign", target="doc012"))
        self.fixture.fail_detection = "malformed"
        traces.append(self.annotate(self.run_case("b006", "retrieval"), "benign", target="doc012"))
        self.fixture.fail_detection = None
        traces.append(self.run_case("h007", "retrieval"))
        other = TestClient(create_app(replace(self.settings, d2_consistency_policy="threshold_only")))
        traces.append(self.annotate(self.run_case("b006", "retrieval", client=other), "benign", target="doc012"))
        response = self.client.post("/api/v1/detector-report", json={"run_ids": [trace["run_id"] for trace in traces]})
        self.assertEqual(response.status_code, 200, response.text)
        self.schema.validate(response.json())
        groups = response.json()["groups"]
        self.assertEqual(len(groups), 3)  # reviewed strict / missing gold / threshold-only
        group = next(group for group in groups if group["inspected_target_count"] == 6)
        self.assertEqual((group["eligible_target_count"], group["detector_error_count"], group["review_needed_count"]), (4, 1, 1))
        self.assertEqual(group["fnr"], {"numerator": 1, "denominator": 2, "value": .5})
        self.assertEqual(group["fpr"], {"numerator": 1, "denominator": 2, "value": .5})
        self.assertEqual(group["benign_fpr"]["value"], 1)
        self.assertEqual(group["hard_negative_fpr"]["value"], 0)
        missing = next(group for group in groups if group["not_evaluated_count"])
        self.assertEqual(missing["fnr"]["denominator"], 0)
        self.assertIsNone(missing["fnr"]["value"])
        self.assertEqual(self.client.post("/api/v1/detector-report", json={"run_ids": [traces[0]["run_id"]]*2}).status_code, 422)

    def test_diagnostic_errors_and_budget_remain_failed_with_every_attempt_accounted(self):
        self.fixture.fail_detection = "malformed"
        trace = self.run_case("b006")
        self.assertEqual(trace["status"], "failed")
        self.assertEqual(trace["metrics"]["model_call_count"], 2)
        self.assertEqual(trace["metrics"]["input_tokens"], 34)
        self.assertEqual(len(trace["detector_evaluation"]), 2)
        self.assertTrue(all(row["analysis_status"] == "detector_error" for row in trace["detector_evaluation"]))
        opened = TestClient(create_app(replace(self.settings, d2_error_policy="fail_open")))
        self.assertEqual(self.run_case("b006", client=opened)["status"], "failed")
        self.fixture.fail_detection = None
        limited = TestClient(create_app(replace(self.settings, max_model_calls=1, d2_error_policy="fail_open")))
        before = len(self.fixture.requests)
        trace = self.run_case("b006", client=limited)
        self.assertEqual(len(self.fixture.requests)-before, 1)
        self.assertEqual(trace["status"], "failed")
        self.assertEqual(trace["error"]["code"], "MODEL_CALL_BUDGET_EXCEEDED")
        self.assertEqual(trace["metrics"]["generation_call_count"], 0)
        self.assertEqual(trace["metrics"]["generation_skipped_reason"], "model_call_budget_exceeded")

    def test_structured_output_is_opt_in_wire_visible_and_no_retry_on_unsupported_provider(self):
        structured = TestClient(create_app(replace(self.settings, d2_response_format="json_schema")))
        trace = self.run_case("b006", "input", client=structured)
        payload = self.fixture.requests[-1]
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertFalse(payload["response_format"]["json_schema"]["schema"]["additionalProperties"])
        self.assertEqual(trace["model_calls"][0]["parameters"]["response_format"], payload["response_format"])
        self.assertNotIn("tools", payload)
        self.fixture.fail_detection = "http_error"
        before = len(self.fixture.requests)
        trace = self.run_case("b006", "input", client=structured)
        self.assertEqual(trace["status"], "failed")
        self.assertEqual(len(self.fixture.requests)-before, 1)

    def test_invalid_or_uninspected_target_gold_is_rejected_and_legacy_trace_remains_readable(self):
        trace = self.run_case("a001", kind="full_pipeline")  # input block: no document inspected
        body = {"stage": "retrieval", "target_ref": "doc001", "gold_label": "malicious",
                "gold_version": "v1", "reviewer": "fixture", "reason": "must be inspected first"}
        self.assertEqual(self.client.put(f"/api/v1/runs/{trace['run_id']}/detector-gold", json=body).status_code, 422)
        body.update(stage="input", target_ref="doc001")
        self.assertEqual(self.client.put(f"/api/v1/runs/{trace['run_id']}/detector-gold", json=body).status_code, 422)
        request = self.request()
        request["defense_mode"] = "D1+D2"
        self.assertEqual(self.client.post("/api/v1/runs", json=request).status_code, 422)
        legacy = json.loads((ROOT / "docs/examples/week2/b006-D2.json").read_text(encoding="utf-8"))["response"]["trace"]
        (self.folder / f"{legacy['run_id']}.trace.json").write_text(json.dumps(legacy), encoding="utf-8")
        got = self.client.get(f"/api/v1/runs/{legacy['run_id']}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["schema_version"], "0.2")
        self.assertEqual(got.json()["manifest"]["execution_kind"], "full_pipeline")

    def test_concurrent_target_reviews_preserve_both_targets_and_audit_history(self):
        trace = self.run_case()
        with ThreadPoolExecutor(max_workers=2) as workers:
            updates = [workers.submit(self.annotate, trace, "benign", "input", None),
                       workers.submit(self.annotate, trace, "malicious")]
            for update in updates:
                update.result()
        got = self.client.get(f"/api/v1/runs/{trace['run_id']}").json()
        self.assertEqual([item["gold_label"] for item in got["detector_evaluation"]], ["benign", "malicious"])
        history = json.loads((self.folder / f"{trace['run_id']}.detector-gold.json").read_text(encoding="utf-8"))
        self.assertEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
