from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from app.models import DefenseEvent, EvaluationResult, RunRequest, RunResponse
from app.shared_variables import DefenseMode, EvaluationStatus, RunStatus, TraceStage

ROOT = Path(__file__).resolve().parents[2]


class SharedVariableTests(unittest.TestCase):
    def test_changed_shared_values_reach_validation_execution_and_saved_trace(self):
        # An isolated checkout proves the JSON file drives the API, rather than
        # merely checking that a second set of constants happens to match today.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backend = root / "backend"
            shutil.copytree(
                ROOT / "backend/app", backend / "app",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            contracts = root / "contracts"
            contracts.mkdir()
            shared = json.loads(
                (ROOT / "contracts/shared-variables-v0.1.json").read_text(encoding="utf-8")
            )
            for group, name, value in (
                ("defense_modes", "NONE", "unprotected"),
                ("run_statuses", "COMPLETED", "finished"),
                ("run_statuses", "FAILED", "execution_error"),
                ("evaluation_statuses", "NOT_EVALUATED", "pending_review"),
                ("output_outcomes", "GENERATED", "generated_response"),
                ("prompt_component_types", "USER", "user_content"),
                ("metric_keys", "LATENCY_MS", "latency_contract_test"),
            ):
                shared[group][name]["value"] = value
            (contracts / "shared-variables-v0.1.json").write_text(
                json.dumps(shared), encoding="utf-8"
            )
            shutil.copytree(ROOT / "data", root / "data")
            environment = dict(os.environ)
            environment.update(
                PYTHONPATH=str(backend), DATA_DIR=str(root / "data"),
                RUNS_DIR=str(root / "runs"), MODEL_PROVIDER="demo",
                PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
            )
            result = subprocess.run(
                [sys.executable, "-c", """
from fastapi.testclient import TestClient
from app.main import create_app

client = TestClient(create_app())
request = {
    "schema_version": "0.1", "artifact_type": "run_request", "case_id": "b006",
    "scenario": "rag_chat", "defense_mode": "unprotected",
    "dataset_version": "synthetic_v0.1.1", "corpus_version": "synthetic_v0.1.1",
    "requested_by": "shared-contract-test",
}
response = client.post("/api/v1/runs", json=request)
assert response.status_code == 201, response.text
body = response.json()
trace = body["trace"]
assert body["status"] == trace["status"] == "finished"
assert trace["request"]["defense_mode"] == "unprotected"
assert trace["evaluation"]["attack_success"] == "pending_review"
assert trace["evaluation"]["normal_task_success"] == "pending_review"
assert trace["output"]["outcome"] == "generated_response"
assert trace["prompt_assembly"][1]["component_type"] == "user_content"
assert trace["metrics"]["latency_contract_test"] is not None
assert "latency_ms" not in trace["metrics"]
assert client.get("/api/v1/runs/" + body["run_id"]).json() == trace
request["defense_mode"] = "none"
assert client.post("/api/v1/runs", json=request).status_code == 422
request["defense_mode"] = "unprotected"
request["case_id"] = "missing-case"
response = client.post("/api/v1/runs", json=request)
assert response.status_code == 404, response.text
failed = client.get("/api/v1/runs/" + response.json()["detail"]["run_id"])
assert failed.status_code == 200, failed.text
assert failed.json()["status"] == "execution_error"
"""],
                cwd=backend, env=environment, capture_output=True, text=True,
                encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_contract_subsets_still_reject_invalid_values(self):
        with self.assertRaises(ValidationError):
            EvaluationResult(
                attack_success=EvaluationStatus.NOT_APPLICABLE,
                normal_task_success=EvaluationStatus.NOT_APPLICABLE,
                evaluator_version="manual-v0.1", reason=None,
            )
        with self.assertRaises(ValidationError):
            DefenseEvent(
                defense_id=DefenseMode.NONE, defense_version="v0.1",
                stage=TraceStage.INPUT, decision="allow", reason_code=None,
            )
        with self.assertRaises(ValidationError):
            DefenseEvent(
                defense_id=DefenseMode.D1, defense_version="v0.1",
                stage=TraceStage.METRICS, decision="allow", reason_code=None,
            )
        with self.assertRaises(ValidationError):
            TypeAdapter(RunResponse.model_fields["status"].annotation).validate_python(
                RunStatus.QUEUED
            )
        with self.assertRaises(ValidationError):
            RunRequest(
                schema_version="0.1", artifact_type="case", case_id="b006",
                scenario="rag_chat", defense_mode=DefenseMode.NONE,
                dataset_version="v0.1", corpus_version="synthetic_v0.1.1",
                requested_by="shared-contract-test",
            )


if __name__ == "__main__":
    unittest.main()
