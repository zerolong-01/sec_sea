"""Bounded, resumable dev pilot against the configured real OpenAI API.

Raw traces stay in the ignored output directory. Public samples and exports use
the current RunService.get_trace read projection, including frozen batch privacy
rules. Matching the HTTP endpoint to that reader checks projection consistency;
independent backend privacy tests establish masking correctness. This is integration evidence, not approval
of draft gold, service criteria, statistical policy or a holdout experiment.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from backend.app.accounting import Accounting
from backend.app.batch import BatchRunner, digest, public_settings
from backend.app.batch_analysis import aggregate, export_report, report_csv, validate_report_export
from backend.app.batch_models import BatchSpec
from backend.app.config import Settings
from backend.app.models import ModelCall
from backend.app.providers import OpenAICompatibleProvider
from backend.app.storage import atomic_json
from scripts.data_contract import CANARY_PATTERN, ROOT, load_bundle
from scripts.pipeline_state import VerificationError, locked_output, record_verification_failure, require
from scripts.week2_data import prepare

PILOT_VERSION = "real-api-dev-pilot-v0.1"
MODEL_ID = "gpt-4.1-mini-2025-04-14"
ENDPOINT = "https://api.openai.com/v1"
DEFAULT_OUTPUT = ROOT / "runs/real-api-2026-10-20"


def assert_safe(value, credentials=(), *, allow_canary=False):
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    require(allow_canary or not CANARY_PATTERN.search(text), "PUBLIC_CANARY_LEAK")
    require(not any(secret and secret in text for secret in credentials), "CREDENTIAL_LEAK")


def _settings(output, supplied, allow_fixture):
    settings = supplied or Settings.from_environment(ROOT)
    fixture = settings.model_provider == "fixture_http"
    require(not fixture or allow_fixture, "REAL_PROVIDER_REQUIRED")
    require(fixture or settings.model_provider == "openai_compatible", "REAL_PROVIDER_REQUIRED")
    if not fixture:
        require(settings.model_base_url == ENDPOINT and
                (settings.d2_base_url or settings.model_base_url) == ENDPOINT, "OFFICIAL_ENDPOINT_REQUIRED")
        require(settings.model_id == MODEL_ID and
                (settings.d2_model_id or settings.model_id) == MODEL_ID, "PINNED_MODEL_REQUIRED")
        require(bool(settings.model_api_key) and bool(settings.d2_api_key or settings.model_api_key),
                "API_KEY_REQUIRED")
    settings = replace(settings, data_dir=ROOT / "data/week2", runs_dir=output / "runs",
        pricing_path=settings.pricing_path if supplied else ROOT / "configs/pricing-openai-2026-10-20.json",
        evaluation_rules_path=ROOT / "configs/evaluation-week2.json",
        common_policy_path=ROOT / "configs/week3-common-policy.txt")
    book = Accounting(settings.pricing_path).book
    for model in {settings.model_id, settings.d2_model_id or settings.model_id}:
        price = next((p for p in book.models if p.model_id == model), None) if book else None
        require(bool(price and price.verified and price.source_url and price.effective_date and
                     price.input_usd_per_million is not None and price.output_usd_per_million is not None),
                "VERIFIED_PRICE_REQUIRED")
    return settings


def _spec(email):
    sources = [
        {"source_id": "rag", "data_dir": str(ROOT / "data/week2"), "split": "dev",
         "case_ids": ["a006", "b006", "h007"]},
        {"source_id": "email", "data_dir": str(email), "split": "dev",
         "case_ids": [row.case_id for row in load_bundle(email).manifest.representative_cases]},
    ]
    require(len(sources[1]["case_ids"]) == 3, "EMAIL_REPRESENTATIVES_CHANGED")
    # UTF-8 admission ceilings are deliberately conservative. Ten million
    # reserved tokens permit all D2 calls while the independent USD cap is $1.
    return BatchSpec.model_validate({"sources": sources, "repeats": 3, "random_seed": 2026,
        "budget": {"max_calls": 500, "max_reserved_tokens": 10_000_000, "max_seconds": 1800,
                   "max_usd": 1.0, "unknown_price_policy": "stop", "per_call_input_token_ceiling": 32768},
        "statistics": {"bootstrap_samples": 1000}, "min_call_interval_seconds": .1,
        "common_policy_file": "configs/week3-common-policy.txt",
        "evaluation_policy_file": "configs/week3-evaluation-policy.json"})


def _state(output, runner):
    marker = output / "pilot.json"
    if not marker.exists():
        require(not output.exists() or not any(p.name != ".pipeline.lock" for p in output.iterdir()), "OUTPUT_DIRECTORY_NOT_OWNED")
        output.mkdir(parents=True, exist_ok=True)
        atomic_json(marker, {"version": PILOT_VERSION})
    require(json.loads(marker.read_text(encoding="utf-8")).get("version") == PILOT_VERSION,
            "PILOT_VERSION_MISMATCH")
    checkpoint = output / "checkpoint.json"
    manifests = list((output / "runs/batches").glob("batch-*/manifest.json"))
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        require(saved.get("version") == PILOT_VERSION, "CHECKPOINT_VERSION_MISMATCH")
        state = runner.store.get(saved["batch_id"])
    elif manifests:
        # A crash after create but before checkpoint must reuse that same plan.
        require(len(manifests) == 1, "AMBIGUOUS_EXISTING_BATCH")
        state = runner.store.get(manifests[0].parent.name)
    else:
        email = output / "email-data"
        if not email.exists():
            prepare(ROOT / "data/week2", email, "email")
        spec = _spec(email)
        atomic_json(output / "spec.real.json", spec.model_dump(mode="json"))
        state = runner.create(spec)
    require(len(state.plan) == 108 and state.spec.repeats == 3 and
            {s.split for s in state.spec.sources} == {"dev"}, "PILOT_PLAN_MISMATCH")
    current = public_settings(runner.settings)
    if state.status == "completed" and "d1_version" not in state.execution_settings:
        # Old completed batches remain readable; unfinished executions still
        # require the exact frozen settings and implementation before transport.
        current.pop("d1_version", None)
    require(current == state.execution_settings, "EXECUTION_SETTINGS_CHANGED")
    runner._verify_inputs(state, executing=False)
    atomic_json(checkpoint, {"version": PILOT_VERSION, "batch_id": state.batch_id})
    return state


def _execute(runner, state, max_items):
    # One writer session validates the frozen batch once and stops before the
    # next item on any failed/uncertain attempt. No automatic paid retry.
    if not any(e["status"] in ("pending", "running") for e in state.plan):
        return state
    return runner.execute(state.batch_id, max_items=max_items, stop_on_error=True)


def _inspect(runner, state, credentials, *, output=None):
    validator = Draft202012Validator(json.loads(
        (ROOT / "contracts/execution-v0.3.schema.json").read_text(encoding="utf-8")))
    samples = Path(output or runner.settings.runs_dir.parent) / "public-samples"
    samples.mkdir(parents=True, exist_ok=True)
    reader = public_trace_reader(runner.settings)
    calls_by_attempt = {}
    for call in state.calls:
        calls_by_attempt.setdefault(call["attempt_id"], []).append(call)
    accounting = Accounting(runner.store.folder(state.batch_id) / "pricing.snapshot")
    projection_hashes = []
    selected_samples = {}
    http_statuses, errors = Counter(), Counter()
    observed_calls = 0
    reconciled_attempts, untraced_attempts, known_attempts = set(), set(), set()
    for entry in state.plan:
        for attempt in entry["attempts"]:
            known_attempts.add(attempt["attempt_id"])
            ledger = calls_by_attempt.get(attempt["attempt_id"], [])
            if attempt["status"] == "cancelled_before_transport":
                require(not ledger, "CANCELLED_ATTEMPT_HAS_LEDGER_CALLS")
                continue
            if attempt["status"] in ("running", "uncertain", "pending"):
                # A crash can leave an earlier settled D2 call and a later
                # reservation without a final trace. Preserve both in the
                # budget and report their unreconciled evidence separately.
                untraced_attempts.add(attempt["attempt_id"])
                continue
            trace = runner.traces.get(attempt["run_id"])
            stored = trace.model_dump(mode="json", by_alias=True)
            public = runner_trace(runner.settings, trace.run_id, reader=reader)
            require(not list(validator.iter_errors(public)), "TRACE_SCHEMA_MISMATCH")
            require(trace.manifest.execution_scope == state.execution_settings["execution_scope"],
                    "TRACE_SCOPE_MISMATCH")
            assert_safe(public, credentials)
            raw = runner.traces.get_raw(trace.run_id)
            require(raw.get("run_id") == trace.run_id and raw.get("request") == stored["request"],
                    "RAW_TRACE_MISMATCH")
            assert_safe(raw, credentials, allow_canary=True)
            calls = raw.get("model_calls", [])
            reconciled_attempts.add(attempt["attempt_id"])
            require(len(calls) == len(ledger) == trace.metrics.model_call_count == len(trace.model_calls),
                    "CALL_COUNT_MISMATCH")
            for call, saved, public_call in zip(calls, ledger, trace.model_calls):
                observed_calls += 1
                http_statuses[str(call.get("http_status"))] += 1
                require(all(call.get(k) == getattr(public_call, k) for k in
                            ("model_id", "purpose", "input_tokens", "output_tokens", "estimated_cost_usd")),
                        "PUBLIC_USAGE_MISMATCH")
                require(all(call.get(k) == saved.get(k) for k in
                            ("model_id", "purpose", "input_tokens", "output_tokens")), "LEDGER_USAGE_MISMATCH")
                require(call.get("estimated_cost_usd") == saved["known_cost_usd"], "LEDGER_COST_MISMATCH")
                recalculated = ModelCall.model_validate(call)
                accounting.price(recalculated)
                require(recalculated.estimated_cost_usd == call.get("estimated_cost_usd"),
                        "ACCOUNTING_COST_MISMATCH")
                if trace.status in ("completed", "blocked"):
                    require(call.get("usage_source") == "observed" and
                            call.get("estimated_cost_usd") is not None and
                            isinstance(call.get("http_status"), int) and 200 <= call["http_status"] < 300,
                            "SUCCESSFUL_CALL_USAGE_REQUIRED")
            if calls and all(call.get("estimated_cost_usd") is not None for call in calls):
                require(math.isclose(sum(c["estimated_cost_usd"] for c in calls),
                                     trace.metrics.known_cost_usd, abs_tol=1e-12), "TRACE_TOTAL_COST_MISMATCH")
            if trace.error:
                errors[trace.error.code] += 1
            projection_hashes.append({"run_id": trace.run_id,
                "stored_trace_model_sha256": digest(stored), "public_projection_sha256": digest(public),
                "projection_changed": stored != public})
            # One sample per condition/case; repeated evidence stays in runs/.
            selected_samples[f"{entry['source_id']}-{entry['case_id']}-{entry['condition_id']}.json"] = {
                "request": public["request"], "trace": public}
    require(all(call["attempt_id"] in known_attempts for call in state.calls), "ORPHAN_LEDGER_CALL")
    traced_calls = [call for call in state.calls if call["attempt_id"] in reconciled_attempts]
    untraced_calls = [call for call in state.calls if call["attempt_id"] in untraced_attempts]
    require(observed_calls == len(traced_calls) and len(traced_calls) + len(untraced_calls) == len(state.calls),
            "UNRECONCILED_LEDGER_CALLS")
    for name, sample in selected_samples.items():
        atomic_json(samples / name, sample)
    committed = [call["committed_usd"] for call in untraced_calls]
    return {"reconciled_calls": observed_calls, "unreconciled_calls": len(untraced_calls),
            "unreconciled_settled_calls": sum(call["status"] == "settled" for call in untraced_calls),
            "unreconciled_known_cost_usd": sum(call["known_cost_usd"] or 0 for call in untraced_calls),
            "unreconciled_committed_usd": sum(committed) if all(value is not None for value in committed) else None,
            "http_status_counts": dict(http_statuses),
            "error_counts": dict(errors), "public_canary_leak": False, "credential_leak": False,
            "public_trace_contract": "RunService.get_trace_read_projection",
            "privacy_correctness_evidence": "independent_backend_privacy_tests",
            "projection_consistency_is_not_independent_masking_verification": True,
            "public_projection_changed_count": sum(row["projection_changed"] for row in projection_hashes),
            "trace_projection_hashes": projection_hashes}


def _read_api(settings, state, summary, report):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app

    # An attempted generation or detector call turns a refresh into a failure.
    with patch.object(OpenAICompatibleProvider, "complete", side_effect=VerificationError("READ_CALLED_MODEL")) as calls:
        reader = public_trace_reader(settings)
        with TestClient(create_app(settings)) as client:
            got = client.get(f"/api/v1/batches/{state.batch_id}")
            require(got.status_code == 200 and got.json() == summary, "HTTP_SUMMARY_MISMATCH")
            got = client.get("/api/v1/batches")
            require(got.status_code == 200 and summary in got.json(), "HTTP_LIST_MISMATCH")
            got = client.post(f"/api/v1/batches/{state.batch_id}/report", json={})
            require(got.status_code == 200 and got.json() == report.model_dump(mode="json"),
                    "HTTP_REPORT_MISMATCH")
            got = client.post(f"/api/v1/batches/{state.batch_id}/export.csv", json={})
            require(got.status_code == 200 and got.text == report_csv(report), "HTTP_CSV_MISMATCH")
            require(len(list(csv.DictReader(io.StringIO(got.text)))) ==
                    sum(len(g["metrics"]) for g in report.groups), "CSV_ROW_COUNT_MISMATCH")
            for entry in state.plan:
                for attempt in entry["attempts"]:
                    if attempt["status"] not in ("completed", "blocked", "failed"):
                        continue
                    got = client.get(f"/api/v1/runs/{attempt['run_id']}")
                    require(got.status_code == 200 and got.json() ==
                            runner_trace(settings, attempt["run_id"], reader=reader), "HTTP_TRACE_MISMATCH")
        require(calls.call_count == 0, "READ_CALLED_MODEL")


def public_trace_reader(settings):
    """Build the API's read service; get_trace never executes the inert provider."""
    from backend.app.repository import ExperimentRepository, RunTraceStore
    from backend.app.service import RunService
    return RunService(settings, ExperimentRepository(settings.data_dir), RunTraceStore(settings.runs_dir), provider=None)


def runner_trace(settings, run_id, *, reader=None):
    """Current safe projection, which may differ from immutable legacy storage."""
    return (reader or public_trace_reader(settings)).get_trace(run_id).model_dump(mode="json", by_alias=True)


def verify(output: Path, *, settings: Settings | None = None, max_items: int | None = None,
           allow_fixture: bool = False) -> dict:
    require(max_items is None or type(max_items) is int and max_items > 0, "MAX_ITEMS_MUST_BE_POSITIVE")
    output = Path(output).resolve()
    settings = _settings(output, settings, allow_fixture)
    credentials = tuple({secret for secret in (settings.model_api_key, settings.d2_api_key) if secret})
    with locked_output(output, "pilot.json"), record_verification_failure(output, PILOT_VERSION, marker="pilot.json"):
        runner = BatchRunner(settings)
        state = _execute(runner, _state(output, runner), max_items)
        return verify_saved(runner, state, credentials, output)


def verify_saved(runner, state, credentials, output, *, version=PILOT_VERSION, extra=None, save_result=True):
    """Shared saved-run/schema/ledger/API/export checks; never sends a model call."""
    settings = runner.settings
    checks = _inspect(runner, state, credentials, output=output)
    summary = runner.store.summary(state)
    report = aggregate(settings.runs_dir, state.batch_id)
    require(not report.counts["invalid_traces"], "REPORT_TRACE_INTEGRITY_FAILURE")
    require(report.decisions["status"] == "deferred", "DRAFT_POLICY_MUST_DEFER_RECOMMENDATION")
    validator = Draft202012Validator(json.loads(
        (ROOT / "contracts/batch-v0.1.schema.json").read_text(encoding="utf-8")))
    for public in (summary, report.model_dump(mode="json")):
        require(not list(validator.iter_errors(public)), "BATCH_SCHEMA_MISMATCH")
        assert_safe(public, credentials)
    _read_api(settings, state, summary, report)
    # Filters and calculation versions can change without a new evaluation.
    export = output / "exports" / report.report_version / digest(report.model_dump(mode="json"))
    if not export.exists():
        export_report(report, export)
    try:
        validate_report_export(report, export)
    except (ValueError, OSError) as exc:
        raise VerificationError("EXPORT_ARTIFACT_MISMATCH") from exc
    for path in export.iterdir():
        assert_safe(path.read_text(encoding="utf-8-sig"), credentials)
    atomic_json(output / "batch-summary.real.json", summary)
    atomic_json(output / "report.real.json", report.model_dump(mode="json"))
    statuses = Counter(e["status"] for e in state.plan)
    failed = bool(statuses["failed"] or statuses["uncertain"] or summary["budget"]["unresolved_calls"])
    complete = state.status == "completed"
    result = {"version": version,
        "status": "failed" if failed else "passed" if complete else "paused",
        "execution_scope": state.execution_settings["execution_scope"],
        "real_model_verified": complete and not failed and state.execution_settings["execution_scope"] == "real",
        "batch_id": state.batch_id, "batch_status": state.status, "reason": state.reason,
        "planned_runs": len(state.plan), "status_counts": dict(statuses),
        "repeats": state.spec.repeats, "unique_conditions": len(state.spec.conditions),
        "two_apps": ["rag_chat", "email_summary"], "budget": summary["budget"],
        "api_report_export_consistent": True, "refresh_model_calls": 0,
        "recommendation_status": report.decisions["status"], "team_agreement": "pending",
        "report_version": report.report_version,
        "evaluation_snapshot_sha256": report.evaluation_snapshot_sha256,
        "holdout_executed": False, "evaluation_scope": "draft_rubric_manual_semantic_review_pending",
        "code_commit": state.code_commit, "implementation_sha256": state.configuration_hashes["implementation"],
        "export_path": str(export.relative_to(output)), **checks, **(extra or {})}
    assert_safe(result, credentials)
    if save_result:
        atomic_json(output / "verification-report.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="실제 OpenAI API 소형 dev 파일럿 ($1 예약 상한, 재개 지원)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-items", type=int, help="이번 실행의 최대 항목 수; 같은 output으로 재개")
    args = parser.parse_args(argv)
    try:
        result = verify(args.output, max_items=args.max_items)
    except Exception as exc:
        result = {"status": "failed", "error": str(exc) if isinstance(exc, VerificationError) else type(exc).__name__,
                  "message": "실제 API 검증 실패; 저장된 checkpoint·마스킹된 trace와 설정을 확인하세요."}
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["status"] == "passed" else 2 if result["status"] == "paused" else 1


if __name__ == "__main__":
    raise SystemExit(main())
