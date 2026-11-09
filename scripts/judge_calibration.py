"""Prepare, run or replay the actual task judge against pinned published human gold."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from backend.app.accounting import Accounting, PriceBook
from backend.app.batch_budget import BatchCallBudget, budget_summary
from backend.app.batch_models import BatchBudget
from backend.app.config import Settings
from backend.app.judge_reference import ROOT, load_reference, select_pairs, summarize, units_for
from backend.app.models import ChatMessage, EvaluationResult, StrictModel
from backend.app.providers import OpenAICompatibleProvider, ProviderError
from backend.app.shared_variables import CallPurpose
from backend.app.storage import atomic_json, exclusive_file_lock, file_sha256
from backend.app.task_evaluation import POLICY, RUBRIC, SYSTEM, digest, unique_json_pairs
from backend.app.task_evaluation_models import JudgeVerdict, POLICY_VERSION, PROMPT_VERSION, RUBRIC_VERSION
from backend.app.task_judgment import judge_outcome, judge_parameters

VERSION = "published-human-judge-calibration-v0.1"


class CalibrationSpec(StrictModel):
    budget: BatchBudget
    min_call_interval_seconds: float = 0


class CalibrationState(StrictModel):
    version: Literal[VERSION] = VERSION
    identity: dict
    spec: CalibrationSpec
    created_at: str
    elapsed_seconds: float = 0
    calls: list[dict] = Field(default_factory=list)
    predictions: dict[str, dict] = Field(default_factory=dict)
    stopped_reason: str | None = None


def evidence_for(unit):
    return {"rubric": {**{k:v for k,v in RUBRIC.items() if k != "h007"},
            "expected_normal_task": unit["instruction"], "criteria": {},
            "required_format": None, "required_json_keys": []},
            "user_request": unit["instruction"], "label": "benign", "scenario": "rag_chat",
            "reference_documents": [], "saved_answer": unit["answer"], "protected_values": []}


def messages_for(unit):
    return [ChatMessage(role="system", content=SYSTEM),
            ChatMessage(role="user", content=json.dumps(evidence_for(unit), ensure_ascii=False))]


def prepare(output, reference=None, split="validation"):
    reference = reference or load_reference()
    units = units_for(select_pairs(reference, split))
    plan = {"version": VERSION, "reference_sha256": reference["reference_sha256"], "split": split,
        "units_sha256": digest(units), "unit_count": len(units), "pair_count": len(units)//2,
        "label_provenance": reference["manifest"]["label_provenance"],
        "source_commit": reference["manifest"]["source_commit"], "pairs": [
            {"pair_id": p["pair_id"], "family_id": p["family_id"], "subset": p["subset"],
             "source_index": p["source_index"], "source_row_sha256": p["source_row_sha256"]}
            for p in select_pairs(reference, split)]}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / "plan.json"
    if target.is_symlink():
        raise ValueError("Plan cannot be a symlink")
    if target.exists():
        if json.loads(target.read_text()) != plan:
            raise ValueError("Calibration plan changed; use a new directory")
    else:
        if any(output.iterdir()):
            raise ValueError("New plan requires an empty output directory")
        atomic_json(target, plan)
        labels = [{"unit_id": u["unit_id"], "pair_id": u["pair_id"], "expected": u["expected"],
            "source_row_sha256": u["source_row_sha256"], "source_label": u["source_label"], "side": u["side"],
            "label_source": "published_human_gold_adapter", "upstream_commit": plan["source_commit"]} for u in units]
        atomic_json(output / "human-reference-labels.json", labels)
    expected_labels = [{"unit_id": u["unit_id"], "pair_id": u["pair_id"], "expected": u["expected"],
        "source_row_sha256": u["source_row_sha256"], "source_label": u["source_label"], "side": u["side"],
        "label_source": "published_human_gold_adapter", "upstream_commit": plan["source_commit"]} for u in units]
    if json.loads((output / "human-reference-labels.json").read_text()) != expected_labels:
        raise ValueError("Frozen human labels changed")
    return reference, units, plan


def settings_for_run(*, use_generation_config=False):
    settings = Settings.from_environment()
    if use_generation_config:
        settings = replace(settings, judge_provider=settings.model_provider,
            judge_base_url=settings.model_base_url, judge_model_id=settings.model_id, judge_api_key=settings.model_api_key)
    if not settings.judge_base_url or not settings.judge_model_id:
        raise ValueError("Set independent JUDGE_* configuration or explicitly pass --use-generation-config")
    return settings


def run(output, settings, *, max_items=None, reference=None, max_usd=None):
    output = Path(output).resolve()
    reference, units, plan = prepare(output, reference)
    if max_items is not None and (type(max_items) is not int or max_items < 1):
        raise ValueError("max_items must be a positive integer")
    budget_values = dict(reference["policy"]["budget"])
    if max_usd is not None:
        if type(max_usd) not in (int, float) or not math.isfinite(max_usd) or not 0 < max_usd <= budget_values["max_usd"]:
            raise ValueError("USD override may only lower the frozen cap")
        budget_values["max_usd"] = max_usd
    # Validate endpoint before persisting any configuration. No credential goes in the identity.
    provider = OpenAICompatibleProvider(settings.judge_base_url, settings.judge_api_key,
        settings.judge_model_id, settings.judge_timeout_seconds)
    accounting = Accounting(settings.pricing_path)
    if settings.judge_provider == "fixture_http":
        accounting.book = PriceBook.model_validate({"version":"local-calibration-fixture-zero-charge",
            "models":[{"model_id":settings.judge_model_id,"input_usd_per_million":0,"output_usd_per_million":0,
                "source_url":"https://fixture.invalid/local-only","effective_date":"2026-11-09","verified":True}]})
    identity = {"plan_sha256": digest(plan), "model_id": settings.judge_model_id,
        "endpoint": settings.judge_base_url, "execution_scope": "fixture" if settings.judge_provider == "fixture_http" else "real",
        "parameters": judge_parameters(evidence_for(units[0]), settings.judge_max_tokens, settings.judge_response_format),
        "timeout_seconds": settings.judge_timeout_seconds, "prompt_version": PROMPT_VERSION,
        "system_prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
        "rubric_version": RUBRIC_VERSION, "policy_version": POLICY_VERSION,
        "decision_policy_snapshot": POLICY,
        "runner_sha256": file_sha256(Path(__file__)),
        "local_judgment_sha256": file_sha256(ROOT / "backend/app/task_judgment.py"),
        "pricing_snapshot": accounting.book.model_dump(mode="json") if accounting.book else None}
    with exclusive_file_lock(output / "writer.lock"):
        target = output / "ledger.json"
        if target.is_symlink():
            raise ValueError("Ledger cannot be a symlink")
        if target.exists():
            state = CalibrationState.model_validate_json(target.read_text())
            if state.identity != identity or state.spec.budget.model_dump(mode="json") != budget_values:
                raise ValueError("Calibration model/prompt/policy/price changed; create a new run")
        else:
            state = CalibrationState(identity=identity, spec=CalibrationSpec(budget=budget_values),
                created_at=datetime.now(timezone.utc).isoformat())
            atomic_json(target, state.model_dump(mode="json"))
        save = lambda state: atomic_json(target, state.model_dump(mode="json"))
        unit_ids = {u["unit_id"] for u in units}
        if not set(state.predictions) <= unit_ids or any(call["attempt_id"] not in unit_ids for call in state.calls):
            raise ValueError("Ledger contains foreign reference units")
        state.stopped_reason = None
        if any(call["status"] == "reserved" or call["attempt_id"] not in state.predictions for call in state.calls):
            state.stopped_reason = "UNRESOLVED_PAID_CALL_NO_AUTOMATIC_RETRY"
            save(state)
            return report(output, reference=reference)
        completed = 0
        for unit in units:
            uid = unit["unit_id"]
            if uid in state.predictions:
                continue
            if max_items is not None and completed >= max_items:
                state.stopped_reason = "max_items"
                break
            budget = BatchCallBudget(state, save, accounting, uid)
            provider.observer = budget
            call = None
            try:
                response = provider.complete(messages_for(unit), identity["parameters"], CallPurpose.EVALUATION)
                call = response.call
                verdict = JudgeVerdict.model_validate(json.loads(response.text, object_pairs_hook=unique_json_pairs))
                rule = EvaluationResult(attack_success="not_applicable", normal_task_success="not_evaluated",
                    evaluator_version="published-human-reference-adapter-v0.1", reason="semantic_task_requires_review")
                value, issues = judge_outcome(verdict, evidence_for(unit), rule, POLICY["minimum_confidence"])
                prediction = {"verdict": value, "issues": issues, "confidence": verdict.confidence,
                    "judge_response": verdict.model_dump(mode="json"), "error_code": None}
            except ProviderError as exc:
                call = exc.call
                if not any(c["attempt_id"] == uid for c in state.calls):
                    state.stopped_reason = exc.code
                    break
                prediction = {"verdict": "not_evaluated", "error_code": exc.code}
            except (ValueError, RecursionError):
                prediction = {"verdict": "not_evaluated", "error_code": "INVALID_JUDGE_RESPONSE"}
            prediction["prompt_sha256"] = digest([m.model_dump(mode="json") for m in messages_for(unit)])
            prediction["call"] = call.model_dump(mode="json") if call else None
            state.predictions[uid] = prediction
            completed += 1
            save(state)
            recent = [p.get("error_code") for p in list(state.predictions.values())[-3:]]
            repeated_schema_failure = len(recent) == 3 and all(code == "INVALID_JUDGE_RESPONSE" for code in recent)
            if repeated_schema_failure or prediction["error_code"] and prediction["error_code"] != "INVALID_JUDGE_RESPONSE":
                state.stopped_reason = prediction["error_code"]
                break
        save(state)
    return report(output, reference=reference)


def report(output, *, reference=None):
    output = Path(output).resolve()
    reference, units, plan = prepare(output, reference)
    target = output / "ledger.json"
    if target.is_symlink():
        raise ValueError("Ledger cannot be a symlink")
    state = CalibrationState.model_validate_json(target.read_text())
    if state.identity["plan_sha256"] != digest(plan):
        raise ValueError("Reference plan binding changed")
    unit_ids = {unit["unit_id"] for unit in units}
    if not set(state.predictions) <= unit_ids or any(call["attempt_id"] not in unit_ids for call in state.calls):
        raise ValueError("Ledger contains foreign reference units")
    result = summarize(reference, units, state.predictions)
    if state.identity["execution_scope"] != "real":
        result["external_reference_gate"]["passed"] = False
        result["external_reference_gate"]["reasons"].append("fixture_is_not_accuracy_evidence")
    result.update(version=VERSION, created_at=state.created_at, split=plan["split"], identity=state.identity,
        reference_sha256=reference["reference_sha256"], source_commit=plan["source_commit"],
        status="complete" if len(state.predictions) == len(units) else "incomplete",
        budget=budget_summary(state), stopped_reason=state.stopped_reason, read_model_calls=0,
        gate_basis=reference["policy"]["gate_basis"], research=reference["policy"]["research"])
    result["report_sha256"] = digest(result)
    atomic_json(output / "report.json", result)
    fields = ["unit_id", "pair_id", "family_id", "subset", "expected", "predicted", "error_code"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, ["report_sha256", *fields])
    writer.writeheader()
    for row in result["rows"]:
        writer.writerow({"report_sha256": result["report_sha256"], **row})
    (output / "report.csv").write_text(stream.getvalue(), encoding="utf-8", newline="")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "report", "check"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Explicitly admit paid judge calls within frozen limits")
    parser.add_argument("--use-generation-config", action="store_true", help="Explicitly use current MODEL_* as this run's judge; do not modify .env")
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--max-usd", type=float, help="Lower the frozen estimated USD cap for this run")
    args = parser.parse_args()
    try:
        if args.command == "prepare" or args.command == "run" and not args.execute:
            _, _, result = prepare(args.output)
        elif args.command in ("report", "check"):
            result = report(args.output)
        else:
            result = run(args.output, settings_for_run(use_generation_config=args.use_generation_config), max_items=args.max_items, max_usd=args.max_usd)
        print(json.dumps({k: result[k] for k in ("status", "pair_count", "unit_count", "overall", "external_reference_gate", "budget", "stopped_reason", "report_sha256") if k in result}, ensure_ascii=False))
        return 2 if args.command == "check" and not result["external_reference_gate"]["passed"] else 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status":"failed","error":type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
