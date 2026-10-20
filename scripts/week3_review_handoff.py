"""Prepare blinded local review packets and consensus API plans without model calls."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import random
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from backend.app.batch import BatchStore, verify_frozen_artifacts
from backend.app.batch_models import BatchReview, RecommendationPolicy
from backend.app.evaluation import RuleSet
from backend.app.models import DetectorGoldUpdate, EvaluationUpdate
from backend.app.repository import RunTraceStore
from backend.app.storage import atomic_json
from scripts.data_contract import CANARY_PATTERN, ROOT, load_bundle, require

VERSION = "week3-independent-review-handoff-v0.1"


def masked_reason(value, targets):
    """Mask registered target literals/encodings in exported review rationales."""
    for target in sorted(set(targets), key=len, reverse=True):
        value = value.replace(base64.b64encode(target.encode()).decode(), "[MASKED_TARGET]")
        value = re.sub(re.escape(quote(target, safe="")), "[MASKED_TARGET]", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*".join(re.escape(char) for char in target), "[MASKED_TARGET]", value)
    return CANARY_PATTERN.sub("[MASKED_CANARY]", value)


def sha(value):
    if isinstance(value, Path):
        value = value.read_bytes()
    elif not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_rows(path, records):
    Path(path).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")


def review_inventory(project_root=ROOT):
    """Record review inputs without asserting that file existence means agreement."""
    root = Path(project_root)
    files = sorted({*root.glob("data/week2/*"), *root.glob("data/week3/*"),
                    *root.glob("configs/week3-*.json"),
                    root / "configs/week3-evaluation-policy.json", root / "configs/evaluation-week2.json",
                    root / "configs/evaluation-week3-protected.json"})
    files = [p for p in files if p.is_file()]
    gold = rows(root / "data/week2/target-gold.v0.1.jsonl")
    translations = read(root / "data/week2/language-variants.v0.1.json")["variants"]
    policy = read(root / "configs/week3-evaluation-policy.json")
    blockers = []
    if any(row["review_status"] != "team_reviewed" for row in gold):
        blockers.append("independent_target_gold_review_pending")
    if any(row["translation_status"] != "team_reviewed" for row in translations):
        blockers.append("independent_translation_review_pending")
    try:
        RecommendationPolicy.model_validate(policy)
        require(policy.get("status") == "frozen" and policy.get("final_recommendation_allowed") and
                len(set(policy.get("reviewed_by", []))) >= 2, "policy remains draft")
    except ValueError:
        blockers.append("service_policy_independent_review_pending")
    # Independent semantic/taxonomy review and representative A/B/C agreement
    # require signed review records; neither is inferred from static checks.
    blockers.extend(["semantic_rubric_taxonomy_review_pending", "representative_three_role_agreement_pending"])
    decision_path = root / "configs/week3-service-decision.v0.2.json"
    return {"files": [{"path": str(p.relative_to(root)).replace("\\", "/"), "sha256": sha(p)} for p in files],
            "gold_review_counts": dict(Counter(row["review_status"] for row in gold)),
            "translation_review_counts": dict(Counter(row["translation_status"] for row in translations)),
            "policy_version": policy.get("version"), "policy_status": policy.get("status"),
            "research_decision_status": read(decision_path).get("decision_status") if decision_path.exists() else "not_recorded",
            "freeze_ready": False, "blockers": blockers,
            "holdout_authorized": False}


def prepare(runs_dir, batch_id, output):
    runs_dir, output = Path(runs_dir).resolve(), Path(output).resolve()
    require(not output.exists(), "review output must be new; preserve previous reviewer evidence")
    store, traces = BatchStore(runs_dir), RunTraceStore(runs_dir)
    state = store.get(batch_id)
    verify_frozen_artifacts(store, state)
    require(all(source["split"] == "dev" for source in state.source_snapshots), "review handoff is dev-only")
    folder = store.folder(batch_id)
    bundles = {source["source_id"]: load_bundle(folder / "inputs" / source["source_id"])
               for source in state.source_snapshots}
    rules_path = folder / "evaluation_rules.snapshot"
    rules = RuleSet.model_validate_json(rules_path.read_text(encoding="utf-8")) if rules_path.exists() else None
    rules_by_id = {rule.case_id: rule for rule in rules.rules} if rules else {}
    packet_id = uuid.uuid4().hex
    tasks, mapping = [], {}
    statuses, source_hashes = Counter(), {}

    def add(kind, run_id, evidence, key):
        task_id = sha([packet_id, kind, run_id, key.get("stage"), key.get("target_ref")])[:24]
        evidence_hash = sha(evidence)
        tasks.append({"packet_id": packet_id, "task_id": task_id, "kind": kind,
                      "source_sha256": evidence_hash, "evidence": evidence})
        mapping[task_id] = {"kind": kind, "run_id": run_id, "source_sha256": evidence_hash, **key}

    for entry in state.plan:
        bundle = bundles[entry["source_id"]]
        case = bundle.cases[entry["case_id"]]
        docs = [bundle.documents[doc_id] for doc_id in case.source_document_ids]
        for attempt in entry["attempts"]:
            if attempt["status"] not in ("completed", "blocked", "failed"):
                continue
            trace = traces.get(attempt["run_id"])
            raw = traces.get_raw(trace.run_id)
            require(raw["run_id"] == trace.run_id and raw["request"] == trace.request.model_dump(mode="json"),
                    "review raw/public request mismatch")
            source_hashes[trace.run_id] = {"raw": sha(raw), "trace": sha(trace.model_dump(mode="json"))}
            if (attempt is entry["attempts"][-1] and trace.status in ("completed", "blocked")
                    and trace.manifest.execution_kind == "full_pipeline"):
                rule = rules_by_id.get(case.case_id)
                generation = [call for call in raw.get("model_calls", []) if call.get("purpose") == "generation"]
                require((trace.status == "blocked" and not generation and raw.get("provider_output") is None) or
                        (trace.status == "completed" and len(generation) == 1 and
                         isinstance(raw.get("provider_output"), str) and
                         generation[0].get("response_text") == raw["provider_output"]), "review raw output differs from generation")
                # These files intentionally stay private: semantic/encoded-value
                # review needs the unmasked output and reference documents.
                evidence = {"user_input": case.user_input,
                    "reference_documents": [{"title": doc.title, "content": doc.content} for doc in docs],
                    "provider_output": raw.get("provider_output"), "generation_blocked": trace.status == "blocked",
                    "criterion": {"goal_kind": entry["metadata"].get("goal_kind", "unspecified"),
                                  "attack_goal": case.attack_goal,
                                  "success_criterion": case.success_criterion.model_dump(mode="json"),
                                  "expected_normal_task": case.expected_normal_task,
                                  "required_terms": rule.required_terms if rule else [],
                                  "target_values": list(dict.fromkeys((rule.protected_values + ([rule.canary] if rule.canary else [])))) if rule else [],
                                  "normal_task_mode": rule.normal_task_mode if rule else "manual"}}
                add("final_output", trace.run_id, evidence, {"label": str(case.label)})
                statuses["attack_" + str(trace.evaluation.attack_success)] += 1
                statuses["normal_" + str(trace.evaluation.normal_task_success)] += 1
            for event in trace.defense_events:
                if event.defense_id != "D2":
                    continue
                inspected = set()
                for call in raw.get("model_calls", []):
                    if call.get("purpose") != "detection" or call.get("target_ref") != event.target_ref:
                        continue
                    try:
                        payload = json.loads(call["messages"][1]["content"])
                        if payload.get("stage") == event.stage and isinstance(payload.get("text"), str):
                            inspected.add(payload["text"])
                    except (KeyError, IndexError, ValueError, TypeError):
                        continue
                if not inspected:
                    statuses["detector_inspection_text_unavailable"] += 1
                    continue
                require(len(inspected) == 1, "actual detector inspected text is ambiguous")
                text = inspected.pop()
                document = bundle.documents.get(event.target_ref) if event.target_ref else None
                expected_text = case.user_input if event.stage == "input" else document.title + "\n" + document.content if document else None
                require(text == expected_text, "detector inspected text differs from frozen source")
                add("detector_target", trace.run_id, {"stage": str(event.stage), "text": text},
                    {"stage": str(event.stage), "target_ref": event.target_ref,
                     "inspected_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})

    require(bool(tasks), "no executed review evidence")
    output.mkdir(parents=True)
    private = output / "private"
    private.mkdir()
    atomic_json(private / "answer-key.json", {"tasks": mapping, "source_hashes": source_hashes,
        "redaction_values": sorted({value for rule in rules_by_id.values()
                                    for value in rule.protected_values + ([rule.canary] if rule.canary else [])})})
    for reviewer in (1, 2):
        ordered = list(tasks)
        random.Random(packet_id + str(reviewer)).shuffle(ordered)
        destination = private / f"reviewer-{reviewer}"
        destination.mkdir()
        write_rows(destination / "tasks.jsonl", ordered)
        write_rows(destination / "responses.template.jsonl", [
            {"packet_id": packet_id, "task_id": task["task_id"], "source_sha256": task["source_sha256"],
             "reviewer": None, "reviewed_at": None, "reason": "", "verdict": None} for task in ordered])
    manifest = {"version": VERSION, "packet_id": packet_id, "batch_id": batch_id,
        "runs_dir": str(runs_dir), "batch_manifest_sha256": sha(folder / "manifest.json"),
        "execution_scope": state.execution_settings["execution_scope"],
        "task_counts": dict(Counter(task["kind"] for task in tasks)), "existing_evaluation_counts": dict(statuses),
        "inventory": review_inventory(), "human_review": "pending", "applied": False,
        "blindness": "case/run/condition IDs, observed detector decisions and existing evaluations withheld from reviewer tasks",
        "private_files": {str(p.relative_to(output)).replace("\\", "/"): sha(p)
                          for p in private.rglob("*") if p.is_file()}}
    atomic_json(output / "manifest.json", manifest)
    atomic_json(output / "team-agreement.template.json", {"packet_id": packet_id, "status": "pending",
        "representative_task_ids": [], "roles": {role: {"reviewer": None, "reason": "", "agreed": None}
                                                    for role in ("A_experiment", "B_backend", "C_frontend")}})
    return {key: manifest[key] for key in ("version", "packet_id", "batch_id", "task_counts", "human_review", "applied")}


def plan(packet, response_files, *, policy_version, gold_version, output):
    packet, output = Path(packet).resolve(), Path(output).resolve()
    require(not output.exists(), "review plan output already exists")
    manifest = read(packet / "manifest.json")
    require(manifest["version"] == VERSION, "review packet version mismatch")
    key_path = packet / "private/answer-key.json"
    require(sha(key_path) == manifest["private_files"]["private/answer-key.json"], "review answer key changed")
    key = read(key_path)
    for reviewer in (1, 2):
        relative = f"private/reviewer-{reviewer}/tasks.jsonl"
        require(sha(packet / relative) == manifest["private_files"][relative], "reviewer task evidence changed")
        tasks = rows(packet / relative)
        require(len(tasks) == len(key["tasks"]) and {task["task_id"] for task in tasks} == set(key["tasks"]),
                "reviewer task inventory changed")
        for task in tasks:
            require(task["packet_id"] == manifest["packet_id"] and
                    sha(task["evidence"]) == task["source_sha256"] == key["tasks"][task["task_id"]]["source_sha256"],
                    "reviewer task evidence hash mismatch")
    store = BatchStore(Path(manifest["runs_dir"]))
    state = store.get(manifest["batch_id"])
    verify_frozen_artifacts(store, state)
    require(sha(store.folder(state.batch_id) / "manifest.json") == manifest["batch_manifest_sha256"], "batch changed after review packet")
    traces = RunTraceStore(Path(manifest["runs_dir"]))
    for run_id, expected in key["source_hashes"].items():
        require(sha(traces.get_raw(run_id)) == expected["raw"] and
                sha(traces.get(run_id).model_dump(mode="json")) == expected["trace"], "review source evidence changed")
    by_task = defaultdict(dict)
    for response_file in response_files:
        for response in rows(response_file):
            task_id, reviewer = response["task_id"], response.get("reviewer")
            require(task_id in key["tasks"] and response["packet_id"] == manifest["packet_id"], "unknown review task")
            require(response["source_sha256"] == key["tasks"][task_id]["source_sha256"], "review evidence hash mismatch")
            require(isinstance(reviewer, str) and bool(reviewer.strip()) and len(reviewer) <= 80, "reviewer identity required")
            reviewer = reviewer.strip().casefold()
            require(reviewer not in by_task[task_id], "duplicate reviewer for task")
            require(isinstance(response.get("reason"), str) and response["reason"].strip(), "review reason required")
            require(isinstance(response.get("reviewed_at"), str), "review timestamp required")
            stamp = datetime.fromisoformat(response["reviewed_at"].replace("Z", "+00:00"))
            require(stamp.utcoffset() is not None, "review timestamp requires timezone")
            require(isinstance(response.get("verdict"), dict), "review verdict required")
            by_task[task_id][reviewer] = response
    updates, pending, conflicts = [], [], []
    for task_id, task in key["tasks"].items():
        reviews = by_task.get(task_id, {})
        if len(reviews) < 2:
            pending.append(task_id)
            continue
        selected = list(reviews.values())
        if any(row["verdict"] != selected[0]["verdict"] for row in selected[1:]):
            conflicts.append({"task_id": task_id, "reviewers": sorted(reviews), "status": "adjudication_required"})
            continue
        reviewers = ";".join(sorted(reviews))
        reason = masked_reason(" | ".join(row["reason"] for row in selected), key.get("redaction_values", []))
        verdict = selected[0]["verdict"]
        context = {"task_id": task_id, "run_id": task["run_id"], "source_sha256": task["source_sha256"]}
        if task["kind"] == "detector_target":
            body = DetectorGoldUpdate(stage=task["stage"], target_ref=task["target_ref"],
                gold_label=verdict["gold_label"], gold_version=gold_version, reviewer=reviewers, reason=reason)
            updates.append(context | {"method": "PUT", "path": f"/api/v1/runs/{task['run_id']}/detector-gold",
                                      "inspected_text_sha256": task["inspected_text_sha256"], "body": body.model_dump(mode="json")})
        else:
            attack = verdict["attack_success"]
            require((task["label"] == "attack" and attack in ("success", "failure", "review_needed")) or
                    (task["label"] != "attack" and attack == "not_applicable"), "attack verdict conflicts with case eligibility")
            body = EvaluationUpdate(attack_success=attack, normal_task_success=verdict["normal_task_success"],
                evaluator_version="independent-consensus-v0.1", policy_version=policy_version, reviewer=reviewers, reason=reason)
            updates.append(context | {"method": "PUT", "path": f"/api/v1/runs/{task['run_id']}/evaluation", "body": body.model_dump(mode="json")})
            for field in ("target_exposed", "excessive_transformation"):
                require(verdict.get(field) is None or type(verdict[field]) is bool, "review flags must be boolean or null")
            if verdict.get("target_exposed") is not None or verdict.get("excessive_transformation") is not None:
                body = BatchReview(reviewer=reviewers, reason=reason, policy_version=policy_version,
                    target_exposed=verdict.get("target_exposed"), excessive_transformation=verdict.get("excessive_transformation"))
                updates.append(context | {"method": "PUT", "path": f"/api/v1/batches/{state.batch_id}/reviews/{task['run_id']}", "body": body.model_dump(mode="json")})
    result = {"version": VERSION, "packet_id": manifest["packet_id"], "batch_id": state.batch_id,
              "applied": False, "policy_version": policy_version, "gold_version": gold_version,
              "updates": updates, "pending_task_ids": pending, "conflicts": conflicts,
              "team_agreement": "pending", "holdout_authorized": False}
    atomic_json(output, result)
    return {"applied": False, "update_count": len(updates), "pending_tasks": len(pending), "conflicts": len(conflicts)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare")
    command.add_argument("--runs-dir", type=Path, required=True)
    command.add_argument("--batch-id", required=True)
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("plan")
    command.add_argument("--packet", type=Path, required=True)
    command.add_argument("--responses", type=Path, nargs="+", required=True)
    command.add_argument("--policy-version", required=True)
    command.add_argument("--gold-version", required=True)
    command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = (prepare(args.runs_dir, args.batch_id, args.output) if args.command == "prepare" else
                  plan(args.packet, args.responses, policy_version=args.policy_version, gold_version=args.gold_version, output=args.output))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (AssertionError, KeyError, ValueError, OSError, TypeError):
        print(json.dumps({"status": "failed", "message": "검토 자료의 경로·해시·검토자·시각·판정과 불일치를 확인하세요."}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
