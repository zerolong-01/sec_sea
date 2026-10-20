"""Bounded, resumable six-condition dev audit with private raw evidence.

Each dataset has its own immutable BatchRunner and evaluation rules. Sources
may execute concurrently; a failure stops further item admissions while other
in-flight items settle. No implicit retry or human-review approval is performed.
"""
from __future__ import annotations

import argparse
import json
import math
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from backend.app.accounting import Accounting
from backend.app.batch import (BatchRunner, batch_lock, digest, file_hash,
                               implementation_hash, public_settings)
from backend.app.batch_analysis import expected_manifest
from backend.app.batch_models import BatchSpec
from backend.app.models import ModelCall
from backend.app.providers import OpenAICompatibleProvider
from backend.app.storage import atomic_json
from scripts.attack_success_review import _mask, classify, extract_targets
from scripts.data_contract import ROOT, load_bundle
from scripts.prepare_attack_audit import prepare, validate
from scripts.verify_real_api import MODEL_ID, VerificationError, _settings, assert_safe, require


VERSION = "full-dev-attack-audit-v0.1"
MAX_EXECUTION_USD = 4.70


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _implementation():
    return digest({"backend": implementation_hash(ROOT), "scripts": {
        name: file_hash(ROOT / "scripts" / name) for name in
        ("run_attack_audit.py", "prepare_attack_audit.py", "attack_success_review.py", "verify_real_api.py")}})


def _generation_records(path, *, allow_fixture):
    saved = _read(path)
    require(isinstance(saved, dict) and saved.get("status") == "completed", "GENERATION_NOT_COMPLETED")
    records = saved.get("records")
    require(isinstance(records, list) and bool(records), "GENERATION_RECORDS_REQUIRED")
    if not allow_fixture:
        require(saved.get("version") == "generated-attack-variants-v0.1" and len(records) == 25,
                "COMPLETE_25_DEV_VARIANTS_REQUIRED")
        require(saved.get("generation_model") == MODEL_ID, "GENERATION_MODEL_MISMATCH")
        require(len(set(saved.get("completed_parent_ids", []))) == 25, "GENERATION_PARENT_INVENTORY_MISMATCH")
    return records


def _spec(source, selected_count):
    count = len(source["case_ids"])
    planned = count * 6
    # Allocate microdollars downwards; independently enforced caps never sum
    # above $4.70, even when several sources have an in-flight call.
    cap = math.floor(MAX_EXECUTION_USD * count / selected_count * 1_000_000) / 1_000_000
    return BatchSpec.model_validate({"sources": [source], "repeats": 1, "random_seed": 2026,
        "budget": {"max_calls": planned * 8, "max_reserved_tokens": planned * 8 * (32768 + 512),
            "max_seconds": 14400, "max_usd": cap, "unknown_price_policy": "stop",
            "per_call_input_token_ceiling": 32768},
        "statistics": {"status": "draft", "bootstrap_samples": 100},
        "common_policy_file": "configs/week3-common-policy.txt",
        "evaluation_policy_file": "configs/week3-evaluation-policy.json",
        "min_call_interval_seconds": .1})


def _state(output, source, runner, spec, *, report_only):
    checkpoint = output / "checkpoint.json"
    manifests = sorted((runner.settings.runs_dir / "batches").glob("batch-*/manifest.json"))
    if checkpoint.exists():
        saved = _read(checkpoint)
        require(saved.get("version") == VERSION and saved.get("source_id") == source["source_id"],
                "SOURCE_CHECKPOINT_MISMATCH")
        state = runner.store.get(saved["batch_id"])
        require(len(manifests) == 1 and manifests[0].parent.name == state.batch_id, "SOURCE_BATCH_INVENTORY_MISMATCH")
    elif manifests:
        require(len(manifests) == 1, "AMBIGUOUS_SOURCE_BATCH")
        state = runner.store.get(manifests[0].parent.name)
    else:
        require(not report_only, "SOURCE_BATCH_NOT_CREATED")
        state = runner.create(spec)
    require(state.spec == spec, "SOURCE_SPEC_CHANGED")
    require(state.execution_settings == public_settings(runner.settings), "EXECUTION_SETTINGS_CHANGED")
    runner._verify_inputs(state, executing=not report_only)
    require({entry["split"] for entry in state.plan} == {"dev"} and state.spec.repeats == 1,
            "AUDIT_MUST_BE_DEV_ONE_REPEAT")
    if not report_only:
        # Recover a crash before any new admission. A reserved/paid attempt
        # becomes uncertain and is never replayed automatically.
        with batch_lock(runner.store.folder(state.batch_id)):
            state = runner.store.get(state.batch_id)
            recovered = False
            for entry in state.plan:
                if entry["status"] == "running":
                    runner._recover(state, entry)
                    recovered = True
            if recovered:
                state.status = "uncertain" if any(e["status"] == "uncertain" for e in state.plan) else "paused"
                state.reason = "recovered_interrupted_attempt"
                runner.store.save(state)
        atomic_json(output / "spec.json", spec.model_dump(mode="json"))
        atomic_json(checkpoint, {"version": VERSION, "source_id": source["source_id"], "batch_id": state.batch_id})
    return state


def _failed(state):
    return any(e["status"] in ("failed", "uncertain", "running") for e in state.plan) or any(
        call["status"] != "settled" for call in state.calls)


class _Admissions:
    def __init__(self, max_items):
        self.max_items, self.count = max_items, 0
        self.stop = threading.Event()
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            if self.stop.is_set() or self.max_items is not None and self.count >= self.max_items:
                return False
            self.count += 1
            return True


def _execute_sources(contexts, max_items, max_workers):
    admission = _Admissions(max_items)
    if any(_failed(state) for _, _, state in contexts):
        return []
    errors = []

    def worker(source_id, runner, state):
        processed = 0
        try:
            while any(e["status"] == "pending" for e in state.plan):
                if _failed(state):
                    admission.stop.set()
                    break
                if not admission.take():
                    break
                before = sum(len(e["attempts"]) for e in state.plan)
                state = runner.execute(state.batch_id, max_items=1)
                after = sum(len(e["attempts"]) for e in state.plan)
                processed += after - before
                if processed and processed % 10 == 0:
                    print(json.dumps({"source_id": source_id, "processed_this_invocation": processed,
                                      "batch_status": state.status}), flush=True)
                if _failed(state) or after == before or state.reason not in (None, "operator_item_limit"):
                    admission.stop.set()
                    break
        except BaseException:
            admission.stop.set()
            raise

    pool = ThreadPoolExecutor(max_workers=min(max_workers, len(contexts)))
    futures = {pool.submit(worker, *context): context[0] for context in contexts}
    try:
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                admission.stop.set()
                errors.append({"source_id": futures[future], "error_type": type(exc).__name__})
    except KeyboardInterrupt:
        admission.stop.set()
    finally:
        # The stop flag blocks new admissions; already admitted source items
        # finish and persist. This is not an atomic global transport barrier.
        pool.shutdown(wait=True)
    return errors


def _inspect_source(source_id, runner, state, cases, credentials):
    runner._verify_inputs(state, executing=False)
    folder = runner.store.folder(state.batch_id)
    snapshot = state.source_snapshots[0]
    bundle = load_bundle(folder / "inputs" / source_id)
    rules = {r["case_id"]: r for r in _read(folder / "evaluation_rules.snapshot")["rules"]}
    accounting = Accounting(folder / "pricing.snapshot")
    conditions = {c.condition_id: c for c in state.spec.conditions}
    manifests = {key: expected_manifest(value, state.execution_settings, folder) for key, value in conditions.items()}
    validator = Draft202012Validator(_read(ROOT / "contracts/execution-v0.3.schema.json"))
    observations, attempt_ids, reconciled = [], set(), set()
    http_counts = Counter()
    for entry in state.plan:
        case = cases[entry["case_id"]]
        canonical = {key: value for key, value in case.items() if not key.startswith("audit_")}
        require(canonical == bundle.cases[entry["case_id"]].model_dump(mode="json"), "REVIEW_CASE_SNAPSHOT_MISMATCH")
        require(case.get("audit_original_split") == "dev" and not case.get("audit_consumed_holdout"),
                "HOLDOUT_EXECUTION_FORBIDDEN")
        docs = [bundle.documents[key].model_dump(mode="json") for key in case["source_document_ids"]]
        condition = conditions[entry["condition_id"]]
        latest_trace, latest_raw = None, None
        for attempt in entry["attempts"]:
            attempt_id = attempt["attempt_id"]
            attempt_ids.add(attempt_id)
            ledger = [call for call in state.calls if call["attempt_id"] == attempt_id]
            if attempt["status"] == "cancelled_before_transport":
                require(not ledger, "CANCELLED_ATTEMPT_HAS_LEDGER_CALLS")
                continue
            if attempt["status"] in ("running", "uncertain", "pending"):
                continue
            trace = runner.traces.get(attempt["run_id"])
            public = trace.model_dump(mode="json")
            require(not list(validator.iter_errors(public)), "TRACE_SCHEMA_MISMATCH")
            actual, manifest = public["request"], public["manifest"]
            expected = {"case_id": entry["case_id"], "scenario": entry["scenario"],
                "defense_mode": condition.defense_mode, "defense_position": condition.defense_position,
                "execution_kind": condition.execution_kind, "dataset_version": snapshot["dataset_version"],
                "corpus_version": snapshot["corpus_version"], "d2_threshold": condition.d2_threshold}
            require(all(actual[k] == v for k, v in expected.items()) and
                    all(manifest[k] == v for k, v in manifests[condition.condition_id].items()),
                    "TRACE_PLAN_CONFIGURATION_MISMATCH")
            raw = runner.traces.get_raw(trace.run_id)
            require(raw.get("run_id") == trace.run_id and raw.get("request") == actual, "RAW_TRACE_MISMATCH")
            assert_safe(raw, credentials, allow_canary=True)
            calls = raw.get("model_calls", [])
            require(len(calls) == len(ledger) == trace.metrics.model_call_count == len(trace.model_calls),
                    "CALL_COUNT_MISMATCH")
            for call, saved, public_call in zip(calls, ledger, trace.model_calls):
                require(all(call.get(k) == saved.get(k) == getattr(public_call, k)
                            for k in ("model_id", "purpose", "input_tokens", "output_tokens")), "LEDGER_USAGE_MISMATCH")
                require(call.get("estimated_cost_usd") == saved["known_cost_usd"] == public_call.estimated_cost_usd,
                        "LEDGER_COST_MISMATCH")
                priced = ModelCall.model_validate(call)
                accounting.price(priced)
                require(priced.estimated_cost_usd == call.get("estimated_cost_usd"), "REPRICED_COST_MISMATCH")
                if trace.status in ("completed", "blocked"):
                    require(call.get("usage_source") == "observed" and isinstance(call.get("http_status"), int)
                            and 200 <= call["http_status"] < 300 and call.get("estimated_cost_usd") is not None,
                            "OBSERVED_SUCCESSFUL_CALL_REQUIRED")
                http_counts[str(call.get("http_status"))] += 1
            if calls and all(c.get("estimated_cost_usd") is not None for c in calls):
                require(math.isclose(sum(c["estimated_cost_usd"] for c in calls), trace.metrics.known_cost_usd,
                                     abs_tol=1e-12), "TRACE_COST_MISMATCH")
            generation = [c for c in calls if c["purpose"] == "generation"]
            if trace.status == "completed":
                require(len(generation) == 1 and isinstance(raw.get("provider_output"), str)
                        and generation[0].get("response_text") == raw["provider_output"], "RAW_GENERATION_OUTPUT_MISMATCH")
            if trace.status == "blocked":
                require(not generation and raw.get("provider_output") is None, "BLOCKED_GENERATION_OUTPUT_PRESENT")
            reconciled.add(attempt_id)
            latest_trace, latest_raw = public, raw
        review_trace = latest_trace or {"status": entry["status"], "request": {"defense_mode": condition.defense_mode}}
        reviewed = classify(case, docs, review_trace, latest_raw or {}, rules.get(entry["case_id"]))
        target_values = extract_targets(case, docs, rules.get(entry["case_id"]))
        observation = {"source_id": source_id, "case_id": entry["case_id"],
            "parent_case_id": case["audit_parent_case_id"], "label": case["label"],
            "condition_id": entry["condition_id"], "defense_mode": str(condition.defense_mode),
            "defense_position": str(condition.defense_position), "repeat": entry["repeat"],
            "entry_id": entry["entry_id"], "execution_status": entry["status"],
            "run_id": latest_trace["run_id"] if latest_trace else None,
            "raw_sha256": file_hash(runner.settings.runs_dir / (latest_trace["run_id"] + ".raw.json")) if latest_trace else None,
            "criterion": {"criterion_type": case["success_criterion"]["criterion_type"],
                "description": _mask(case["success_criterion"]["description"], target_values)},
            "human_review": "pending", **reviewed}
        observations.append(observation)
    require(all(c["attempt_id"] in attempt_ids for c in state.calls), "ORPHAN_LEDGER_CALL")
    untraced = [c for c in state.calls if c["attempt_id"] not in reconciled]
    summary = runner.store.summary(state)
    source_report = {"source_id": source_id, "batch_id": state.batch_id, "status": state.status,
        "reason": state.reason, "planned_runs": len(state.plan), "status_counts": summary["status_counts"],
        "execution_scope": state.execution_settings["execution_scope"], "budget": summary["budget"],
        "code_commit": state.code_commit, "implementation_sha256": state.configuration_hashes["implementation"],
        "reconciled_calls": len(state.calls) - len(untraced), "unreconciled_calls": len(untraced),
        "http_status_counts": dict(http_counts), "pricing_usage_ledger_consistent": True}
    return source_report, observations


def _report(output, contexts, prepared, configured, ownership, errors):
    credentials = tuple(s for s in (configured.model_api_key, configured.d2_api_key) if s)
    cases = _read(prepared["private_audit_cases_path"])
    sources, observations = [], []
    for source_id, runner, old_state in contexts:
        state = runner.store.get(old_state.batch_id)
        source_report, measured = _inspect_source(source_id, runner, state, cases[source_id], credentials)
        sources.append(source_report)
        observations.extend(measured)
    states = Counter(row["execution_status"] for row in observations)
    failed = bool(errors or states["failed"] or states["uncertain"] or states["running"] or
                  any(s["budget"]["unresolved_calls"] for s in sources))
    complete = all(s["status"] == "completed" for s in sources)
    known_cost = sum(s["budget"]["known_cost_usd"] for s in sources)
    committed = [s["budget"]["committed_usd"] for s in sources]
    require(sum(s["budget"]["known_cost_usd"] for s in sources) <= MAX_EXECUTION_USD + 1e-9,
            "GLOBAL_EXECUTION_USD_BOUND_EXCEEDED")
    successes = [row for row in observations if row["verdict"] == "success"]
    result = {"version": VERSION, "status": "failed" if failed else "passed" if complete else "paused",
        "scope": "all_existing_unique_dev_cases_and_generated_dev_attack_variants",
        "execution_scope": public_settings(configured)["execution_scope"],
        "planned_runs": sum(s["planned_runs"] for s in sources), "repeats": 1,
        "unique_conditions": 6, "inventory": prepared["inventory"], "status_counts": dict(states),
        "budget": {"max_execution_usd": MAX_EXECUTION_USD, "known_execution_cost_usd": known_cost,
            "committed_execution_usd": sum(committed) if all(v is not None for v in committed) else None,
            "admitted_calls": sum(s["budget"]["admitted_calls"] for s in sources),
            "unresolved_calls": sum(s["budget"]["unresolved_calls"] for s in sources),
            "generation_cost_included": False, "note": "Variant generation is accounted for separately."},
        "sources": sources, "classification_counts": dict(Counter(row["verdict"] for row in observations)),
        "attack_classification_counts": dict(Counter(row["verdict"] for row in observations if row["label"] == "attack")),
        "success_count": len(successes), "success_case_count": len({(r["source_id"], r["case_id"]) for r in successes}),
        "observations": observations, "successes": successes, "errors": errors,
        "raw_generation_usage_price_ledger_verified": True, "refresh_model_calls": 0,
        "generation_file_sha256": ownership["generation_file_sha256"],
        "frozen_orchestrator_sha256": ownership["implementation_sha256"],
        "review_orchestrator_sha256": _implementation(), "preparation_sha256": digest(prepared),
        "team_review": "pending", "final_recommendation": "deferred",
        "holdout_executed": False, "inference": "Exploratory n=1 per condition; exact evidence and context-review candidates, not final ASR/FPR.",
        "parallel_stop_semantics": "Stop further item admissions on failure; other already admitted items settle."}
    assert_safe(result, credentials)
    atomic_json(output / "audit-report.json", result)
    atomic_json(output / "successes.json", {"version": VERSION, "status": result["status"],
        "success_count": len(successes), "successes": successes, "team_review": "pending"})
    return result


def verify(output: Path, generation_file: Path, *, settings=None, allow_fixture=False,
           max_items=None, report_only=False, max_workers=3):
    require(max_items is None or type(max_items) is int and max_items > 0, "MAX_ITEMS_MUST_BE_POSITIVE")
    require(type(max_workers) is int and 1 <= max_workers <= 3, "MAX_WORKERS_MUST_BE_1_TO_3")
    output, generation_file = Path(output).resolve(), Path(generation_file).resolve()
    configured = _settings(output, settings, allow_fixture)
    records = _generation_records(generation_file, allow_fixture=allow_fixture)
    marker = output / "audit.json"
    if not marker.exists():
        require(not report_only, "AUDIT_NOT_CREATED")
        require(not output.exists() or not any(output.iterdir()), "OUTPUT_DIRECTORY_NOT_OWNED")
    output.mkdir(parents=True, exist_ok=True)
    with batch_lock(output):
        if not marker.exists():
            require({p.name for p in output.iterdir()} <= {"writer.lock"}, "OUTPUT_DIRECTORY_NOT_OWNED")
            atomic_json(marker, {"version": VERSION, "implementation_sha256": _implementation(),
                "generation_file_sha256": file_hash(generation_file)})
        ownership = _read(marker)
        require(ownership.get("version") == VERSION, "AUDIT_VERSION_CHANGED")
        require(ownership.get("generation_file_sha256") == file_hash(generation_file), "GENERATION_FILE_CHANGED")
        require(report_only or ownership.get("implementation_sha256") == _implementation(), "AUDIT_IMPLEMENTATION_CHANGED")
        preparation_path = output / "prepared"
        if preparation_path.exists():
            prepared = validate(preparation_path)
        else:
            require(not report_only, "AUDIT_PREPARATION_MISSING")
            prepared = prepare(preparation_path, records, include_holdout=False)
        require(prepared["ai_records_sha256"] == digest(records), "PREPARED_AI_RECORDS_CHANGED")
        require(prepared["inventory"]["holdout_selected"] == 0 and prepared["inventory"]["holdout_preserved"],
                "HOLDOUT_EXECUTION_FORBIDDEN")
        contexts = []
        for source in prepared["sources"]:
            source_output = output / "executions" / source["source_id"]
            source_settings = replace(configured, data_dir=Path(source["data_dir"]),
                runs_dir=source_output / "runs", evaluation_rules_path=Path(prepared["source_rules"][source["source_id"]]))
            runner = BatchRunner(source_settings)
            state = _state(source_output, source, runner, _spec(source, prepared["inventory"]["selected_cases"]), report_only=report_only)
            contexts.append((source["source_id"], runner, state))
        errors = [] if report_only else _execute_sources(contexts, max_items, max_workers)
        # A report refresh has no route to paid transport. Turn accidental
        # provider calls into an immediate error rather than a hidden refresh.
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=VerificationError("REPORT_CALLED_MODEL")) as calls:
            result = _report(output, contexts, prepared, configured, ownership, errors)
            require(calls.call_count == 0, "REPORT_CALLED_MODEL")
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generation-file", type=Path, required=True)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--max-items", type=int, help="이번 호출 전체 source를 합친 최대 실행 항목 수")
    args = parser.parse_args(argv)
    try:
        result = verify(args.output, args.generation_file, max_items=args.max_items, report_only=args.report_only)
        public = {key: value for key, value in result.items() if key not in ("observations", "successes")}
    except Exception as exc:
        public = {"status": "failed", "error": str(exc) if isinstance(exc, VerificationError) else type(exc).__name__}
    print(json.dumps(public, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if public["status"] == "passed" else 2 if public["status"] == "paused" else 1


if __name__ == "__main__":
    raise SystemExit(main())
