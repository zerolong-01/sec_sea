"""Compare saved task evaluations with source-bound dev labels; never call a model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.config import Settings
from backend.app.repository import ExperimentRepository, RunTraceStore
from backend.app.service import RunService
from backend.app.storage import atomic_json, file_sha256
from backend.app.task_evaluation import TaskEvaluationService


def benchmark(settings, labels):
    store = RunTraceStore(settings.runs_dir)
    # No generation provider, judge, environment loading or network is needed.
    runs = RunService(settings, ExperimentRepository(settings.data_dir), store, None)
    service = TaskEvaluationService(settings, runs, store)
    rows, seen = [], set()
    for label in labels:
        if set(label) != {"run_id", "source_sha256", "normal_task_success", "label_source", "reviewer", "reason"}:
            raise ValueError("Invalid label fields")
        run_id, expected = label["run_id"], label["normal_task_success"]
        if (run_id in seen or expected not in ("success", "failure", "review_needed") or
                label["label_source"] not in ("human", "fixture") or
                not isinstance(label["reviewer"], str) or not label["reviewer"].strip() or
                not isinstance(label["reason"], str) or not label["reason"].strip()):
            raise ValueError("Invalid or duplicate dev label")
        seen.add(run_id)
        raw = store.get_raw(run_id)
        case = (raw.get("evaluation_context") or {}).get("case")
        if not case or case["split"] != "dev":
            raise ValueError("Benchmark requires frozen dev evidence")
        if label["source_sha256"] != file_sha256(store._path(run_id, "raw")):
            raise ValueError("Label is not bound to saved evidence")
        report = service.report(run_id)
        # Manual corrections are not an automatic judge prediction.
        predictions = [r for r in report.records if r.source != "manual_review"]
        if not predictions:
            raise ValueError("Missing saved automatic prediction")
        prediction = predictions[-1]
        rows.append({"run_id": run_id, "label_source": label["label_source"],
            "expected": expected, "predicted": prediction.normal_task_success,
            "evaluation_id": prediction.evaluation_id, "source_sha256": prediction.source_sha256,
            "error_code": prediction.error_code, "metrics": prediction.metrics.model_dump(mode="json"),
            "report_sha256": report.report_sha256, "evaluator_version": prediction.evaluator_version,
            "rubric_version": prediction.rubric_version, "policy_version": prediction.policy_version,
            "model_id": prediction.model_id, "execution_scope": prediction.execution_scope})
    if len({(r["evaluator_version"], r["rubric_version"], r["policy_version"], r["model_id"], r["execution_scope"])
            for r in rows}) > 1:
        raise ValueError("Different judge/model/rubric/policy versions require separate benchmarks")
    groups = {}
    for source in sorted({r["label_source"] for r in rows}):
        selected = [r for r in rows if r["label_source"] == source]
        decisive = [r for r in selected if r["expected"] in ("success", "failure") and r["predicted"] in ("success", "failure")]
        costs = [r["metrics"]["estimated_cost_usd"] for r in selected]
        groups[source] = {"count": len(selected), "exact_matches": sum(r["expected"] == r["predicted"] for r in selected),
            "exact_agreement": sum(r["expected"] == r["predicted"] for r in selected)/len(selected),
            "decisive_count": len(decisive), "decisive_agreement": sum(r["expected"] == r["predicted"] for r in decisive)/len(decisive) if decisive else None,
            "false_success_count": sum(r["expected"] == "failure" and r["predicted"] == "success" for r in selected),
            "review_return_rate": sum(r["predicted"] == "review_needed" for r in selected)/len(selected),
            "not_evaluated_count": sum(r["predicted"] == "not_evaluated" for r in selected),
            "error_count": sum(r["error_code"] is not None for r in selected),
            "model_calls": sum(r["metrics"]["model_call_count"] for r in selected),
            "estimated_cost_usd": sum(costs) if all(c is not None for c in costs) else None,
            "known_cost_usd": sum(r["metrics"]["known_cost_usd"] for r in selected),
            "total_latency_ms": sum(r["metrics"]["latency_ms"] or 0 for r in selected)}
    return {"version": "normal-task-benchmark-v0.1", "groups": groups, "rows": rows,
            "read_model_calls": 0, "human_labeled_comparison": "performed" if "human" in groups else "pending",
            "limitations": ["Fixture votes test transport and contracts, not judge quality.",
                "Confidence threshold and rubric require independent human dev validation."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = Settings(project_root=root, data_dir=root / "data/week2", runs_dir=args.runs_dir,
        model_provider="demo", model_id="offline-reader", system_prompt_version="v0.1",
        retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None)
    labels = [json.loads(line) for line in args.labels.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = benchmark(settings, labels)
    atomic_json(args.output, result)
    print(json.dumps({"status": "passed", "groups": result["groups"], "read_model_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
