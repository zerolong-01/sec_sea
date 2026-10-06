from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .shared_variables import (
    METRIC_KEYS,
    ArtifactType,
    CaseLabel,
    CallPurpose,
    DataSplit,
    DefenseDecision,
    DefenseMode,
    DefensePosition,
    ExecutionScope,
    EvaluationStatus,
    Language,
    OutputOutcome,
    PromptComponentType,
    RunStatus,
    Scenario,
    SchemaVersion,
    TraceStage,
    UsageSource,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SuccessCriterion(StrictModel):
    criterion_type: Literal[
        "canary_leak", "instruction_override", "task_quality", "human_rubric"
    ]
    description: str = Field(min_length=1)


class CaseRecord(StrictModel):
    schema_version: Literal[SchemaVersion.CURRENT]
    artifact_type: Literal[ArtifactType.CASE]
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    scenario: Scenario
    language: Language
    split: DataSplit
    label: CaseLabel
    user_input: str = Field(min_length=1)
    source_document_ids: list[str]
    attack_type: (
        Literal[
            "direct_instruction",
            "indirect_document",
            "role_override",
            "data_exfiltration",
            "encoding_obfuscation",
            "other",
        ]
        | None
    )
    attack_goal: str | None
    expected_normal_task: str = Field(min_length=1)
    success_criterion: SuccessCriterion
    source_version: str = Field(min_length=1)

    @field_validator("source_document_ids")
    @classmethod
    def validate_unique_source_document_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("source_document_ids must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_attack_fields(self) -> "CaseRecord":
        if self.label == CaseLabel.ATTACK and (
            self.attack_type is None or not self.attack_goal
        ):
            raise ValueError(
                "attack 라벨 케이스에는 attack_type과 attack_goal이 필요합니다."
            )
        if self.label != CaseLabel.ATTACK and (
            self.attack_type is not None or self.attack_goal is not None
        ):
            raise ValueError(
                "benign/hard_negative 케이스의 attack_type과 attack_goal은 null이어야 합니다."
            )
        return self


class SourceDocument(StrictModel):
    schema_version: Literal[SchemaVersion.CURRENT]
    artifact_type: Literal[ArtifactType.SOURCE_DOCUMENT]
    document_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    language: Language
    source_type: Literal[
        "seed_corpus", "email_body", "uploaded_document", "web_snapshot"
    ]
    source_version: str = Field(min_length=1)
    is_untrusted_content: bool


class RunRequest(StrictModel):
    schema_version: Literal[SchemaVersion.CURRENT, SchemaVersion.EXECUTION]
    artifact_type: Literal[ArtifactType.RUN_REQUEST]
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    scenario: Scenario
    defense_mode: DefenseMode
    dataset_version: str = Field(min_length=1)
    corpus_version: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    defense_position: DefensePosition = DefensePosition.BOTH
    d2_threshold: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class RetrievalItem(StrictModel):
    document_id: str
    rank: int = Field(ge=1)
    score: float | None
    included_in_prompt: bool


class PromptComponent(StrictModel):
    order: int = Field(ge=0)
    component_type: PromptComponentType
    source_ref: str | None
    display_text: str
    is_masked: bool


class DefenseEvent(StrictModel):
    defense_id: Literal[DefenseMode.D1, DefenseMode.D2]
    defense_version: str = Field(min_length=1)
    stage: Literal[
        TraceStage.INPUT, TraceStage.RETRIEVAL, TraceStage.PROMPT_ASSEMBLY,
        TraceStage.OUTPUT,
    ]
    decision: DefenseDecision
    reason_code: str | None
    score: float | None = Field(default=None, ge=0, le=1)
    target_ref: str | None = None
    threshold: float | None = Field(default=None, ge=0, le=1)
    policy_version: str | None = None
    reason: str | None = None
    error: str | None = None
    score_kind: str | None = None


class EvaluationResult(StrictModel):
    attack_success: EvaluationStatus
    normal_task_success: Literal[
        EvaluationStatus.SUCCESS, EvaluationStatus.FAILURE,
        EvaluationStatus.NOT_EVALUATED, EvaluationStatus.REVIEW_NEEDED,
    ]
    evaluator_version: str = Field(min_length=1)
    reason: str | None
    reviewer: str | None = None
    evaluated_at: str | None = None
    policy_version: str | None = None


class EvaluationUpdate(EvaluationResult):
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ChatMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelCall(StrictModel):
    purpose: CallPurpose
    target_ref: str | None = None
    model_id: str
    endpoint: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    messages: list[ChatMessage]
    parameters: dict[str, Any]
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    usage_source: UsageSource = UsageSource.UNKNOWN
    estimated_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cost_reason: str | None = None
    error_code: str | None = None
    response_text: str | None = None
    pricing_snapshot: dict[str, Any] = Field(default_factory=dict)


class StageMetric(StrictModel):
    stage: TraceStage
    latency_ms: int = Field(ge=0)



class OutputRecord(StrictModel):
    outcome: OutputOutcome
    display_text: str | None
    is_masked: bool


class Metrics(StrictModel):
    latency_ms: int | None = Field(default=None, ge=0, alias=METRIC_KEYS["LATENCY_MS"])
    input_tokens: int | None = Field(default=None, ge=0, alias=METRIC_KEYS["INPUT_TOKENS"])
    output_tokens: int | None = Field(default=None, ge=0, alias=METRIC_KEYS["OUTPUT_TOKENS"])
    estimated_cost_usd: float | None = Field(
        default=None, ge=0, alias=METRIC_KEYS["ESTIMATED_COST_USD"]
    )
    stages: list[StageMetric] = Field(default_factory=list)
    model_call_count: int = Field(default=0, ge=0)
    generation_call_count: int = Field(default=0, ge=0)
    detection_call_count: int = Field(default=0, ge=0)
    unpriced_call_count: int = Field(default=0, ge=0)
    known_cost_usd: float = Field(default=0, ge=0)
    cost_complete: bool = False
    usage_source: UsageSource = UsageSource.UNKNOWN
    generation_skipped_reason: str | None = None


class ErrorRecord(StrictModel):
    code: str
    message: str


class Manifest(StrictModel):
    model_id: str = Field(min_length=1)
    system_prompt_version: str = Field(min_length=1)
    generation_parameters: dict[str, str | float | int | bool | None]
    retrieval_config_version: str = Field(min_length=1)
    defense_config_versions: dict[str, str]
    provider: str = "demo"
    execution_scope: ExecutionScope = ExecutionScope.DEMO
    base_system_prompt_version: str | None = None
    defense_position: DefensePosition = DefensePosition.BOTH
    d2_configuration: dict[str, Any] = Field(default_factory=dict)
    evaluator_version: str = "manual-v0.1"
    pricing_version: str | None = None
    max_model_calls: int = Field(default=8, ge=1)
    pricing_snapshot: dict[str, Any] = Field(default_factory=dict)


class RunTrace(StrictModel):
    schema_version: Literal[SchemaVersion.CURRENT, SchemaVersion.EXECUTION] = SchemaVersion.EXECUTION
    artifact_type: Literal[ArtifactType.RUN_TRACE] = ArtifactType.RUN_TRACE
    run_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    status: RunStatus
    created_at: str
    request: RunRequest
    manifest: Manifest
    input: dict[str, Any]
    retrieval: list[RetrievalItem]
    prompt_assembly: list[PromptComponent]
    defense_events: list[DefenseEvent]
    output: OutputRecord
    evaluation: EvaluationResult
    metrics: Metrics
    error: ErrorRecord | None
    model_calls: list[ModelCall] = Field(default_factory=list)


class RunResponse(StrictModel):
    run_id: str
    status: Literal[RunStatus.COMPLETED, RunStatus.BLOCKED, RunStatus.FAILED]
    trace: RunTrace
