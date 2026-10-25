"""Descriptive cross-model comparisons of compatible saved batch reports."""
from __future__ import annotations

import csv
import io
import json
import tempfile
from pathlib import Path

from .batch import digest, file_hash
from .batch_analysis import aggregate
from .batch_models import BatchFilters
from .experiment_models import ExperimentReport
from .experiments import ExperimentRunner
from .repository import ArtifactValidationError
from .storage import atomic_json

DIMENSIONS = ("source_id", "scenario", "language", "split", "ablation_variant", "goal_kind",
              "execution_kind", "evaluator_version", "evaluation_policy_version", "pricing_version", "condition_id")
METRICS = ("asr", "benign_fpr", "hard_negative_fpr", "task_success", "latency_p50_ms",
           "latency_p95_ms", "input_tokens", "output_tokens", "cost_per_request_usd", "run_failure_rate")


def source_inventory(runner, state):
    paths = {runner.store.folder(state.experiment_id) / "manifest.json"}
    for child in runner.validate_members(state):
        folder = runner.batches.folder(child.batch_id)
        if folder.is_symlink():
            raise ArtifactValidationError("Model batch must not be a symlink")
        paths.update(folder / name for name in ("manifest.json", "reviews.json"))
        paths.update(folder.glob("*.snapshot"))
        paths.update((folder / "inputs").rglob("*"))
        paths.update(runner.runs_dir / (a["run_id"] + ".trace.json")
                     for entry in child.plan for a in entry["attempts"])
    if any(path.is_symlink() for path in paths):
        raise ArtifactValidationError("Comparison evidence must not be a symlink")
    return {path.relative_to(runner.runs_dir).as_posix(): file_hash(path)
            for path in sorted(paths) if path.is_file()}


def experiment_report(project_root, runs_dir, experiment_id, filters=None):
    filters = filters or BatchFilters()
    runner = ExperimentRunner(project_root, runs_dir)
    state = runner.store.get(experiment_id)
    before = source_inventory(runner, state)
    summary = runner.summary(experiment_id)
    rows, comparisons, reports = [], {}, {}
    expected_models = [m.model_key for m in state.members]
    for member in state.members:
        report = aggregate(runner.runs_dir, member.batch_id, filters)
        reports[member.model_key] = {"batch_id": member.batch_id,
            "report_sha256": report.provenance["report_sha256"],
            "evaluation_snapshot_sha256": report.evaluation_snapshot_sha256,
            "invalid_traces": report.counts["invalid_traces"]}
        for group in report.recommendation_cohorts:
            cohort = {key: group[key] for key in DIMENSIONS}
            comparison_id = digest({"common_sha256": state.common_sha256, "cohort": cohort})
            reference = group["utility_reference"]
            row = {"row_id": digest([member.model_key, group["group_id"]]),
                "model_key": member.model_key, "model_id": group["model_id"],
                "batch_id": member.batch_id, "group_id": group["group_id"],
                "comparison_id": comparison_id, "cohort": cohort,
                "condition": group["condition"], "metrics": {name: group["metrics"][name] for name in METRICS},
                "normal_benchmark_id": group["normal_benchmark_id"],
                "normal_benchmark_coverage": reference["evaluation_coverage"] if reference else None,
                "cost_scope": group["cost_scope"], "planned_count": group["planned_count"],
                "attempt_count": group["attempt_count"], "status_counts": group["status_counts"],
                "run_ids": group["run_ids"], "known_cost_usd": group["known_cost_usd"],
                "total_cost_usd": group["total_cost_usd"],
                "unpriced_or_unresolved_call_count": group["unpriced_or_unresolved_call_count"]}
            rows.append(row)
            comparison = comparisons.setdefault(comparison_id, {"comparison_id": comparison_id,
                "cohort": cohort, "model_rows": {}, "missing_models": [], "status": "incomplete"})
            comparison["model_rows"][member.model_key] = row["row_id"]
    for comparison in comparisons.values():
        comparison["missing_models"] = [key for key in expected_models if key not in comparison["model_rows"]]
        comparison["status"] = "complete_membership" if not comparison["missing_models"] else "incomplete"
    if source_inventory(runner, runner.store.get(experiment_id)) != before:
        raise ArtifactValidationError("Experiment evidence changed during report generation")
    payload = {"schema_version": "0.1", "artifact_type": "model_experiment_report",
        "report_version": "model-comparison-v0.1", "experiment_id": experiment_id,
        "filters": filters.model_dump(mode="json"), "summary": summary.model_dump(mode="json"),
        "provenance": {"common_sha256": state.common_sha256, "manifest_sha256": state.manifest_sha256,
            "source_inventory_sha256": digest(before), "batch_reports": reports,
            "calculation_implementation_sha256": file_hash(Path(__file__)),
            "evaluation_source": "original_saved_evaluation", "model_calls": 0,
            "comparison_method": "same frozen inputs and runtime conditions; separate model estimates with original denominators and exclusions",
            "inference_status": "descriptive_not_paired_cross_model_inference",
            "selection_status": "not_performed", "holdout_authorized": False,
            "resource_scope": "all attempts; per-cohort costs are not a traffic-weighted overall cost",
            "execution_order": "sequential_profile_order; latency may reflect temporal/provider conditions"},
        "rows": rows, "comparisons": list(comparisons.values())}
    return ExperimentReport(**payload, report_sha256=digest(payload))


def experiment_csv(report):
    stream = io.StringIO(newline="")
    fields = ("row_kind", "experiment_id", "report_sha256", "source_inventory_sha256", "filters",
              "model_key", "model_id", "batch_id", "comparison_id", "cohort", "metric", "value",
              "numerator", "denominator", "ci95", "excluded", "normal_benchmark_id", "cost_scope", "summary")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    common = {"experiment_id": report.experiment_id, "report_sha256": report.report_sha256,
              "source_inventory_sha256": report.provenance["source_inventory_sha256"],
              "filters": json.dumps(report.filters.model_dump(exclude_none=True), sort_keys=True)}
    writer.writerow({**common, "row_kind": "report_metadata", "summary": report.summary.model_dump_json()})
    for row in report.rows:
        for name, metric in row["metrics"].items():
            writer.writerow({**common, "row_kind": "model_metric",
                **{key: row[key] for key in ("model_key", "model_id", "batch_id", "comparison_id",
                                           "normal_benchmark_id", "cost_scope")},
                "cohort": json.dumps(row["cohort"], sort_keys=True), "metric": name,
                **{key: metric[key] for key in ("value", "numerator", "denominator")},
                "ci95": json.dumps(metric["ci95"]), "excluded": json.dumps(metric["excluded"], sort_keys=True)})
    return stream.getvalue()


def export_experiment_report(report, output):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("Use a new export directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".model-comparison-", dir=output.parent) as temporary:
        staged = Path(temporary) / "export"
        atomic_json(staged / "report.json", report.model_dump(mode="json"))
        (staged / "metrics.csv").write_text(experiment_csv(report), encoding="utf-8-sig", newline="")
        atomic_json(staged / "export-manifest.json", {"report_sha256": report.report_sha256,
            "source_inventory_sha256": report.provenance["source_inventory_sha256"],
            "model_calls": 0, "artifacts": {name: file_hash(staged / name) for name in ("report.json", "metrics.csv")}})
        if output.exists() or output.is_symlink():
            raise ValueError("Export destination changed")
        staged.rename(output)
