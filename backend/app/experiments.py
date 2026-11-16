"""Model comparison planning and frozen membership, without model invocation."""
from __future__ import annotations

import re
import os
import uuid
from dataclasses import fields, replace
from datetime import datetime, timezone
from pathlib import Path

from .batch import BatchRunner, BatchStore, digest, implementation_hash, verify_frozen_artifacts
from .batch_budget import budget_summary
from .config import Settings
from .environment import resolve_project_path
from .experiment_models import EXPERIMENT_ID_PATTERN, ExperimentManifest, ExperimentSpec, ExperimentSummary
from .repository import ArtifactNotFound, ArtifactValidationError
from .storage import atomic_json, exclusive_file_lock


def common_identity(state):
    """Everything except the target provider endpoint/model must be identical."""
    settings = {key: value for key, value in state.execution_settings.items()
                if key not in ("model_provider", "model_id", "model_base_url")}
    hashes = {key: value for key, value in state.configuration_hashes.items() if key != "settings"}
    return digest({"settings": settings, "hashes": hashes, "batch": state.spec.model_dump(mode="json")})


class ExperimentStore:
    def __init__(self, runs_dir: Path):
        self.root = runs_dir / "model-experiments"

    def folder(self, experiment_id):
        if not re.fullmatch(EXPERIMENT_ID_PATTERN, experiment_id):
            raise ValueError("Invalid experiment ID")
        folder = self.root / experiment_id
        if folder.is_symlink():
            raise ArtifactValidationError("Experiment directory must not be a symlink")
        return folder

    def get(self, experiment_id):
        path = self.folder(experiment_id) / "manifest.json"
        if path.is_symlink():
            raise ArtifactValidationError("Experiment manifest must not be a symlink")
        try:
            state = ExperimentManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ArtifactNotFound("Model experiment not found") from exc
        except (ValueError, OSError) as exc:
            raise ArtifactValidationError("Invalid model experiment manifest") from exc
        payload = state.model_dump(mode="json", exclude={"manifest_sha256"})
        if state.experiment_id != experiment_id or digest(payload) != state.manifest_sha256:
            raise ArtifactValidationError("Model experiment identity mismatch")
        return state

    def save(self, state):
        return atomic_json(self.folder(state.experiment_id) / "manifest.json", state.model_dump(mode="json"))


class ExperimentRunner:
    def __init__(self, project_root: Path, runs_dir: Path):
        self.project_root, self.runs_dir = project_root.resolve(), runs_dir.resolve()
        self.store, self.batches = ExperimentStore(self.runs_dir), BatchStore(self.runs_dir)

    def create(self, spec: ExperimentSpec, *, settings: Settings | None = None):
        spec = ExperimentSpec.model_validate(spec.model_dump(mode="json"))
        base = settings or Settings.from_environment(self.project_root)
        # One set of runtime parameters and one shared detector for all models.
        common = replace(base, project_root=self.project_root, runs_dir=self.runs_dir,
            pricing_path=resolve_project_path(spec.pricing_file, self.project_root) if spec.pricing_file else base.pricing_path,
            evaluation_rules_path=resolve_project_path(spec.evaluation_rules_file, self.project_root)
                if spec.evaluation_rules_file else base.evaluation_rules_path,
            d2_model_id=spec.detector.model_id if spec.detector else None,
            d2_base_url=spec.detector.base_url if spec.detector else None,
            d2_api_key=None, model_api_key=None)
        runners = [BatchRunner(replace(common, model_provider=m.provider,
            model_id=m.model_id, model_base_url=m.base_url)) for m in spec.models]
        # Reject missing/invalid sources or configuration before creating plans.
        for runner in runners:
            runner.inspect_inputs(spec.batch)
        members, shared = [], None
        for profile, runner in zip(spec.models, runners):
            child = runner.create(spec.batch)
            identity = common_identity(child)
            if shared is not None and identity != shared:
                raise ArtifactValidationError("Comparison inputs changed while planning models")
            shared = identity
            members.append({"model_key": profile.model_key, "batch_id": child.batch_id,
                            "settings_sha256": child.configuration_hashes["settings"]})
        payload = {"schema_version": "0.1", "artifact_type": "model_experiment_manifest",
            "experiment_id": "experiment-" + uuid.uuid4().hex[:12],
            "created_at": datetime.now(timezone.utc).isoformat(), "code_commit": child.code_commit,
            "spec": spec.model_dump(mode="json"), "members": members, "common_sha256": shared}
        state = ExperimentManifest(**payload, manifest_sha256=digest(payload))
        self.store.save(state)
        return state

    def validate_members(self, state):
        children = []
        for profile, member in zip(state.spec.models, state.members):
            child = self.batches.get(member.batch_id)
            verify_frozen_artifacts(self.batches, child)
            if (common_identity(child) != state.common_sha256 or
                    child.configuration_hashes["settings"] != member.settings_sha256 or
                    any(child.execution_settings[key] != value for key, value in {
                        "model_provider": profile.provider, "model_id": profile.model_id,
                        "model_base_url": profile.base_url}.items())):
                raise ArtifactValidationError("Model batch differs from frozen comparison conditions")
            children.append(child)
        return children

    def summary(self, experiment_id):
        state = self.store.get(experiment_id)
        children = self.validate_members(state)
        models = []
        for member, child in zip(state.members, children):
            summary = self.batches.summary(child)
            models.append({"model_key": member.model_key, "model_id": child.execution_settings["model_id"],
                "provider": child.execution_settings["model_provider"], "batch_id": child.batch_id,
                **{key: summary[key] for key in ("status", "reason", "planned_count", "attempt_count",
                                                "status_counts", "budget", "execution_scope")}})
        statuses = {child.status for child in children}
        status = ("uncertain" if "uncertain" in statuses else "running" if "running" in statuses
                  else "completed" if statuses == {"completed"}
                  else "planned" if statuses == {"planned"} else "paused"
                  if statuses & {"running", "paused", "planned"} else "partial")
        budgets = [budget_summary(child) for child in children]
        def total(key):
            return sum(b[key] for b in budgets) if all(b[key] is not None for b in budgets) else None
        limit, count = state.spec.batch.budget, len(models)
        return ExperimentSummary(experiment_id=state.experiment_id, created_at=state.created_at,
            code_commit=state.code_commit, status=status, common_sha256=state.common_sha256,
            planned_count=sum(m["planned_count"] for m in models),
            attempt_count=sum(m["attempt_count"] for m in models), models=models,
            budget_limits={"scope": "per_model_no_budget_transfer", "per_model": limit.model_dump(mode="json"),
                "total_max_calls": count * limit.max_calls,
                "total_max_reserved_tokens": count * limit.max_reserved_tokens,
                "total_max_usd": count * limit.max_usd if limit.max_usd is not None else None,
                "max_execution_seconds_sum": count * limit.max_seconds},
            budget_usage={key: total(key) for key in ("admitted_calls", "reserved_tokens", "known_cost_usd",
                "total_cost_usd", "committed_usd", "unresolved_calls", "elapsed_seconds")})

    def list(self):
        return [self.summary(path.parent.name) for path in sorted(self.store.root.glob("experiment-*/manifest.json"))]

    @staticmethod
    def _credential(profile):
        if profile is None or profile.api_key_env is None:
            return None
        value = os.environ.get(profile.api_key_env)
        if not value:
            raise ValueError("A required model credential environment variable is missing")
        return value

    def _execution_settings(self, child, profile, detector):
        folder = self.batches.folder(child.batch_id)
        excluded = {"project_root", "data_dir", "runs_dir", "model_api_key", "d2_api_key",
                    "pricing_path", "evaluation_rules_path", "common_policy_path"}
        frozen = {f.name: child.execution_settings[f.name] for f in fields(Settings)
                  if f.name not in excluded and f.name in child.execution_settings}
        def snapshot(name):
            return folder / (name + ".snapshot") if child.configuration_hashes[name] != "not_configured" else None
        return Settings(project_root=self.project_root, runs_dir=self.runs_dir,
            data_dir=folder / "inputs" / child.source_snapshots[0]["source_id"],
            model_api_key=self._credential(profile), d2_api_key=self._credential(detector),
            pricing_path=snapshot("pricing"), evaluation_rules_path=snapshot("evaluation_rules"),
            common_policy_path=snapshot("common_policy"), **frozen)

    def execute(self, experiment_id, *, max_items=None, model_keys=None,
                retry_failed=False, retry_uncertain=False, stop_on_error=False):
        if max_items is not None and (type(max_items) is not int or max_items < 1):
            raise ValueError("max_items must be a positive integer")
        self.store.get(experiment_id)
        with exclusive_file_lock(self.store.folder(experiment_id) / "writer.lock"):
            state = self.store.get(experiment_id)
            children = self.validate_members(state)
            selected = set(model_keys) if model_keys is not None else {p.model_key for p in state.spec.models}
            if not selected or not selected <= {p.model_key for p in state.spec.models}:
                raise ValueError("Unknown or empty model selection")
            # Preflight ALL selected credentials and frozen code before sending
            # any request. Settings are restored from snapshots, never live .env.
            runners = {}
            current = implementation_hash(self.project_root)
            for profile, child in zip(state.spec.models, children):
                if profile.model_key not in selected or child.status == "completed":
                    continue
                if child.configuration_hashes["implementation"] != current:
                    raise ValueError("Experiment implementation changed; create a new experiment")
                configured = self._execution_settings(child, profile, state.spec.detector)
                runners[profile.model_key] = BatchRunner(configured)
            processed = 0
            for profile, child in zip(state.spec.models, children):
                runner = runners.get(profile.model_key)
                if runner is None:
                    continue
                remaining = None if max_items is None else max_items - processed
                if remaining == 0:
                    break
                before = sum(len(e["attempts"]) for e in child.plan)
                result = runner.execute(child.batch_id, max_items=remaining, retry_failed=retry_failed,
                    retry_uncertain=retry_uncertain, stop_on_error=stop_on_error)
                processed += sum(len(e["attempts"]) for e in result.plan) - before
                if (result.status == "uncertain" or result.reason == "operator_interrupt" or
                        stop_on_error and any(e["status"] == "failed" for e in result.plan)):
                    break
            return self.summary(experiment_id)
