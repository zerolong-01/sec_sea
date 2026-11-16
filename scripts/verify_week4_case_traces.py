"""Replay the ten published audit examples in the UI without model calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

from backend.app.batch import digest, file_hash
from backend.app.config import Settings
from scripts.data_contract import ROOT, require
from scripts.verify_real_api import public_trace_reader
from scripts.week4_package import tree_hashes

INDEX = ROOT / "frontend/verification/week4-case-trace-links.md"


def selected_cases(index=INDEX):
    selected = []
    for line in index.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\| \d+ \|", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        match = re.fullmatch(r"(week2|ai|legacy) / `([a-z0-9_]+)`", cells[1])
        run = re.search(r"`(run-[a-z0-9_-]+)`", cells[4])
        require(match is not None and run is not None, "Invalid selected audit example")
        selected.append((match[1], match[2], run[1]))
    require(len(selected) == 10 and len({row[2] for row in selected}) == 10,
            "Expected ten distinct selected audit runs")
    return selected


def verify(audit_root, output):
    from fastapi.testclient import TestClient
    from streamlit.testing.v1 import AppTest
    from backend.app.providers import DemoRagProvider, OpenAICompatibleProvider

    sys.path.insert(0, str(ROOT / "frontend"))
    from ui_core import label_of

    audit_root, output = Path(audit_root).resolve(), Path(output).resolve()
    require(not output.exists() and not output.is_relative_to(audit_root), "Output must be new and outside audit evidence")
    selected = selected_cases()
    folders = {source: audit_root / "exploration/executions" / source / "runs"
               for source, _, _ in selected}
    before = {source: tree_hashes(folder) for source, folder in folders.items()}
    results = []
    for source, case_id, run_id in selected:
        settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=folders[source],
                            model_provider="demo", model_id="demo-rag-v0.1", system_prompt_version="v0.1",
                            retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None)
        reader = public_trace_reader(settings)
        trace = reader.get_trace(run_id)
        require(trace.request.case_id == case_id, "Selected run/case mismatch")
        expected = trace.model_dump(mode="json", by_alias=True)
        with patch.object(Settings, "from_environment", return_value=settings):
            from backend.app.main import create_app

        with TestClient(create_app(settings)) as client:
            def get(url, **kwargs):
                path = urlsplit(url).path
                require(path == f"/api/v1/runs/{run_id}", "Unexpected UI request")
                response = client.get(path)
                require(response.status_code == 200 and response.json() == expected, "API/reader mismatch")
                return response

            env = {"DATA_DIR": str(ROOT / "data"), "MVP_MANIFEST": str(ROOT / "data/mvp-manifest.v0.1.json"),
                   "EVALUATION_RULES_FILE": "", "MVP_LOAD_DOTENV": "0"}
            with patch.dict(os.environ, env), \
                    patch("requests.get", side_effect=get) as reads, \
                    patch("requests.post", side_effect=AssertionError("UI attempted execution")), \
                    patch("requests.sessions.Session.request", side_effect=AssertionError("UI attempted network I/O")), \
                    patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("Paid call")) as paid, \
                    patch.object(DemoRagProvider, "generate_prepared", side_effect=AssertionError("Model call")) as demo:
                app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=60).run()
                app.text_input(key="stored_run_id").set_value(run_id)
                app.button(key="load_run").click().run()
                require(not app.exception and not app.error, "Saved audit trace did not render")
                require(reads.call_count == 1, "Expected a single read-only trace request")
                require(trace.output.display_text in [element.value for element in app.code], "UI output mismatch")
                require(bool(trace.evaluation.reason) and trace.evaluation.reason in
                        [element.value for element in app.text], "UI evaluation reason mismatch")
                if trace.defense_events:
                    tables = [element.value for element in app.dataframe if "근거 코드" in element.value.columns]
                    require(len(tables) == 1, "Missing defense evidence table")
                    table = tables[0]
                    require(table["판정"].tolist() == [label_of("defense_decisions", e.decision)
                                                   for e in trace.defense_events], "UI defense decisions mismatch")
                    require(table["근거 코드"].tolist() == [e.reason_code or "기록 없음" for e in trace.defense_events],
                            "UI defense reasons mismatch")
                rendered = [str(e.value) for e in [*app.text, *app.code, *app.caption, *app.markdown, *app.dataframe]]
                require(reader.safe_for_trace(trace, rendered) == rendered, "Protected value in public UI")
                require(paid.call_count == demo.call_count == 0, "Unexpected model call")

        results.append({"source_id": source, "case_id": case_id, "run_id": run_id,
                        "public_trace_sha256": digest(expected), "output_matches": True,
                        "evaluation_reason_matches": True, "defense_event_count": len(trace.defense_events),
                        "defense_evidence_matches": True, "public_masking_checked": True})
    require({source: tree_hashes(folder) for source, folder in folders.items()} == before,
            "Audit source files changed during replay")
    result = {"status": "passed", "verified_at": datetime.now(timezone.utc).isoformat(),
              "verification_actor": "Codex_automated_read_only_UI_replay_not_human_acceptance",
              "selection_index": INDEX.relative_to(ROOT).as_posix(), "selection_sha256": digest(selected),
              "implementation_sha256": {name: file_hash(ROOT / name) for name in (
                  "frontend/app.py", "frontend/trace_view.py", "frontend/case_browser.py", "backend/app/privacy.py",
                  "scripts/verify_week4_case_traces.py")}, "selected_runs": len(results),
              "model_calls": 0, "source_files_unchanged": True,
              "source_inventory_sha256": digest(before), "cases": results,
              "human_ABC_acceptance": "pending", "real_model_rerun": "not_performed", "holdout_executed": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = verify(args.audit_root, args.output)
    print(json.dumps({key: result[key] for key in ("status", "selected_runs", "model_calls", "source_files_unchanged")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
