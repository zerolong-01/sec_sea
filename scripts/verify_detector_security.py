"""Synthetic D2 failure scenarios through HTTP, saved artifacts and UI; no robustness claim."""
from __future__ import annotations

import json
import os
import urllib.request
from unittest.mock import patch

from jsonschema import Draft202012Validator
from streamlit.testing.v1 import AppTest

from scripts.data_contract import CANARY_PATTERN, require
from scripts.mvp import HTTP, ROOT, request_json


def verify(execute, backend_url, env, runs_dir, fixture):
    validator = Draft202012Validator(json.loads((ROOT / "contracts/execution-v0.3.schema.json").read_text(encoding="utf-8")))
    samples = runs_dir / "public-samples"
    traces = []

    def annotate(trace, stage, target, label, name):
        body = {"stage": stage, "target_ref": target, "gold_label": label,
                "gold_version": "fixture-target-gold-v0.1", "reviewer": "fixture-reviewer",
                "reason": "Independently assigned synthetic fixture label; no actual model validation."}
        before = len(fixture.requests)
        request = urllib.request.Request(f"{backend_url}/api/v1/runs/{trace['run_id']}/detector-gold",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="PUT")
        with HTTP.open(request, timeout=5) as response:
            updated = json.load(response)
        validator.validate(updated)
        require(len(fixture.requests) == before, "Gold update must not call any model")
        require(request_json(f"{backend_url}/api/v1/runs/{trace['run_id']}") == updated, "Gold update GET mismatch")
        stored = json.loads((runs_dir / f"{trace['run_id']}.trace.json").read_text(encoding="utf-8"))
        require(stored == updated, "Gold update/store mismatch")
        require(not CANARY_PATTERN.search(json.dumps(updated)), "Gold update leaked a canary")
        (samples / f"{name}.json").write_text(json.dumps({"method": "PUT", "request": body, "response": updated},
                                                       ensure_ascii=False, indent=2), encoding="utf-8")
        return updated

    doc = fixture.documents["doc006"]
    text = doc["title"] + "\n" + doc["content"]
    try:
        fixture.detection_overrides[text] = {"score": .0, "reason_code": "normal_request",
            "reason": "Predetermined semantically wrong classification; not a measured model bypass."}
        wrong = execute("a006", "D2", name="valid-json-misclassification-initial")
        require(wrong["status"] == "completed" and wrong["evaluation"]["attack_success"] == "success", "Wrong JSON scenario did not reach independent raw evaluation")
        wrong = annotate(wrong, "input", None, "benign", "target-gold-input")
        wrong = annotate(wrong, "retrieval", "doc006", "malicious", "valid-json-misclassification")
        require(wrong["detector_evaluation"][1]["analysis_status"] == "valid_json_misclassification", "Misclassification was not independently detected")
        traces.append(wrong)

        fixture.detection_overrides[text]["reason_code"] = "malicious_instruction"
        contradiction = execute("a006", "D2", "retrieval", "score-reason-contradiction-initial")
        require(contradiction["status"] == "blocked" and contradiction["metrics"]["generation_call_count"] == 0, "Contradiction must restrict generation")
        contradiction = annotate(contradiction, "retrieval", "doc006", "malicious", "score-reason-contradiction")
        require(contradiction["detector_evaluation"][0]["analysis_status"] == "review_needed", "Contradiction must not count as a correct detection")
        traces.append(contradiction)
        fixture.detection_overrides.clear()

        diagnostic = execute("a001", "D2", name="detector-only-input-block", kind="detector_only")
        require(diagnostic["status"] == "completed" and len(diagnostic["defense_events"]) == 2, "Diagnostic must continue after input block")
        require(diagnostic["metrics"]["generation_call_count"] == 0 and diagnostic["evaluation"]["attack_success"] == "not_evaluated", "Diagnostic must not invent a final attack result")
        require(diagnostic["evaluation"]["evaluator_version"] == "detector-only-v0.1" and
                diagnostic["evaluation"]["reason"] == "detector_only:no_generation_or_final_outcome", "Diagnostic evaluation scope is incorrect")
        traces.append(diagnostic)

        fixture.fail_detection = "malformed"
        failed = execute("b006", "D2", name="detector-only-error-initial", kind="detector_only")
        require(failed["status"] == "failed" and failed["metrics"]["detection_call_count"] == 2, "Diagnostic errors must retain both attempts")
        failed = annotate(failed, "input", None, "benign", "detector-only-error-input")
        failed = annotate(failed, "retrieval", "doc012", "benign", "detector-only-error")
        traces.append(failed)
        fixture.fail_detection = None

        missing = execute("h007", "D2", "retrieval", "detector-only-gold-pending", kind="detector_only")
        traces.append(missing)
        report_request = {"run_ids": [trace["run_id"] for trace in traces]}
        report = request_json(f"{backend_url}/api/v1/detector-report", report_request)
        validator.validate(report)
        require(sum(group["eligible_target_count"] for group in report["groups"]) == 2, "Incorrect eligible denominator")
        require(sum(group["review_needed_count"] for group in report["groups"]) == 1, "Contradiction exclusion missing")
        require(sum(group["detector_error_count"] for group in report["groups"]) == 2, "Detector error exclusion missing")
        require(sum(group["not_evaluated_count"] for group in report["groups"]) == 3, "Missing gold exclusion missing")
        (samples / "detector-report.json").write_text(json.dumps({"method": "POST", "request": report_request,
            "response": report}, ensure_ascii=False, indent=2), encoding="utf-8")

        with patch.dict(os.environ, env):
            app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30).run()
            for trace in (wrong, contradiction, failed):
                app.session_state["result"] = {"trace": trace, "error": None}
                app.run()
                require(not app.exception, "New detector fields broke the UI")
                shown = "\n".join(str(element.value) for element in [*app.code, *app.text, *app.caption])
                require(not CANARY_PATTERN.search(shown), "Detector UI leaked a canary")
                evaluation_frames = [element.value for element in app.dataframe if "분석" in element.value.columns]
                require(len(evaluation_frames) == 1 and len(evaluation_frames[0]) == len(trace["detector_evaluation"]), "Target evaluations missing from UI")
        return {"status": "passed", "run_count": 5, "gold_updates_verified": True,
                "independent_misclassification_verified": True, "ui_verified": True,
                "real_model_verified": False}
    finally:
        fixture.detection_overrides.clear()
        fixture.fail_detection = None
