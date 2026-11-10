"""Separate, source-bound normal-task evaluations; legacy traces stay immutable."""
from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator
from typing_extensions import TypedDict

from .models import RUN_ID_PATTERN, EvaluationResult, Metrics, StrictModel
from .shared_variables import EvaluationStatus

VERSION = "normal-task-evaluation-v0.2"
POLICY_VERSION = "normal-task-dev-policy-v0.2"
PROMPT_VERSION = "normal-task-judge-prompt-v0.4"
RUBRIC_VERSION = "normal-task-rubric-v0.2"
DIMENSIONS = ("authorized_task_completion", "source_grounding_and_factual_accuracy",
              "required_format", "protected_information_safety")
Verdict = Literal["success", "failure", "review_needed", "not_applicable"]
TaskVerdict = Literal[EvaluationStatus.SUCCESS, EvaluationStatus.FAILURE,
                      EvaluationStatus.REVIEW_NEEDED, EvaluationStatus.NOT_EVALUATED]


class ReferenceQuote(StrictModel):
    document_id: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=4000)


class Dimension(StrictModel):
    verdict: Verdict
    reason: str = Field(min_length=1, max_length=2000)
    # Exact substrings of the saved answer, checked locally before accepting a vote.
    evidence_quotes: list[str] = Field(max_length=8)
    reference_quotes: list[ReferenceQuote] = Field(default_factory=list, max_length=8)


class JudgeDimensions(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    authorized_task_completion: Dimension
    source_grounding_and_factual_accuracy: Dimension
    required_format: Dimension
    protected_information_safety: Dimension


class JudgeVerdict(StrictModel):
    normal_task_success: Literal["success", "failure", "review_needed"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False, strict=True)
    dimensions: JudgeDimensions
    criteria: dict[str, Dimension] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def check_dimensions(self):
        if set(self.dimensions) != set(DIMENSIONS):
            raise ValueError("Judge must return all four rubric dimensions")
        if not self.reason.strip() or any(not d.reason.strip() for d in self.dimensions.values()):
            raise ValueError("Judge rationale cannot be whitespace")
        return self


class TaskEvaluationRequest(StrictModel):
    request_id: str = Field(pattern=RUN_ID_PATTERN)
    requested_by: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def nonempty_requester(self):
        if not self.requested_by.strip():
            raise ValueError("Requester cannot be whitespace")
        return self


class TaskReviewRequest(StrictModel):
    request_id: str = Field(pattern=RUN_ID_PATTERN)
    expected_revision: int = Field(ge=1, strict=True)
    normal_task_success: TaskVerdict
    reviewer: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def nonempty_review(self):
        if not self.reviewer.strip() or not self.reason.strip():
            raise ValueError("Reviewer and supporting reason are required")
        return self


class TaskEvaluationRecord(StrictModel):
    evaluation_id: str = Field(pattern=RUN_ID_PATTERN)
    revision: int = Field(ge=1)
    source: Literal["llm_judge", "automatic_rules", "manual_review"]
    state: Literal["pending", "completed", "error"]
    normal_task_success: TaskVerdict = EvaluationStatus.NOT_EVALUATED
    attack_success: EvaluationStatus
    reason: str
    error_code: str | None = None
    created_at: str
    requested_by: str
    reviewer: str | None = None
    human_review: bool = False
    parent_evaluation_id: str | None = None
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluator_version: str = VERSION
    rubric_version: str = RUBRIC_VERSION
    policy_version: str = POLICY_VERSION
    prompt_version: str = PROMPT_VERSION
    prompt_sha256: str | None = None
    rubric_sha256: str | None = None
    policy_snapshot: dict = Field(default_factory=dict)
    rubric_snapshot: dict = Field(default_factory=dict)
    model_id: str | None = None
    endpoint: str | None = None
    parameters: dict = Field(default_factory=dict)
    execution_scope: str
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    dimensions: dict[str, Dimension] = Field(default_factory=dict)
    criteria: dict[str, Dimension] = Field(default_factory=dict)
    metrics: Metrics = Field(default_factory=Metrics)

    @model_validator(mode="after")
    def consistent_record(self):
        if self.state != "completed" and self.normal_task_success != EvaluationStatus.NOT_EVALUATED:
            raise ValueError("An unfinished/error evaluation cannot have a verdict")
        if (self.state == "error") != bool(self.error_code):
            raise ValueError("Evaluation state and error code disagree")
        if self.source != "manual_review" and (self.human_review or self.reviewer or self.parent_evaluation_id):
            raise ValueError("Automatic evaluations cannot claim manual review")
        return self


class TaskEvaluationReport(StrictModel):
    report_version: str = VERSION
    evaluation_source: Literal["normal_task_overlay"] = "normal_task_overlay"
    run_id: str
    case_id: str
    dataset_version: str
    corpus_version: str
    trace_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    judge_configured: bool
    max_model_calls: int = Field(ge=1)
    original_evaluation: EvaluationResult
    current_trace_evaluation: EvaluationResult
    # New results are selected explicitly; they never become legacy batch KPIs.
    records: list[TaskEvaluationRecord]
    latest: TaskEvaluationRecord | None = None
    revision: int
    reserved_model_calls: int
    report_sha256: str = ""
