"""Render saved real-model results in Streamlit without another model call."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import BatchStore
from backend.app.repository import RepositoryError, RunTraceStore
from backend.app.storage import atomic_json
from scripts.data_contract import CANARY_PATTERN, ROOT, load_bundle, require


def verify(runs_dir: Path, batch_id: str) -> dict:
    from streamlit.testing.v1 import AppTest

    sys.path.insert(0, str(ROOT / "frontend"))
    from ui_core import COMPARE_SAME, compare_verdict, label_of, summary_row

    state = BatchStore(runs_dir).get(batch_id)
    store = RunTraceStore(runs_dir)
    bundle = load_bundle(ROOT / "data/week2")
    selected = {}
    for entry in state.plan:
        if entry["case_id"] not in ("a006", "b006", "h007"):
            continue
        for attempt in entry["attempts"]:
            if attempt["status"] not in ("completed", "blocked"):
                continue
            trace = store.get(attempt["run_id"]).model_dump(mode="json")
            require(trace["manifest"]["execution_scope"] == "real", "UI replay needs real traces")
            if trace["status"] in ("completed", "blocked"):
                selected.setdefault((entry["case_id"], entry["condition_id"]), trace)

    checked = []
    with patch.dict(os.environ, {"DATA_DIR": str(ROOT / "data/week2"),
                                 "MVP_MANIFEST": str(ROOT / "data/week2/mvp-manifest.v0.1.json")}), \
            patch("requests.post", side_effect=AssertionError("UI replay attempted a paid request")), \
            patch("requests.get", side_effect=AssertionError("UI replay attempted a network request")):
        for case_id in ("a006", "b006", "h007"):
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
              "cases": checked}
    atomic_json(runs_dir.parent / "ui-verification-report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(args.runs_dir.resolve(), args.batch_id), ensure_ascii=False))
        return 0
    except (ValueError, AssertionError, OSError, KeyError, RepositoryError):
        print(json.dumps({"status": "failed", "message": "UI replay verification failed; inspect saved results."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
