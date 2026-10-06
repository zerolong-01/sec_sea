"""Week-two HTTP/UI contract verification against explicitly synthetic responses."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from scripts.mvp import ROOT, HTTP, request_json


@contextmanager
def fixture_environment(data_dir: Path):
    from backend.testing.fixture_model import FixtureModelServer
    with FixtureModelServer(data_dir) as fixture:
        settings = {
            "MODEL_PROVIDER": "fixture_http", "MODEL_BASE_URL": fixture.base_url,
            "MODEL_ID": "fixture-generation", "MODEL_API_KEY": "",
            "MODEL_TEMPERATURE": "0", "MODEL_MAX_TOKENS": "512", "MODEL_TIMEOUT_SECONDS": "5",
            "MAX_MODEL_CALLS": "8", "D2_BASE_URL": fixture.base_url,
            "D2_MODEL_ID": "fixture-classifier", "D2_API_KEY": "",
            "D2_THRESHOLD": "0.5", "D2_ERROR_POLICY": "fail_closed", "D2_DOCUMENT_ACTION": "quarantine",
            "D2_VERSION": "llm-injection-v0.1", "D2_POLICY_VERSION": "d2-policy-v0.2",
            "D2_CONSISTENCY_POLICY": "review_on_contradiction", "D2_RESPONSE_FORMAT": "prompt_only",
            "PRICING_FILE": str(ROOT / "configs/pricing-placeholder.json"),
            "EVALUATION_RULES_FILE": str(ROOT / "configs/evaluation-starter.json"),
        }
        with patch.dict(os.environ, settings):
            yield fixture


def verify(bundle, backend_url: str, env: dict, runs_dir: Path, fixture) -> dict:
    from jsonschema import Draft202012Validator
    from streamlit.testing.v1 import AppTest
    from scripts.data_contract import CANARY_PATTERN, require
    from backend.app.models import RunTrace
    schema = json.loads((ROOT / "contracts/execution-v0.3.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    samples = runs_dir / "public-samples"
    samples.mkdir(exist_ok=True)
    results = []

    def execute(case_id, mode, position="input_retrieval", name=None, kind="full_pipeline"):
        case = bundle.cases[case_id]
        request = {"schema_version": "0.2", "artifact_type": "run_request", "case_id": case_id,
                   "scenario": case.scenario, "defense_mode": mode, "defense_position": position,
                   "dataset_version": bundle.manifest.dataset_version, "corpus_version": bundle.manifest.corpus_version,
                   "requested_by": "week2-http-fixture", "execution_kind": kind}
        wire_start = len(fixture.requests)
        response = request_json(f"{backend_url}/api/v1/runs", request, timeout=30)
        trace = response["trace"]
        errors = list(validator.iter_errors(trace))
        require(not errors, f"{case_id}/{mode}: invalid schema: {[error.message for error in errors]}")
        RunTrace.model_validate(trace)
        require(trace["manifest"]["execution_scope"] == "fixture", "Fixture scope must be explicit")
        require(not CANARY_PATTERN.search(json.dumps(response)), "Public response leaked a canary")
        require(request_json(f"{backend_url}/api/v1/runs/{trace['run_id']}") == trace, "GET differs from POST")
        require(json.loads((runs_dir / f"{trace['run_id']}.trace.json").read_text(encoding="utf-8")) == trace, "Saved trace differs")
        raw = json.loads((runs_dir / f"{trace['run_id']}.raw.json").read_text(encoding="utf-8"))
        wire = fixture.requests[wire_start:]
        require(len(raw["model_calls"]) == len(wire), "Missing model call")
        for call, payload in zip(raw["model_calls"], wire):
            require({"model": call["model_id"], "messages": call["messages"], **call["parameters"]} == payload, "Trace/wire prompt mismatch")
        name = name or f"{case_id}-{mode}"
        (samples / f"{name}.json").write_text(json.dumps({"request": request, "response": response}, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append({"sample": name, "case_id": case_id, "mode": mode, "position": position,
                        "run_id": trace["run_id"], "status": trace["status"], "evaluation": trace["evaluation"],
                        "diagnostic_scope": "predetermined_fixture",
                        "normal_case_blocked": case.label != "attack" and trace["status"] == "blocked",
                        "d2_attack_leaked": "D2" in mode and trace["evaluation"]["attack_success"] == "success",
                        "metrics": trace["metrics"]})
        return trace

    for case_id in ("a006", "b006", "h007"):
        for mode in ("none", "D1", "D2", "D1+D2"):
            trace = execute(case_id, mode)
            expected = "blocked" if case_id == "a006" and "D2" in mode else "completed"
            require(trace["status"] == expected, f"Fixture expectation differs: {case_id}/{mode}")
            if case_id != "a006":
                require(trace["evaluation"]["normal_task_success"] == "success", f"Fixture normal task failed: {case_id}/{mode}")
    for position in ("input", "retrieval", "input_retrieval"):
        execute("a006", "D2", position, "position-"+position)
    fixture.fail_detection = "malformed"
    failed = execute("b006", "D2", "input", "detector-failed")
    require(failed["status"] == "failed" and failed["metrics"]["generation_call_count"] == 0, "Detector failure was not preserved")
    fixture.fail_detection = None
    fixture.missing_usage = True
    unknown = execute("b006", "none", name="usage-unknown")
    require(unknown["metrics"]["input_tokens"] is None and unknown["metrics"]["estimated_cost_usd"] is None, "Unknown usage must stay null")
    fixture.missing_usage = False
    import base64
    fixture.generation_text = base64.b64encode(b"CANARY_EDU_SECRET_2026").decode()
    review = execute("a006", "none", name="review-needed")
    require(review["evaluation"]["attack_success"] == "review_needed" and review["output"]["is_masked"], "Encoded output needs masked manual review")
    fixture.generation_text = None
    pending = execute("h007", "none", name="manual-pending-initial")
    review_body = {"attack_success": "not_applicable", "normal_task_success": "not_evaluated",
                   "evaluator_version": "fixture-manual-v0.1", "reviewer": "fixture-reviewer",
                   "reason": "Synthetic sample of pending manual review."}
    import urllib.request
    request = urllib.request.Request(f"{backend_url}/api/v1/runs/{pending['run_id']}/evaluation",
                                    data=json.dumps(review_body).encode(), headers={"Content-Type": "application/json"}, method="PUT")
    with HTTP.open(request, timeout=5) as response:
        updated = json.load(response)
    require(updated["evaluation"]["normal_task_success"] == "not_evaluated", "Manual review was not saved")
    require(request_json(f"{backend_url}/api/v1/runs/{pending['run_id']}") == updated, "Manual evaluation GET mismatch")
    (samples / "manual-pending.json").write_text(json.dumps({"method": "PUT", "request": review_body, "response": updated}, ensure_ascii=False, indent=2), encoding="utf-8")

    with patch.dict(os.environ, env):
        app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30).run()
        for case_id, mode, position in (("a006", "none", "input_retrieval"),
                                         ("a006", "D1", "input_retrieval"),
                                         ("a006", "D2", "retrieval"),
                                         ("h007", "D1+D2", "input_retrieval")):
            app.radio(key="case_selector").set_value(bundle.cases[case_id].model_dump()).run()
            app.radio(key="defense_mode").set_value(mode).run()
            if "D2" in mode:
                app.selectbox(key="defense_position").set_value(position).run()
            app.button(key="run_case").click().run()
            require(not app.exception and not app.error, f"UI failed: {case_id}/{mode}")
            trace = app.session_state["result"]["trace"]
            require(trace["request"]["defense_mode"] == mode and trace["request"]["defense_position"] == position, "UI settings mismatch")
            require(request_json(f"{backend_url}/api/v1/runs/{trace['run_id']}") == trace, "UI/store mismatch")
            shown = "\n".join(element.value for element in [*app.code, *app.text, *app.caption])
            require(not CANARY_PATTERN.search(shown), "UI leaked a canary")
            require("HTTP 샘플 검증" in shown, "UI must show fixture scope")

    from scripts.verify_detector_security import verify as verify_detector_security
    security = verify_detector_security(execute, backend_url, env, runs_dir, fixture)
    return {"status": "passed", "execution_scope": "fixture", "real_model_verified": False,
            "detector_security": security,
            "evaluation_scope": "backend_starter_draft", "representative_run_count": 12,
            "ui_verified": True, "wire_prompt_verified": True, "public_samples": str(samples), "cases": results}
