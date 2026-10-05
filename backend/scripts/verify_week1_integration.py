from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from app.config import Settings
from app.models import CaseRecord, RunRequest, RunTrace
from app.repository import ExperimentRepository, RunTraceStore
from app.service import RunService, build_provider

REQUIRED_LABELS = {"attack", "benign", "hard_negative"}


def validate_trace(trace: RunTrace, case: CaseRecord) -> None:
    """Assert the fields the week-one UI needs for one completed RAG run."""

    if trace.status != "completed":
        raise RuntimeError(f"{case.case_id}: run status is {trace.status}")
    if trace.request.case_id != case.case_id:
        raise RuntimeError(f"{case.case_id}: trace request does not match the case")
    if trace.request.defense_mode != "none" or trace.defense_events:
        raise RuntimeError(f"{case.case_id}: week-one run must have no defense events")
    if not trace.retrieval:
        raise RuntimeError(f"{case.case_id}: retrieval is empty")
    if len(trace.prompt_assembly) < 2:
        raise RuntimeError(f"{case.case_id}: prompt assembly is incomplete")
    if trace.output.outcome != "generated" or trace.output.display_text is None:
        raise RuntimeError(f"{case.case_id}: generated output is missing")
    if trace.metrics.latency_ms is None:
        raise RuntimeError(f"{case.case_id}: latency metric is missing")
    if not all(
        (
            trace.manifest.model_id,
            trace.manifest.system_prompt_version,
            trace.manifest.retrieval_config_version,
        )
    ):
        raise RuntimeError(f"{case.case_id}: manifest is incomplete")


def run_representative_cases(
    settings: Settings, case_ids: list[str], corpus_version: str, requested_by: str
) -> list[tuple[CaseRecord, RunTrace]]:
    repository = ExperimentRepository(settings.data_dir)
    service = RunService(
        settings,
        repository,
        RunTraceStore(settings.runs_dir),
        build_provider(settings),
    )
    results: list[tuple[CaseRecord, RunTrace]] = []

    for case_id in case_ids:
        case = repository.get_case(case_id)
        if case.scenario != "rag_chat":
            raise RuntimeError(f"{case_id}: week-one verification only supports rag_chat")
        trace = service.execute(
            RunRequest(
                schema_version="0.1",
                artifact_type="run_request",
                case_id=case.case_id,
                scenario=case.scenario,
                defense_mode="none",
                dataset_version=case.source_version,
                corpus_version=corpus_version,
                requested_by=requested_by,
            )
        )
        validate_trace(trace, case)
        results.append((case, trace))

    labels = {case.label for case, _ in results}
    if labels != REQUIRED_LABELS:
        received = ", ".join(sorted(labels))
        raise RuntimeError(
            "representative cases must include exactly attack, benign, and "
            f"hard_negative; received: {received}"
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and verify the three representative week-one RAG cases."
    )
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        required=True,
        help="Representative case ID; provide this option three times.",
    )
    parser.add_argument(
        "--corpus-version",
        required=True,
        help="source_version shared by the supplied corpus documents.",
    )
    parser.add_argument("--data-dir", type=Path, help="Override DATA_DIR.")
    parser.add_argument("--runs-dir", type=Path, help="Override RUNS_DIR.")
    parser.add_argument(
        "--requested-by", default="week1-integration", help="Trace requester label."
    )
    args = parser.parse_args()
    if len(args.case_ids) != 3:
        parser.error("provide exactly three --case-id values")
    if len(set(args.case_ids)) != 3:
        parser.error("the three --case-id values must be distinct")
    return args


def main() -> int:
    args = parse_args()
    settings = Settings.from_environment()
    settings = replace(
        settings,
        data_dir=args.data_dir.resolve() if args.data_dir else settings.data_dir,
        runs_dir=args.runs_dir.resolve() if args.runs_dir else settings.runs_dir,
    )

    try:
        results = run_representative_cases(
            settings, args.case_ids, args.corpus_version, args.requested_by
        )
    except Exception as exc:
        print(f"week-one integration verification failed: {exc}")
        return 1

    for case, trace in results:
        print(
            f"{case.label}: {case.case_id} -> {trace.run_id} "
            f"({trace.metrics.latency_ms} ms)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
