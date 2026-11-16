"""Explicit, read-only research overlay contract; batch/execution contracts stay intact."""
from __future__ import annotations

from typing import Literal

from .batch_models import BatchModel
from .shared_variables import RESEARCH_EXPORT

RESEARCH_VERSION = "week3-two-ai-review-v0.1"
RESEARCH_REPORT_VERSION = RESEARCH_EXPORT["report_version"]


class ResearchFilters(BatchModel):
    evaluation_version: Literal[RESEARCH_VERSION] = RESEARCH_VERSION
    source_id: str | None = None
    scenario: str | None = None
    language: str | None = None
    split: Literal["dev"] | None = None
    condition_id: str | None = None
    goal_kind: str | None = None
    ablation_variant: str | None = None
    severity: str | None = None
    attack_type: str | None = None
    execution_kind: str | None = None
    model_id: str | None = None
    evaluator_version: str | None = None
    evaluation_policy_version: str | None = None
    pricing_version: str | None = None


class ResearchReport(BatchModel):
    schema_version: Literal["0.1"] = "0.1"
    artifact_type: Literal["research_overlay_report"] = "research_overlay_report"
    report_version: Literal["week4-public-overlay-v0.1", "week4-public-overlay-v0.2"] = RESEARCH_REPORT_VERSION
    batch_id: str
    evaluation_version: Literal[RESEARCH_VERSION] = RESEARCH_VERSION
    evaluation_source: Literal["ai_research_overlay"] = "ai_research_overlay"
    report_sha256: str
    evaluation_snapshot_sha256: str
    filters: ResearchFilters
    provenance: dict
    counts: dict
    groups: list[dict]
    target_gold_groups: list[dict]
    members: list[dict]
    capabilities: dict
    decisions: dict


class ResearchComparisonReport(BatchModel):
    """Fixed final-report selection, separate from the archived overlay formats."""

    schema_version: Literal["0.1"] = "0.1"
    artifact_type: Literal["research_comparison_report"] = "research_comparison_report"
    report_version: Literal["week4-original-attack-comparison-v0.1"] = "week4-original-attack-comparison-v0.1"
    batch_id: str
    evaluation_version: Literal[RESEARCH_VERSION] = RESEARCH_VERSION
    evaluation_source: Literal["ai_research_overlay"] = "ai_research_overlay"
    report_sha256: str
    evaluation_snapshot_sha256: str
    selection: dict
    rows: list[dict]
    members: list[dict]
    provenance: dict
    limitations: list[str]
    decisions: dict
