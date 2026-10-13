"""Local, single-writer batch runner with immutable inputs and durable attempts."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import datetime, timezone
from pathlib import Path

from .accounting import Accounting
from .batch_budget import BatchCallBudget, budget_summary
from .batch_models import BatchArtifact, BatchSpec, CaseMetadata
from .models import RunRequest
from .repository import ArtifactNotFound, ExperimentRepository, RunTraceStore
from .service import RunService, TraceableRunError, build_provider


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@contextmanager
def batch_lock(folder: Path):
    """OS lock is released on crash; no stale PID file authorizes a replay."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "writer.lock").open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Batch already has an active writer") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class BatchStore:
    def __init__(self, runs_dir: Path):
        self.root = runs_dir / "batches"

    def folder(self, batch_id):
        if not re.fullmatch(r"batch-[a-f0-9]{12}", batch_id):
            raise ValueError("Invalid batch ID")
        return self.root / batch_id

    def get(self, batch_id):
        path = self.folder(batch_id) / "manifest.json"
        if not path.exists():
            raise ArtifactNotFound("Batch not found")
        return BatchArtifact.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, state):
        atomic_json(self.folder(state.batch_id) / "manifest.json", state.model_dump(mode="json"))

    def list(self):
        return [self.summary(self.get(path.parent.name)) for path in sorted(self.root.glob("batch-*/manifest.json"))]

    def summary(self, state):
        counts = Counter(entry["status"] for entry in state.plan)
        return {"schema_version": "0.1", "artifact_type": "batch_summary", "batch_id": state.batch_id,
                "created_at": state.created_at, "code_commit": state.code_commit,
                "status": state.status, "reason": state.reason, "planned_count": len(state.plan),
                "status_counts": dict(counts), "attempt_count": sum(len(e["attempts"]) for e in state.plan),
                "budget": budget_summary(state), "configuration_hashes": state.configuration_hashes,
                "execution_scope": state.execution_settings["execution_scope"],
                "statistics": state.spec.statistics.model_dump(mode="json"),
                "sources": [{k: v for k, v in s.items() if k != "original_data_dir"} for s in state.source_snapshots],
                "conditions": [c.model_dump(mode="json") for c in state.spec.conditions],
                "plan": state.plan}


def public_settings(settings):
    excluded = {"project_root", "data_dir", "runs_dir", "model_api_key", "d2_api_key",
                "pricing_path", "evaluation_rules_path", "common_policy_path"}
    result = {f.name: getattr(settings, f.name) for f in fields(settings) if f.name not in excluded}
    result["execution_scope"] = ("demo" if settings.model_provider == "demo" else "fixture"
                                 if settings.model_provider == "fixture_http" else "real")
    return result


class BatchRunner:
    def __init__(self, settings):
        self.settings = settings
        self.store = BatchStore(settings.runs_dir)
        self.traces = RunTraceStore(settings.runs_dir)

    def _path(self, value):
        path = Path(value)
        return path if path.is_absolute() else self.settings.project_root / path

    def inspect_inputs(self, spec: BatchSpec):
        """Read-only freeze inventory; does not start a model or create a batch."""
        from scripts.data_contract import load_bundle
        snapshots, bundles, hashes = [], {}, {}
        for source in spec.sources:
            bundle = load_bundle(self._path(source.data_dir))
            selected = [c for c in bundle.cases.values() if c.split == source.split
                        and (not source.languages or c.language in source.languages)
                        and (not source.case_ids or c.case_id in source.case_ids)]
            if not selected or (source.case_ids and {c.case_id for c in selected} != set(source.case_ids)):
                raise ValueError("Source selects no cases, duplicates or cases outside its split/language")
            if len(source.case_ids) != len(set(source.case_ids)):
                raise ValueError("Duplicate selected case IDs")
            if set(source.metadata) - {c.case_id for c in selected}:
                raise ValueError("Metadata must refer to selected cases")
            snapshot = {"source_id": source.source_id, "original_data_dir": str(bundle.data_dir.resolve()),
                        "dataset_version": bundle.manifest.dataset_version,
                        "corpus_version": bundle.manifest.corpus_version, "scenario": bundle.manifest.scenario,
                        "split": source.split, "case_ids": sorted(c.case_id for c in selected),
                        "cases_sha256": file_hash(bundle.data_dir / "cases.v0.1.jsonl"),
                        "corpus_sha256": file_hash(bundle.data_dir / "corpus.v0.1.jsonl"),
                        "manifest_sha256": file_hash(bundle.manifest_path),
                        "metadata_sha256": digest({k: v.model_dump(mode="json") for k, v in source.metadata.items()})}
            for name in ("cases_sha256", "corpus_sha256", "manifest_sha256", "metadata_sha256"):
                hashes[source.source_id + "/" + name] = snapshot[name]
            snapshots.append(snapshot)
            bundles[source.source_id] = bundle
        files = {"common_policy": self._path(spec.common_policy_file),
                 "pricing": self.settings.pricing_path, "evaluation_rules": self.settings.evaluation_rules_path,
                 "evaluation_policy": self._path(spec.evaluation_policy_file) if spec.evaluation_policy_file else None}
        for name, path in files.items():
            hashes[name] = file_hash(path) if path else "not_configured"
        hashes["settings"] = digest(public_settings(self.settings))
        hashes["design"] = digest({"conditions": [c.model_dump(mode="json") for c in spec.conditions],
                                   "repeats": spec.repeats, "statistics": spec.statistics.model_dump(mode="json"),
                                   "random_seed": spec.random_seed, "budget": spec.budget.model_dump(mode="json")})
        return snapshots, bundles, files, hashes

    def create(self, spec: BatchSpec):
        snapshots, bundles, files, hashes = self.inspect_inputs(spec)
        if any(s.split == "holdout" for s in spec.sources):
            if spec.freeze_hashes != hashes:
                raise ValueError("Holdout inputs differ from reviewed freeze inventory")
            policy = json.loads(files["evaluation_policy"].read_text(encoding="utf-8")) if files["evaluation_policy"] else {}
            if (policy.get("status") != "frozen" or not policy.get("final_recommendation_allowed")
                    or any(v is None for v in policy.get("thresholds", {}).values()) or not policy.get("thresholds")):
                raise ValueError("Holdout requires a frozen, complete evaluation policy")
        folder = self.store.folder("batch-" + uuid.uuid4().hex[:12])
        folder.mkdir(parents=True)
        for source in snapshots:
            target = folder / "inputs" / source["source_id"]
            target.mkdir(parents=True)
            bundle = bundles[source["source_id"]]
            for name, original in (("cases.v0.1.jsonl", bundle.data_dir / "cases.v0.1.jsonl"),
                                   ("corpus.v0.1.jsonl", bundle.data_dir / "corpus.v0.1.jsonl"),
                                   ("mvp-manifest.v0.1.json", bundle.manifest_path)):
                (target / name).write_bytes(original.read_bytes())
        for name, path in files.items():
            if path:
                (folder / (name + ".snapshot")).write_bytes(path.read_bytes())
        plan = []
        for source in spec.sources:
            bundle = bundles[source.source_id]
            snapshot = next(s for s in snapshots if s["source_id"] == source.source_id)
            for case_id in snapshot["case_ids"]:
                case = bundle.cases[case_id]
                meta = source.metadata.get(case_id, CaseMetadata(family_id=case_id,
                                          goal_kind="unspecified" if case.label == "attack" else "normal"))
                for repeat in range(spec.repeats):
                    for condition in spec.conditions:
                        plan.append({"entry_id": f"entry-{len(plan):06d}", "source_id": source.source_id,
                                     "case_id": case_id, "scenario": str(case.scenario), "language": str(case.language),
                                     "label": str(case.label), "split": str(case.split), "attack_type": case.attack_type,
                                     "metadata": meta.model_dump(mode="json"), "repeat": repeat,
                                     "condition_id": condition.condition_id, "status": "pending", "attempts": []})
        random.Random(spec.random_seed).shuffle(plan)
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.settings.project_root,
                                             text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            commit = "unknown"
        state = BatchArtifact(batch_id=folder.name, created_at=datetime.now(timezone.utc).isoformat(),
                              code_commit=commit, status="planned", spec=spec,
                              execution_settings=public_settings(self.settings), source_snapshots=snapshots,
                              configuration_hashes=hashes, plan=plan)
        # Detect a source changing while being copied before any model runs.
        self._verify_inputs(state)
        self.store.save(state)
        return state

    def _verify_inputs(self, state):
        folder = self.store.folder(state.batch_id)
        for snapshot in state.source_snapshots:
            for filename, key in (("cases.v0.1.jsonl", "cases_sha256"), ("corpus.v0.1.jsonl", "corpus_sha256"),
                                  ("mvp-manifest.v0.1.json", "manifest_sha256")):
                if file_hash(folder / "inputs" / snapshot["source_id"] / filename) != snapshot[key]:
                    raise ValueError("Frozen batch data hash mismatch")
        for name in ("common_policy", "pricing", "evaluation_rules", "evaluation_policy"):
            expected = state.configuration_hashes[name]
            if expected != "not_configured" and file_hash(folder / (name + ".snapshot")) != expected:
                raise ValueError("Frozen configuration hash mismatch")

    def execute(self, batch_id, *, max_items=None, retry_failed=False, retry_uncertain=False):
        folder = self.store.folder(batch_id)
        with batch_lock(folder):
            state = self.store.get(batch_id)
            if public_settings(self.settings) != state.execution_settings:
                raise ValueError("Execution settings changed; create a new batch")
            self._verify_inputs(state)
            condition_by_id = {c.condition_id: c for c in state.spec.conditions}
            state.status, state.reason = "running", None
            self.store.save(state)
            processed = 0
            try:
                for entry in state.plan:
                    if entry["status"] == "running":
                        self._recover(state, entry)
                    if entry["status"] in ("completed", "blocked"):
                        continue
                    if entry["status"] == "failed" and not retry_failed:
                        continue
                    if entry["status"] == "uncertain":
                        if not retry_uncertain:
                            state.reason = "uncertain_attempt_requires_explicit_retry"
                            break
                        for call in state.calls:
                            if call["attempt_id"] == entry["attempts"][-1]["attempt_id"] and call["status"] != "settled":
                                call["status"] = "abandoned_unknown"
                    if max_items is not None and processed >= max_items:
                        state.reason = "operator_item_limit"
                        break
                    attempt_id = entry["entry_id"] + "-attempt-" + str(len(entry["attempts"]) + 1)
                    run_id = "run-" + state.batch_id[6:] + "-" + attempt_id
                    attempt = {"attempt_id": attempt_id, "run_id": run_id, "status": "running", "error_code": None}
                    entry["attempts"].append(attempt)
                    entry["status"] = "running"
                    self.store.save(state)
                    condition = condition_by_id[entry["condition_id"]]
                    source = next(s for s in state.source_snapshots if s["source_id"] == entry["source_id"])
                    def snapshot_path(name):
                        return folder / (name + ".snapshot") if state.configuration_hashes[name] != "not_configured" else None
                    settings = replace(self.settings, data_dir=folder / "inputs" / entry["source_id"],
                                       common_policy_path=snapshot_path("common_policy"),
                                       pricing_path=snapshot_path("pricing"), evaluation_rules_path=snapshot_path("evaluation_rules"),
                                       d2_consistency_policy=condition.consistency_policy or self.settings.d2_consistency_policy)
                    provider = build_provider(settings)
                    service = RunService(settings, ExperimentRepository(settings.data_dir), self.traces, provider)
                    guard = BatchCallBudget(state, self.store.save, Accounting(settings.pricing_path), attempt_id)
                    provider.observer = guard
                    if service._classifier is not None:
                        service._classifier.provider.observer = guard
                    request = RunRequest(schema_version="0.3", artifact_type="run_request", case_id=entry["case_id"],
                                         scenario=entry["scenario"], defense_mode=condition.defense_mode,
                                         defense_position=condition.defense_position, execution_kind=condition.execution_kind,
                                         d2_threshold=condition.d2_threshold, dataset_version=source["dataset_version"],
                                         corpus_version=source["corpus_version"], requested_by=state.batch_id)
                    try:
                        trace = service.execute(request, run_id=run_id)
                    except TraceableRunError as exc:
                        trace = exc.trace
                    finally:
                        guard.checkpoint()
                    entry["status"] = attempt["status"] = str(trace.status)
                    attempt["error_code"] = trace.error.code if trace.error else None
                    self.store.save(state)
                    processed += 1
                    if trace.error and trace.error.code.startswith("BATCH_"):
                        state.reason = trace.error.code
                        break
            except KeyboardInterrupt:
                state.reason = "operator_interrupt"
            finally:
                for entry in state.plan:
                    if entry["status"] == "running":
                        self._recover(state, entry)
                statuses = {entry["status"] for entry in state.plan}
                state.status = ("uncertain" if "uncertain" in statuses else "paused" if "pending" in statuses
                                else "partial" if "failed" in statuses else "completed")
                self.store.save(state)
            return state

    def _recover(self, state, entry):
        attempt = entry["attempts"][-1]
        try:
            trace = self.traces.get(attempt["run_id"])
            entry["status"] = attempt["status"] = str(trace.status)
            attempt["error_code"] = trace.error.code if trace.error else None
        except ArtifactNotFound:
            paid_or_sent = any(c["attempt_id"] == attempt["attempt_id"] for c in state.calls)
            entry["status"] = attempt["status"] = "uncertain" if paid_or_sent else "pending"
        self.store.save(state)

    def review(self, batch_id, run_id, review):
        with batch_lock(self.store.folder(batch_id)):
            state = self.store.get(batch_id)
            if not any(a["run_id"] == run_id for e in state.plan for a in e["attempts"]):
                raise ValueError("Run does not belong to this batch")
            trace = self.traces.get(run_id)
            if trace.status not in ("completed", "blocked") or trace.manifest.execution_kind != "full_pipeline":
                raise ValueError("Final-output review requires a completed or defense-blocked full pipeline")
            service = RunService(self.settings, ExperimentRepository(self.settings.data_dir), self.traces,
                                 build_provider(self.settings))
            from .service import CANARY_PATTERN
            raw = self.traces.get_raw(run_id)
            payload = service._safe({**review.model_dump(mode="json"), "run_id": run_id,
                                     "reviewed_at": datetime.now(timezone.utc).isoformat()},
                                    set(CANARY_PATTERN.findall(json.dumps(raw))))
            path = self.store.folder(batch_id) / "reviews.json"
            history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            history.append(payload)
            atomic_json(path, history)
            return payload
