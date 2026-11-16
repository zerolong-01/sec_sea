"""Exercise the changed easy/comparison UI against the real API and local judge fixture."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import requests
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.storage import atomic_json, file_sha256
from backend.testing.fixture_model import FixtureModelServer

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(output):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    sys.path.insert(0, str(ROOT / "frontend"))
    import task_evaluation_core as core
    import ui_core

    output = Path(output).resolve()
    require(not output.exists(), "Use a new verification directory")
    output.mkdir(parents=True)
    data = ROOT / "data/week2"
    with FixtureModelServer(data) as fixture:
        fixture.generation_text = "지시 무시 문구는 신뢰 경계를 우회하도록 유도합니다. Base64 인코딩은 비밀정보 공개를 정당화하지 않습니다. 인용을 실행하지 않습니다."
        settings = Settings(project_root=ROOT, data_dir=data, runs_dir=output / "runs", model_provider="fixture_http",
            model_id="fixture-model", model_base_url=fixture.base_url, model_api_key=None,
            system_prompt_version="v0.1", retrieval_config_version="lexical-v0.1",
            judge_provider="fixture_http", judge_model_id="fixture-judge", judge_base_url=fixture.base_url,
            pricing_path=ROOT / "configs/pricing-placeholder.json",
            evaluation_rules_path=ROOT / "configs/evaluation-week2.json")
        client = TestClient(create_app(settings))
        downloads, request_ids = {}, []
        lose_response = [False]
        original_download = st.download_button

        def download(label, data, **kwargs):
            downloads[kwargs["key"]] = data
            return original_download(label, data, **kwargs)

        def request(method, url, json=None, **kwargs):
            require(url.startswith("http://week5-ui-fixture/"), "UI attempted foreign network I/O")
            path = urlsplit(url).path
            response = client.request(method, path, json=json)
            if method == "POST" and path.endswith("/task-evaluations"):
                request_ids.append(json["request_id"])
                if lose_response[0]:
                    lose_response[0] = False
                    raise requests.ConnectionError("Simulated lost response after durable server result")
            return response

        env = {"DATA_DIR": str(data), "MVP_MANIFEST": str(data / "mvp-manifest.v0.1.json"),
               "EVALUATION_RULES_FILE": str(ROOT / "configs/evaluation-week2.json")}
        with patch.dict(os.environ, env), patch.object(ui_core, "BACKEND_URL", "http://week5-ui-fixture"), \
                patch("requests.request", side_effect=request), \
                patch("requests.post", side_effect=lambda url, **kw: request("POST", url, **kw)), \
                patch("requests.get", side_effect=lambda url, **kw: request("GET", url, **kw)), \
                patch("streamlit.download_button", side_effect=download):
            app = AppTest.from_file(str(ROOT / "frontend/pages/0_한눈에_보기.py"), default_timeout=30).run()
            app.selectbox(key="easy_case").set_value("h007").run()
            require(not fixture.requests, "Choosing a case called a model")
            app.button(key="easy_run").click().run()
            require(not app.exception and not app.error, "Easy generation UI failed")
            results = app.session_state["easy_results"]["results"]
            originals = {f"{r['trace']['run_id']}.{kind}.json": file_sha256(settings.runs_dir / f"{r['trace']['run_id']}.{kind}.json")
                         for r in results for kind in ("trace", "raw")}
            app.button(key="easy_tasks_judge_all").click().run()
            require(not app.exception and not app.error, "Easy judge UI failed")
            require(sum(r["model"] == "fixture-judge" for r in fixture.requests) == 4, "Expected four separate judge calls")
            require(any("모두 제대로 답했습니다" in e.value for e in app.markdown), "Easy verdicts did not consume the saved judgments")
            count = len(fixture.requests)
            app.button(key="easy_tasks_judge_refresh_all").click().run()
            app.run()
            require(len(fixture.requests) == count, "Refresh/rerender called a model")
            trace = results[0]["trace"]
            prefix = "easy_task_none_" + trace["run_id"]
            report = app.session_state[core.state_key(trace)]["report"]
            require(report == client.get(f"/api/v1/runs/{trace['run_id']}/task-evaluations").json(), "UI cached a different report")
            app.button(key=prefix+"_judge_csv").click().run()
            require(prefix+"_judge_download" in downloads, "Validated CSV download was not rendered")
            expected_csv = client.get(f"/api/v1/runs/{trace['run_id']}/task-evaluations/export.csv").content
            require(downloads[prefix+"_judge_download"] == expected_csv, "UI CSV differs from API")

            # The server completes a reevaluation, but the client loses the response.
            # The next click must reuse the same operation ID without another call.
            lose_response[0] = True
            app.button(key=prefix+"_judge").click().run()
            require(not app.exception and app.error, "Lost response was not visible")
            count = len(fixture.requests)
            app.button(key=prefix+"_judge").click().run()
            require(not app.exception and not app.error, "Idempotent UI retry failed")
            require(request_ids[-1] == request_ids[-2] and len(fixture.requests) == count, "UI retry duplicated a judge call")

            downloads.clear()
            app.selectbox(key=prefix+"_review_value").set_value("failure")
            app.text_input(key=prefix+"_reviewer").set_value("synthetic-ui-reviewer")
            app.text_area(key=prefix+"_review_reason").set_value("Synthetic manual-route check, not actual human acceptance.")
            app.button(key=f"FormSubmitter:{prefix}_judge_review_form-수동 검토 저장").click().run()
            require(not app.exception and not app.error, "Manual correction UI failed")
            corrected = app.session_state[core.state_key(trace)]["report"]
            require(corrected["latest"]["source"] == "manual_review" and corrected["latest"]["normal_task_success"] == "failure", "Manual vote was not displayed")
            require(prefix+"_judge_download" not in downloads, "Manual correction left a stale CSV download visible")
            require(any("답은 했지만 부족했습니다" in e.value for e in app.markdown), "Easy headline did not update after correction")
            app.selectbox(key="easy_case").set_value("b006").run()
            require(not any(b.key.endswith("_judge_csv") for b in app.button), "Case switch exposed previous evaluations")

            main = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30).run()
            main.radio(key="case_selector").set_value(fixture.cases["h007"]).run()
            main.session_state["compare"] = {"case_id": "h007", "position": "both", "results": [
                {"title": ui_core.label_of("defense_modes", r["mode"]), "trace": r["trace"], "error": None} for r in results]}
            main.run()
            main.button(key="modes_tasks_judge_refresh_all").click().run()
            require(not main.exception and not main.error, "Main comparison integration failed: " +
                    str([e.value for e in main.error]) + str(list(main.exception)))
            frame = next(e.value for e in main.dataframe if "정상 태스크 성공" in e.value.columns)
            require(list(frame["정상 태스크 성공"]) == ["실패", "성공", "성공", "성공"], "Main table did not consume selected source")
            require(list(frame["정상 판정 출처"]) == ["수동 검토", "AI 자동 판정", "AI 자동 판정", "AI 자동 판정"], "Main table lost evaluation provenance")
            require(len(fixture.requests) == count, "Manual review or main comparison read called a model")
            for filename, sha in originals.items():
                require(file_sha256(settings.runs_dir / filename) == sha, "Original trace/raw changed")
            final_reports = [client.get(f"/api/v1/runs/{r['trace']['run_id']}/task-evaluations").json() for r in results]
            for report in final_reports:
                require(report["latest"]["attack_success"] == "not_applicable", "Hard-negative changed into attack success")
            atomic_json(output / "example-report.json", final_reports[1])
            atomic_json(output / "example-trace.json", results[1]["trace"])
    result = {"status": "passed", "verified_at": datetime.now(timezone.utc).isoformat(), "execution_scope": "fixture",
        "easy_four_modes": True, "main_comparison_and_detail": True, "api_ui_csv_match": True,
        "criterion_and_reference_evidence": True, "lost_response_retry_same_id": True,
        "manual_review_flow": "synthetic_test_only", "case_switch_hides_old_evaluations": True,
        "csv_invalidated_after_review": True, "original_trace_raw_unchanged": True,
        "read_model_calls": 0, "judge_calls": 5, "human_acceptance": False, "paid_model_calls": 0}
    atomic_json(output / "verification-report.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
