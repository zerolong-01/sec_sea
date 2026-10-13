"""Separate v0.1 batch contract; execution v0.3 and old traces stay compatible."""
from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, ValidationInfo, model_validator

from .models import StrictModel
from .shared_variables import BATCH_VERSION, DefenseMode, DefensePosition, ExecutionKind


class BatchModel(StrictModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CaseMetadata(BatchModel):
    family_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    parent_case_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    ablation_variant: str = Field(default="original", pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    removed_components: list[str] = Field(default_factory=list)
    information_available: bool | None = None
    goal_kind: Literal["marker", "secret_leak", "task_hijack", "detector_bypass", "normal", "unspecified"] = "unspecified"
    severity: Literal["low", "medium", "high", "critical", "unspecified"] = "unspecified"


class BatchSource(BatchModel):
    source_id: str = Field(pattern=r"^[a-z0-9_-]{1,50}$")
    data_dir: str = Field(min_length=1)
    split: Literal["dev", "holdout"]
    case_ids: list[str] = Field(default_factory=list)
    languages: list[Literal["ko", "en"]] = Field(default_factory=list)
    metadata: dict[str, CaseMetadata] = Field(default_factory=dict)


class BatchCondition(BatchModel):
    condition_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    defense_mode: DefenseMode
    defense_position: DefensePosition = DefensePosition.BOTH
    execution_kind: ExecutionKind = ExecutionKind.FULL_PIPELINE
    d2_threshold: float | None = Field(default=None, ge=0, le=1)
    consistency_policy: Literal["threshold_only", "review_on_contradiction"] | None = None
    comparisons: list[Literal["technique", "position", "payload", "detector"]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_condition(self):
        if self.execution_kind == ExecutionKind.DETECTOR_ONLY and self.defense_mode != DefenseMode.D2:
            raise ValueError("detector_only requires D2")
        if "position" in self.comparisons and self.defense_mode != DefenseMode.D2:
            raise ValueError("Position comparisons require D2 without D1")
        if "technique" in self.comparisons and self.defense_mode in ("D2", "D1+D2") and self.defense_position != DefensePosition.BOTH:
            raise ValueError("Technique comparisons fix D2 to input+retrieval")
        if self.execution_kind == ExecutionKind.DETECTOR_ONLY and set(self.comparisons) & {"position", "technique"}:
            raise ValueError("Detector-only runs require a separate diagnostic comparison")
        if len(set(self.comparisons)) != len(self.comparisons):
            raise ValueError("Duplicate comparison membership")
        return self


def default_conditions() -> list[BatchCondition]:
    return [BatchCondition(condition_id=name, defense_mode=mode, defense_position=position,
                           comparisons=comparisons) for name, mode, position, comparisons in (
        ("none", "none", "input_retrieval", ["technique"]),
        ("D1", "D1", "input_retrieval", ["technique"]),
        ("D2-both", "D2", "input_retrieval", ["technique", "position"]),
        ("D1-D2", "D1+D2", "input_retrieval", ["technique"]),
        ("D2-input", "D2", "input", ["position"]),
        ("D2-retrieval", "D2", "retrieval", ["position"]),
    )]


class BatchBudget(BatchModel):
    max_calls: int = Field(ge=1)
    max_reserved_tokens: int = Field(ge=1)
    max_seconds: float = Field(gt=0)
    max_usd: float | None = Field(default=None, gt=0)
    unknown_price_policy: Literal["stop", "calls_tokens"] = "stop"
    per_call_input_token_ceiling: int = Field(default=32768, ge=1)

    @model_validator(mode="after")
    def validate_money(self):
        if self.max_usd is not None and self.unknown_price_policy != "stop":
            raise ValueError("A USD cap requires verified prices; fallback cannot promise a USD cap")
        return self


class StatisticsPolicy(BatchModel):
    version: str = "cluster-bootstrap-v0.1-draft"
    status: Literal["draft", "frozen"] = "draft"
    reviewed_by: list[str] = Field(default_factory=list)
    bootstrap_samples: int = Field(default=1000, ge=100, le=10000)
    seed: int = 2026
    minimum_families: int = Field(default=2, ge=2)
    minimum_evaluated_runs: int = Field(default=3, ge=1)


class ServiceThresholds(BatchModel):
    ASR_MAX: float | None = Field(default=None, ge=0, le=1)
    FPR_BENIGN_MAX: float | None = Field(default=None, ge=0, le=1)
    FPR_HARD_NEGATIVE_MAX: float | None = Field(default=None, ge=0, le=1)
    TASK_SUCCESS_MIN: float | None = Field(default=None, ge=0, le=1)
    TASK_SUCCESS_DROP_MAX_PP: float | None = Field(default=None, ge=0, le=100)
    P95_LATENCY_MAX: float | None = Field(default=None, ge=0)
    COST_PER_REQUEST_MAX: float | None = Field(default=None, ge=0)
    RUN_FAILURE_RATE_MAX: float | None = Field(default=None, ge=0, le=1)


class RecommendationPolicy(BatchModel):
    version: str = Field(min_length=1)
    status: Literal["draft", "frozen"] = "draft"
    final_recommendation_allowed: bool = False
    reviewed_by: list[str] = Field(default_factory=list)
    thresholds: ServiceThresholds = Field(default_factory=ServiceThresholds)
    priority: list[Literal["asr", "benign_fpr", "hard_negative_fpr", "task_success",
                           "latency_p95_ms", "cost_per_request_usd"]] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    critical_goal_success_max: Literal[0] = 0

    @model_validator(mode="after")
    def validate_frozen(self):
        if len(self.priority) != len(set(self.priority)):
            raise ValueError("Priority must not contain duplicates")
        if self.status == "frozen" and (len(set(self.reviewed_by)) < 2 or not self.priority
                or not self.final_recommendation_allowed or any(v is None for v in self.thresholds.model_dump().values())):
            raise ValueError("Frozen recommendation policy requires reviewed, complete criteria")
        return self


class BatchSpec(BatchModel):
    schema_version: Literal[BATCH_VERSION] = BATCH_VERSION
    artifact_type: Literal["batch_spec"] = "batch_spec"
    sources: list[BatchSource] = Field(min_length=1)
    conditions: list[BatchCondition] = Field(default_factory=default_conditions, min_length=1)
    repeats: int = Field(default=3, ge=1, le=100)
    random_seed: int = 2026
    budget: BatchBudget
    statistics: StatisticsPolicy = Field(default_factory=StatisticsPolicy)
    evaluation_policy_file: str | None = None
    common_policy_file: str = "configs/week3-common-policy.txt"
    freeze_hashes: dict[str, str] = Field(default_factory=dict)
    holdout_reviewers: list[str] = Field(default_factory=list)
    warmup: Literal["none"] = "none"
    cache: Literal["disabled_by_runner_provider_cache_unknown"] = "disabled_by_runner_provider_cache_unknown"
    concurrency: Literal[1] = 1
    seed_support: Literal["order_only_provider_seed_not_requested"] = "order_only_provider_seed_not_requested"
    min_call_interval_seconds: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_spec(self, info: ValidationInfo):
        for values, name in (([s.source_id for s in self.sources], "source_id"),
                             ([c.condition_id for c in self.conditions], "condition_id")):
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {name}")
        signatures = [(c.defense_mode, c.defense_position if c.defense_mode in ("D2", "D1+D2") else None,
                       c.execution_kind, c.d2_threshold, c.consistency_policy) for c in self.conditions]
        if len(signatures) != len(set(signatures)):
            raise ValueError("Duplicate execution conditions; share comparisons instead of duplicate runs")
        if len({s.split for s in self.sources}) != 1:
            raise ValueError("A batch cannot mix dev and holdout")
        if any(s.split == "holdout" for s in self.sources) and not (info.context or {}).get("inventory_only"):
            if (self.repeats < 3 or not self.freeze_hashes or len(set(self.holdout_reviewers)) < 2
                    or self.statistics.status != "frozen" or len(set(self.statistics.reviewed_by)) < 2):
                raise ValueError("Holdout requires frozen hashes, >=3 repeats and reviewed statistical policy")
        return self


class BatchFilters(BatchModel):
    source_id: str | None = None
    scenario: str | None = None
    language: str | None = None
    split: Literal["dev", "holdout"] | None = None
    condition_id: str | None = None
    comparison: Literal["technique", "position", "payload", "detector"] | None = None
    family_id: str | None = None
    attack_type: str | None = None
    label: Literal["attack", "benign", "hard_negative"] | None = None
    goal_kind: str | None = None
    severity: str | None = None
    execution_kind: str | None = None


class BatchReview(BatchModel):
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    policy_version: str = Field(min_length=1, max_length=200)
    excessive_transformation: bool | None = None
    target_exposed: bool | None = None


class BatchArtifact(BatchModel):
    schema_version: Literal[BATCH_VERSION] = BATCH_VERSION
    artifact_type: Literal["batch_manifest"] = "batch_manifest"
    batch_id: str = Field(pattern=r"^batch-[a-f0-9]{12}$")
    created_at: str
    code_commit: str
    status: Literal["planned", "running", "paused", "completed", "partial", "uncertain"]
    reason: str | None = None
    spec: BatchSpec
    execution_settings: dict
    source_snapshots: list[dict]
    configuration_hashes: dict[str, str]
    plan: list[dict]
    calls: list[dict] = Field(default_factory=list)
    elapsed_seconds: float = 0


class BatchReport(BatchModel):
    schema_version: Literal[BATCH_VERSION] = BATCH_VERSION
    artifact_type: Literal["batch_report"] = "batch_report"
    batch_id: str
    report_version: str
    evaluation_snapshot_sha256: str
    filters: BatchFilters
    statistics: StatisticsPolicy
    provenance: dict
    counts: dict
    groups: list[dict]
    payload_comparisons: list[dict]
    detector_report: dict
    decisions: dict


class BatchSummary(BatchModel):
    schema_version: Literal[BATCH_VERSION] = BATCH_VERSION
    artifact_type: Literal["batch_summary"] = "batch_summary"
    batch_id: str
    created_at: str
    code_commit: str
    status: str
    reason: str | None
    planned_count: int = Field(ge=0)
    status_counts: dict[str, int]
    attempt_count: int = Field(ge=0)
    budget: dict
    configuration_hashes: dict[str, str]
    execution_scope: str
    statistics: StatisticsPolicy
    sources: list[dict]
    conditions: list[BatchCondition]
    plan: list[dict]

