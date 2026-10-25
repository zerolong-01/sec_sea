"""Opt-in paid model-matrix validation; saved-result verification never calls models."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.accounting import Accounting
from backend.app.batch import BatchRunner, digest, file_hash
from backend.app.batch_models import BatchFilters
from backend.app.environment import load_project_environment
from backend.app.experiment_models import ExperimentSpec
from backend.app.experiment_reports import experiment_csv, experiment_report, export_experiment_report, source_inventory
from backend.app.experiments import ExperimentRunner
from backend.app.providers import OpenAICompatibleProvider
from backend.app.repository import RepositoryError
from backend.app.storage import atomic_json
from scripts.data_contract import ROOT
from scripts.pipeline_state import VerificationError, locked_output, record_verification_failure, require
from scripts.verify_real_api import _inspect, assert_safe

VERSION = "real-model-experiment-verification-v0.1"
MARKER = "real-model-experiment.json"


def _limits(spec, max_total_usd, allow_fixture):
    budget = spec.batch.budget
    require(math.isfinite(max_total_usd) and max_total_usd > 0, "INVALID_TOTAL_USD_LIMIT")
    require(budget.max_usd is not None and budget.unknown_price_policy == "stop", "VERIFIED_USD_CAP_REQUIRED")
    require(len(spec.models) * budget.max_usd <= max_total_usd + 1e-12, "TOTAL_USD_CAP_EXCEEDED")
    fixture = all(model.provider == "fixture_http" for model in spec.models)
    require(fixture and allow_fixture or all(model.provider == "openai_compatible" for model in spec.models),
            "REAL_PROVIDER_REQUIRED")
    if not fixture:
        require(all(model.base_url == "https://api.openai.com/v1" for model in
                    [*spec.models, *([spec.detector] if spec.detector else [])]), "OFFICIAL_ENDPOINT_REQUIRED")
    return "fixture" if fixture else "real"


def _read_settings(runner, child, profile, detector):
    # Restoring frozen paths/settings requires no live credentials or .env.
    profile = profile.model_copy(update={"api_key_env": None})
    detector = detector.model_copy(update={"api_key_env": None}) if detector else None
    return runner._execution_settings(child, profile, detector)


def _audit_saved(runner, state, output, credentials):
    before = source_inventory(runner, state)
    audits, request_hashes = {}, {}
    children = runner.validate_members(state)
    settings_by_model = {}
    for profile, member, child in zip(state.spec.models, state.members, children):
        settings = _read_settings(runner, child, profile, state.spec.detector)
        settings_by_model[profile.model_key] = settings
        inspector = BatchRunner(settings)
        audits[profile.model_key] = _inspect(inspector, child, credentials,
            output=output / "inspection" / profile.model_key)
        hashes = {}
        for entry in child.plan:
            if not entry["attempts"]:
                continue
            attempt = entry["attempts"][-1]
            if attempt["status"] not in ("completed", "blocked"):
                continue
            raw = inspector.traces.get_raw(attempt["run_id"])
            for call in raw.get("model_calls", []):
                unit = (entry["source_id"], entry["case_id"], entry["condition_id"], entry["repeat"],
                        call["purpose"], call.get("target_ref"))
                hashes[unit] = digest({"messages": call["messages"], "parameters": call["parameters"]})
        request_hashes[profile.model_key] = hashes
    compared, absent = 0, 0
    first = request_hashes[state.spec.models[0].model_key]
    for profile in state.spec.models[1:]:
        other = request_hashes[profile.model_key]
        shared = set(first) & set(other)
        require(all(first[key] == other[key] for key in shared), "TRANSMITTED_CONDITIONS_DIFFER")
        compared += len(shared)
        absent += len(set(first) ^ set(other))
    report = experiment_report(runner.project_root, runner.runs_dir, state.experiment_id)
    assert_safe(report.model_dump(mode="json"), credentials)
    target = output / "exports" / report.report_sha256
    if not target.exists():
        export_experiment_report(report, target)
    require(json.loads((target / "report.json").read_text(encoding="utf-8")) == report.model_dump(mode="json"),
            "SAVED_REPORT_MISMATCH")
    require((target / "metrics.csv").read_text(encoding="utf-8-sig") == experiment_csv(report).replace("\r\n", "\n"),
            "SAVED_CSV_MISMATCH")
    exported = json.loads((target / "export-manifest.json").read_text(encoding="utf-8"))
    require(exported["report_sha256"] == report.report_sha256 and
            all(file_hash(target / name) == sha for name, sha in exported["artifacts"].items()), "EXPORT_HASH_MISMATCH")
    # Use real saved traces through the API, while making paid refreshes fail.
    settings = settings_by_model[state.spec.models[0].model_key]
    with patch.object(OpenAICompatibleProvider, "complete", side_effect=VerificationError("READ_CALLED_MODEL")) as calls:
        from backend.app.config import Settings
        with patch.object(Settings, "from_environment", return_value=settings):
            from backend.app.main import create_app
        from fastapi.testclient import TestClient
        with TestClient(create_app(settings)) as client:
            base = "/api/v1/model-experiments/" + state.experiment_id
            require(client.get(base).json() == report.summary.model_dump(mode="json"), "HTTP_SUMMARY_MISMATCH")
            require(client.post(base + "/report", json={}).json() == report.model_dump(mode="json"), "HTTP_REPORT_MISMATCH")
            csv = client.post(base + "/export.csv", json={})
            require(csv.status_code == 200 and csv.text == experiment_csv(report) and
                    csv.headers.get("X-Report-SHA256") == report.report_sha256, "HTTP_CSV_MISMATCH")
            empty = client.post(base + "/report", json={"condition_id": ""})
            require(empty.status_code == 200 and not empty.json()["rows"] and
                    empty.json()["filters"]["condition_id"] == "", "EMPTY_FILTER_MISMATCH")
            for child in children:
                for entry in child.plan:
                    if entry["attempts"] and entry["attempts"][-1]["status"] in ("completed", "blocked", "failed"):
                        trace = client.get("/api/v1/runs/" + entry["attempts"][-1]["run_id"])
                        require(trace.status_code == 200, "HTTP_TRACE_MISMATCH")
                        assert_safe(trace.json(), credentials)
        require(calls.call_count == 0, "READ_CALLED_MODEL")
    require(source_inventory(runner, state) == before, "SOURCE_CHANGED_DURING_VERIFICATION")
    return report, audits, compared, absent, target


def verify(spec_path, output, *, execute=False, max_items=None, max_total_usd=1.0,
           retry_failed=False, retry_uncertain=False, settings=None, allow_fixture=False):
    require(max_items is None or type(max_items) is int and max_items > 0, "MAX_ITEMS_MUST_BE_POSITIVE")
    spec = ExperimentSpec.model_validate_json(Path(spec_path).read_text(encoding="utf-8"))
    scope = _limits(spec, max_total_usd, allow_fixture)
    output = Path(output).resolve()
    with locked_output(output, MARKER), record_verification_failure(output, VERSION, marker=MARKER):
        marker = output / MARKER
        if not marker.exists():
            atomic_json(marker, {"version": VERSION, "spec_sha256": digest(spec.model_dump(mode="json"))})
        owner = json.loads(marker.read_text(encoding="utf-8"))
        require(owner.get("version") == VERSION and owner.get("spec_sha256") == digest(spec.model_dump(mode="json")),
                "REAL_EXPERIMENT_SPEC_CHANGED")
        runner = ExperimentRunner(ROOT, output / "runs")
        checkpoint = output / "checkpoint.json"
        if checkpoint.exists():
            state = runner.store.get(json.loads(checkpoint.read_text(encoding="utf-8"))["experiment_id"])
        else:
            existing = list(runner.store.root.glob("experiment-*/manifest.json"))
            require(len(existing) <= 1, "AMBIGUOUS_EXISTING_EXPERIMENT")
            state = runner.store.get(existing[0].parent.name) if existing else runner.create(spec, settings=settings)
            atomic_json(checkpoint, {"version": VERSION, "experiment_id": state.experiment_id})
        require(state.spec == spec, "FROZEN_EXPERIMENT_SPEC_CHANGED")
        children = runner.validate_members(state)
        for child in children:
            book = Accounting(runner.batches.folder(child.batch_id) / "pricing.snapshot").book
            wanted = {child.execution_settings["model_id"]}
            if spec.detector:
                wanted.add(spec.detector.model_id)
            prices = {p.model_id: p for p in book.models} if book else {}
            require(all(model in prices and prices[model].verified and prices[model].source_url and
                        prices[model].effective_date and prices[model].input_usd_per_million is not None and
                        prices[model].output_usd_per_million is not None for model in wanted), "VERIFIED_PRICE_REQUIRED")
        credentials = ()
        if execute:
            load_project_environment(ROOT)
            credentials = tuple(filter(None, (runner._credential(model) for model in
                                [*spec.models, *([spec.detector] if spec.detector else [])])))
            runner.execute(state.experiment_id, max_items=max_items, retry_failed=retry_failed,
                           retry_uncertain=retry_uncertain, stop_on_error=True)
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=VerificationError("READ_CALLED_MODEL")) as refresh:
            report, audits, compared, absent, export = _audit_saved(runner, state, output, credentials)
            require(refresh.call_count == 0, "READ_CALLED_MODEL")
        complete = report.summary.status == "completed" and all(
            audit["reconciled_calls"] > 0 and not audit["error_counts"] and not audit["unreconciled_calls"]
            for audit in audits.values()) and not any(
                source["invalid_traces"] for source in report.provenance["batch_reports"].values())
        result = {"version": VERSION, "status": "passed" if complete else "incomplete",
            "verified_at": datetime.now(timezone.utc).isoformat(), "execution_scope": scope,
            "experiment_id": state.experiment_id, "planned_runs": report.summary.planned_count,
            "attempt_count": report.summary.attempt_count, "model_count": len(spec.models),
            "max_total_usd": max_total_usd, "budget_usage": report.summary.budget_usage,
            "models": report.summary.models, "audits": audits, "compared_transmitted_calls": compared,
            "unpaired_calls_due_to_execution_outcomes": absent,
            "api_csv_export_consistent": True, "read_model_calls": 0, "source_unchanged": True,
            "report_sha256": report.report_sha256, "export": str(export.relative_to(output)),
            "selection_status": "not_performed", "human_independent_review": "not_performed",
            "cost_basis": "observed tokens times frozen standard uncached rates; estimate, not invoice"}
        assert_safe(result, credentials)
        atomic_json(output / "verification-report.json", result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Explicitly allow paid calls within the frozen USD caps")
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--max-total-usd", type=float, default=1.0)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--retry-uncertain", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify(args.spec, args.output, execute=args.execute, max_items=args.max_items,
            max_total_usd=args.max_total_usd, retry_failed=args.retry_failed, retry_uncertain=args.retry_uncertain)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if result["status"] == "passed" else 2
    except (ValueError, OSError, KeyError, RepositoryError, VerificationError) as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, VerificationError) else type(exc).__name__,
                          "status": "failed"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
