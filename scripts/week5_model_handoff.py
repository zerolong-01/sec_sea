"""Transfer one complete saved model experiment without credentials or model calls."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from backend.app.batch import digest, file_hash
from backend.app.experiment_reports import experiment_report, source_inventory
from backend.app.experiments import ExperimentRunner
from backend.app.repository import RepositoryError
from backend.app.storage import atomic_json
from scripts.data_contract import ROOT
from scripts.verify_week5_saved_models import verify as verify_saved_models
from scripts.week4_package import tree_hashes

VERSION = "week5-model-handoff-v0.1"
MANIFEST = "handoff-manifest.json"
REAL_EXPERIMENT = "experiment-4e1e9895fd7f"


def _separate(first, second):
    if first == second or first.is_relative_to(second) or second.is_relative_to(first):
        raise ValueError("Use separate, non-overlapping source and output directories")


def _path(root, name):
    relative = PurePosixPath(name)
    if (not name or relative.is_absolute() or str(relative) != name or
            any(part in (".", "..") for part in relative.parts) or
            any(char in name for char in ("\\", ":", "\0"))):
        raise ValueError("Invalid handoff artifact path")
    path = root.joinpath(*relative.parts)
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent.is_relative_to(root)):
        raise ValueError("Handoff artifacts must not use symlinks")
    if not path.is_file():
        raise ValueError("A required handoff artifact is missing")
    return path


def _evidence(runs, experiment_id, *, expected_runs, allow_fixture, root):
    runner = ExperimentRunner(root, runs)
    state = runner.store.get(experiment_id)
    summary = runner.summary(experiment_id)
    scopes = {model["execution_scope"] for model in summary.models}
    if scopes != {"real"} and not (allow_fixture and scopes == {"fixture"}):
        raise ValueError("Real saved evidence is required; fixture use must be explicit")
    if (summary.status != "completed" or summary.planned_count != expected_runs or
            summary.attempt_count != expected_runs or
            any(set(model["status_counts"]) - {"completed", "blocked"} for model in summary.models)):
        raise ValueError("Expected a complete experiment with one settled attempt per planned run")
    files = source_inventory(runner, state)
    for child in runner.validate_members(state):
        for entry in child.plan:
            if len(entry["attempts"]) != 1 or entry["attempts"][0]["status"] not in ("completed", "blocked"):
                raise ValueError("Every planned run must have exactly one settled attempt")
            run_id = entry["attempts"][0]["run_id"]
            for suffix in ("trace", "raw"):
                name = f"{run_id}.{suffix}.json"
                files[name] = file_hash(_path(runs, name))
    files = dict(sorted(files.items()))
    for name, expected in files.items():
        if file_hash(_path(runs, name)) != expected:
            raise ValueError("Source evidence changed during inventory")
    report = experiment_report(root, runs, experiment_id)
    if any(item["invalid_traces"] for item in report.provenance["batch_reports"].values()):
        raise ValueError("Saved experiment contains invalid traces")
    if experiment_id == REAL_EXPERIMENT:
        reference = json.loads((root / "docs/examples/model-experiment-live/verification-report.json").read_text(encoding="utf-8"))
        if (scopes != {"real"} or summary.planned_count != reference["planned_runs"] or
                report.provenance["source_inventory_sha256"] != reference["source_inventory_sha256"] or
                {(m["model_id"], m["batch_id"]) for m in summary.models} !=
                {(m["model_id"], m["batch_id"]) for m in reference["models"]}):
            raise ValueError("216-run source differs from the published experiment identity/inventory")
    return state, summary, files, report


def export_handoff(runs_dir, experiment_id, output, *, expected_runs=216, allow_fixture=False, root=ROOT):
    source_arg, output_arg = Path(runs_dir), Path(output)
    if source_arg.is_symlink() or not source_arg.is_dir():
        raise ValueError("Original runs directory is unavailable; export on the PC holding the original files")
    if output_arg.exists() or output_arg.is_symlink():
        raise ValueError("Use a new handoff output directory")
    source, output = source_arg.resolve(), output_arg.resolve()
    _separate(source, output)
    state, summary, files, report = _evidence(source, experiment_id, expected_runs=expected_runs,
                                            allow_fixture=allow_fixture, root=root)
    # Only the selected experiment, frozen member inputs/settings/reviews and
    # every original raw/trace pair are copied. No .env, logs or other runs.
    output.mkdir(parents=True)
    for name, expected in files.items():
        target = output / "runs" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_path(source, name), target)
        if file_hash(target) != expected:
            raise ValueError("Source changed while copying; incomplete handoff must not be used")
    after = _evidence(source, experiment_id, expected_runs=expected_runs, allow_fixture=allow_fixture, root=root)
    if after[2] != files or after[3].report_sha256 != report.report_sha256:
        raise ValueError("Source changed during export; incomplete handoff must not be used")
    payload = {"version": VERSION, "experiment_id": experiment_id,
        "created_at": datetime.now(timezone.utc).isoformat(), "code_commit": state.code_commit,
        "execution_scope": summary.models[0]["execution_scope"], "planned_runs": summary.planned_count,
        "attempt_count": summary.attempt_count, "models": summary.models,
        "report_sha256": report.report_sha256,
        "source_inventory_sha256": report.provenance["source_inventory_sha256"],
        "runs_files": files, "runs_files_sha256": digest(files),
        "model_calls": 0, "human_acceptance": False,
        "distribution": "restricted_raw_evidence; keep outside Git and public attachments"}
    manifest = {**payload, "manifest_sha256": digest(payload)}
    atomic_json(output / MANIFEST, manifest)
    inspect_handoff(output, expected_manifest_sha256=manifest["manifest_sha256"],
                    expected_runs=expected_runs, allow_fixture=allow_fixture, root=root)
    return manifest


def inspect_handoff(package, *, expected_manifest_sha256, expected_runs=216, allow_fixture=False, root=ROOT):
    package = Path(package)
    if package.is_symlink() or not package.is_dir():
        raise ValueError("Handoff package directory is unavailable")
    package = package.resolve()
    # Reject symlinked ancestors and extra artifacts before reading a manifest.
    inventory = tree_hashes(package)
    manifest = json.loads((package / MANIFEST).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Invalid handoff manifest")
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if (manifest.get("version") != VERSION or not re.fullmatch(r"[a-f0-9]{64}", expected_manifest_sha256) or
            digest(payload) != expected_manifest_sha256 or manifest.get("manifest_sha256") != expected_manifest_sha256 or
            manifest.get("planned_runs") != expected_runs):
        raise ValueError("Handoff manifest differs from the sender's trusted identity")
    files = manifest["runs_files"]
    if not isinstance(files, dict) or digest(files) != manifest["runs_files_sha256"]:
        raise ValueError("Invalid handoff file inventory")
    for name, expected in files.items():
        if file_hash(_path(package / "runs", name)) != expected:
            raise ValueError("Handoff artifact hash mismatch")
    if set(inventory) != {MANIFEST, *("runs/" + name for name in files)}:
        raise ValueError("Missing or unexpected handoff artifacts")
    state, summary, observed, report = _evidence(package / "runs", manifest["experiment_id"],
        expected_runs=expected_runs, allow_fixture=allow_fixture, root=root)
    if (observed != files or report.report_sha256 != manifest["report_sha256"] or
            report.provenance["source_inventory_sha256"] != manifest["source_inventory_sha256"] or
            state.code_commit != manifest["code_commit"] or summary.models != manifest["models"] or
            summary.models[0]["execution_scope"] != manifest["execution_scope"] or
            summary.attempt_count != manifest["attempt_count"] or manifest["model_calls"] != 0 or
            manifest["human_acceptance"] is not False):
        raise ValueError("Transferred evidence differs from the manifest")
    if tree_hashes(package) != inventory:
        raise ValueError("Handoff package changed during inspection")
    return manifest


def verify_handoff(package, output, *, expected_manifest_sha256, expected_runs=216, allow_fixture=False, root=ROOT):
    if Path(package).is_symlink():
        raise ValueError("Handoff package must not be a symlink")
    package, output = Path(package).resolve(), Path(output).resolve()
    _separate(package, output)
    manifest = inspect_handoff(package, expected_manifest_sha256=expected_manifest_sha256,
                              expected_runs=expected_runs, allow_fixture=allow_fixture, root=root)
    before = tree_hashes(package)
    result = verify_saved_models(package / "runs", manifest["experiment_id"], output)
    if tree_hashes(package) != before or result["report_sha256"] != manifest["report_sha256"]:
        raise ValueError("Transferred evidence changed during API/UI verification")
    result = {**result, "handoff_manifest_sha256": manifest["manifest_sha256"],
              "handoff_unchanged": True, "execution_scope": manifest["execution_scope"], "paid_model_calls": 0}
    atomic_json(output / "handoff-verification.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--runs-dir", type=Path, required=True)
    export.add_argument("--experiment-id", default=REAL_EXPERIMENT)
    export.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("verify")
    check.add_argument("--package", type=Path, required=True)
    check.add_argument("--expected-manifest-sha256", required=True)
    check.add_argument("--output", type=Path, required=True)
    for command in (export, check):
        command.add_argument("--expected-runs", type=int, default=216)
        command.add_argument("--allow-fixture", action="store_true", help="Transport tests only; never real-model evidence")
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    if args["expected_runs"] < 1:
        parser.error("--expected-runs must be positive")
    try:
        result = export_handoff(**args) if command == "export" else verify_handoff(**args)
    except (ValueError, OSError, RepositoryError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc), "model_calls": 0}, ensure_ascii=False))
        return 1
    if command == "export":
        result = {"status": "ready_for_receiver_verification", "experiment_id": result["experiment_id"],
            "planned_runs": result["planned_runs"], "execution_scope": result["execution_scope"],
            "files": len(result["runs_files"]), "manifest_sha256": result["manifest_sha256"], "model_calls": 0}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
