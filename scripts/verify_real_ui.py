"""Render saved real-model results in Streamlit without another model call."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from backend.app.batch import BatchStore
from backend.app.repository import RepositoryError, RunTraceStore
from backend.app.storage import atomic_json
from scripts.data_contract import CANARY_PATTERN, ROOT, load_bundle, require


def verify_dashboard(runs_dir: Path, batch_id: str, *, allow_fixture=False) -> dict:
    """Replay the saved batch dashboard through the real read-only API, offline."""
    import streamlit as st
    from fastapi.testclient import TestClient
    from streamlit.testing.v1 import AppTest

    from backend.app.batch_analysis import aggregate, report_csv
    from backend.app.batch_models import BatchFilters
    from backend.app.config import Settings
    from backend.app.providers import OpenAICompatibleProvider

    sys.path.insert(0, str(ROOT / "frontend"))
    import batch_core
    from ui_core import BACKEND_URL

    runs_dir = Path(runs_dir).resolve()
    batch_store = BatchStore(runs_dir)
    state = batch_store.get(batch_id)
    scope = state.execution_settings["execution_scope"]
    require(scope == "real" or allow_fixture, "Dashboard replay needs real traces")
    summary = batch_store.summary(state)
    original = aggregate(runs_dir, batch_id)
    require(original.groups, "Dashboard replay needs a nonempty report")
    require(not original.counts["invalid_traces"], "Dashboard report contains invalid traces")
    manifest = batch_store.folder(batch_id) / "manifest.json"
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    # API construction needs a repository, but no model credentials or runtime .env.
    data_dir = batch_store.folder(batch_id) / "inputs" / state.source_snapshots[0]["source_id"]
    settings = Settings(project_root=ROOT, data_dir=data_dir, runs_dir=runs_dir,
        model_provider="demo", model_id="demo-rag-v0.1", system_prompt_version="v0.1",
        retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None)
    # main creates its default ASGI app during import. Saved-result replay must
    # also work in a fresh interpreter with missing or invalid model settings.
    with patch.object(Settings, "from_environment", return_value=settings):
        from backend.app.main import create_app
    downloads, api_calls, checked = {}, [], []
    download_button = st.download_button

    def capture_download(label, data, **kwargs):
        downloads[kwargs.get("key")] = data
        return download_button(label, data, **kwargs)

    with TestClient(create_app(settings)) as client:
        def request(method, url, json=None, **kwargs):
            path = urlsplit(url).path
            allowed = ((method == "GET" and path in ("/api/v1/batches", f"/api/v1/batches/{batch_id}")) or
                       (method == "GET" and path.startswith("/api/v1/runs/")) or
                       (method == "POST" and path in (f"/api/v1/batches/{batch_id}/report",
                                                       f"/api/v1/batches/{batch_id}/export.csv")))
            require(url.startswith(BACKEND_URL + "/") and allowed, "Dashboard attempted a non-read API")
            api_calls.append({"method": method, "path": path, "filters": json})
            response = client.request(method, path, json=json)
            require(response.status_code == 200, "Dashboard saved API request failed")
            return response

        with patch("requests.request", side_effect=request), \
                patch("requests.get", side_effect=lambda url, **kw: request("GET", url, **kw)), \
                patch("requests.post", side_effect=AssertionError("Dashboard attempted model execution")), \
                patch("requests.sessions.Session.request", side_effect=AssertionError("Dashboard attempted network I/O")), \
                patch("urllib.request.urlopen", side_effect=AssertionError("Dashboard attempted provider I/O")), \
                patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("Dashboard called model")) as model, \
                patch("streamlit.download_button", side_effect=capture_download):
            app = AppTest.from_file(str(ROOT / "frontend/pages/1_배치_대시보드.py"), default_timeout=60)
            app.session_state["batch_id"] = batch_id
            app.run()
            contexts = [{}] + [{"source_id": source["source_id"]} for source in state.source_snapshots]
            for filters in contexts:
                if filters:
                    app.selectbox(key=f"filter_{batch_id}_source_id").select(filters["source_id"])
                    next(button for button in app.button if button.label == "필터 적용").click().run()
                require(not app.exception and not app.error, "Dashboard failed to render saved report")
                expected = aggregate(runs_dir, batch_id, BatchFilters.model_validate(filters))
                expected_json = expected.model_dump(mode="json")
                require(json.loads(downloads["download_json"]) == expected_json,
                        "Dashboard JSON differs from saved aggregate")
                expected_rows = [{key: value for key, value in row.items() if key != "group_id"}
                                 for row in batch_core.comparison_rows(expected_json)]
                frames = [element.value for element in app.dataframe]
                tables = [frame for frame in frames if "ASR (공격 성공률)" in frame.columns and "변형" in frame.columns]
                require(len(tables) == 1 and tables[0].to_dict("records") == expected_rows,
                        "Dashboard comparison differs from saved aggregate")
                payload = batch_core.payload_rows(expected_json)
                if payload:
                    tables = [frame for frame in frames if "공격 변형 vs 대조" in frame.columns]
                    require(len(tables) == 1 and tables[0].to_dict("records") == payload,
                            "Dashboard payload uncertainty differs from saved aggregate")
                app.button(key="prepare_csv").click().run()
                require(not app.exception and not app.error, "Dashboard CSV preparation failed")
                require(downloads.get("download_csv") == report_csv(expected).encode("utf-8"),
                        "Dashboard CSV differs from saved aggregate")
                downloadable = [element for element in app.get("download_button")
                                if element.proto.label == "지표 CSV 내려받기"]
                require(len(downloadable) == 1, "Dashboard did not offer verified CSV")

                trace_id = None
                available = next((group for group in expected.groups if group["run_ids"]), None)
                if available:
                    app.selectbox(key="trace_group").select(available["group_id"]).run()
                    trace_id = app.selectbox(key="trace_run").value
                    app.button(key="load_trace").click().run()
                    require(not app.exception and not app.error, "Dashboard trace lookup failed")
                    trace = RunTraceStore(runs_dir).get(trace_id).model_dump(mode="json")
                    shown = [json.loads(element.value) for element in app.json]
                    require(trace in shown, "Dashboard trace differs from saved public trace")
                visible = "\n".join(str(element.value) for element in [*app.code, *app.text, *app.caption, *app.json])
                visible += "\n".join(frame.to_json(force_ascii=False) for frame in frames)
                visible += "\n".join(str(value) for value in downloads.values())
                require(not CANARY_PATTERN.search(visible), "Dashboard leaked a protected canary")
                checked.append({"filters": filters, "group_count": len(expected.groups),
                    "payload_comparison_count": len(payload), "trace_run_id": trace_id,
                    "evaluation_snapshot_sha256": expected.evaluation_snapshot_sha256})
            require(model.call_count == 0, "Dashboard called model")
    require(hashlib.sha256(manifest.read_bytes()).hexdigest() == before, "Dashboard modified saved batch")
    actual_trace_replayed = any(context["trace_run_id"] for context in checked)
    real_complete = (scope == "real" and state.status == "completed" and actual_trace_replayed and
                     not any(summary["status_counts"].get(status) for status in ("failed", "uncertain")) and
                     not summary["budget"]["unresolved_calls"])
    result = {"status": "passed", "verification_kind": "saved_batch_dashboard_api_ui_replay",
        "execution_scope": scope, "real_model_verified": bool(real_complete), "batch_id": batch_id,
        "batch_status": state.status, "status_counts": summary["status_counts"],
        "attempt_count": summary["attempt_count"],
        "report_version": original.report_version,
        "calculation_implementation_sha256": original.provenance.get("calculation_implementation_sha256"),
        "additional_model_calls": 0, "network_calls": 0, "saved_batch_unchanged": True,
        "api_aggregate_ui_json_csv_consistent": True, "canary_masking_verified": True,
        "contexts": checked, "read_api_requests": len(api_calls)}
    atomic_json(runs_dir.parent / "dashboard-verification-report.json", result)
    return result


def verify(runs_dir: Path, batch_id: str, *, data_dir=None, case_ids=None) -> dict:
    from streamlit.testing.v1 import AppTest

    sys.path.insert(0, str(ROOT / "frontend"))
    from ui_core import COMPARE_SAME, compare_verdict, label_of, summary_row

    state = BatchStore(runs_dir).get(batch_id)
    store = RunTraceStore(runs_dir)
    data_dir = Path(data_dir or ROOT / "data/week2").resolve()
    case_ids = case_ids or ("a006", "b006", "h007")
    bundle = load_bundle(data_dir)
    selected = {}
    for entry in state.plan:
        if entry["case_id"] not in case_ids:
            continue
        for attempt in entry["attempts"]:
            if attempt["status"] not in ("completed", "blocked"):
                continue
            trace = store.get(attempt["run_id"]).model_dump(mode="json")
            require(trace["manifest"]["execution_scope"] == "real", "UI replay needs real traces")
            if trace["status"] in ("completed", "blocked"):
                selected.setdefault((entry["case_id"], entry["condition_id"]), trace)

    checked = []
    with patch.dict(os.environ, {"DATA_DIR": str(data_dir),
                                 "MVP_MANIFEST": str(data_dir / "mvp-manifest.v0.1.json")}), \
            patch("requests.post", side_effect=AssertionError("UI replay attempted a paid request")), \
            patch("requests.get", side_effect=AssertionError("UI replay attempted a network request")):
        for case_id in case_ids:
            modes = [(mode, selected[(case_id, condition)]) for mode, condition in
                     (("none", "none"), ("D1", "D1"), ("D2", "D2-both"), ("D1+D2", "D1-D2"))]
            comparison = [{"title": label_of("defense_modes", mode), "trace": trace, "error": None}
                          for mode, trace in modes]
            positions = [{"title": label_of("defense_positions", position),
                          "trace": selected[(case_id, condition)], "error": None}
                         for position, condition in (("input", "D2-input"), ("retrieval", "D2-retrieval"),
                                                     ("input_retrieval", "D2-both"))]
            require(compare_verdict(comparison)[0] == COMPARE_SAME, "UI mode conditions differ")
            require(compare_verdict(positions)[0] == COMPARE_SAME, "UI position conditions differ")
            app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30)
            app.session_state["case_selector"] = bundle.cases[case_id].model_dump(mode="json")
            app.session_state["result"] = {"trace": modes[0][1], "error": None}
            app.session_state["compare"] = {"case_id": case_id, "position": "input_retrieval",
                                            "results": comparison}
            app.session_state["positions"] = {"case_id": case_id, "results": positions}
            app.run()
            require(not app.exception and not app.error, "Streamlit failed to render actual results")
            frames = [element.value for element in app.dataframe]
            for column, results in (("방어 모드", comparison), ("D2 적용 위치", positions)):
                expected = [summary_row(column, item["title"], item["trace"], None) for item in results]
                tables = [frame for frame in frames if column in frame.columns and "실행 번호" in frame.columns]
                require(len(tables) == 1 and tables[0].to_dict("records") == expected,
                        "Rendered comparison differs from saved trace metrics")
            visible = "\n".join(str(element.value) for element in [*app.code, *app.text, *app.caption])
            visible += "\n".join(frame.to_json(force_ascii=False) for frame in frames)
            require(not CANARY_PATTERN.search(visible), "UI leaked a protected canary")
            checked.append({"case_id": case_id, "mode_rows": 4, "position_rows": 3})

    report = {"status": "passed", "execution_scope": "real", "batch_id": batch_id,
              "verification_kind": "saved_real_trace_ui_replay", "additional_model_calls": 0,
              "comparison_metrics_match_saved_traces": True, "canary_masking_verified": True,
              "cases": checked, "dashboard": verify_dashboard(runs_dir, batch_id)}
    atomic_json(runs_dir.parent / "ui-verification-report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--case-ids", nargs="+")
    parser.add_argument("--dashboard-only", action="store_true", help="저장 배치 대시보드/API/CSV/trace만 오프라인 검증")
    args = parser.parse_args(argv)
    try:
        report = (verify_dashboard(args.runs_dir.resolve(), args.batch_id) if args.dashboard_only else
                  verify(args.runs_dir.resolve(), args.batch_id, data_dir=args.data_dir, case_ids=args.case_ids))
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except (ValueError, AssertionError, OSError, KeyError, RepositoryError):
        print(json.dumps({"status": "failed", "message": "UI replay verification failed; inspect saved results."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
