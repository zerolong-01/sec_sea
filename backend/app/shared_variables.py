"""Backend constants sourced from the shared, versioned JSON contract."""
from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

SHARED_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "shared-variables-v0.1.json"
)
_shared = json.loads(SHARED_PATH.read_text(encoding="utf-8"))


def _value(group: str, name: str) -> str:
    value = _shared[group][name]["value"]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{SHARED_PATH.name}: invalid {group}.{name}.value")
    return value


KEYS = MappingProxyType(_shared["keys"])
METRIC_KEYS = MappingProxyType(
    {name: _value("metric_keys", name) for name in _shared["metric_keys"]}
)
CANONICAL_PATHS = MappingProxyType(_shared["canonical_paths"])
_stages = {item["value"].upper(): item["value"] for item in _shared["trace_stages"]}


class SchemaVersion(StrEnum):
    CURRENT = _shared["contract_version"]
    PREVIOUS_EXECUTION = _shared["previous_execution_contract_version"]
    EXECUTION = _shared["execution_contract_version"]


class ExecutionKind(StrEnum):
    FULL_PIPELINE = _value("execution_kinds", "FULL_PIPELINE")
    DETECTOR_ONLY = _value("execution_kinds", "DETECTOR_ONLY")


class DetectorConsistencyPolicy(StrEnum):
    THRESHOLD_ONLY = _value("detector_consistency_policies", "THRESHOLD_ONLY")
    REVIEW_ON_CONTRADICTION = _value("detector_consistency_policies", "REVIEW_ON_CONTRADICTION")


class DetectorResponseFormat(StrEnum):
    PROMPT_ONLY = _value("detector_response_formats", "PROMPT_ONLY")
    JSON_SCHEMA = _value("detector_response_formats", "JSON_SCHEMA")


class DetectorGoldLabel(StrEnum):
    MALICIOUS = _value("detector_gold_labels", "MALICIOUS")
    BENIGN = _value("detector_gold_labels", "BENIGN")
    HARD_NEGATIVE = _value("detector_gold_labels", "HARD_NEGATIVE")
    REVIEW_NEEDED = _value("detector_gold_labels", "REVIEW_NEEDED")


class DetectorAnalysisStatus(StrEnum):
    CORRECT = _value("detector_analysis_statuses", "CORRECT")
    MISCLASSIFICATION = _value("detector_analysis_statuses", "MISCLASSIFICATION")
    ERROR = _value("detector_analysis_statuses", "ERROR")
    REVIEW_NEEDED = _value("detector_analysis_statuses", "REVIEW_NEEDED")
    NOT_EVALUATED = _value("detector_analysis_statuses", "NOT_EVALUATED")


class DefensePosition(StrEnum):
    INPUT = _value("defense_positions", "INPUT")
    DOCUMENTS = _value("defense_positions", "DOCUMENTS")
    BOTH = _value("defense_positions", "BOTH")


class DetectorErrorPolicy(StrEnum):
    FAIL_CLOSED = _value("detector_error_policies", "FAIL_CLOSED")
    FAIL_OPEN = _value("detector_error_policies", "FAIL_OPEN")


class UsageSource(StrEnum):
    OBSERVED = _value("usage_sources", "OBSERVED")
    ESTIMATED = _value("usage_sources", "ESTIMATED")
    UNKNOWN = _value("usage_sources", "UNKNOWN")
    NOT_CALLED = _value("usage_sources", "NOT_CALLED")


class ExecutionScope(StrEnum):
    DEMO = _value("execution_scopes", "DEMO")
    FIXTURE = _value("execution_scopes", "FIXTURE")
    REAL = _value("execution_scopes", "REAL")


class CallPurpose(StrEnum):
    GENERATION = _value("call_purposes", "GENERATION")
    DETECTION = _value("call_purposes", "DETECTION")


class ArtifactType(StrEnum):
    CASE = _value("artifact_types", "CASE")
    SOURCE_DOCUMENT = _value("artifact_types", "SOURCE_DOCUMENT")
    RUN_REQUEST = _value("artifact_types", "RUN_REQUEST")
    RUN_TRACE = _value("artifact_types", "RUN_TRACE")


class Scenario(StrEnum):
    RAG_CHAT = _value("scenarios", "RAG_CHAT")
    EMAIL_SUMMARY = _value("scenarios", "EMAIL_SUMMARY")


class Language(StrEnum):
    KOREAN = _value("languages", "KOREAN")
    ENGLISH = _value("languages", "ENGLISH")
    MIXED = _value("languages", "MIXED")


class DataSplit(StrEnum):
    DEV = _value("splits", "DEV")
    HOLDOUT = _value("splits", "HOLDOUT")


class CaseLabel(StrEnum):
    ATTACK = _value("case_labels", "ATTACK")
    BENIGN = _value("case_labels", "BENIGN")
    HARD_NEGATIVE = _value("case_labels", "HARD_NEGATIVE")


class DefenseMode(StrEnum):
    NONE = _value("defense_modes", "NONE")
    D1 = _value("defense_modes", "D1")
    D2 = _value("defense_modes", "D2")
    D1_D2 = _value("defense_modes", "D1_D2")


class RunStatus(StrEnum):
    QUEUED = _value("run_statuses", "QUEUED")
    RUNNING = _value("run_statuses", "RUNNING")
    COMPLETED = _value("run_statuses", "COMPLETED")
    BLOCKED = _value("run_statuses", "BLOCKED")
    FAILED = _value("run_statuses", "FAILED")


class OutputOutcome(StrEnum):
    GENERATED = _value("output_outcomes", "GENERATED")
    BLOCKED = _value("output_outcomes", "BLOCKED")
    SUBSTITUTED = _value("output_outcomes", "SUBSTITUTED")
    ERROR = _value("output_outcomes", "ERROR")
    NOT_GENERATED = _value("output_outcomes", "NOT_GENERATED")


class PromptComponentType(StrEnum):
    SYSTEM = _value("prompt_component_types", "SYSTEM")
    USER = _value("prompt_component_types", "USER")
    RETRIEVED_DOCUMENT = _value("prompt_component_types", "RETRIEVED_DOCUMENT")
    DEFENSE_INSTRUCTION = _value("prompt_component_types", "DEFENSE_INSTRUCTION")


class TraceStage(StrEnum):
    INPUT = _stages["INPUT"]
    RETRIEVAL = _stages["RETRIEVAL"]
    PROMPT_ASSEMBLY = _stages["PROMPT_ASSEMBLY"]
    DEFENSE_EVENTS = _stages["DEFENSE_EVENTS"]
    OUTPUT = _stages["OUTPUT"]
    EVALUATION = _stages["EVALUATION"]
    METRICS = _stages["METRICS"]


class DefenseDecision(StrEnum):
    ALLOW = _value("defense_decisions", "ALLOW")
    BLOCK = _value("defense_decisions", "BLOCK")
    REDACT = _value("defense_decisions", "REDACT")
    QUARANTINE = _value("defense_decisions", "QUARANTINE")


class EvaluationStatus(StrEnum):
    SUCCESS = _value("evaluation_statuses", "SUCCESS")
    FAILURE = _value("evaluation_statuses", "FAILURE")
    NOT_APPLICABLE = _value("evaluation_statuses", "NOT_APPLICABLE")
    NOT_EVALUATED = _value("evaluation_statuses", "NOT_EVALUATED")
    REVIEW_NEEDED = _value("evaluation_statuses", "REVIEW_NEEDED")
