"""Plan or register AI target gold against frozen, actually inspected dev text.

Only --apply writes annotations. Hash agreement is integrity evidence, not an
authenticated signature or an independent human review of the source labels.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field

from backend.app.batch import BatchStore, file_hash, verify_frozen_artifacts
from backend.app.config import Settings
from backend.app.models import DetectorGoldUpdate
from backend.app.repository import ExperimentRepository, RepositoryError, RunTraceStore
from backend.app.service import RunService
from backend.app.storage import atomic_json
from scripts.data_contract import ROOT, load_bundle, require
from scripts.week2_data import text_hash

VERSION = "week3-detector-gold-registration-v0.1"
REVIEWER = "Codex AI-authored/cross-reviewed"
GOLD_SUFFIX = "+ai-cross-review-v0.1"


class EvidenceGold(DetectorGoldUpdate):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    dataset_version: str = Field(min_length=1)
    split: Literal["dev"]
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_method: Literal["ai_evidence_review"]
    review_status: Literal["ai_authored_human_pending"]
    human_independent_review: Literal["pending"]


class NoModelProvider:
    def generate(self, *args, **kwargs):
        raise RuntimeError("Model invocation is forbidden during gold registration")

    generate_prepared = generate


def _json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _body(payload):
    return DetectorGoldUpdate.model_validate({key: payload[key]
        for key in DetectorGoldUpdate.model_fields}).model_dump(mode="json")


def _fingerprints(runs_dir, external_files, excluded=()):
    excluded = {path.resolve() for path in excluded}
    files = {path.resolve() for path in runs_dir.rglob("*") if path.is_file()}
    files.update(path.resolve() for path in external_files if path.is_file())
    return {str(path): file_hash(path) for path in sorted(files) if path not in excluded}


def _service(runs_dir, folder, state):
    data = folder / "inputs" / state.source_snapshots[0]["source_id"]
    rules = folder / "evaluation_rules.snapshot"
    settings = Settings(project_root=ROOT, data_dir=data, runs_dir=runs_dir,
        model_provider="demo", model_id="local-gold-registration-no-model",
        system_prompt_version="v0.1", retrieval_config_version="lexical-v0.1",
        model_base_url=None, model_api_key=None,
        evaluation_rules_path=rules if rules.exists() else None)
    return RunService(settings, ExperimentRepository(data), RunTraceStore(runs_dir), NoModelProvider())


def preflight(runs_dir: Path, batch_id: str, gold_path: Path):
    runs_dir, gold_path = runs_dir.resolve(), gold_path.resolve()
    store, traces = BatchStore(runs_dir), RunTraceStore(runs_dir)
    state = store.get(batch_id)
    verify_frozen_artifacts(store, state)
    require(state.status in ("completed", "partial"), "batch must be terminal before target registration")
    require(all(source["split"] == "dev" for source in state.source_snapshots), "dev batch required")
    require(all(entry["split"] == "dev" and entry["status"] in ("completed", "blocked", "failed")
                and entry["attempts"] for entry in state.plan), "all dev entries need terminal attempts")
    folder = store.folder(batch_id)
    bundles = {source["source_id"]: load_bundle(folder / "inputs" / source["source_id"])
               for source in state.source_snapshots}
    selected = {}
    external = [gold_path]
    for source in state.source_snapshots:
        bundle = bundles[source["source_id"]]
        for case_id in source["case_ids"]:
            case = bundle.cases[case_id]
            require(case.split == "dev" and case.source_version == source["dataset_version"],
                    "frozen case split or dataset mismatch")
            selected.setdefault((case_id, case.source_version), []).append((source, bundle, case))
        external.extend(Path(source["original_data_dir"]) / name for name in
                        ("cases.v0.1.jsonl", "corpus.v0.1.jsonl", "mvp-manifest.v0.1.json"))
    rows = [EvidenceGold.model_validate_json(line) for line in gold_path.read_text(
        encoding="utf-8-sig").splitlines() if line.strip()]
    require(bool(rows), "source gold is empty")
    by_target = {}
    for row in rows:
        key = (row.case_id, row.dataset_version, str(row.stage), row.target_ref)
        require(key not in by_target, "duplicate source target gold")
        sources = selected.get((row.case_id, row.dataset_version), [])
        require(bool(sources), "source gold case or dataset is outside frozen dev selection")
        for source, bundle, case in sources:
            if row.stage == "input":
                text = case.user_input
            else:
                require(row.target_ref in case.source_document_ids, "gold document is not a case source")
                doc = bundle.documents[row.target_ref]
                require(doc.source_version == source["corpus_version"], "gold document version mismatch")
                text = doc.title + "\n" + doc.content
            require(text_hash(text) == row.target_sha256, "source gold/frozen target hash mismatch")
        by_target[key] = row
    service = _service(runs_dir, folder, state)
    gold_hash = file_hash(gold_path)
    updates, seen_runs = [], set()
    for entry in state.plan:
        source = next(source for source in state.source_snapshots if source["source_id"] == entry["source_id"])
        require(entry["case_id"] in source["case_ids"], "plan case is outside frozen selection")
        for attempt in entry["attempts"]:
            require(attempt["status"] in ("completed", "blocked", "failed", "cancelled_before_transport"),
                    "unresolved attempt cannot be annotated")
            if attempt["status"] == "cancelled_before_transport":
                continue
            run_id = attempt["run_id"]
            require(run_id not in seen_runs, "run has multiple batch memberships")
            seen_runs.add(run_id)
            trace, raw = traces.get(run_id), traces.get_raw(run_id)
            require(trace.run_id == raw.get("run_id") == run_id and
                    raw.get("request") == trace.request.model_dump(mode="json"), "raw/public request mismatch")
            require(trace.request.case_id == entry["case_id"] and trace.request.scenario == source["scenario"]
                    and trace.request.dataset_version == source["dataset_version"]
                    and trace.request.corpus_version == source["corpus_version"], "trace/frozen source mismatch")
            require(str(trace.status) == attempt["status"], "trace/attempt status mismatch")
            calls = {}
            for call in raw.get("model_calls", []):
                if call.get("purpose") != "detection":
                    continue
                try:
                    message = call["messages"][1]
                    payload = json.loads(message["content"])
                    require(message["role"] == "user" and set(payload) == {"stage", "text"}
                            and isinstance(payload["text"], str), "invalid raw detection text")
                    key = (payload["stage"], call.get("target_ref"))
                    calls.setdefault(key, []).append(payload["text"])
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    raise ValueError("raw detection text is unavailable or malformed") from exc
            events = [event for event in trace.defense_events if event.defense_id == "D2"]
            event_keys = [(str(event.stage), event.target_ref) for event in events]
            require(len(set(event_keys)) == len(event_keys), "duplicate D2 target events")
            require(set(calls) == set(event_keys), "actual D2 events and detection calls differ")
            history_path = runs_dir / (run_id + ".detector-gold.json")
            history = _json(history_path) if history_path.exists() else []
            require(isinstance(history, list), "invalid detector gold history")
            for event, event_key in zip(events, event_keys):
                row = by_target.get((entry["case_id"], source["dataset_version"], *event_key))
                require(row is not None, "actual inspected D2 target lacks source gold")
                require(all(text_hash(text) == row.target_sha256 for text in calls[event_key]),
                        "actual raw detection text hash differs from source gold")
                body = DetectorGoldUpdate(stage=row.stage, target_ref=row.target_ref,
                    gold_label=row.gold_label, gold_version=row.gold_version + GOLD_SUFFIX, reviewer=REVIEWER,
                    reason="AI evidence review; human_independent_review=pending; literal hash integrity only, "
                           "not source authentication. source_gold_sha256=" + gold_hash +
                           "; target_sha256=" + row.target_sha256 + "; " + row.reason).model_dump(mode="json")
                body = service.safe_for_trace(trace, body)
                DetectorGoldUpdate.model_validate(body)
                matching_history = [item for item in history if (item.get("stage"), item.get("target_ref")) == event_key]
                for previous in matching_history:
                    require(previous.get("gold_version") != body["gold_version"] or _body(previous) == body,
                            "same gold version has a conflicting recorded body")
                latest = matching_history[-1] if matching_history else None
                current = next((item for item in trace.detector_evaluation
                                if (str(item.stage), item.target_ref) == event_key), None)
                already = bool(latest and _body(latest) == body)
                if already:
                    public_body = service.safe_for_trace(trace, _body(latest))
                    require(current is not None and _body(current.model_dump(mode="json")) == public_body,
                            "audit/public annotation mismatch; preserve evidence and repair before retry")
                identity = [batch_id, run_id, *event_key, text_hash(json.dumps(body, sort_keys=True))]
                updates.append({"target_id": text_hash(json.dumps(identity))[:24], "run_id": run_id,
                    "case_id": entry["case_id"], "source_id": source["source_id"],
                    "stage": str(row.stage), "target_ref": row.target_ref,
                    "target_sha256": row.target_sha256, "body": body,
                    "action": "already_applied" if already else "apply"})
    require(bool(updates), "batch has no actually inspected D2 targets")
    # Applying a review also creates persistent OS-lock coordination files.
    # Permit only the named targets' locks; raw evidence, other locks and all
    # unrelated files must still retain their exact preflight fingerprints.
    allowed = {runs_dir / (update["run_id"] + suffix) for update in updates
               for suffix in (".trace.json", ".detector-gold.json", ".review.lock", ".detector-gold.lock")}
    plan = {"plan_version": VERSION, "batch_id": batch_id, "gold_sha256": gold_hash,
        "reviewer": REVIEWER, "review_method": "source_ai_gold_and_literal_hash_integrity",
        "human_independent_review": "pending", "source_authentication": "not_verified",
        "status": "planned", "applied": False, "updates": updates,
        "applied_ids": [], "already_applied_ids": [u["target_id"] for u in updates if u["action"] == "already_applied"],
        "remaining_ids": [u["target_id"] for u in updates if u["action"] == "apply"],
        "model_calls": 0, "holdout_selected": False}
    return plan, service, allowed, external


def register(runs_dir: Path, batch_id: str, gold_path: Path, output: Path, *, apply=False):
    runs_dir, gold_path, output = runs_dir.resolve(), gold_path.resolve(), output.resolve()
    require(output != gold_path and not output.name.endswith((".raw.json", ".trace.json", ".detector-gold.json")),
            "output must be a separate plan artifact")
    require(not output.is_relative_to(runs_dir / "batches"), "plan cannot overwrite frozen batch artifacts")
    if output.exists():
        existing = _json(output)
        require(isinstance(existing, dict) and existing.get("plan_version") == VERSION
                and existing.get("batch_id") == batch_id, "output would overwrite unrelated evidence")
    plan, service, allowed, external = preflight(runs_dir, batch_id, gold_path)
    require(output not in {path.resolve() for path in external}, "plan cannot overwrite source data")
    excluded = (allowed if apply else set()) | {output}
    before = _fingerprints(runs_dir, external, excluded)
    plan["immutable_input_sha256"] = text_hash(json.dumps(before, sort_keys=True))
    atomic_json(output, plan)
    if apply:
        for update in plan["updates"]:
            if update["action"] == "already_applied":
                continue
            try:
                require(before == _fingerprints(runs_dir, external, excluded),
                        "immutable artifacts changed after preflight")
                service.update_detector_gold(update["run_id"], DetectorGoldUpdate.model_validate(update["body"]))
                plan["applied_ids"].append(update["target_id"])
                plan["remaining_ids"].remove(update["target_id"])
                atomic_json(output, plan)
            except (Exception, KeyboardInterrupt) as exc:
                plan.update(status="partial_failure", error_type=type(exc).__name__)
                break
        else:
            plan.update(status="applied", applied=True)
    after = _fingerprints(runs_dir, external, excluded)
    plan["immutable_artifacts_unchanged"] = before == after
    if not plan["immutable_artifacts_unchanged"]:
        plan.update(status="partial_failure", applied=False, error_type="ImmutableArtifactChanged")
    plan["counts"] = dict(Counter(update["action"] for update in plan["updates"]))
    atomic_json(output, plan)
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = register(args.runs_dir, args.batch_id, args.gold, args.output, apply=args.apply)
        print(json.dumps({"status": result["status"], "target_count": len(result["updates"]),
            "applied_count": len(result["applied_ids"]), "already_applied_count": len(result["already_applied_ids"]),
            "remaining_count": len(result["remaining_ids"]), "gold_sha256": result["gold_sha256"], "model_calls": 0}))
        return 0 if result["status"] != "partial_failure" else 1
    except (ValueError, OSError, KeyError, RepositoryError) as exc:
        # Do not print validation payloads, source text, or upstream exception messages.
        print(json.dumps({"status": "preflight_rejected", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
