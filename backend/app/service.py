from __future__ import annotations

import base64
import json
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .accounting import Accounting
from .config import Settings
from .defenses import Classifier, LLMInjectionClassifier
from .evaluation import EvaluationContext, Evaluator, ManualEvaluator, RuleEvaluator
from .models import (CaseRecord, DefenseEvent, EvaluationUpdate, Manifest, ModelCall,
                     OutputRecord, PromptComponent, RunRequest, RunTrace, StageMetric)
from .prompts import D1_VERSION, prepare_prompt
from .providers import DemoRagProvider, OpenAICompatibleProvider, ProviderError
from .repository import ArtifactNotFound, ArtifactValidationError, ExperimentRepository, RunTraceStore
from .retrieval import lexical_retrieve
from .shared_variables import (DefenseDecision, DefenseMode, DefensePosition, DetectorErrorPolicy,
                               ExecutionScope, KEYS, OutputOutcome, RunStatus, Scenario, TraceStage)

CANARY_PATTERN = re.compile(r"CANARY_[A-Z0-9_]+")


class UnsupportedDefenseMode(Exception):
    """Reserved for a future defense mode outside the shared contract."""


def mask_display_text(text: str) -> tuple[str, bool]:
    masked = CANARY_PATTERN.sub("[MASKED_CANARY]", text)
    return masked, masked != text


class TraceableRunError(Exception):
    def __init__(self, trace: RunTrace, error_code: str, http_status: int, cause: Exception):
        super().__init__(mask_display_text(str(cause))[0])
        self.trace, self.error_code, self.http_status = trace, error_code, http_status


@dataclass
class Execution:
    request: RunRequest
    manifest: Manifest
    run_id: str = field(default_factory=lambda: f"run-{uuid.uuid4().hex[:12]}")
    started: float = field(default_factory=time.perf_counter)
    case: CaseRecord | None = None
    retrieval: list = field(default_factory=list)
    components: list[PromptComponent] = field(default_factory=list)
    events: list[DefenseEvent] = field(default_factory=list)
    calls: list[ModelCall] = field(default_factory=list)
    stages: list[StageMetric] = field(default_factory=list)
    raw_output: str | None = None
    skipped: str | None = None


class RunService:
    def __init__(self, settings: Settings, repository: ExperimentRepository,
                 trace_store: RunTraceStore, provider: Any,
                 classifier: Classifier | None = None, evaluator: Evaluator | None = None):
        self._settings, self._repository, self._trace_store, self._provider = settings, repository, trace_store, provider
        self._classifier = classifier or build_classifier(settings)
        self._evaluator = evaluator or (RuleEvaluator(settings.evaluation_rules_path)
                                       if settings.evaluation_rules_path else ManualEvaluator())
        self._accounting = Accounting(settings.pricing_path)

    @contextmanager
    def _stage(self, execution: Execution, stage: TraceStage):
        started = time.perf_counter()
        try:
            yield
        finally:
            execution.stages.append(StageMetric(stage=stage, latency_ms=round((time.perf_counter()-started)*1000)))

    def _budget(self, execution: Execution):
        if len(execution.calls) >= self._settings.max_model_calls:
            execution.skipped = "model_call_budget_exceeded"
            raise ProviderError("요청의 모델 호출 제한을 초과했습니다.", "MODEL_CALL_BUDGET_EXCEEDED")

    def _record(self, execution: Execution, call: ModelCall | None):
        if call is not None:
            self._accounting.price(call)
            execution.calls.append(call)

    def _inspect(self, execution: Execution, text: str, stage: TraceStage, target_ref: str | None):
        threshold = execution.manifest.d2_configuration["threshold"]
        try:
            self._budget(execution)
            if self._classifier is None:
                raise ProviderError("D2_BASE_URL 또는 MODEL_BASE_URL을 설정해야 합니다.", "D2_NOT_CONFIGURED")
            detection, response = self._classifier.classify(text, stage, target_ref)
            self._record(execution, response.call)
            suspicious = detection.score >= threshold
            decision = (DefenseDecision.BLOCK if stage == TraceStage.INPUT or self._settings.d2_document_action == DefenseDecision.BLOCK
                        else DefenseDecision.QUARANTINE) if suspicious else DefenseDecision.ALLOW
            execution.events.append(DefenseEvent(
                defense_id=DefenseMode.D2, defense_version=self._settings.d2_version, stage=stage,
                decision=decision, score=detection.score, threshold=threshold,
                target_ref=target_ref, policy_version=self._settings.d2_policy_version,
                reason_code=detection.reason_code, reason=detection.reason, score_kind="llm_self_reported"))
            return decision
        except ProviderError as exc:
            self._record(execution, exc.call)
            closed = self._settings.d2_error_policy == DetectorErrorPolicy.FAIL_CLOSED
            execution.events.append(DefenseEvent(
                defense_id=DefenseMode.D2, defense_version=self._settings.d2_version, stage=stage,
                decision=DefenseDecision.BLOCK if closed else DefenseDecision.ALLOW,
                score=None, threshold=threshold, target_ref=target_ref,
                policy_version=self._settings.d2_policy_version, reason_code=exc.code,
                reason="detector_error_fail_closed" if closed else "detector_error_fail_open", error=str(exc)))
            if closed or exc.code == "MODEL_CALL_BUDGET_EXCEEDED":
                if exc.code != "MODEL_CALL_BUDGET_EXCEEDED":
                    execution.skipped = "detector_error"
                raise ProviderError(str(exc), exc.code) from exc
            return DefenseDecision.ALLOW

    def execute(self, request: RunRequest) -> RunTrace:
        execution = Execution(request, self._build_manifest(request))
        d1 = request.defense_mode in (DefenseMode.D1, DefenseMode.D1_D2)
        d2 = request.defense_mode in (DefenseMode.D2, DefenseMode.D1_D2)
        try:
            with self._stage(execution, TraceStage.INPUT):
                execution.case = self._repository.get_case(request.case_id)
                case = execution.case
                self._validate_request_against_case(request, case)
                if d2 and request.defense_position in (DefensePosition.INPUT, DefensePosition.BOTH):
                    decision = self._inspect(execution, case.user_input, TraceStage.INPUT, None)
                else:
                    decision = DefenseDecision.ALLOW
            if decision == DefenseDecision.BLOCK:
                execution.skipped = "input_blocked"
                return self._finish(execution, RunStatus.BLOCKED, OutputOutcome.BLOCKED)
            with self._stage(execution, TraceStage.RETRIEVAL):
                documents = self._repository.get_documents(case.source_document_ids, request.corpus_version)
                if request.scenario == Scenario.EMAIL_SUMMARY:
                    from .models import RetrievalItem
                    ranked = [(doc, RetrievalItem(document_id=doc.document_id, rank=index, score=None, included_in_prompt=True))
                              for index, doc in enumerate(documents, 1)]
                else:
                    ranked = lexical_retrieve(case.user_input, documents)
                execution.retrieval = [item for _, item in ranked]
            included = []
            for document, item in ranked:
                decision = DefenseDecision.ALLOW
                if d2 and request.defense_position in (DefensePosition.DOCUMENTS, DefensePosition.BOTH):
                    with self._stage(execution, TraceStage.RETRIEVAL):
                        decision = self._inspect(execution, document.title+"\n"+document.content,
                                                 TraceStage.RETRIEVAL, document.document_id)
                item.included_in_prompt = decision == DefenseDecision.ALLOW
                if decision == DefenseDecision.BLOCK:
                    # No generation occurs, so no retrieved item reaches a prompt.
                    for result in execution.retrieval:
                        result.included_in_prompt = False
                    execution.skipped = "document_blocked"
                    return self._finish(execution, RunStatus.BLOCKED, OutputOutcome.BLOCKED)
                if item.included_in_prompt:
                    included.append(document)
            if ranked and not included:
                execution.skipped = "all_documents_quarantined"
                return self._finish(execution, RunStatus.BLOCKED, OutputOutcome.BLOCKED)
            with self._stage(execution, TraceStage.PROMPT_ASSEMBLY):
                prompt = prepare_prompt(case.user_input, included, request.scenario, d1, self._settings.system_prompt_version)
                execution.components = prompt.components
                if d1:
                    execution.events.append(DefenseEvent(
                        defense_id=DefenseMode.D1, defense_version=D1_VERSION, stage=TraceStage.PROMPT_ASSEMBLY,
                        decision=DefenseDecision.ALLOW, reason_code="instruction_data_boundary_applied"))
            with self._stage(execution, TraceStage.OUTPUT):
                self._budget(execution)
                try:
                    if hasattr(self._provider, "generate_prepared"):
                        response = self._provider.generate_prepared(prompt, execution.manifest.generation_parameters)
                    else:
                        if d1:
                            raise ProviderError("D1에는 generate_prepared 프롬프트 인터페이스가 필요합니다.", "PROVIDER_PROMPT_INTERFACE_REQUIRED")
                        response = self._provider.generate(case.user_input, included)
                    self._record(execution, response.call if hasattr(response, "call") else None)
                except ProviderError as exc:
                    self._record(execution, exc.call)
                    raise
                execution.raw_output = response.text
            return self._finish(execution, RunStatus.COMPLETED, OutputOutcome.GENERATED)
        except ProviderError as exc:
            outcome = OutputOutcome.BLOCKED if execution.skipped == "detector_error" else OutputOutcome.ERROR
            return self._finish(execution, RunStatus.FAILED, outcome, exc.code, str(exc))
        except (ArtifactNotFound, ArtifactValidationError, ValueError) as exc:
            code = "ARTIFACT_NOT_FOUND" if isinstance(exc, ArtifactNotFound) else "INVALID_EXPERIMENT_INPUT"
            trace = self._finish(execution, RunStatus.FAILED, OutputOutcome.ERROR, code, str(exc))
            raise TraceableRunError(trace, code, 404 if isinstance(exc, ArtifactNotFound) else 422, exc) from exc

    def _safe(self, value, canaries=()):
        if isinstance(value, str):
            masked = value
            for canary in canaries:
                masked = masked.replace(base64.b64encode(canary.encode()).decode(), "[MASKED_CANARY]")
                encoded = "".join(f"(?:{re.escape(character)}|%{ord(character):02X})" for character in canary)
                masked = re.sub(encoded, "[MASKED_CANARY]", masked, flags=re.IGNORECASE)
                masked = re.sub(r"\s*".join(re.escape(character) for character in canary), "[MASKED_CANARY]", masked)
            masked = mask_display_text(masked)[0]
            for secret in (self._settings.model_api_key, self._settings.d2_api_key):
                if secret:
                    masked = masked.replace(secret, "[MASKED_CREDENTIAL]")
            return masked
        if isinstance(value, dict):
            return {key: self._safe(item, canaries) for key, item in value.items()}
        if isinstance(value, list):
            return [self._safe(item, canaries) for item in value]
        return value

    def _finish(self, execution: Execution, status: RunStatus, outcome: OutputOutcome,
                error_code: str | None = None, error_message: str | None = None) -> RunTrace:
        if not execution.components:
            for item in execution.retrieval:
                item.included_in_prompt = False
        with self._stage(execution, TraceStage.EVALUATION):
            try:
                evaluation = self._evaluator.evaluate(EvaluationContext(execution.case, status, execution.raw_output))
            except Exception as exc:
                from .models import EvaluationResult
                from .shared_variables import EvaluationStatus
                evaluation = EvaluationResult(attack_success=EvaluationStatus.NOT_EVALUATED,
                    normal_task_success=EvaluationStatus.NOT_EVALUATED,
                    evaluator_version=self._evaluator.version,
                    reason=f"evaluator_error:{type(exc).__name__}")
        raw_input = {"user_input": execution.case.user_input if execution.case else "",
                     "external_document_ids": execution.case.source_document_ids if execution.case else []}
        raw = {
            KEYS["ARTIFACT_TYPE"]: "private_raw_run_log", KEYS["RUN_ID"]: execution.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(), "request": execution.request.model_dump(mode="json"),
            "input": raw_input, "retrieval": [item.model_dump(mode="json") for item in execution.retrieval],
            "prompt_assembly": [item.model_dump(mode="json") for item in execution.components],
            "model_calls": [call.model_dump(mode="json") for call in execution.calls],
            "provider_output": execution.raw_output, "provider_error": error_message,
            "evaluation": evaluation.model_dump(mode="json"),
        }
        self._trace_store.save_raw(execution.run_id, raw)
        canaries = set(CANARY_PATTERN.findall(json.dumps(raw)))
        components = []
        for component in execution.components:
            safe = self._safe(component.display_text, canaries)
            components.append(component.model_copy(update={"display_text": safe, "is_masked": safe != component.display_text}))
        metrics = self._accounting.metrics(execution.calls, execution.stages,
                                           round((time.perf_counter()-execution.started)*1000), execution.skipped)
        output = self._safe(execution.raw_output, canaries) if execution.raw_output is not None else None
        trace = RunTrace(
            run_id=execution.run_id, status=status, created_at=raw["created_at"], request=execution.request,
            manifest=execution.manifest, input=self._safe(raw_input, canaries), retrieval=execution.retrieval,
            prompt_assembly=components, defense_events=[DefenseEvent.model_validate(self._safe(event.model_dump(mode="json"), canaries))
                                                       for event in execution.events],
            output=OutputRecord(outcome=outcome, display_text=output,
                                is_masked=output != execution.raw_output),
            evaluation=type(evaluation).model_validate(self._safe(evaluation.model_dump(mode="json"), canaries)), metrics=metrics,
            error={"code": error_code, "message": self._safe(error_message, canaries)} if error_code else None,
            model_calls=[ModelCall.model_validate(self._safe(call.model_dump(mode="json"), canaries)) for call in execution.calls])
        self._trace_store.save(trace)
        return trace

    def _build_manifest(self, request: RunRequest) -> Manifest:
        d1 = request.defense_mode in (DefenseMode.D1, DefenseMode.D1_D2)
        d2 = request.defense_mode in (DefenseMode.D2, DefenseMode.D1_D2)
        versions = {}
        if d1:
            versions[str(DefenseMode.D1)] = D1_VERSION
        if d2:
            versions[str(DefenseMode.D2)] = self._settings.d2_version
        scope = (ExecutionScope.DEMO if self._settings.model_provider == "demo" else ExecutionScope.FIXTURE
                 if self._settings.model_provider == "fixture_http" else ExecutionScope.REAL)
        return Manifest(
            model_id=self._settings.model_id, provider=self._settings.model_provider, execution_scope=scope,
            base_system_prompt_version=self._settings.system_prompt_version,
            system_prompt_version=(self._settings.system_prompt_version+"+"+D1_VERSION if d1
                                   else self._settings.system_prompt_version),
            generation_parameters={"temperature": self._settings.temperature, "max_tokens": self._settings.max_tokens},
            retrieval_config_version=self._settings.retrieval_config_version, defense_config_versions=versions,
            defense_position=request.defense_position, evaluator_version=self._evaluator.version,
            pricing_version=self._accounting.book.version if self._accounting.book else None,
            pricing_snapshot=self._accounting.book.model_dump(mode="json") if self._accounting.book else {},
            max_model_calls=self._settings.max_model_calls,
            d2_configuration={"model_id": self._settings.d2_model_id or self._settings.model_id,
                              "detector_version": self._settings.d2_version, "policy_version": self._settings.d2_policy_version,
                              "threshold": request.d2_threshold if request.d2_threshold is not None else self._settings.d2_threshold,
                              "error_policy": self._settings.d2_error_policy,
                              "input_action": DefenseDecision.BLOCK, "document_action": self._settings.d2_document_action}
            if d2 else {})

    @staticmethod
    def _validate_request_against_case(request: RunRequest, case: CaseRecord):
        if request.scenario != case.scenario:
            raise ValueError("요청 scenario와 case scenario가 다릅니다.")
        if request.dataset_version != case.source_version:
            raise ValueError("요청 dataset_version과 case source_version이 다릅니다.")

    def get_trace(self, run_id: str) -> RunTrace:
        return self._trace_store.get(run_id)

    def update_evaluation(self, run_id: str, update: EvaluationUpdate) -> RunTrace:
        trace = self.get_trace(run_id)
        from .shared_variables import EvaluationStatus
        if trace.status == RunStatus.FAILED and any(value in (EvaluationStatus.SUCCESS, EvaluationStatus.FAILURE)
            for value in (update.attack_success, update.normal_task_success)):
            raise ValueError("실행 실패는 성공·실패 평가의 집계 대상에 포함할 수 없습니다.")
        evaluation = update.model_dump(mode="json")
        evaluation["evaluated_at"] = datetime.now(timezone.utc).isoformat()
        self._trace_store.save_evaluation(run_id, evaluation)
        from .models import EvaluationResult
        trace.evaluation = EvaluationResult.model_validate(self._safe(evaluation))
        trace.manifest.evaluator_version = trace.evaluation.evaluator_version
        self._trace_store.save(trace)
        return trace


def build_provider(settings: Settings):
    if settings.model_provider == "demo":
        return DemoRagProvider()
    if settings.model_provider in ("openai_compatible", "fixture_http"):
        if not settings.model_base_url:
            raise ValueError("HTTP 제공자에는 MODEL_BASE_URL이 필요합니다.")
        return OpenAICompatibleProvider(settings.model_base_url, settings.model_api_key, settings.model_id,
                                         settings.model_timeout_seconds)
    raise ValueError("MODEL_PROVIDER must be demo, openai_compatible or fixture_http")


def build_classifier(settings: Settings):
    base_url = settings.d2_base_url or settings.model_base_url
    if not base_url:
        return None
    return LLMInjectionClassifier(OpenAICompatibleProvider(
        base_url, settings.d2_api_key or settings.model_api_key, settings.d2_model_id or settings.model_id,
        settings.model_timeout_seconds))
