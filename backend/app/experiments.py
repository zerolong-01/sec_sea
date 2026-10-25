"""Model comparison planning and frozen membership, without model invocation."""
from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .batch import BatchRunner, BatchStore, digest, verify_frozen_artifacts
from .config import Settings
from .environment import resolve_project_path
from .experiment_models import EXPERIMENT_ID_PATTERN, ExperimentManifest, ExperimentSpec
from .repository import ArtifactNotFound, ArtifactValidationError
from .storage import atomic_json


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
