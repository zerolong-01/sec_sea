"""A model comparison owns separate, otherwise identical frozen batches."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .batch_models import BatchModel, BatchSpec
from .providers import OpenAICompatibleProvider

EXPERIMENT_VERSION = "0.1"
EXPERIMENT_ID_PATTERN = r"^experiment-[a-f0-9]{12}$"


class ExperimentModel(BatchModel):
    model_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    provider: Literal["demo", "fixture_http", "openai_compatible"]
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$")
    base_url: str | None = None
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,127}$")

    @model_validator(mode="after")
    def validate_endpoint(self):
        if self.provider == "demo":
            if self.base_url is not None or self.api_key_env is not None:
                raise ValueError("Demo models do not consume an endpoint or credentials")
        else:
            if not self.base_url:
                raise ValueError("HTTP models require base_url")
            OpenAICompatibleProvider(self.base_url, None, self.model_id)
            self.base_url = self.base_url.rstrip("/")
        return self


class ExperimentSpec(BatchModel):
    schema_version: Literal[EXPERIMENT_VERSION] = EXPERIMENT_VERSION
    artifact_type: Literal["model_experiment_spec"] = "model_experiment_spec"
    models: list[ExperimentModel] = Field(min_length=2, max_length=16)
    detector: ExperimentModel | None = None
    batch: BatchSpec
    pricing_file: str | None = None
    evaluation_rules_file: str | None = None

    @model_validator(mode="after")
    def validate_comparison(self):
        if len({m.model_key for m in self.models}) != len(self.models):
            raise ValueError("Duplicate model_key")
        if len({(m.provider, m.model_id, m.base_url) for m in self.models}) != len(self.models):
            raise ValueError("Duplicate model endpoint and ID")
        if len({m.provider for m in self.models}) != 1:
            raise ValueError("A comparison cannot mix demo, fixture and real executions")
        if any(source.split != "dev" for source in self.batch.sources):
            raise ValueError("Model experiments v0.1 support development data only")
        d2 = any(c.defense_mode in ("D2", "D1+D2") for c in self.batch.conditions)
        if d2:
            if (self.detector is None or self.detector.provider == "demo" or
                    self.detector.provider != self.models[0].provider or not self.detector.api_key_env):
                raise ValueError("D2 comparisons require one shared HTTP detector and its credential env name")
        elif self.detector is not None:
            raise ValueError("A detector is only used by D2-enabled conditions")
        return self


class ExperimentMember(BatchModel):
    model_key: str
    batch_id: str = Field(pattern=r"^batch-[a-f0-9]{12}$")
    settings_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ExperimentManifest(BatchModel):
    schema_version: Literal[EXPERIMENT_VERSION] = EXPERIMENT_VERSION
    artifact_type: Literal["model_experiment_manifest"] = "model_experiment_manifest"
    experiment_id: str = Field(pattern=EXPERIMENT_ID_PATTERN)
    created_at: str
    code_commit: str
    spec: ExperimentSpec
    members: list[ExperimentMember]
    common_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_members(self):
        if ([m.model_key for m in self.members] != [m.model_key for m in self.spec.models] or
                len({m.batch_id for m in self.members}) != len(self.members)):
            raise ValueError("Experiment members must match the ordered unique model profiles")
        return self
