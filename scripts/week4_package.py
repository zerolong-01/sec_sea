"""Version inventory and immutable saved-result replay for issue #47.

No execution command and no Settings.from_environment: credentials, .env, live
endpoints and current model configuration are irrelevant to replay.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import digest, file_hash
from backend.app.batch_analysis import aggregate, batch_decision_record, export_report, report_csv
from backend.app.batch_models import BatchFilters, BatchReport
from backend.app.repository import RepositoryError
from backend.app.research_models import ResearchFilters, ResearchReport
from backend.app.research_reports import INDEX, ROOT, load_evidence, research_csv, research_report
from backend.app.storage import atomic_json

VERSION = "week4-reproduction-package-v0.2"
PACKAGE_VERSIONS = {"week4-reproduction-package-v0.1", VERSION}
ARTIFACT_NAMES = {"report.json", "metrics.csv", "decision-record.json"}
SHA256 = re.compile(r"[a-f0-9]{64}")


def tree_hashes(folder):
    result = {}
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise ValueError("Evidence symlinks are not supported")
        if path.is_file():
            result[path.relative_to(folder).as_posix()] = file_hash(path)
    return result


def environment():
    return {"python": platform.python_version(), "platform": platform.platform(),
            "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}}


def release_evidence(root, index):
    """Validate every local public reference, including completed smoke evidence."""
    references = [index["research_overlay"], index["public_result_summary"]]
    references += [index[name] for name in ("new_dev_reproduction_attempt", "new_dev_reproduction_completed",
                   "clean_checkout_verification") if name in index]
    audit = index.get("exploratory_audit", {})
    if "source_index" in audit:
        references.append(audit["source_index"])
    result = {}
    for reference in references:
        name = reference["path"]
        if not isinstance(name, str) or not name.startswith(("docs/", "configs/")):
            raise ValueError("Published release evidence must use a public project path")
        path = root / name
        if (not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or
                file_hash(path) != reference["sha256"]):
            raise ValueError("Published release evidence differs from the release index")
        result[name] = reference["sha256"]
    return result


def inventory(*, root=ROOT):
    # Allowlisted tracked/new project files only; no .env, agent settings, local
    # artifacts, credentials or private raw evidence are copied or enumerated.
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=root, check=True, capture_output=True)
    prefixes = ("backend/app/", "backend/testing/", "frontend/", "scripts/", "contracts/", "configs/", "data/", "docs/", ".github/")
    names = [name for name in result.stdout.decode("utf-8").split("\0") if name and
             (name.startswith(prefixes) or name in ("requirements.txt", "requirements.lock", ".gitattributes", "README.md", "backend/requirements.txt"))]
    files = {name: file_hash(root / name) for name in sorted(set(names)) if (root / name).is_file()}
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root))
    index = json.loads((root / INDEX).read_text(encoding="utf-8"))
    public = release_evidence(root, index)
    _, _, evidence = load_evidence(root)
    return {"version": VERSION, "code_commit": revision, "working_tree_dirty": dirty,
            "code_and_data_files": files, "code_and_data_inventory_sha256": digest(files),
            "environment": environment(), "release_index": index, "research_evidence_files": evidence,
            "release_evidence_files": public,
            "private_material_available": {p["name"]: (root / p["private_runs_dir"]).is_dir() for p in index["experiments"]},
            "model_calls": 0, "human_ABC_acceptance": "pending", "holdout_authorized": False}


def decision_record(report, source):
    if source == "original":
        return batch_decision_record(report)
    result = {"batch_id": report.batch_id, "report_version": report.report_version,
              "report_sha256": report.report_sha256 if source == "overlay" else report.provenance["report_sha256"],
              "evaluation_snapshot_sha256": report.evaluation_snapshot_sha256,
              "filters": report.filters.model_dump(mode="json"), "provenance": report.provenance,
              **report.decisions}
    if source == "overlay":
        result["evaluation_version"] = report.evaluation_version
    return result


def verify_package(package, *, expected_report_sha256=None, expected_source_inventory_sha256=None):
    """Check a transferred package without its source store, keys, Git or network.

    Hashes supplied by a trusted sender can pin the expected report/source. A
    self-consistent manifest alone cannot authenticate its author or establish
    that the separately held source is still unchanged.
    """
    package = Path(package)
    if package.is_symlink() or not package.is_dir():
        raise ValueError("Package must be a real directory")
    before = tree_hashes(package)
    if set(before) != ARTIFACT_NAMES | {"reproduction-manifest.json"}:
        raise ValueError("Package has missing or unexpected files")
    manifest = json.loads((package / "reproduction-manifest.json").read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("version"), str) or
            manifest["version"] not in PACKAGE_VERSIONS):
        raise ValueError("Unsupported package version")
    declared = manifest.get("artifacts")
    if not isinstance(declared, dict) or declared != {name: before[name] for name in ARTIFACT_NAMES}:
        raise ValueError("Package artifact hashes differ from its manifest")
    for key, expected in (("report_sha256", expected_report_sha256),
                          ("source_inventory_sha256", expected_source_inventory_sha256)):
        value = manifest.get(key)
        if (not isinstance(value, str) or not SHA256.fullmatch(value) or
                (expected is not None and value != expected)):
            raise ValueError("Package identity does not match the expected hash")
    if (manifest.get("model_calls") != 0 or manifest.get("source_unchanged") is not True or
            type(manifest.get("source_file_count")) is not int or manifest["source_file_count"] < 1):
        raise ValueError("Package does not declare a completed zero-call replay")
    payload = json.loads((package / "report.json").read_text(encoding="utf-8"))
    source = manifest.get("evaluation_source")
    if source == "overlay":
        report = ResearchReport.model_validate(payload)
        calculated = dict(payload)
        report_hash = calculated.pop("report_sha256")
        expected_csv = research_csv(report)
    elif source == "original":
        report = BatchReport.model_validate(payload)
        if report.report_version not in ("batch-cluster-summary-v0.5", "batch-cluster-summary-v0.6"):
            raise ValueError("Unsupported original report rendering version")
        calculated = {**payload, "provenance": dict(payload["provenance"])}
        report_hash = calculated["provenance"].pop("report_sha256")
        expected_csv = report_csv(report)
    else:
        raise ValueError("Unsupported package evaluation source")
    if (digest(calculated) != report_hash or manifest["report_sha256"] != report_hash or
            any(manifest.get(key) != getattr(report, key) for key in
                ("batch_id", "report_version", "evaluation_snapshot_sha256")) or
            manifest.get("filters") != report.filters.model_dump(mode="json")):
        raise ValueError("Package report identity or canonical hash is inconsistent")
    decision = json.loads((package / "decision-record.json").read_text(encoding="utf-8"))
    if decision != decision_record(report, source):
        raise ValueError("Package decision record differs from its report")
    actual_csv = (package / "metrics.csv").read_text(encoding="utf-8-sig")
    if actual_csv != expected_csv.replace("\r\n", "\n"):
        raise ValueError("Package CSV differs from its report")
    if tree_hashes(package) != before:
        raise ValueError("Package changed during verification")
    return {"status": "passed", "verification_kind": "transferred_package_integrity_and_consistency",
            "package_version": manifest["version"], "batch_id": report.batch_id,
            "evaluation_source": source, "report_sha256": report_hash,
            "source_inventory_sha256": manifest["source_inventory_sha256"],
            "package_inventory_sha256": digest(before), "artifact_count": len(ARTIFACT_NAMES),
            "expected_report_hash_matched": expected_report_sha256 is not None,
            "expected_source_hash_matched": expected_source_inventory_sha256 is not None,
            "source_evidence_revalidated": False, "package_unchanged": True, "model_calls": 0}


def replay(batch_id, output, *, source="original", runs_dir=None, filters=None, root=ROOT):
    output = output.resolve()
    if output.exists():
        raise ValueError("Output exists; use a new version/path")
    if source not in ("original", "overlay"):
        raise ValueError("Unsupported evaluation source")
    if source == "original":
        if runs_dir is None or not runs_dir.is_dir():
            raise ValueError("Original replay requires a transferred private runs directory")
        folder = runs_dir.resolve()
        if output.is_relative_to(folder) or folder.is_relative_to(output):
            raise ValueError("Output overlaps the original store")
        index = json.loads((root / INDEX).read_text(encoding="utf-8"))
        expected = next((p for p in index["experiments"] if p["batch_id"] == batch_id), None)
        if expected and file_hash(folder / "batches" / batch_id / "manifest.json") != expected["manifest_sha256"]:
            raise ValueError("Transferred private manifest differs from the release index")
        before = tree_hashes(folder)
    else:
        if runs_dir is not None:
            raise ValueError("Public overlay replay does not consume private stores")
        folder = None
        _, _, evidence = load_evidence(root)
        protected = [root / INDEX, *[root / name for name in evidence]]
        if any(output == p or p.is_relative_to(output) for p in protected):
            raise ValueError("Output overlaps source evidence")
        before = {p.relative_to(root).as_posix(): file_hash(p) for p in protected}
    # Existing project transports are blocked as an executable regression guard.
    with patch("backend.app.providers.OpenAICompatibleProvider.complete", side_effect=AssertionError("Replay cannot call models")) as paid, \
         patch("backend.app.providers.DemoRagProvider.generate_prepared", side_effect=AssertionError("Replay cannot generate")) as demo:
        report = (aggregate(folder, batch_id, BatchFilters.model_validate(filters or {})) if source == "original" else
                  research_report(batch_id, ResearchFilters.model_validate(filters or {}), root=root))
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="." + output.name + "-", dir=output.parent) as temporary:
            staged = Path(temporary) / "package"
            if source == "original":
                export_report(report, staged)
                report_hash = report.provenance["report_sha256"]
            else:
                staged.mkdir()
                atomic_json(staged / "report.json", report.model_dump(mode="json"))
                (staged / "metrics.csv").write_text(research_csv(report), encoding="utf-8-sig", newline="")
                report_hash = report.report_sha256
                atomic_json(staged / "decision-record.json", decision_record(report, source))
            after = tree_hashes(folder) if folder else {p.relative_to(root).as_posix(): file_hash(p) for p in protected}
            if after != before:
                raise ValueError("Source artifacts changed during replay")
            manifest = {"version": VERSION, "batch_id": batch_id, "evaluation_source": source,
                "report_version": report.report_version, "report_sha256": report_hash,
                "evaluation_snapshot_sha256": report.evaluation_snapshot_sha256,
                "filters": report.filters.model_dump(mode="json"),
                "created_at": datetime.now(timezone.utc).isoformat(), "environment": environment(),
                "reader_code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "reader_implementation_sha256": file_hash(Path(__file__)),
                "source_inventory_sha256": digest(before), "source_file_count": len(before),
                "source_unchanged": True, "model_calls": paid.call_count + demo.call_count,
                "artifacts": tree_hashes(staged),
                "comparison_rule": "Compare report hash, snapshot, filters, artifact hashes and source inventory; exclude created_at/environment and destination path"}
            atomic_json(staged / "reproduction-manifest.json", manifest)
            verify_package(staged, expected_report_sha256=report_hash,
                           expected_source_inventory_sha256=manifest["source_inventory_sha256"])
            # Include files added/deleted while staging, and do not publish partial
            # packages or overwrite another process's existing package.
            final = tree_hashes(folder) if folder else {p.relative_to(root).as_posix(): file_hash(p) for p in protected}
            if final != before or output.exists():
                raise ValueError("Source or destination changed during publication")
            staged.rename(output)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="4주차 버전 inventory·저장 결과 재생성 (모델 호출 0)")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inventory")
    inspect.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify", help="Verify a transferred package without keys or its original store")
    check.add_argument("package", type=Path)
    check.add_argument("--expected-report-sha256")
    check.add_argument("--expected-source-inventory-sha256")
    run = commands.add_parser("replay")
    run.add_argument("batch_id")
    run.add_argument("--source", choices=("original", "overlay"), default="original")
    run.add_argument("--runs-dir", type=Path)
    run.add_argument("--filters", type=Path)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            result = inventory()
            args.output.mkdir(parents=True, exist_ok=False)
            atomic_json(args.output / "release-manifest.json", result)
        elif args.command == "verify":
            result = verify_package(args.package, expected_report_sha256=args.expected_report_sha256,
                                    expected_source_inventory_sha256=args.expected_source_inventory_sha256)
        else:
            filters = json.loads(args.filters.read_text(encoding="utf-8")) if args.filters else {}
            result = replay(args.batch_id, args.output, source=args.source, runs_dir=args.runs_dir, filters=filters)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, RepositoryError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": "재현 실패: 자료·버전·필터·새 출력 경로를 확인하세요."}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
