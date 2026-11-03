"""Read-only API → report UI → download → trace verification for current result views."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

from backend.app.config import Settings
from backend.app.batch import digest
from backend.app.storage import atomic_json
from scripts.data_contract import ROOT, require
from scripts.week4_package import tree_hashes


def verify(runs_dir, output, *, research_batch_id=None, experiment_id=None, comparison=False, require_trace=False):
    import streamlit as st
    from fastapi.testclient import TestClient
    from streamlit.testing.v1 import AppTest
    from backend.app.providers import DemoRagProvider, OpenAICompatibleProvider
    from backend.app.service import RunService
    from backend.app.repository import ExperimentRepository, RunTraceStore

    runs_dir, output = Path(runs_dir).resolve(), Path(output).resolve()
    require(not output.exists() and not output.is_relative_to(runs_dir) and not runs_dir.is_relative_to(output),
            "Use a new output outside the source store")
    before = tree_hashes(runs_dir)
    settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=runs_dir,
        model_provider="demo", model_id="demo", system_prompt_version="v0.1",
        retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None)
    reader = RunService(settings, ExperimentRepository(settings.data_dir), RunTraceStore(runs_dir), provider=None)
    with patch.object(Settings, "from_environment", return_value=settings):
        from backend.app.main import create_app
    sys.path.insert(0, str(ROOT / "frontend"))
    from ui_core import BACKEND_URL
    from batch_core import METRICS, metric_cell
    from research_core import RESEARCH_METRICS, research_cell

    downloads, calls, contexts = {}, [], []
    download_button = st.download_button

    def capture(label, data, **kwargs):
        downloads[kwargs.get("key")] = data
        return download_button(label, data, **kwargs)

    with TestClient(create_app(settings)) as client:
        def request(method, url, json=None, **kwargs):
            path = urlsplit(url).path
            allowed = ((method == "GET" and (path == "/api/v1/batches" or path == "/api/v1/model-experiments" or
                        path.startswith("/api/v1/runs/") or path.startswith("/api/v1/research/week4-original-attacks") or
                        path.endswith("/evaluation-sources"))) or
                       (method == "POST" and path.endswith(("/report", "/export.csv"))))
            require(url.startswith(BACKEND_URL + "/") and allowed, "Result view attempted a non-read request")
            response = client.request(method, path, json=json)
            require(response.status_code == 200, "Result view read failed: " + path)
            calls.append({"method": method, "path": path})
            return response

        def check(app, *, json_key, csv_key, expected):
            require(not app.exception and not app.error, "Result view failed to render")
            require(json.loads(downloads[json_key]) == expected, "UI JSON differs from current API report")
            require(csv_key in downloads and any("CSV" in e.value for e in app.success), "UI CSV validation failed")
            if json_key == "experiment_json" and expected["rows"]:
                frame = next(e.value for e in app.dataframe if "프로필" in e.value.columns)
                require(len(frame) == len(expected["rows"]), "Model table omitted observations")
                for actual, row in zip(frame.to_dict("records"), expected["rows"]):
                    require(actual["프로필"] == row["model_key"] and actual["모델"] == row["model_id"] and
                            actual["방어 조건"] == row["cohort"]["condition_id"], "Model table membership mismatch")
                    require(all(actual[METRICS[name][0]] == metric_cell(metric, METRICS[name][1])
                                for name, metric in row["metrics"].items()), "Model table metric differs from API")
            elif json_key == "comparison_json":
                frame = next(e.value for e in app.dataframe if "공격 상황 업무 성공" in e.value.columns)
                require(len(frame) == len(expected["rows"]), "Original comparison omitted conditions")
                for actual, row in zip(frame.to_dict("records"), expected["rows"]):
                    require(actual["방어 조건"] == row["display_condition"] and
                            actual["공격 목표 달성"] == research_cell(row["metrics"]["fresh_ai_attack_success"]) and
                            actual["공격 상황 업무 성공"] == research_cell(row["metrics"]["fresh_ai_attack_task_utility"]),
                            "Original comparison table differs from API")
            elif json_key == "research_json" and expected["groups"]:
                frame = next(e.value for e in app.dataframe if RESEARCH_METRICS["fresh_ai_attack_success"] in e.value.columns)
                require(len(frame) == len(expected["groups"]), "Research table omitted cohorts")
                for actual, group in zip(frame.to_dict("records"), expected["groups"]):
                    require(all(actual[label] == research_cell(group["metrics"][name])
                                for name, label in RESEARCH_METRICS.items()), "Research table differs from API")

        def trace(app, key):
            run_id = app.selectbox(key=f"{key}_run").value
            app.button(key=f"{key}_load_trace").click().run()
            require(not app.exception and not app.error, "Original trace failed to render")
            expected = client.get(f"/api/v1/runs/{run_id}").json()
            require(run_id in [e.value for e in app.text], "Trace identity missing from UI")
            reason = expected["evaluation"].get("reason")
            if reason:
                require(reason in [e.value for e in app.text], "Trace evaluation reason missing")
            output_text = expected["output"].get("display_text")
            if output_text:
                require(output_text in [e.value for e in app.code], "Trace output differs from API")
            public_trace = reader.get_trace(run_id)
            rendered = [str(e.value) for e in [*app.text, *app.code, *app.caption, *app.markdown, *app.dataframe]]
            require(reader.safe_for_trace(public_trace, rendered) == rendered, "Protected value in result UI")
            return {"run_id": run_id, "public_trace_sha256": digest(expected), "reason_and_output_match": True,
                    "defense_event_count": len(expected["defense_events"]), "masking_checked": True}

        with patch("requests.request", side_effect=request), \
                patch("requests.get", side_effect=lambda url, **kw: request("GET", url, **kw)), \
                patch("requests.post", side_effect=AssertionError("View attempted execution")), \
                patch("requests.sessions.Session.request", side_effect=AssertionError("View attempted network I/O")), \
                patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("Paid call")) as paid, \
                patch.object(DemoRagProvider, "generate_prepared", side_effect=AssertionError("Generation call")) as demo, \
                patch("streamlit.download_button", side_effect=capture):
            if comparison:
                expected = client.get("/api/v1/research/week4-original-attacks").json()
                app = AppTest.from_file(str(ROOT / "frontend/pages/3_보고서_원본공격_비교.py"), default_timeout=60).run()
                app.button(key="comparison_csv_prepare").click().run()
                check(app, json_key="comparison_json", csv_key="comparison_csv_download", expected=expected)
                evidence = {"view": "original_attack_comparison", "report_sha256": expected["report_sha256"],
                            "output_runs": expected["selection"]["output_runs"], "api_ui_csv_match": True}
                if require_trace:
                    evidence["trace"] = trace(app, "comparison")
                contexts.append(evidence)

            if research_batch_id:
                app = AppTest.from_file(str(ROOT / "frontend/pages/2_연구_판정_보기.py"), default_timeout=60)
                app.session_state["research_batch"] = research_batch_id
                app.run()
                for filters in ({}, {"condition_id": "D2-input"}):
                    if filters:
                        app.selectbox(key=f"research_{research_batch_id}_condition_id").select(filters["condition_id"])
                        next(b for b in app.button if b.label == "필터 적용").click().run()
                    expected = client.post(f"/api/v1/batches/{research_batch_id}/research/report", json=filters).json()
                    app.button(key="research_csv_prepare").click().run()
                    check(app, json_key="research_json", csv_key="research_csv_download", expected=expected)
                    evidence = {"view": "research_overlay", "batch_id": research_batch_id, "filters": filters,
                                "report_sha256": expected["report_sha256"], "api_ui_csv_match": True}
                    if require_trace:
                        evidence["trace"] = trace(app, "research")
                    contexts.append(evidence)

            if experiment_id:
                app = AppTest.from_file(str(ROOT / "frontend/pages/4_모델_비교.py"), default_timeout=60)
                app.session_state["experiment_id"] = experiment_id
                app.run()
                for filters in ({}, {"condition_id": "D1"}):
                    if filters:
                        app.selectbox(key=f"experiment_{experiment_id}_condition_id").select(filters["condition_id"])
                        next(b for b in app.button if b.label == "필터 적용").click().run()
                    expected = client.post(f"/api/v1/model-experiments/{experiment_id}/report", json=filters).json()
                    app.button(key="experiment_csv_prepare").click().run()
                    check(app, json_key="experiment_json", csv_key="experiment_csv_download", expected=expected)
                    evidence = {"view": "model_comparison", "experiment_id": experiment_id, "filters": filters,
                                "report_sha256": expected["report_sha256"], "model_count": len(expected["summary"]["models"]),
                                "api_ui_csv_match": True}
                    if require_trace:
                        evidence["trace"] = trace(app, "experiment")
                    contexts.append(evidence)
            require(paid.call_count == demo.call_count == 0, "Read view called a model")
    require(bool(contexts), "Select at least one result view")
    require(tree_hashes(runs_dir) == before, "Source store changed during result UI replay")
    result = {"status": "passed", "verified_at": datetime.now(timezone.utc).isoformat(), "contexts": contexts,
              "api_reads": len(calls), "model_calls": 0, "source_unchanged": True,
              "source_inventory_sha256": digest(before), "required_original_traces": require_trace,
              "human_acceptance": False, "holdout_executed": False}
    atomic_json(output, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--research-batch-id")
    parser.add_argument("--experiment-id")
    parser.add_argument("--comparison", action="store_true")
    parser.add_argument("--require-trace", action="store_true")
    args = parser.parse_args(argv)
    result = verify(args.runs_dir, args.output, research_batch_id=args.research_batch_id,
                    experiment_id=args.experiment_id, comparison=args.comparison, require_trace=args.require_trace)
    print(json.dumps({"status": result["status"], "contexts": len(result["contexts"]), "model_calls": result["model_calls"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
