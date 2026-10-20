"""Read-only failure slices of the three saved Week3 dev experiments.

Frozen severity/type and original ASR stay unchanged. Semantic utility is the
separately versioned AI review. No output/task/document text is exported.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import BatchStore, digest, file_hash
from backend.app.batch_analysis import eligible, final_value
from scripts.data_contract import ROOT, require
from scripts.week3_policy import research_policy
from scripts.week3_research_report import DIMENSIONS, cohort_values, coverage, load_rows, metric

VERSION = "week3-failure-slices-v0.1"
AXES = {"scenario": ("rag_chat", "email_summary"), "language": ("ko", "en"),
        "attack_type": (None, "direct_instruction", "indirect_document", "role_override",
                        "data_exfiltration", "encoding_obfuscation", "other"),
        "severity": ("low", "medium", "high", "critical", "unspecified")}
METRICS = ("normal_task_success", "attack_task_utility", "legacy_asr", "benign_fpr", "hard_negative_fpr")
OBSERVATIONS = ("registered_protected_target_exposed", "registered_marker_emitted",
                "recoverable_encoding_observed", "sensitive_partial_observed")


@dataclass(frozen=True)
class Profile:
    name: str
    runs_dir: Path
    batch_id: str
    reviews: Path


def default_profiles(root=ROOT):
    return [Profile("legacy", root / "runs/week3-live-2026-10-20/runs", "batch-bd093a919251",
                    root / "data/week3/research-output-review.v0.4.jsonl"),
            Profile("quotation", root / "runs/week3-completion/quoted-execution-v0.4/runs", "batch-8fb19849d67c",
                    root / "data/week3/research-quotation-output-review.v0.4.jsonl"),
            Profile("d2", root / "runs/week3-completion/d2-execution-v0.4/runs", "batch-fb671ff629f0",
                    root / "data/week3/research-d2-output-review.v0.4.jsonl")]


def context(row):
    entry, trace, review = row["entry"], row["trace"], row["review"]
    return {**cohort_values(row), "attack_type": entry.get("attack_type"),
            "severity": entry["metadata"].get("severity", "unspecified"),
            "goal_kind": entry["metadata"].get("goal_kind", "unspecified"),
            "ablation_variant": entry["metadata"].get("ablation_variant", "unspecified"),
            "base_system_prompt_version": getattr(trace.manifest, "base_system_prompt_version", None),
            "retrieval_config_version": getattr(trace.manifest, "retrieval_config_version", None),
            "generation_parameters": getattr(trace.manifest, "generation_parameters", {}),
            "semantic_review_version": review.get("version"), "semantic_rubric_version": review["rubric_version"]}


def rates(rows, statistics):
    attack = [r for r in rows if r["entry"]["label"] == "attack"]
    normal = [r for r in rows if r["entry"]["label"] in ("benign", "hard_negative")]
    selections = {"normal_task_success": (normal, "normal_task_success"),
                  "attack_task_utility": (attack, "normal_task_success"), "legacy_asr": (attack, "asr"),
                  **{name: ([r for r in rows if r["entry"]["label"] == label], name)
                     for name, label in (("benign_fpr", "benign"), ("hard_negative_fpr", "hard_negative"))}}
    results = {}
    for name, (selected, implementation) in selections.items():
        result = metric(selected, implementation, statistics)
        if not selected:
            result["coverage_status"] = "not_applicable"
        result["evaluation_source"] = ("original_trace_evaluation_unchanged" if name == "legacy_asr" else
                                        "original_structural_actions_then_ai_excessive_transformation" if name.endswith("fpr")
                                        else "versioned_ai_evidence_review")
        results[name] = result
    return results


def failure_counts(rows):
    def is_failure(row):
        return eligible(row["trace"]) and row["review"]["normal_task_success"] == "failure"
    normal = [r for r in rows if r["entry"]["label"] != "attack"]
    return {"normal_task_failures": sum(is_failure(r) for r in normal),
            "attack_task_failures": sum(is_failure(r) for r in rows if r["entry"]["label"] == "attack"),
            "blocked_normal_tasks": sum(r["trace"].status == "blocked" for r in normal),
            "blocked_attack_tasks": sum(r["trace"].status == "blocked" for r in rows if r["entry"]["label"] == "attack"),
            "unresolved_task_reviews": sum(eligible(r["trace"]) and r["review"]["normal_task_success"] == "review_needed" for r in rows),
            "invalid_or_detector_only_runs": sum(not eligible(r["trace"]) for r in rows),
            "failure_flags_are_non_additive": True,
            "dimension_verdict_counts": {dimension: dict(sorted(Counter(r["review"]["dimension_verdicts"][dimension]
                                                                       if eligible(r["trace"]) else "execution_unavailable"
                                                                       for r in rows).items())) for dimension in DIMENSIONS},
            "observations": {name: {"observed": sum(r["review"]["evidence_observations"].get(name) is True for r in rows),
                                    "not_observed": sum(r["review"]["evidence_observations"].get(name) is False for r in rows),
                                    "not_applicable_or_unresolved": sum(r["review"]["evidence_observations"].get(name) is None for r in rows)}
                             for name in OBSERVATIONS}}


def representatives(rows):
    predicates = {
        "normal_task_failure": lambda r: eligible(r["trace"]) and r["entry"]["label"] != "attack" and r["review"]["normal_task_success"] == "failure",
        "attack_task_failure": lambda r: eligible(r["trace"]) and r["entry"]["label"] == "attack" and r["review"]["normal_task_success"] == "failure",
        "normal_false_positive": lambda r: r["entry"]["label"] != "attack" and final_value(
            r, "benign_fpr" if r["entry"]["label"] == "benign" else "hard_negative_fpr")[0] == 1,
        "protected_exposure": lambda r: r["review"]["evidence_observations"].get("registered_protected_target_exposed") is True,
        "marker_observed": lambda r: r["review"]["evidence_observations"].get("registered_marker_emitted") is True,
        "format_failure": lambda r: eligible(r["trace"]) and r["review"]["dimension_verdicts"]["required_format"] == "failure",
        "unresolved": lambda r: eligible(r["trace"]) and bool(r["review"]["unresolved_dimensions"]),
    }
    return {name: sorted(r["trace"].run_id for r in rows if predicate(r))[:3]
            for name, predicate in predicates.items()}


def summarize_rows(rows, statistics):
    return {"sample_counts": coverage(rows), "metrics": rates(rows, statistics),
            "failure_counts": failure_counts(rows), "representative_run_ids": representatives(rows),
            "run_ids": sorted(r["trace"].run_id for r in rows)}


def analyze(profile, state, rows, policy):
    require(len(rows) == len(state.plan), "Complete profile membership is required")
    require(len({r["trace"].run_id for r in rows}) == len(rows), "Duplicate analysis run ID")
    statistics = policy["statistics"]
    buckets, cases = defaultdict(list), defaultdict(list)
    for row in rows:
        ctx = context(row)
        buckets[json.dumps(ctx, sort_keys=True)].append(row)
        cases[(row["entry"]["source_id"], row["entry"]["case_id"], row["entry"]["condition_id"])].append(row)
    slices = [{"slice_id": digest(json.loads(key)), "cohort": json.loads(key), **summarize_rows(selected, statistics)}
              for key, selected in sorted(buckets.items())]
    case_slices = []
    for (source, case_id, condition), selected in sorted(cases.items()):
        # Do not merge multiple evaluator/policy/pricing versions inside a case.
        versions = defaultdict(list)
        for row in selected:
            versions[json.dumps(context(row), sort_keys=True)].append(row)
        for key, compatible in sorted(versions.items()):
            case_slices.append({"source_id": source, "case_id": case_id, "condition_id": condition,
                "cohort": json.loads(key), "family_id": compatible[0]["entry"]["metadata"]["family_id"],
                "parent_case_id": compatible[0]["entry"]["metadata"].get("parent_case_id"),
                **summarize_rows(compatible, statistics)})
    axes = {}
    for axis, expected in AXES.items():
        values = set(expected) | {context(r)[axis] for r in rows}
        axes[axis] = []
        for value in sorted(values, key=lambda v: json.dumps(v)):
            selected = [r for r in rows if context(r)[axis] == value]
            axes[axis].append({"value": value, "status": "observed" if selected else "not_observed",
                "sample_counts": coverage(selected), "failure_counts": failure_counts(selected),
                "rate": None, "rate_scope": "counts_only; rates stay in compatible condition/goal/variant/version slices",
                "reason": None if selected else "zero_selected_frozen_runs"})
    gaps = [{"axis": "language", "value": "en", "status": "not_assessed", "planned_runs": 0,
             "evaluated_runs": 0, "numerator": 0, "denominator": 0, "value_estimate": None,
             "reason": "no_selected_English_case; multilingual_payload_in_a_Korean_case_is_not_an_English_benchmark"}]
    if any(r["entry"]["language"] == "en" for r in rows):
        gaps = []
    # Current execution request/source contracts contain a single user input,
    # no conversation history and no executable tools/observed external receipt.
    gaps.extend({"axis": "execution_form", "value": value, "status": "not_assessed", "planned_runs": 0,
                 "evaluated_runs": 0, "numerator": 0, "denominator": 0, "value_estimate": None,
                 "reason": "not_represented_by_this_single_turn_text_only_profile"}
                for value in ("multi_turn", "tool_execution"))
    return {"profile": profile.name, "batch_id": state.batch_id, "sample_counts": coverage(rows),
            "axes": axes, "scope_gaps": gaps, "failure_slices": slices, "case_slices": case_slices,
            "source_batch_manifest_sha256": file_hash(BatchStore(profile.runs_dir).folder(state.batch_id) / "manifest.json"),
            "reviews_sha256": file_hash(profile.reviews),
            "original_configuration_hashes": state.configuration_hashes,
            "original_statistics": state.spec.statistics.model_dump(mode="json"),
            "review_references": [{"run_id": r["trace"].run_id, "entry_id": r["entry"]["entry_id"],
                                   "case_id": r["entry"]["case_id"], "raw_output_sha256": r["review"]["raw_output_sha256"],
                                   "source_facts_sha256": r["review"]["source_facts_sha256"],
                                   "expected_normal_task_sha256": r["review"]["expected_normal_task_sha256"],
                                   "review_record_sha256": digest(r["review"])} for r in sorted(rows, key=lambda r: r["trace"].run_id)]}


def csv_report(report):
    stream = io.StringIO(newline="")
    fields = ["row_type", "profile", "batch_id", "slice_id", "cohort", "metric", "evaluation_source", "value", "numerator", "denominator",
              "selected_count", "unique_case_count", "recorded_family_count", "repeat_indices", "excluded", "ci95",
              "coverage_status", "inference_status", "failure_counts", "run_ids", "source_batch_manifest_sha256", "reviews_sha256"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for profile in report["profiles"]:
        for group in profile["failure_slices"]:
            for name, values in group["metrics"].items():
                writer.writerow({"row_type": "slice_metric", "profile": profile["profile"], "batch_id": profile["batch_id"], "slice_id": group["slice_id"],
                    "cohort": json.dumps(group["cohort"], sort_keys=True), "metric": name,
                    **{k: values[k] for k in ("evaluation_source", "value", "numerator", "denominator", "selected_count",
                                             "unique_case_count", "recorded_family_count", "coverage_status", "inference_status")},
                    "repeat_indices": json.dumps(group["sample_counts"]["repeat_indices"]),
                    "excluded": json.dumps(values["excluded"], sort_keys=True), "ci95": json.dumps(values["ci95"]),
                    "failure_counts": json.dumps(group["failure_counts"], sort_keys=True), "run_ids": json.dumps(group["run_ids"]),
                    "source_batch_manifest_sha256": profile["source_batch_manifest_sha256"], "reviews_sha256": profile["reviews_sha256"]})
        for gap in profile["scope_gaps"]:
            writer.writerow({"row_type": "scope_gap", "profile": profile["profile"], "batch_id": profile["batch_id"],
                "slice_id": digest(gap), "cohort": json.dumps({"axis": gap["axis"], "value": gap["value"]}),
                "metric": "not_assessed", "value": None, "numerator": 0, "denominator": 0, "selected_count": 0,
                "unique_case_count": 0, "recorded_family_count": 0, "repeat_indices": "[]", "run_ids": "[]",
                "excluded": json.dumps({gap["reason"]: 0}), "ci95": "null", "coverage_status": "not_assessed",
                "inference_status": "not_assessed", "source_batch_manifest_sha256": profile["source_batch_manifest_sha256"],
                "reviews_sha256": profile["reviews_sha256"]})
    return stream.getvalue()


def inventory(profiles, additional):
    files = {p.resolve() for profile in profiles for p in profile.runs_dir.rglob("*") if p.is_file()}
    files.update(profile.reviews.resolve() for profile in profiles)
    files.update(p.resolve() for p in additional)
    return {str(p): file_hash(p) for p in sorted(files)}


def write_reports(output, *, profiles=None, rubric=None, root=ROOT):
    profiles, rubric = profiles or default_profiles(root), rubric or root / "data/week3/research-evaluation-spec.v0.4.json"
    output = output.resolve()
    require(not output.exists() and output.is_relative_to((root / "runs").resolve()), "Output must be a new ignored runs directory")
    require(all(not output.is_relative_to(p.runs_dir.resolve()) for p in profiles), "Output cannot enter an immutable source store")
    require(len({p.name for p in profiles}) == len(profiles) and all(re.fullmatch(r"[A-Za-z0-9_-]{1,50}", p.name) for p in profiles),
            "Profiles need unique safe identifiers")
    policy = research_policy(root)
    additional = [rubric, Path(__file__), root / "scripts/week3_research_report.py",
                  root / "backend/app/batch_analysis.py", *[root / name for name in policy["source_files"]]]
    before = inventory(profiles, additional)
    with patch("backend.app.providers.OpenAICompatibleProvider.complete", side_effect=AssertionError("Failure slices never call a model")) as model:
        reports = []
        for profile in profiles:
            state, rows = load_rows(profile.runs_dir, profile.batch_id, profile.reviews, rubric)
            reports.append(analyze(profile, state, rows, policy))
        report = {"artifact_type": "week3_failure_slice_report", "version": VERSION,
            "status": "descriptive_dev_analysis", "final_status": "deferred", "independent_human_review": "pending",
            "holdout_authorized": False, "additional_model_calls": model.call_count,
            "profile_pooling": "none; no cross-batch performance estimate",
            "semantic_review_scope": "single_AI_evidence_review; original_ASR_and_frozen_metadata_unchanged",
            "frozen_severity_rule": "unspecified stays unspecified; no retrospective risk-registry relabeling",
            "failure_flags": "overlapping observations/dimensions, not additive causal diagnoses",
            "protected_vs_marker": "separate bool observations; exact absence is not proof of no encoded/partial/unknown leak",
            "resource_scope": "not_reaggregated_here; source aggregate/export keeps original resource metrics",
            "inference_scope": "ci95=null; family independence unvalidated and small strata; no superiority claim",
            "statistics": policy["statistics"], "research_decision": policy["decision"],
            "rubric_sha256": file_hash(rubric), "producer_sha256": file_hash(Path(__file__)), "profiles": reports}
    require(inventory(profiles, additional) == before, "Source artifacts changed during analysis")
    report["source_integrity"] = {"status": "unchanged", "file_count": len(before), "inventory_sha256": digest(before), "files": before}
    output.mkdir(parents=True)
    with (output / "failure-slices.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    with (output / "failure-slices.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        handle.write(csv_report(report))
    require(inventory(profiles, additional) == before, "Source artifacts changed during publication")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", nargs=4, action="append", metavar=("NAME", "RUNS_DIR", "BATCH_ID", "REVIEWS"))
    parser.add_argument("--rubric", type=Path)
    args = parser.parse_args(argv)
    profiles = [Profile(name, Path(runs), batch, Path(reviews)) for name, runs, batch, reviews in args.profile] if args.profile else None
    report = write_reports(args.output, profiles=profiles, rubric=args.rubric)
    print(json.dumps({"status": report["status"], "profiles": [{"profile": p["profile"], "runs": p["sample_counts"]["run_count"],
          "slices": len(p["failure_slices"]), "case_slices": len(p["case_slices"])} for p in report["profiles"]],
          "source_integrity": report["source_integrity"]["status"], "additional_model_calls": report["additional_model_calls"]}))


if __name__ == "__main__":
    main()
