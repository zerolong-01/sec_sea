"""Plan, run/resume and compare several target models under frozen conditions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.batch_models import BatchFilters
from backend.app.environment import PROJECT_ROOT, load_project_environment
from backend.app.experiment_models import ExperimentSpec
from backend.app.experiment_reports import experiment_report, export_experiment_report
from backend.app.experiments import ExperimentRunner
from backend.app.repository import RepositoryError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=PROJECT_ROOT / "runs")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Freeze all model plans without calling models")
    create.add_argument("--spec", type=Path, required=True)
    run = commands.add_parser("run", help="Explicitly execute/resume planned model batches")
    run.add_argument("experiment_id")
    run.add_argument("--max-items", type=int, help="Total new attempts across selected models")
    run.add_argument("--models", nargs="+", dest="model_keys")
    run.add_argument("--retry-failed", action="store_true")
    run.add_argument("--retry-uncertain", action="store_true", help="May duplicate a paid request; preserves its reservation")
    run.add_argument("--stop-on-error", action="store_true")
    commands.add_parser("list")
    for name in ("show", "report", "export"):
        command = commands.add_parser(name)
        command.add_argument("experiment_id")
        if name != "show":
            command.add_argument("--filters", type=Path)
        if name == "export":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        runner = ExperimentRunner(PROJECT_ROOT, args.runs_dir)
        if args.command == "create":
            load_project_environment(PROJECT_ROOT)
            spec = ExperimentSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
            result = runner.summary(runner.create(spec).experiment_id).model_dump(mode="json")
        elif args.command == "run":
            load_project_environment(PROJECT_ROOT)
            result = runner.execute(args.experiment_id, max_items=args.max_items, model_keys=args.model_keys,
                retry_failed=args.retry_failed, retry_uncertain=args.retry_uncertain,
                stop_on_error=args.stop_on_error).model_dump(mode="json")
        elif args.command == "list":
            result = [item.model_dump(mode="json") for item in runner.list()]
        elif args.command == "show":
            result = runner.summary(args.experiment_id).model_dump(mode="json")
        else:
            filters = BatchFilters.model_validate_json(args.filters.read_text(encoding="utf-8")) if args.filters else BatchFilters()
            report = experiment_report(PROJECT_ROOT, args.runs_dir, args.experiment_id, filters)
            if args.command == "export":
                export_experiment_report(report, args.output)
            result = report.model_dump(mode="json")
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return (0 if result["status"] == "completed" else 2) if args.command == "run" else 0
    except (ValueError, OSError, KeyError, RepositoryError):
        print(json.dumps({"error": "MODEL_EXPERIMENT_REQUEST_FAILED",
            "message": "모델 실험 요청 실패; 계획·스냅샷·환경 변수·실행 상태를 확인하세요."}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
