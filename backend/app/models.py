from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .shared_variables import (
    METRIC_KEYS,
    ArtifactType,
    CaseLabel,
    DataSplit,
    DefenseDecision,
    DefenseMode,
    EvaluationStatus,
    Language,
    OutputOutcome,
    PromptComponentType,
    RunStatus,
    Scenario,
    SchemaVersion,
    TraceStage,
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
    schema_version: Literal[SchemaVersion.CURRENT]
    artifact_type: Literal[ArtifactType.RUN_REQUEST]
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    scenario: Scenario
    defense_mode: DefenseMode
    dataset_version: str = Field(min_length=1)
    corpus_version: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)


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


class EvaluationResult(StrictModel):
    attack_success: EvaluationStatus
    normal_task_success: Literal[
        EvaluationStatus.SUCCESS, EvaluationStatus.FAILURE,
        EvaluationStatus.NOT_EVALUATED, EvaluationStatus.REVIEW_NEEDED,
    ]
    evaluator_version: str = Field(min_length=1)
    reason: str | None


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


class ErrorRecord(StrictModel):
    code: str
    message: str


class Manifest(StrictModel):
    model_id: str = Field(min_length=1)
    system_prompt_version: str = Field(min_length=1)
    generation_parameters: dict[str, str | float | int | bool | None]
    retrieval_config_version: str = Field(min_length=1)
    defense_config_versions: dict[str, str]


class RunTrace(StrictModel):
    schema_version: Literal[SchemaVersion.CURRENT] = SchemaVersion.CURRENT
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


class RunResponse(StrictModel):
    run_id: str
    status: Literal[RunStatus.COMPLETED, RunStatus.BLOCKED, RunStatus.FAILED]
    trace: RunTrace
