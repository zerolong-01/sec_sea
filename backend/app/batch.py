"""Local, single-writer batch runner with immutable inputs and durable attempts."""
from __future__ import annotations

import hashlib
import json
import random
import platform
import importlib.metadata
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
from .batch_models import BatchArtifact, BatchSpec, CaseMetadata, RecommendationPolicy
from .models import RunRequest
from .repository import ArtifactNotFound, ExperimentRepository, RunTraceStore
from .service import RunService, TraceableRunError, build_provider
from .shared_variables import BATCH_VERSION
from .storage import atomic_json, exclusive_file_lock, file_sha256


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def file_hash(path: Path) -> str:
    return file_sha256(path)


def implementation_hash(root):
    paths = sorted((root / "backend/app").glob("*.py")) + [root / "scripts/data_contract.py", root / "scripts/week3_batch.py"]
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_text(encoding="utf-8").encode()).hexdigest() for p in paths})


def design_hash(spec):
    return digest({"conditions": [c.model_dump(mode="json") for c in spec.conditions],
                   "repeats": spec.repeats, "statistics": spec.statistics.model_dump(mode="json"),
                   "random_seed": spec.random_seed, "budget": spec.budget.model_dump(mode="json"),
                   "min_call_interval_seconds": spec.min_call_interval_seconds})


def selection_hash(spec):
    sources = [s.model_dump(mode="json", exclude={"data_dir"}) for s in spec.sources]
    for source in sources:
        for metadata in source["metadata"].values():
            # Preserve the exact pre-pair-id frozen selection representation.
            # Other optional nulls/defaults remain part of the original hash.
            if metadata.get("comparison_pair_id") is None:
                metadata.pop("comparison_pair_id", None)
    return digest(sources)


def plan_hash(plan):
    return digest([{k: v for k, v in entry.items() if k not in ("status", "attempts")} for entry in plan])


def verify_frozen_artifacts(store, state):
    folder = store.folder(state.batch_id)
    if state.configuration_hashes["design"] != design_hash(state.spec) or state.configuration_hashes["selection"] != selection_hash(state.spec):
        raise ValueError("Frozen design or selection changed")
    if state.configuration_hashes.get("plan") != plan_hash(state.plan):
        raise ValueError("Frozen plan metadata changed; re-create legacy development batches without a plan hash")
    if state.configuration_hashes.get("source_snapshots") != digest(state.source_snapshots):
        raise ValueError("Frozen source inventory changed")
    if state.configuration_hashes["settings"] != digest(state.execution_settings):
        raise ValueError("Frozen execution settings changed")
    for snapshot in state.source_snapshots:
        for filename, key in (("cases.v0.1.jsonl", "cases_sha256"), ("corpus.v0.1.jsonl", "corpus_sha256"),
                              ("mvp-manifest.v0.1.json", "manifest_sha256")):
            if file_hash(folder / "inputs" / snapshot["source_id"] / filename) != snapshot[key]:
                raise ValueError("Frozen batch data hash mismatch")
    for name in ("common_policy", "pricing", "evaluation_rules", "evaluation_policy"):
        expected = state.configuration_hashes[name]
        if expected != "not_configured" and file_hash(folder / (name + ".snapshot")) != expected:
            raise ValueError("Frozen configuration hash mismatch")


@contextmanager
def batch_lock(folder: Path):
    with exclusive_file_lock(folder / "writer.lock"):
        yield


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
        state = BatchArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        if state.batch_id != batch_id:
            raise ValueError("Batch ID does not match its directory")
        return state

    def save(self, state):
        atomic_json(self.folder(state.batch_id) / "manifest.json", state.model_dump(mode="json"))

    def list(self):
        return [self.summary(self.get(path.parent.name)) for path in sorted(self.root.glob("batch-*/manifest.json"))]

    def summary(self, state):
        counts = Counter(entry["status"] for entry in state.plan)
        return {"schema_version": BATCH_VERSION, "artifact_type": "batch_summary", "batch_id": state.batch_id,
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
    from .prompts import D1_VERSION
    excluded = {"project_root", "data_dir", "runs_dir", "model_api_key", "d2_api_key",
                "pricing_path", "evaluation_rules_path", "common_policy_path"}
    result = {f.name: getattr(settings, f.name) for f in fields(settings) if f.name not in excluded}
    result["d1_version"] = D1_VERSION
    from .providers import OpenAICompatibleProvider
    for name in ("model_base_url", "d2_base_url"):
        if result[name]:
            # Reuse transport URL validation even for a dry-run plan. Never
            # persist credentials embedded in an invalid endpoint URL.
            OpenAICompatibleProvider(result[name], None, "endpoint-validation-only")
    result["execution_scope"] = ("demo" if settings.model_provider == "demo" else "fixture"
                                 if settings.model_provider == "fixture_http" else "real")
    result["environment"] = {"python": platform.python_version(), "platform": platform.platform(),
                             "machine": platform.machine(), "packages": {name: importlib.metadata.version(name)
                                 for name in ("pydantic", "fastapi", "jsonschema")}}
    for key, value in result.items():
        if isinstance(value, str):
            for secret in (settings.model_api_key, settings.d2_api_key):
                if secret:
                    value = value.replace(secret, "[MASKED_CREDENTIAL]")
            result[key] = value
    return json.loads(json.dumps(result))


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
            for meta in source.metadata.values():
                if meta.parent_case_id and (meta.parent_case_id not in bundle.cases
                        or bundle.cases[meta.parent_case_id].split != source.split):
                    raise ValueError("Parent and derived case must exist in the same split")
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
        if not files["common_policy"].read_text(encoding="utf-8").strip():
            raise ValueError("Common application policy must not be empty")
        for name, path in files.items():
            hashes[name] = file_hash(path) if path else "not_configured"
        hashes["settings"] = digest(public_settings(self.settings))
        hashes["implementation"] = implementation_hash(self.settings.project_root)
        hashes["design"] = design_hash(spec)
        hashes["selection"] = selection_hash(spec)
        return snapshots, bundles, files, hashes

    def create(self, spec: BatchSpec):
        # Revalidate even an object previously used for read-only inventory.
        spec = BatchSpec.model_validate(spec.model_dump(mode="json"))
        effective = []
        for condition in spec.conditions:
            d2 = condition.defense_mode in ("D2", "D1+D2")
            effective.append((condition.defense_mode, condition.defense_position if d2 else None,
                              condition.execution_kind,
                              condition.d2_threshold if condition.d2_threshold is not None else self.settings.d2_threshold if d2 else None,
                              condition.consistency_policy or self.settings.d2_consistency_policy if d2 else None))
        if len(set(effective)) != len(effective):
            raise ValueError("Duplicate effective conditions after applying runtime defaults")
        for comparison in ("technique", "position"):
            detector_configs = {(e[3], e[4]) for e, c in zip(effective, spec.conditions)
                                if comparison in c.comparisons and c.defense_mode in ("D2", "D1+D2")}
            if len(detector_configs) > 1:
                raise ValueError("Comparison changes more than the intended defense mode/position")
        snapshots, bundles, files, hashes = self.inspect_inputs(spec)
        if any(s.split == "holdout" for s in spec.sources):
            if spec.freeze_hashes != hashes:
                raise ValueError("Holdout inputs differ from reviewed freeze inventory")
            policy = RecommendationPolicy.model_validate_json(files["evaluation_policy"].read_text(encoding="utf-8")) if files["evaluation_policy"] else None
            if policy is None or policy.status != "frozen":
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
        hashes["plan"] = plan_hash(plan)
        hashes["source_snapshots"] = digest(snapshots)
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

    def _verify_inputs(self, state, *, executing=True):
        if executing and state.configuration_hashes["implementation"] != implementation_hash(self.settings.project_root):
            raise ValueError("Batch implementation changed; create a new batch")
        verify_frozen_artifacts(self.store, state)

    def execute(self, batch_id, *, max_items=None, retry_failed=False, retry_uncertain=False, stop_on_error=False):
        if max_items is not None and (type(max_items) is not int or max_items < 1):
            raise ValueError("max_items must be a positive integer")
        folder = self.store.folder(batch_id)
        with batch_lock(folder):
            state = self.store.get(batch_id)
            # A pilot resumes only after the operator resolves earlier failures.
            # Returning untouched also preserves the original interruption reason.
            if stop_on_error and any(e["status"] in ("failed", "uncertain") for e in state.plan):
                return state
            if public_settings(self.settings) != state.execution_settings:
                raise ValueError("Execution settings changed; create a new batch")
            self._verify_inputs(state)
            condition_by_id = {c.condition_id: c for c in state.spec.conditions}
            source_by_id = {s["source_id"]: s for s in state.source_snapshots}
            repositories = {source_id: ExperimentRepository(folder / "inputs" / source_id,
                expected_hashes={"cases.v0.1.jsonl": source["cases_sha256"],
                                 "corpus.v0.1.jsonl": source["corpus_sha256"]})
                for source_id, source in source_by_id.items()}
            state.status, state.reason = "running", None
            started, elapsed_before = time.monotonic(), state.elapsed_seconds
            self.store.save(state)
            processed = 0
            try:
                for entry in state.plan:
                    state.elapsed_seconds = max(state.elapsed_seconds, elapsed_before + time.monotonic() - started)
                    if entry["status"] == "running":
                        self._recover(state, entry)
                    if entry["status"] in ("completed", "blocked"):
                        continue
                    if entry["status"] == "failed" and not retry_failed:
                        continue
                    if state.elapsed_seconds >= state.spec.budget.max_seconds:
                        state.reason = "BATCH_TIME_BUDGET_EXCEEDED"
                        break
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
                    source = source_by_id[entry["source_id"]]
                    def snapshot_path(name):
                        expected = state.configuration_hashes[name]
                        if expected == "not_configured":
                            return None
                        path = folder / (name + ".snapshot")
                        if file_hash(path) != expected:
                            raise ValueError("Frozen configuration hash mismatch")
                        return path
                    settings = replace(self.settings, data_dir=folder / "inputs" / entry["source_id"],
                                       common_policy_path=snapshot_path("common_policy"),
                                       pricing_path=snapshot_path("pricing"), evaluation_rules_path=snapshot_path("evaluation_rules"),
                                       d2_consistency_policy=condition.consistency_policy or self.settings.d2_consistency_policy)
                    provider = build_provider(settings)
                    service = RunService(settings, repositories[entry["source_id"]], self.traces, provider)
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
                    if stop_on_error and trace.status == "failed":
                        break
            except KeyboardInterrupt:
                state.reason = "operator_interrupt"
            finally:
                state.elapsed_seconds = max(state.elapsed_seconds, elapsed_before + time.monotonic() - started)
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
            entry["status"] = "uncertain" if paid_or_sent else "pending"
            # Keep the interrupted attempt for auditing without claiming an
            # unresolved request when no transport reservation ever existed.
            attempt["status"] = "uncertain" if paid_or_sent else "cancelled_before_transport"
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
            payload = service.safe_for_trace(trace, {**review.model_dump(mode="json"), "run_id": run_id,
                                                     "reviewed_at": datetime.now(timezone.utc).isoformat()})
            path = self.store.folder(batch_id) / "reviews.json"
            history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            history.append(payload)
            atomic_json(path, history)
            return payload
