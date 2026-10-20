"""Load the adopted dev research decisions without granting holdout authority."""
from __future__ import annotations

import json
from pathlib import Path

from backend.app.batch_models import RecommendationPolicy, StatisticsPolicy
from scripts.data_contract import ROOT, require

SOURCE_FILES = (
    "configs/week3-evaluation-policy.json", "configs/week3-service-decision.v0.2.json",
    "configs/week3-statistical-policy.json", "data/week3/research-evaluation-spec.v0.4.json",
    "data/week2/target-gold.v0.1.jsonl", "data/week2/attack-catalog.v0.1.json",
    "data/week2/language-variants.v0.1.json", "data/week2/rubric_v0.2.md",
    "data/week3/rubric_v0.3.md", "scripts/week3_policy.py",
)


def research_policy(root: Path = ROOT) -> dict:
    def read(name):
        return json.loads((root / name).read_text(encoding="utf-8-sig"))

    service = read("configs/week3-service-decision.v0.2.json")
    statistics = read("configs/week3-statistical-policy.json")
    rubric = read("data/week3/research-evaluation-spec.v0.4.json")
    runtime = RecommendationPolicy.model_validate(read(service["runtime_policy_file"]))
    compiled_statistics = StatisticsPolicy.model_validate(statistics["runtime_statistics"])
    require(all(value["decision_status"] == "adopted_for_dev" for value in (service, statistics, rubric)),
            "Research decisions must explicitly apply to dev")
    require(service["runtime_policy_version"] == runtime.version, "Research/runtime service version mismatch")
    require({key: row["value"] for key, row in service["threshold_basis"].items()} == runtime.thresholds.model_dump(),
            "Research/runtime threshold mismatch")
    require(statistics["execution_plan"]["split"] == "dev" and
            statistics["execution_plan"]["holdout_execution_authorized"] is False and
            service["independent_gates"]["holdout_authorized"] is False and rubric["holdout_authorized"] is False,
            "Research loader never authorizes holdout")
    require(runtime.status == compiled_statistics.status == "draft" and
            not runtime.final_recommendation_allowed and not runtime.reviewed_by and
            not compiled_statistics.reviewed_by, "Do not turn delegated research into fabricated reviewed policy")
    return {"statistics": compiled_statistics.model_dump(mode="json"),
            "repeats": statistics["execution_plan"]["repeats_per_case_condition"],
            "evaluation_policy_file": service["runtime_policy_file"],
            "source_files": list(SOURCE_FILES),
            "decision": {"status": "adopted_for_dev", "service_version": runtime.version,
                         "statistics_version": compiled_statistics.version, "rubric_version": rubric["version"],
                         "authority": service["authority"], "holdout_authorized": False}}
