"""Budgeted dev-only D2 diagnostics; resume saved attempts without retrying them."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import replace
from pathlib import Path

from jsonschema import Draft202012Validator

from backend.app.accounting import Accounting
from backend.app.batch import BatchRunner, public_settings
from backend.app.batch_models import BatchSpec
from backend.app.config import Settings
from backend.app.detector_evaluation import report as detector_report
from backend.app.models import ModelCall
from backend.app.repository import ArtifactNotFound
from backend.app.storage import atomic_json
from scripts.data_contract import CANARY_PATTERN, ROOT, load_bundle, require
from scripts.pipeline_state import locked_output, record_verification_failure
from scripts.week2_data import gold_plan, prepare

VERSION = "real-detector-dev-v0.1"
RAG_CASES = ("a006", "b006", "h007", "a021", "a022", "a023", "a024",
             "b021", "b022", "b023", "b024", "h021", "h022", "h023", "h024")
EMAIL_CASES = ("email-benign-001", "email-attack-001", "email-hard-negative-001")


def _settings(output: Path, settings: Settings | None, allow_fixture: bool) -> Settings:
    supplied = settings is not None
    settings = settings or Settings.from_environment(ROOT)
    settings = replace(settings, data_dir=ROOT / "data/week2", runs_dir=output / "runs",
                       pricing_path=settings.pricing_path if supplied else ROOT / "configs/pricing-openai-2026-10-20.json",
                       evaluation_rules_path=ROOT / "configs/evaluation-week2.json")
    fixture = settings.model_provider == "fixture_http"
    require(fixture and allow_fixture or settings.model_provider == "openai_compatible",
            "An explicitly configured real provider is required")
    if not fixture:
        require((settings.model_base_url or "").rstrip("/") == "https://api.openai.com/v1"
                and (settings.d2_base_url or settings.model_base_url or "").rstrip("/") == "https://api.openai.com/v1",
                "Only the configured official OpenAI endpoint is accepted")
        require(bool(settings.model_api_key) and bool(settings.d2_api_key or settings.model_api_key),
                "Both generation and detector authentication must be configured")
    accounting = Accounting(settings.pricing_path)
    prices = {price.model_id: price for price in accounting.book.models} if accounting.book else {}
    for model in {settings.model_id, settings.d2_model_id or settings.model_id}:
        price = prices.get(model)
        require(price is not None and price.verified and bool(price.source_url) and bool(price.effective_date)
                and price.input_usd_per_million is not None and price.output_usd_per_million is not None,
                "A verified price for every configured model is required")
    return settings


def _public(value, settings: Settings, *, allow_canary: bool = False):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    require(allow_canary or not CANARY_PATTERN.search(encoded), "Public diagnostic artifacts contain an unmasked canary")
    require(not any(secret and secret in encoded for secret in (settings.model_api_key, settings.d2_api_key)),
            "Public diagnostic artifacts contain a credential")
    return value


def _spec(email: Path) -> BatchSpec:
    return BatchSpec.model_validate({
        "sources": [
            {"source_id": "rag-dev", "data_dir": str(ROOT / "data/week2"), "split": "dev", "case_ids": list(RAG_CASES)},
            {"source_id": "email-dev", "data_dir": str(email), "split": "dev", "case_ids": list(EMAIL_CASES)},
        ],
        "conditions": [{"condition_id": "D2-diagnostic", "defense_mode": "D2",
                        "defense_position": "input_retrieval", "execution_kind": "detector_only",
                        "comparisons": ["detector"]}],
        "repeats": 1, "random_seed": 20261020,
        "budget": {"max_calls": 60, "max_reserved_tokens": 2_000_000, "max_seconds": 600,
                   "max_usd": 0.25, "unknown_price_policy": "stop", "per_call_input_token_ceiling": 16384},
        "statistics": {"bootstrap_samples": 100},
        "evaluation_policy_file": "configs/week3-evaluation-policy.json",
    })


def _summarize(output: Path, runner: BatchRunner, state) -> dict:
    settings = runner.settings
    schema = json.loads((ROOT / "contracts/execution-v0.3.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    traces, rows, calls = [], [], []
    http_statuses = Counter()
    calls_by_attempt = {}
    for call in state.calls:
        calls_by_attempt.setdefault(call["attempt_id"], []).append(call)
    accounting = Accounting(runner.store.folder(state.batch_id) / "pricing.snapshot")
    expected_targets = sum(1 + len(bundle.cases[cid].source_document_ids)
                           for source in state.spec.sources
                           for bundle in [load_bundle(runner.store.folder(state.batch_id) / "inputs" / source.source_id)]
                           for cid in source.case_ids)
    for entry in state.plan:
        require(entry["split"] == "dev", "Holdout is excluded from this diagnostic")
        for attempt in entry["attempts"]:
            ledger = calls_by_attempt.get(attempt["attempt_id"], [])
            if attempt["status"] == "cancelled_before_transport":
                require(not ledger, "A cancelled-before-transport attempt contains reserved model calls")
                continue
            try:
                trace = runner.traces.get(attempt["run_id"])
            except ArtifactNotFound:
                require(entry["status"] in ("pending", "uncertain"), "A settled attempt is missing its saved trace")
                continue
            payload = trace.model_dump(mode="json")
            validator.validate(payload)
            _public(payload, settings)
            raw = runner.traces.get_raw(trace.run_id)
            _public(raw, settings, allow_canary=True)
            require(raw.get("run_id") == trace.run_id and raw.get("request") == trace.request.model_dump(mode="json"),
                    "Saved trace and private request differ")
            require(trace.manifest.execution_kind == "detector_only" and trace.metrics.generation_call_count == 0,
                    "Diagnostic unexpectedly generated a final answer")
            require(trace.manifest.execution_scope == state.execution_settings["execution_scope"], "Saved trace scope differs")
            require(not trace.prompt_assembly and not any(item.included_in_prompt for item in trace.retrieval),
                    "Diagnostic unexpectedly assembled a generation prompt")
            require(trace.evaluation.attack_success == "not_evaluated" and trace.evaluation.normal_task_success == "not_evaluated",
                    "Diagnostic invented a final-output evaluation")
            raw_calls = raw.get("model_calls", [])
            require(len(raw_calls) == len(ledger) == len(trace.model_calls) == trace.metrics.model_call_count,
                    "Private, public and reserved model call counts differ")
            for call, reservation, displayed in zip(raw_calls, ledger, trace.model_calls):
                require(call["purpose"] == "detection", "Diagnostic contains a generation call")
                require(all(call.get(key) == getattr(displayed, key) for key in
                            ("model_id", "purpose", "input_tokens", "output_tokens", "estimated_cost_usd")),
                        "Private and public model usage differ")
                require(all(call.get(key) == reservation.get(key) for key in
                            ("model_id", "purpose", "input_tokens", "output_tokens")),
                        "Private and reserved model usage differ")
                require(call.get("estimated_cost_usd") == reservation["known_cost_usd"], "Reserved cost differs")
                priced = ModelCall.model_validate(call)
                accounting.price(priced)
                require(priced.estimated_cost_usd == call.get("estimated_cost_usd"), "Frozen price calculation differs")
                if trace.status == "completed":
                    require(call.get("usage_source") == "observed" and call.get("estimated_cost_usd") is not None
                            and isinstance(call.get("http_status"), int) and 200 <= call["http_status"] < 300,
                            "Completed diagnostic lacks confirmed provider usage")
                http_statuses[str(call.get("http_status"))] += 1
                inspected = json.loads(call["messages"][1]["content"])
                require(set(inspected) == {"stage", "text"}, "Evaluation metadata reached the detector")
            if all(call.get("estimated_cost_usd") is not None for call in raw_calls):
                require(math.isclose(sum(call["estimated_cost_usd"] for call in raw_calls),
                                     trace.metrics.known_cost_usd, abs_tol=1e-12), "Saved trace total cost differs")
            calls.extend(raw_calls)
            traces.append(trace)
            targets = [{"stage": event.stage, "target_ref": event.target_ref, "score": event.score,
                        "decision": event.decision, "review_needed": event.review_needed,
                        "consistency_issue": event.consistency_issue,
                        "inspection_error": event.error is not None}
                       for event in trace.defense_events if event.defense_id == "D2"]
            rows.append({"run_id": trace.run_id, "source_id": entry["source_id"], "case_id": entry["case_id"],
                         "status": trace.status, "model_call_count": trace.metrics.model_call_count,
                         "targets": targets})
    require(len(calls) == sum(trace.metrics.model_call_count for trace in traces), "Saved call count mismatch")
    settled = [call for call in state.calls if call["status"] == "settled"]
    if state.status != "uncertain":
        require(len(calls) == len(state.calls), "Saved calls and budget reservations differ")
    covered = sum(len(row["targets"]) for row in rows)
    if state.status == "completed":
        require(len(traces) == 18 and covered == expected_targets == 36, "Completed diagnostic lacks its target coverage")
    plan = gold_plan(ROOT / "data/week2", settings.runs_dir) if traces else {
        "plan_version": "week2-target-gold-plan-v0.1", "applied": False,
        "includes_single_review": False, "updates": [], "excluded": []}
    require(not plan["includes_single_review"] and not plan["applied"], "Draft gold must remain unapplied")
    scope = state.execution_settings["execution_scope"]
    budget = runner.store.summary(state)["budget"]
    usage_complete = (len(calls) == len(state.calls) and
                      all(call["input_tokens"] is not None and call["output_tokens"] is not None for call in state.calls))
    cost_complete = len(calls) == len(state.calls) and budget["total_cost_usd"] is not None
    verified = state.status == "completed" and len(settled) == len(calls) and usage_complete and cost_complete
    result = {
        "diagnostic_version": VERSION, "status": "passed" if verified else "incomplete",
        "execution_scope": scope, "real_model_verified": scope == "real" and verified,
        "batch_id": state.batch_id, "batch_status": state.status, "reason": state.reason,
        "planned_runs": len(state.plan), "saved_runs": len(traces), "model_call_count": len(state.calls),
        "reconciled_calls": len(calls), "http_status_counts": dict(http_statuses),
        "generation_call_count": 0, "expected_target_count": expected_targets, "inspected_target_count": covered,
        "uninspected_target_count": max(0, expected_targets - covered),
        "usage_complete": usage_complete, "cost_complete": cost_complete,
        "known_cost_usd": budget["known_cost_usd"],
        "total_cost_usd": budget["total_cost_usd"] if cost_complete else None,
        "budget": budget,
        "team_agreement": "pending", "gold_review_scope": "team_reviewed_only",
        "gold_updates_planned": len(plan["updates"]), "gold_updates_applied": 0,
        "gold_exclusions": dict(Counter(row["reason"] for row in plan["excluded"])),
        "holdout_executed": False, "final_output_performance_evaluated": False,
        "detector_report": detector_report(traces).model_dump(mode="json"), "runs": rows,
        "public_canary_leak": False, "public_credential_leak": False,
    }
    for name, value in (("gold-plan.json", plan), ("batch-summary.real.json", runner.store.summary(state)),
                        ("verification-report.json", result)):
        atomic_json(output / name, _public(value, settings))
    return result


def verify(output: Path, *, settings: Settings | None = None, max_items: int | None = None,
           allow_fixture: bool = False) -> dict:
    """Run/resume a paid dev diagnostic. Tests must explicitly enable fixture settings."""
    require(max_items is None or type(max_items) is int and max_items > 0, "max_items must be positive")
    output = output.resolve()
    settings = _settings(output, settings, allow_fixture)
    with locked_output(output, "checkpoint.json"), \
         record_verification_failure(output, VERSION, marker="checkpoint.json", version_key="diagnostic_version"):
        return _verify(output, settings, max_items)


def _verify(output, settings, max_items):
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / "checkpoint.json"
    runner = BatchRunner(settings)
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        require(saved.get("diagnostic_version") == VERSION, "Checkpoint belongs to a different diagnostic")
        state = runner.store.get(saved["batch_id"])
        expected_spec = _spec(output / "email-data")
        require(state.spec == expected_spec, "Diagnostic design differs from its saved checkpoint")
    else:
        require(not (output / "runs").exists(), "Existing uncheckpointed run artifacts require a new output directory")
        email = prepare(ROOT / "data/week2", output / "email-data", "email")
        state = runner.create(_spec(email))
        atomic_json(checkpoint, _public({"diagnostic_version": VERSION, "batch_id": state.batch_id}, settings))
    if state.status != "completed":
        state = runner.execute(state.batch_id, max_items=max_items, stop_on_error=True)
        atomic_json(checkpoint, _public({"diagnostic_version": VERSION, "batch_id": state.batch_id,
                                        "batch_status": state.status, "saved_attempts": sum(len(e["attempts"]) for e in state.plan)}, settings))
    # Revalidate immutable snapshots even if a completed checkpoint avoids execute().
    runner._verify_inputs(state, executing=False)
    require(state.execution_settings == public_settings(settings),
            "Execution settings changed; use a new output directory")
    return _summarize(output, runner, state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-items", type=int)
    args = parser.parse_args(argv)
    try:
        result = verify(args.output, max_items=args.max_items)
    except Exception:
        # Validation/provider payloads and filesystem paths may contain private data.
        print(json.dumps({"status": "error", "message": "실제 탐지 검증 실패; 로컬 설정·예산·체크포인트를 확인하세요."}, ensure_ascii=False))
        return 1
    print(json.dumps({key: value for key, value in result.items() if key not in ("runs", "detector_report")},
                     ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
