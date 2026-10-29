"""Reproduce the week-four original-attack table from pinned public AI evidence."""
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path

from .batch import digest, file_hash
from .research_models import ResearchComparisonReport, ResearchFilters
from .research_reports import ROOT, research_report

BATCH_ID = "batch-bd093a919251"
CASE_IDS = ("w3_a001_original", "w3_a006_original", "w3_a021_original", "w3pv_a11")
CONDITION_IDS = ("none", "D1", "D2-input", "D2-retrieval", "D2-both", "D1-D2")
METRICS = {"fresh_ai_attack_success": "fresh_ai_attack_success",
           "fresh_ai_attack_task_utility": "fresh_ai_task_success"}


def _rate(members, field):
    included = [m for m in members if m[field] in ("success", "failure")]
    excluded = Counter(m[field] for m in members if m[field] not in ("success", "failure"))
    numerator = sum(m[field] == "success" for m in included)
    denominator = len(included)
    return {"value": numerator / denominator if denominator else None,
            "numerator": numerator, "denominator": denominator, "selected_count": len(members),
            "excluded": dict(sorted(excluded.items())), "ci95": None,
            "coverage_status": ("complete" if denominator == len(members) and denominator else
                                "partial" if denominator else "unavailable"),
            "unique_case_count": len({m["case_id"] for m in included}),
            "recorded_family_count": len({m["family_id"] for m in included})}


def original_attack_comparison(*, root=ROOT):
    source = research_report(BATCH_ID, ResearchFilters(source_id="week3"), root=root)
    members = [m for m in source.members if m["kind"] == "final_output" and m["case_id"] in CASE_IDS]
    expected = Counter((case, condition, repeat) for case in CASE_IDS
                       for condition in CONDITION_IDS for repeat in range(3))
    if (Counter((m["case_id"], m["condition_id"], m["repeat"]) for m in members) != expected or
            len({m["run_id"] for m in members}) != len(members) or
            len({m["task_id"] for m in members}) != len(members) or
            any(m["label"] != "attack" or m["source_id"] != "week3" for m in members)):
        raise ValueError("Original-attack comparison membership mismatch")
    by_run = {m["run_id"]: m for m in members}
    groups, linked = [], []
    for group in source.groups:
        ids = set(group["run_ids"])
        if not ids.intersection(by_run):
            continue
        if not ids or not ids.issubset(by_run):
            raise ValueError("Comparison cannot select part of a published cohort")
        selected = [by_run[rid] for rid in group["run_ids"]]
        if any(m["condition_id"] != group["cohort"]["condition_id"] or
               m["goal_kind"] != group["cohort"]["goal_kind"] for m in selected):
            raise ValueError("Comparison cohort membership mismatch")
        for metric, field in METRICS.items():
            calculated = _rate(selected, field)
            if any(group["metrics"][metric].get(key) != value for key, value in calculated.items()):
                raise ValueError("Comparison members differ from published metrics")
        groups.append(group)
        linked.extend(group["run_ids"])
    if Counter(linked) != Counter(by_run.keys()):
        raise ValueError("Comparison has missing or duplicate published run links")
    rows = []
    for condition in CONDITION_IDS:
        selected = sorted((m for m in members if m["condition_id"] == condition),
                          key=lambda m: (m["case_id"], m["repeat"]))
        goal_groups = []
        for goal in sorted({m["goal_kind"] for m in selected}):
            observations = [m for m in selected if m["goal_kind"] == goal]
            goal_groups.append({"goal_kind": goal, "run_ids": sorted(m["run_id"] for m in observations),
                                "source_group_ids": sorted(g["group_id"] for g in groups
                                    if g["cohort"]["condition_id"] == condition and g["cohort"]["goal_kind"] == goal),
                                "metrics": {name: _rate(observations, field) for name, field in METRICS.items()}})
        rows.append({"condition_id": condition, "display_condition": condition.replace("D1-D2", "D1+D2"),
                     "run_count": len(selected), "run_ids": sorted(m["run_id"] for m in selected),
                     "source_group_ids": sorted(g["group_id"] for g in groups if g["cohort"]["condition_id"] == condition),
                     "metrics": {name: _rate(selected, field) for name, field in METRICS.items()},
                     "goal_groups": goal_groups})
    # Only identifiers, hashes and typed verdicts enter this projection.
    fields = ("batch_id", "source_id", "case_id", "condition_id", "repeat", "family_id", "goal_kind",
              "run_id", "task_id", "unit_id", "source_sha256", "fresh_ai_attack_success", "fresh_ai_task_success")
    payload = dict(batch_id=BATCH_ID, schema_version="0.1", artifact_type="research_comparison_report",
        report_version="week4-original-attack-comparison-v0.1", evaluation_version=source.evaluation_version,
        evaluation_source=source.evaluation_source, evaluation_snapshot_sha256=source.evaluation_snapshot_sha256,
        selection={"source_id": "week3", "case_ids": list(CASE_IDS), "condition_ids": list(CONDITION_IDS),
                   "repeat_indices": [0, 1, 2], "output_runs": len(members),
                   "inference_status": "descriptive_mixed_goals_not_for_candidate_selection"},
        rows=rows, members=[{field: m[field] for field in fields} for m in sorted(members, key=lambda m: m["run_id"])],
        provenance={"source_files": source.provenance["source_files"], "source_report_sha256": source.report_sha256,
                    "source_filters": source.filters.model_dump(mode="json"),
                    "source_cohorts": {g["group_id"]: g["cohort"] for g in groups},
                    "calculation_implementation_sha256": file_hash(Path(__file__)),
                    "metric_sources": {name: "ai_research_overlay" for name in METRICS},
                    "human_review": source.provenance["human_review"], "model_calls": 0},
        limitations=["Attack utility is distinct from benign/hard-negative task success.",
                     "Combined counts describe mixed goals; use goal_groups for goal-specific interpretation.",
                     "Repeated/shared families are not independent; ci95=null.",
                     "This projection does not provide detector rates, latency, costs or holdout evidence."],
        decisions=source.decisions)
    return ResearchComparisonReport(**payload, report_sha256=digest(payload))


def comparison_csv(report):
    stream = io.StringIO(newline="")
    columns = ["batch_id", "report_version", "report_sha256", "evaluation_source", "evaluation_version",
               "evaluation_snapshot_sha256", "source_report_sha256", "source_files", "selection", "human_review",
               "decision_status", "inference_status", "condition_id", "display_condition", "goal_kind",
               "run_ids", "source_group_ids", "metric", "metric_source", "value", "numerator", "denominator",
               "selected_count", "excluded", "coverage_status", "unique_case_count", "recorded_family_count", "ci95"]
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    encoded = lambda value: json.dumps(value, sort_keys=True)
    common = {key: getattr(report, key) for key in ("batch_id", "report_version", "report_sha256",
              "evaluation_source", "evaluation_version", "evaluation_snapshot_sha256")}
    common.update(source_report_sha256=report.provenance["source_report_sha256"],
                  source_files=encoded(report.provenance["source_files"]), selection=encoded(report.selection),
                  human_review=report.provenance["human_review"], decision_status=report.decisions["status"],
                  inference_status=report.selection["inference_status"])
    for row in report.rows:
        for section in [{"goal_kind": "combined_descriptive", "metrics": row["metrics"], "run_ids": row["run_ids"]},
                        *row["goal_groups"]]:
            for name, metric in section["metrics"].items():
                writer.writerow({**common, "condition_id": row["condition_id"], "display_condition": row["display_condition"],
                    "goal_kind": section["goal_kind"], "run_ids": encoded(section["run_ids"]),
                    "source_group_ids": encoded(section.get("source_group_ids", row["source_group_ids"])), "metric": name,
                    "metric_source": report.provenance["metric_sources"][name],
                    "inference_status": (report.selection["inference_status"] if section["goal_kind"] == "combined_descriptive"
                                         else "family_independence_not_validated_small_strata"),
                    **{key: metric[key] for key in ("value", "numerator", "denominator", "selected_count",
                                                  "coverage_status", "unique_case_count", "recorded_family_count")},
                    "excluded": encoded(metric["excluded"]), "ci95": encoded(metric["ci95"])})
    return stream.getvalue()
