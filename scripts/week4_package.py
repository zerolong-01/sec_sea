"""Version inventory and immutable saved-result replay for issue #47.

No execution command and no Settings.from_environment: credentials, .env, live
endpoints and current model configuration are irrelevant to replay.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import digest, file_hash
from backend.app.batch_analysis import aggregate, export_report
from backend.app.batch_models import BatchFilters
from backend.app.repository import RepositoryError
from backend.app.research_models import ResearchFilters
from backend.app.research_reports import INDEX, ROOT, load_evidence, research_csv, research_report
from backend.app.storage import atomic_json

VERSION = "week4-reproduction-package-v0.1"


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
    public = index["public_result_summary"]
    if file_hash(root / public["path"]) != public["sha256"]:
        raise ValueError("Published result summary differs from the release index")
    _, _, evidence = load_evidence(root)
    return {"version": VERSION, "code_commit": revision, "working_tree_dirty": dirty,
            "code_and_data_files": files, "code_and_data_inventory_sha256": digest(files),
            "environment": environment(), "release_index": index, "research_evidence_files": evidence,
            "private_material_available": {p["name"]: (root / p["private_runs_dir"]).is_dir() for p in index["experiments"]},
            "model_calls": 0, "human_ABC_acceptance": "pending", "holdout_authorized": False}


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
                atomic_json(staged / "decision-record.json", {
                    "batch_id": batch_id, "report_version": report.report_version,
                    "report_sha256": report_hash, "evaluation_version": report.evaluation_version,
                    "evaluation_snapshot_sha256": report.evaluation_snapshot_sha256,
                    "filters": report.filters.model_dump(mode="json"), "provenance": report.provenance, **report.decisions})
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
