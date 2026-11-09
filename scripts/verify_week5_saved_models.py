"""Recheck an existing model experiment through API/UI/CSV/trace, with model calls blocked."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.experiments import ExperimentRunner
from backend.app.providers import OpenAICompatibleProvider
from backend.app.storage import atomic_json
from scripts.verify_real_model_experiment import _audit_saved
from scripts.verify_result_views import verify as verify_views
from scripts.week4_package import tree_hashes


def verify(runs_dir, experiment_id, output):
    root = Path(__file__).resolve().parents[1]
    source, output = runs_dir.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Use a new output outside the original run store")
    output.mkdir(parents=True)
    before = tree_hashes(source)
    runner = ExperimentRunner(root, source)
    state = runner.store.get(experiment_id)
    with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("Read called a model")) as calls:
        report, audits, compared, absent, _ = _audit_saved(runner, state, output, ())
        if calls.call_count:
            raise ValueError("Read called a model")
    if (report.summary.status != "completed" or any(audit["error_counts"] or audit["unreconciled_calls"]
            for audit in audits.values()) or any(item["invalid_traces"] for item in report.provenance["batch_reports"].values())):
        raise ValueError("Saved experiment is incomplete or has unreconciled evidence")
    ui = verify_views(source, output / "model-ui-verification.json", experiment_id=experiment_id, require_trace=True)
    if before != tree_hashes(source):
        raise ValueError("Original experiment changed")
    atomic_json(output / "source-file-hashes.json", before)
    result = {"status": "passed", "verified_at": datetime.now(timezone.utc).isoformat(),
        "experiment_id": experiment_id, "planned_runs": report.summary.planned_count,
        "attempt_count": report.summary.attempt_count, "source_file_count": len(before),
        "model_count": len(report.summary.models), "report_sha256": report.report_sha256,
        "audits": audits, "compared_transmitted_calls": compared, "unpaired_calls": absent,
        "api_ui_csv_trace_match": ui["status"] == "passed", "read_model_calls": 0,
        "source_unchanged": True, "human_acceptance": False, "holdout_executed": False}
    atomic_json(output / "verification-report.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.runs_dir, args.experiment_id, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "audits"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
