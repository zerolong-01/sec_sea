"""Create/resume batches; report/export never call a model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.batch import BatchRunner
from backend.app.batch_analysis import aggregate, export_report
from backend.app.batch_models import BatchFilters, BatchReview, BatchSpec
from backend.app.config import Settings
from backend.app.repository import RepositoryError


def main(argv=None):
    parser = argparse.ArgumentParser(description="3주차 배치·예산·집계·export")
    parser.add_argument("--runs-dir", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inventory", help="Read-only hashes for a reviewed freeze record")
    inspect.add_argument("--spec", type=Path, required=True)
    create = commands.add_parser("create", help="Snapshot and plan, without any model call")
    create.add_argument("--spec", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("batch_id")
    run.add_argument("--max-items", type=int)
    run.add_argument("--retry-failed", action="store_true")
    run.add_argument("--retry-uncertain", action="store_true", help="May duplicate a paid call; preserves prior reservation")
    for name in ("show", "report", "export", "review"):
        command = commands.add_parser(name)
        command.add_argument("batch_id")
        if name in ("report", "export"):
            command.add_argument("--filters", type=Path)
        if name == "export":
            command.add_argument("--output", type=Path, required=True)
        if name == "review":
            command.add_argument("run_id")
            command.add_argument("--body", type=Path, required=True)
    commands.add_parser("list")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_environment()
        if args.runs_dir:
            from dataclasses import replace
            settings = replace(settings, runs_dir=args.runs_dir.resolve())
        runner = BatchRunner(settings)
        if args.command in ("inventory", "create"):
            spec = BatchSpec.model_validate_json(args.spec.read_text(encoding="utf-8"),
                                                context={"inventory_only": args.command == "inventory"})
            result = (runner.inspect_inputs(spec)[-1] if args.command == "inventory" else
                      runner.store.summary(runner.create(spec)))
        elif args.command == "run":
            if args.max_items is not None and args.max_items < 1:
                raise ValueError("max-items must be positive")
            state = runner.execute(args.batch_id, max_items=args.max_items, retry_failed=args.retry_failed,
                                   retry_uncertain=args.retry_uncertain)
            result = runner.store.summary(state)
        elif args.command in ("report", "export"):
            filters = BatchFilters.model_validate_json(args.filters.read_text(encoding="utf-8")) if args.filters else BatchFilters()
            report = aggregate(settings.runs_dir, args.batch_id, filters)
            if args.command == "export":
                export_report(report, args.output)
            result = report.model_dump(mode="json")
        elif args.command == "review":
            result = runner.review(args.batch_id, args.run_id, BatchReview.model_validate_json(args.body.read_text(encoding="utf-8")))
        elif args.command == "show":
            result = runner.store.summary(runner.store.get(args.batch_id))
        else:
            result = runner.store.list()
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return (0 if result["status"] == "completed" else 2) if args.command == "run" else 0
    except (ValueError, OSError, KeyError, RepositoryError) as exc:
        # Error messages must not include private config or provider payloads.
        print(json.dumps({"error": type(exc).__name__, "message": "배치 요청 실패; 입력·버전·경로·실행 상태를 확인하세요."}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
