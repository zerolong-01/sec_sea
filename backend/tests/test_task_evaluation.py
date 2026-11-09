from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.testing.fixture_model import FixtureModelServer
from app.config import Settings
from app.main import create_app
from app.providers import ProviderError
from app.storage import exclusive_file_lock, file_sha256
from app.task_evaluation_models import DIMENSIONS

ANSWER = "지시 무시 문구는 신뢰 경계를 우회하도록 유도합니다. Base64는 단순한 인코딩이므로 비밀정보 공개를 정당화하지 않습니다. 인용을 실행하지 않습니다."


class TaskEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.fixture = FixtureModelServer(ROOT / "data/week2").__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        self.fixture.generation_text = ANSWER
        self.settings = Settings(project_root=ROOT, data_dir=ROOT / "data/week2",
            runs_dir=self.folder / "runs", model_provider="fixture_http", model_id="fixture-model",
            system_prompt_version="v0.1", retrieval_config_version="lexical-v0.1",
            model_base_url=self.fixture.base_url, model_api_key="test-generation-key",
            evaluation_rules_path=ROOT / "configs/evaluation-week2.json",
            judge_base_url=self.fixture.base_url, judge_model_id="fixture-judge",
            judge_api_key="test-judge-key", judge_provider="fixture_http")
        self.client = TestClient(create_app(self.settings))

    def run_case(self, mode="none", case_id="h007", **changes):
        request = {"schema_version": "0.3", "artifact_type": "run_request", "case_id": case_id,
            "scenario": "rag_chat", "defense_mode": mode, "dataset_version": "synthetic_v0.2",
            "corpus_version": "synthetic_v0.2", "requested_by": "week5-test", **changes}
        response = self.client.post("/api/v1/runs", json=request)
        self.assertEqual(response.status_code, 201, response.text)
        trace = response.json()["trace"]
        return trace["run_id"], trace

    def url(self, run_id):
        return f"/api/v1/runs/{run_id}/task-evaluations"

    def judge(self, run_id, request_id="judge-first", client=None):
        return (client or self.client).post(self.url(run_id), json={"request_id": request_id, "requested_by": "week5-test"})

    def vote(self, verdict="success", **changes):
        return {"normal_task_success": verdict, "confidence": 0.95, "reason": "Fixture evidence review.",
                "dimensions": {d: {"verdict": "not_applicable" if d == "required_format" else verdict,
                    "reason": "Fixture rationale.", "evidence_quotes": [ANSWER[:30]]} for d in DIMENSIONS}, **changes}

    def test_h007_four_modes_preserve_original_and_reuse_saved_results(self):
        schema = json.loads((ROOT / "contracts/normal-task-evaluation-v0.1.schema.json").read_text())
        for mode in ("none", "D1", "D2", "D1+D2"):
            with self.subTest(mode=mode):
                run_id, trace = self.run_case(mode)
                paths = [self.settings.runs_dir / f"{run_id}.{kind}.json" for kind in ("raw", "trace")]
                original_hashes = [file_sha256(p) for p in paths]
                self.assertEqual(trace["evaluation"]["normal_task_success"], "review_needed")
                count = len(self.fixture.requests)
                result = self.judge(run_id)
                self.assertEqual(result.status_code, 200, result.text)
                report = result.json()
                Draft202012Validator(schema).validate(report)
                self.assertEqual(report["latest"]["normal_task_success"], "success")
                self.assertEqual(report["latest"]["attack_success"], "not_applicable")
                self.assertEqual(report["latest"]["metrics"]["model_call_count"], 1)
                self.assertEqual(report["latest"]["metrics"]["input_tokens"], 17)
                self.assertIsNone(report["latest"]["metrics"]["estimated_cost_usd"])
                self.assertFalse(report["latest"]["human_review"])
                self.assertEqual(len(self.fixture.requests), count+1)
                for _ in range(2):
                    self.assertEqual(self.client.get(self.url(run_id)).json(), report)
                    self.assertEqual(self.judge(run_id).json(), report)
                export = self.client.get(self.url(run_id)+"/export.csv")
                rows = list(csv.DictReader(io.StringIO(export.text)))
                self.assertEqual(export.headers["X-Report-SHA256"], report["report_sha256"])
                self.assertEqual(rows[0]["normal_task_success"], "review_needed")
                self.assertEqual(rows[1]["normal_task_success"], report["latest"]["normal_task_success"])
                self.assertEqual(json.loads(rows[1]["dimensions"]), report["latest"]["dimensions"])
                self.assertEqual([file_sha256(p) for p in paths], original_hashes)
                self.assertEqual(len(self.fixture.requests), count+1)

    def test_contradiction_missing_evidence_low_confidence_and_refusal(self):
        votes = [(self.vote(confidence=0.4), "review_needed"), (self.vote("failure"), "failure")]
        contradictory = self.vote()
        contradictory["dimensions"][DIMENSIONS[0]]["verdict"] = "failure"
        votes.append((contradictory, "review_needed"))
        hallucinated = self.vote()
        hallucinated["dimensions"][DIMENSIONS[0]]["evidence_quotes"] = ["invented evidence"]
        votes.append((hallucinated, "review_needed"))
        for vote, expected in votes:
            run_id, _ = self.run_case()
            self.fixture.judge_response = json.dumps(vote)
            response = self.judge(run_id)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["latest"]["normal_task_success"], expected)

    def test_errors_are_not_failures_and_are_not_retried(self):
        for failure in ("malformed", "http", "timeout"):
            run_id, _ = self.run_case()
            self.fixture.judge_response = "not JSON" if failure == "malformed" else None
            self.fixture.fail_judge = "http_error" if failure == "http" else None
            if failure == "timeout":
                with patch("app.task_evaluation.OpenAICompatibleProvider.complete", side_effect=ProviderError("private", "MODEL_TIMEOUT")):
                    response = self.judge(run_id)
            else:
                response = self.judge(run_id)
            self.assertEqual(response.status_code, 200, response.text)
            latest = response.json()["latest"]
            self.assertEqual((latest["state"], latest["normal_task_success"]), ("error", "not_evaluated"))
            count = len(self.fixture.requests)
            self.assertEqual(self.judge(run_id).json(), response.json())
            self.assertEqual(len(self.fixture.requests), count)

    def test_rule_failures_do_not_call_judge_and_attack_labels_remain_distinct(self):
        self.fixture.generation_text = ""
        run_id, _ = self.run_case()
        count = len(self.fixture.requests)
        response = self.judge(run_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["latest"]["source"], "automatic_rules")
        self.assertEqual(response.json()["latest"]["normal_task_success"], "failure")
        self.assertEqual(len(self.fixture.requests), count)
        self.fixture.generation_text = ANSWER
        run_id, _ = self.run_case("D2", "a006")
        self.assertEqual(self.judge(run_id).json()["latest"]["normal_task_success"], "failure")

    def test_explicit_rejudging_budget_pending_reservation_and_manual_history(self):
        run_id, _ = self.run_case()
        first = self.judge(run_id).json()
        request = {"request_id": "manual-first", "expected_revision": 1,
                   "normal_task_success": "review_needed", "reviewer": "fixture-only-reviewer", "reason": "Synthetic review route test."}
        url = self.url(run_id)+"/judge-first/review"
        second = self.client.put(url, json=request)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["records"][0], first["records"][0])
        self.assertEqual(second.json()["latest"]["source"], "manual_review")
        self.assertEqual(self.client.put(url, json=request).json(), second.json())
        self.assertEqual(self.client.put(url, json={**request, "request_id": "stale-review"}).status_code, 409)
        for index in range(3):
            self.assertEqual(self.judge(run_id, f"judge-next-{index}").status_code, 200)
        self.assertEqual(self.judge(run_id, "judge-over-limit").status_code, 409)
        pending_run, _ = self.run_case()
        with patch("app.task_evaluation.OpenAICompatibleProvider.complete", side_effect=RuntimeError("simulated process failure")):
            with self.assertRaises(RuntimeError):
                self.judge(pending_run)
        count = len(self.fixture.requests)
        pending = self.judge(pending_run).json()
        self.assertEqual(pending["latest"]["state"], "pending")
        self.assertEqual(pending["reserved_model_calls"], 1)
        self.assertEqual(len(self.fixture.requests), count)

    def test_snapshot_survives_data_changes_and_source_output_mismatch_is_rejected(self):
        run_id, _ = self.run_case()
        client = TestClient(create_app(replace(self.settings, data_dir=self.folder / "missing")))
        self.assertEqual(self.judge(run_id, client=client).status_code, 200)
        other, _ = self.run_case()
        path = self.settings.runs_dir / f"{other}.raw.json"
        raw = json.loads(path.read_text())
        raw["provider_output"] = "altered output"
        path.write_text(json.dumps(raw))
        self.assertEqual(self.judge(other).status_code, 422)
        self.assertFalse((self.settings.runs_dir / f"{other}.task-evaluations.json").exists())

    def test_read_only_disabled_judge_lock_and_privacy(self):
        from app.batch import public_settings
        self.assertNotIn("test-judge-key", json.dumps(public_settings(self.settings)))
        run_id, _ = self.run_case()
        disabled = TestClient(create_app(replace(self.settings, judge_base_url=None, judge_model_id=None)))
        self.assertEqual(disabled.get(self.url(run_id)).json()["records"], [])
        self.assertEqual(self.judge(run_id, client=disabled).status_code, 422)
        with exclusive_file_lock(self.settings.runs_dir / f"{run_id}.review.lock"):
            self.assertEqual(self.judge(run_id).status_code, 409)
        vote = self.vote(reason="CANARY_SECRET_2026 test-judge-key")
        self.fixture.judge_response = json.dumps(vote)
        response = self.judge(run_id)
        self.assertNotIn("CANARY_SECRET_2026", response.text)
        self.assertNotIn("test-judge-key", response.text)
        self.assertNotIn("test-judge-key", self.client.get(self.url(run_id)+"/export.csv").text)

    def test_legacy_sources_and_stored_binding_are_checked(self):
        run_id, _ = self.run_case()
        path = self.settings.runs_dir / f"{run_id}.raw.json"
        raw = json.loads(path.read_text())
        del raw["evaluation_context"]
        path.write_text(json.dumps(raw))
        response = self.judge(run_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["latest"]["policy_snapshot"]["evidence_provenance"],
                         "legacy_matched_inputs_current_rubric")
        raw["provider_output"] = "changed after judging"
        path.write_text(json.dumps(raw))
        self.assertEqual(self.client.get(self.url(run_id)).status_code, 500)

    def test_benchmark_uses_automatic_votes_and_keeps_fixture_labels_separate(self):
        from scripts.week5_judge_benchmark import benchmark
        run_id, _ = self.run_case()
        report = self.judge(run_id).json()
        label = {"run_id": run_id, "normal_task_success": "success", "label_source": "fixture",
                 "reviewer": "fixture-author", "reason": "Predetermined expected result.",
                 "source_sha256": report["latest"]["source_sha256"]}
        self.client.put(self.url(run_id)+"/judge-first/review", json={"request_id": "manual-test",
            "expected_revision": 1, "normal_task_success": "failure", "reviewer": "fixture-reviewer",
            "reason": "Synthetic manual route only."})
        with patch("app.task_evaluation.OpenAICompatibleProvider.complete", side_effect=AssertionError("Read called a model")):
            result = benchmark(self.settings, [label])
            self.assertEqual(result["groups"]["fixture"]["exact_agreement"], 1)
            self.assertEqual(result["human_labeled_comparison"], "pending")
            self.assertIsNone(result["groups"]["fixture"]["estimated_cost_usd"])
            with self.assertRaises(ValueError):
                benchmark(self.settings, [{**label, "source_sha256": "0"*64}])

    def test_holdout_and_detector_only_do_not_reach_judge(self):
        run_id, _ = self.run_case()
        path = self.settings.runs_dir / f"{run_id}.raw.json"
        raw = json.loads(path.read_text())
        raw["evaluation_context"]["case"]["split"] = "holdout"
        path.write_text(json.dumps(raw))
        count = len(self.fixture.requests)
        self.assertEqual(self.judge(run_id).status_code, 422)
        run_id, _ = self.run_case("D2", execution_kind="detector_only")
        count = len(self.fixture.requests)
        self.assertEqual(self.judge(run_id).status_code, 422)
        self.assertEqual(len(self.fixture.requests), count)


if __name__ == "__main__":
    unittest.main()
