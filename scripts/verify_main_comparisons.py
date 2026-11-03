"""Manifest-driven four-mode and D2-position UI verification for either app."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from backend.app.storage import atomic_json
from scripts.data_contract import CANARY_PATTERN, ROOT, load_bundle, require
from scripts.mvp import request_json, services
from scripts.verify_week2 import fixture_environment


def verify(data_dir, output, evaluation_rules=None):
    from streamlit.testing.v1 import AppTest
    sys.path.insert(0, str(ROOT / "frontend"))
    from ui_core import COMPARE_SAME, compare_verdict, summary_row

    output, data_dir = Path(output).resolve(), Path(data_dir).resolve()
    require(not output.is_relative_to(data_dir) and not data_dir.is_relative_to(output), "Output overlaps source data")
    bundle = load_bundle(data_dir)
    require(all(bundle.cases[item.case_id].split != "holdout" for item in bundle.manifest.representative_cases),
            "Only development representatives may be executed")
    output.mkdir(parents=True, exist_ok=False)
    runs, checked = output / "runs", []
    overrides = {"EVALUATION_RULES_FILE": str(Path(evaluation_rules).resolve())} if evaluation_rules else {}
    with fixture_environment(bundle.data_dir) as fixture:
        with services(bundle, runs, 0, 0, demo=False, environment_overrides=overrides,
                      service_logs_dir=output / "service-logs") as (url, _, env, _):
            require(request_json(url + "/health")["model_provider"] == "fixture_http", "Expected local HTTP fixture")
            with patch.dict(os.environ, env):
                app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=60).run()

                def check(state_key, experiment, column):
                    require(not app.exception and not app.error, "Comparison UI failed")
                    results = app.session_state[state_key]["results"]
                    require(compare_verdict(results, experiment)[0] == COMPARE_SAME, "Comparison conditions differ")
                    frame = next(e.value for e in app.dataframe if column in e.value.columns and "실행 번호" in e.value.columns)
                    require(len(frame) == len(results), "Comparison table dropped results")
                    for item, actual in zip(results, frame.to_dict("records")):
                        trace = item["trace"]
                        require(trace["manifest"]["execution_scope"] == "fixture", "Fixture scope missing")
                        require(request_json(url + "/api/v1/runs/" + trace["run_id"]) == trace,
                                "UI comparison differs from stored API trace")
                        require(json.loads((runs / (trace["run_id"] + ".trace.json")).read_text(encoding="utf-8")) == trace,
                                "UI comparison differs from saved bytes")
                        require(actual == summary_row(column, item["title"], trace, None), "Comparison table values differ")
                        checked.append({"case_id": trace["request"]["case_id"], "scenario": trace["request"]["scenario"],
                                        "mode": trace["request"]["defense_mode"], "position": trace["request"]["defense_position"],
                                        "run_id": trace["run_id"], "status": trace["status"]})
                    shown = "\n".join(str(e.value) for e in [*app.code, *app.text, *app.caption])
                    require(not CANARY_PATTERN.search(shown), "Unmasked canary in comparison UI")

                for item in bundle.manifest.representative_cases:
                    app.radio(key="case_selector").set_value(bundle.cases[item.case_id].model_dump()).run()
                    app.button(key="run_compare").click().run()
                    check("compare", "modes", "방어 모드")
                    require(all(r["case_id"] == item.case_id for r in checked[-4:]), "Selected and executed case differ")
                attack = next(item for item in bundle.manifest.representative_cases if item.label == "attack")
                app.radio(key="case_selector").set_value(bundle.cases[attack.case_id].model_dump()).run()
                app.button(key="run_positions").click().run()
                check("positions", "positions", "D2 적용 위치")
                before = len(fixture.requests)
                app.button(key="refresh_compare").click().run()
                app.button(key="refresh_positions").click().run()
                require(not app.exception and not app.error, "Saved comparison refresh failed")
                require(len(fixture.requests) == before, "Saved comparison refresh called a model")
    result = {"status": "passed", "execution_scope": "fixture", "paid_model_calls": 0,
              "real_model_quality_verified": False, "dataset_version": bundle.manifest.dataset_version,
              "cases": checked, "comparison_runs": len(checked), "wire_calls": before,
              "selected_case_request_match": True, "ui_api_store_table_match": True,
              "read_model_calls": 0, "canary_masking_checked": True, "holdout_executed": False}
    atomic_json(output / "verification-report.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evaluation-rules", type=Path)
    args = parser.parse_args(argv)
    result = verify(args.data_dir, args.output, args.evaluation_rules)
    print(json.dumps({k: result[k] for k in ("status", "comparison_runs", "paid_model_calls", "read_model_calls")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
