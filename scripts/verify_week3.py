"""Two-app, six-condition, three-repeat HTTP fixture handoff; no real LLM."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from jsonschema import Draft202012Validator
import requests

from backend.app.batch import BatchRunner, atomic_json
from backend.app.batch_analysis import aggregate, export_report
from backend.app.batch_models import BatchFilters, BatchSpec
from backend.app.config import Settings
from scripts.data_contract import ROOT, CANARY_PATTERN, load_bundle, require
from scripts.mvp import services
from scripts.verify_week2 import fixture_environment
from scripts.week2_data import prepare


def verify(output: Path):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    email = prepare(ROOT / "data/week2", output / "email-data", "email")
    rag = load_bundle(ROOT / "data")
    email_bundle = load_bundle(email)
    sources = []
    for name, bundle in (("rag", rag), ("email", email_bundle)):
        ids = [c.case_id for c in bundle.manifest.representative_cases]
        sources.append({"source_id": name, "data_dir": str(bundle.data_dir), "split": "dev", "case_ids": ids,
                        "metadata": {cid: {"family_id": "fixture-family-" + cid,
                                           "goal_kind": "marker" if bundle.cases[cid].label == "attack" else "normal",
                                           "severity": "high"} for cid in ids}})
    spec = BatchSpec.model_validate({"sources": sources, "repeats": 3,
        "budget": {"max_calls": 1000, "max_reserved_tokens": 40_000_000, "max_seconds": 180,
                   "unknown_price_policy": "calls_tokens"},
        "statistics": {"bootstrap_samples": 100}, "evaluation_policy_file": "configs/week3-evaluation-policy.json"})
    schema = json.loads((ROOT / "contracts/batch-v0.1.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    validator.validate(spec.model_dump(mode="json"))
    runs = output / "runs"
    with fixture_environment(rag.data_dir) as fixture:
        # Use one local transport for both apps. Responses are predetermined.
        fixture.cases.update({k: c.model_dump(mode="json") for k, c in email_bundle.cases.items()})
        fixture.documents.update({k: d.model_dump(mode="json") for k, d in email_bundle.documents.items()})
        settings = replace(Settings.from_environment(ROOT), data_dir=rag.data_dir, runs_dir=runs)
        runner = BatchRunner(settings)
        spec_path = output / "spec.fixture.json"
        atomic_json(spec_path, spec.model_dump(mode="json"))
        cli_env = dict(os.environ, MVP_LOAD_DOTENV="0", PYTHONIOENCODING="utf-8")
        def batch_cli(arguments, expected_code=0):
            result = subprocess.run([sys.executable, "-m", "scripts.week3_batch", "--runs-dir", str(runs), *arguments],
                cwd=ROOT, env=cli_env, capture_output=True, text=True, encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            require(result.returncode == expected_code, f"Batch CLI failed: {result.stdout} {result.stderr}")
            return json.loads(result.stdout)
        created = batch_cli(["create", "--spec", str(spec_path)])
        state = runner.store.get(created["batch_id"])
        require(len(state.plan) == 108, "Expected 2 apps x 3 cases x 6 unique conditions x 3 repeats")
        batch_cli(["run", state.batch_id, "--max-items", "7"], expected_code=2)
        state = runner.store.get(state.batch_id)
        require(state.status == "paused" and sum(len(e["attempts"]) for e in state.plan) == 7, "Partial progress lost")
        batch_cli(["run", state.batch_id])
        state = runner.store.get(state.batch_id)
        require(state.status == "completed", "Fixture batch failed")
        before_refresh = len(fixture.requests)
        state = runner.execute(state.batch_id)
        require(len(fixture.requests) == before_refresh, "Resume replayed a completed run")
        summary = runner.store.summary(state)
        validator.validate(summary)
        require(len(state.calls) == len(fixture.requests), "Ledger differs from wire calls")
        recorded_calls = 0
        for entry in state.plan:
            require(len(entry["attempts"]) == 1, "Unexpected duplicate attempt")
            run_id = entry["attempts"][0]["run_id"]
            trace = runner.traces.get(run_id)
            raw = runner.traces.get_raw(run_id)
            recorded_calls += trace.metrics.model_call_count
            require(len(raw["model_calls"]) == trace.metrics.model_call_count, "Trace/raw call mismatch")
            for call in raw["model_calls"]:
                payload = {"model": call["model_id"], "messages": call["messages"], **call["parameters"]}
                require(payload in fixture.requests, "Saved prompt not transmitted")
            require(trace.manifest.execution_scope == "fixture", "Scope must remain fixture")
        require(recorded_calls == len(fixture.requests), "Missing transmitted call")
        wire = json.dumps(fixture.requests, ensure_ascii=False)
        require("fixture-family-" not in wire, "Analysis metadata leaked into model input")
        with services(rag, runs, 0, 0, demo=False) as (url, _, env, _):
            response = requests.get(f"{url}/api/v1/batches/{state.batch_id}", timeout=10)
            require(response.status_code == 200 and response.json() == summary, "HTTP batch summary differs")
            for entry in state.plan:
                if entry["label"] == "attack":
                    continue
                run_id = entry["attempts"][0]["run_id"]
                trace = runner.traces.get(run_id)
                review = {"reviewer": "fixture-contract-check", "reason": "Synthetic contract review; not a real-model quality judgment",
                          "policy_version": trace.evaluation.policy_version or "fixture-review-v0.1",
                          "excessive_transformation": False}
                got = requests.put(f"{url}/api/v1/batches/{state.batch_id}/reviews/{run_id}", json=review, timeout=10)
                require(got.status_code == 200, "Review endpoint failed")
            report = aggregate(runs, state.batch_id)
            validator.validate(report.model_dump(mode="json"))
            require(not report.counts["invalid_traces"], "Actual fixture trace failed condition validation")
            require(report.decisions["status"] == "deferred", "Fixtures must not yield a real recommendation")
            require(all("non_real_execution" in r["reasons"] for r in report.decisions["records"]), "Scope gate missing")
            got = requests.post(f"{url}/api/v1/batches/{state.batch_id}/report", json={}, timeout=30)
            require(got.status_code == 200 and got.json() == report.model_dump(mode="json"), "API/report differs")
            filtered = BatchFilters(source_id="rag", comparison="technique", condition_id="none")
            selected = aggregate(runs, state.batch_id, filtered)
            got_csv = requests.post(f"{url}/api/v1/batches/{state.batch_id}/export.csv",
                                    json=filtered.model_dump(exclude_none=True), timeout=30)
            require(got_csv.status_code == 200, "CSV endpoint failed")
            rows = list(csv.DictReader(io.StringIO(got_csv.text)))
            require(all(r["evaluation_snapshot_sha256"] == selected.evaluation_snapshot_sha256 for r in rows), "CSV snapshot differs")
            for group in selected.groups:
                for name, metric in group["metrics"].items():
                    row = next(r for r in rows if r["group_id"] == group["group_id"] and r["metric"] == name)
                    require(int(row["denominator"]) == metric["denominator"], "CSV denominator differs")
                    require((float(row["value"]) if row["value"] else None) == metric["value"], "CSV metric differs")
            export_report(report, output / "export")
            command = [sys.executable, "-m", "scripts.week3_batch", "--runs-dir", str(runs), "report", state.batch_id]
            cli = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", check=True)
            require(json.loads(cli.stdout) == report.model_dump(mode="json"), "CLI re-generation differs")
            require(len(fixture.requests) == before_refresh, "Read/review/report/export called a model")
            public = {"summary": summary, "report": report.model_dump(mode="json")}
            require(not CANARY_PATTERN.search(json.dumps(public)), "Public handoff leaked a canary")
            atomic_json(output / "batch-summary.fixture.json", summary)
            atomic_json(output / "report.fixture.json", report.model_dump(mode="json"))
    result = {"status": "passed", "execution_scope": "fixture", "real_model_verified": False,
              "batch_id": state.batch_id, "planned_runs": 108, "wire_calls": before_refresh,
              "resume_duplicate_calls": 0, "api_cli_export_consistent": True,
              "recommendation_status": "deferred", "two_apps": ["rag_chat", "email_summary"],
              "repeats": 3, "unique_conditions": 6, "public_canary_leak": False,
              "code_commit": state.code_commit, "implementation_sha256": state.configuration_hashes["implementation"]}
    atomic_json(output / "verification-report.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="3주차 두 앱 배치·집계 HTTP fixture 인계 검증")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
