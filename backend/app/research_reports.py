"""Serve hash-pinned public evidence without private runs, providers, or live settings.

Filters select whole published cohorts. Unsupported run/family filters are rejected
by ResearchFilters instead of silently returning an unfiltered denominator.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .batch import digest, file_hash
from .repository import ArtifactNotFound
from .research_models import RESEARCH_VERSION, ResearchFilters, ResearchReport

ROOT = Path(__file__).resolve().parents[2]
INDEX = "configs/week4-release-index.v0.1.json"


def load_evidence(root=ROOT):
    reference = json.loads((root / INDEX).read_text(encoding="utf-8"))["research_overlay"]
    summary_path = root / reference["path"]
    if file_hash(summary_path) != reference["sha256"]:
        raise ValueError("Research summary hash mismatch")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary["version"] != RESEARCH_VERSION or summary["applied_to_original_store"]:
        raise ValueError("Unsupported research source")
    files = {reference["path"]: reference["sha256"]}
    records = {}
    # Only these fixed, repository-owned files can enter the public projection.
    for name in ("members", "metrics", "units"):
        ref = summary["references"][name]
        path = (summary_path.parent / ref["path"]).resolve()
        if not path.is_relative_to(summary_path.parent.resolve()) or file_hash(path) != ref["sha256"]:
            raise ValueError("Research evidence hash mismatch")
        records[name] = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        if len(records[name]) != ref["record_count"]:
            raise ValueError("Research evidence count mismatch")
        files[path.relative_to(root.resolve()).as_posix()] = ref["sha256"]
    policy = (summary_path.parent / summary["policy"]["path"]).resolve()
    if not policy.is_relative_to(root.resolve()) or file_hash(policy) != summary["policy"]["sha256"]:
        raise ValueError("Research policy hash mismatch")
    files[policy.relative_to(root.resolve()).as_posix()] = summary["policy"]["sha256"]
    return summary, records, files


def available_sources(batch_id, *, root=ROOT):
    _, records, files = load_evidence(root)
    available = any(row["batch_id"] == batch_id for row in records["members"])
    return {"batch_id": batch_id, "default": "original_saved_evaluation",
            "original_requires_private_store": True,
            "research": {"evaluation_version": RESEARCH_VERSION, "available": available,
                         "evaluation_source": "ai_research_overlay", "human_review": "not_performed",
                         "source_files": files if available else {}}}


def research_report(batch_id, filters=None, *, root=ROOT):
    filters = filters or ResearchFilters()
    summary, records, files = load_evidence(root)
    batch_members = [r for r in records["members"] if r["batch_id"] == batch_id]
    if not batch_members:
        raise ArtifactNotFound("No published research overlay for this batch")
    selected = filters.model_dump(exclude_none=True, exclude={"evaluation_version"})
    groups, gold_groups = [], []
    for row in records["metrics"]:
        cohort = row["cohort"]
        if cohort["batch_id"] != batch_id or any(cohort.get(k) != v for k, v in selected.items()):
            continue
        (groups if row["kind"] == "final_output_metrics" else gold_groups).append(row)
    output_ids = {run_id for g in groups for run_id in g["run_ids"]}
    target_groups = {}
    for group in gold_groups:
        cohort = group["cohort"]
        key = (cohort["source_id"], cohort["condition_id"], cohort["stage"])
        target_groups.setdefault(key, set()).update(group["run_ids"])
    members = [r for r in batch_members if
               (r["kind"] == "final_output" and r["run_id"] in output_ids) or
               (r["kind"] == "detector_target" and r["run_id"] in target_groups.get(
                   (r["source_id"], r["condition_id"], r["stage"]), set()))]
    # Consensus has typed judgments only; free-text votes/reasons and source text
    # stay in their separately audited source artifacts, outside this API/export.
    units = {r["unit_id"]: r for r in records["units"]}
    members = [{**r, "consensus": units[r["unit_id"]]["consensus"]} for r in members]
    capabilities = {key: {"value": None, "reason": reason} for key, reason in {
        "normal_benchmark": "not_published_for_this_overlay",
        "paired_changes": "not_published_for_this_overlay",
        "resources": "use_original_saved_report_without_reaveraging",
        "detector_fnr_fpr": "published_gold_counts_do_not_include_detector_decisions",
        "confidence_intervals": "family_independence_not_validated_small_strata",
    }.items()}
    payload = dict(batch_id=batch_id, evaluation_version=RESEARCH_VERSION,
        evaluation_source="ai_research_overlay", report_version="week4-public-overlay-v0.1",
        schema_version="0.1", artifact_type="research_overlay_report",
        evaluation_snapshot_sha256=digest(files), filters=filters.model_dump(mode="json"),
        provenance={"source_files": files, "source_summary_sha256": files[next(iter(files))],
                    "calculation_implementation_sha256": file_hash(Path(__file__)),
                    "human_review": summary["human_review"], "review_route": summary["review_route"],
                    "review_status": summary["review_status"], "decision_status": summary["decision_status"],
                    "research_decision": summary["research_decision"], "statistics": summary["statistics"],
                    "applied_to_original_store": False, "model_calls": 0,
                    "metric_sources": {"original_asr": "original_saved_evaluation",
                        "fresh_ai_attack_success": "ai_research_overlay",
                        "fresh_ai_normal_task_success": "ai_research_overlay",
                        "fresh_ai_attack_task_utility": "ai_research_overlay",
                        "benign_fpr": "original_structural_actions_then_ai_excessive_transformation",
                        "hard_negative_fpr": "original_structural_actions_then_ai_excessive_transformation"}},
        counts={"output_runs": len(output_ids), "target_observations": sum(r["kind"] == "detector_target" for r in members),
                "members": len(members), "output_groups": len(groups), "target_gold_groups": len(gold_groups),
                "unresolved_members": sum(r["contains_unresolved_judgment"] for r in members)},
        groups=groups, target_gold_groups=gold_groups, members=members, capabilities=capabilities,
        decisions={"status": "deferred", "no_candidate": True, "holdout_authorized": False,
                   "reasons": ["research_overlay_is_descriptive", "independent_human_review_pending",
                               "family_independence_not_validated_small_strata"], "records": []})
    return ResearchReport(**payload, report_sha256=digest(payload))


def research_csv(report):
    stream = io.StringIO(newline="")
    fields = ["batch_id", "report_version", "report_sha256", "evaluation_version", "evaluation_snapshot_sha256",
              "filters", "source_files", "research_policy_versions", "human_review", "decision_status", "group_id", "cohort", "run_ids", "metric", "metric_source", "value", "numerator", "denominator",
              "selected_count", "excluded", "unique_case_count", "recorded_family_count", "ci95", "inference_status"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for group in report.groups:
        for name, metric in group["metrics"].items():
            writer.writerow({"batch_id": report.batch_id, "report_version": report.report_version,
                "report_sha256": report.report_sha256, "evaluation_version": report.evaluation_version,
                "evaluation_snapshot_sha256": report.evaluation_snapshot_sha256,
                "filters": json.dumps(report.filters.model_dump(exclude_none=True), sort_keys=True),
                "source_files": json.dumps(report.provenance["source_files"], sort_keys=True),
                "research_policy_versions": json.dumps(report.provenance["research_decision"], sort_keys=True),
                "human_review": report.provenance["human_review"], "decision_status": report.decisions["status"],
                "group_id": group["group_id"], "cohort": json.dumps(group["cohort"], sort_keys=True),
                "run_ids": json.dumps(group["run_ids"]), "metric": name,
                "metric_source": report.provenance["metric_sources"][name],
                **{key: metric[key] for key in ("value", "numerator", "denominator", "selected_count", "unique_case_count", "recorded_family_count", "inference_status")},
                "excluded": json.dumps(metric["excluded"], sort_keys=True), "ci95": "null"})
    return stream.getvalue()
