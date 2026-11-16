"""최종 보고서의 고정 4개 원본 공격 비교표를 공개 API와 연결한다."""
from batch_core import _json, _request, goal_text
from report_integrity import csv_error, report_error
from research_core import research_cell
from ui_core import SHARED, api_error

PATHS = SHARED["research_api_paths"]
VERSION = "week4-original-attack-comparison-v0.1"
METRICS = {"fresh_ai_attack_success": "공격 목표 달성", "fresh_ai_attack_task_utility": "공격 상황 업무 성공"}


def get_report():
    report, error = _json(*_request("GET", PATHS["ORIGINAL_ATTACKS"]), dict)
    if report is not None:
        error = report_error(report, version=VERSION, identifier="batch_id", value="batch-bd093a919251",
                             source="ai_research_overlay")
        if error:
            return None, error
    return report, error


def expected_csv_rows(report):
    common = {k: report[k] for k in ("batch_id", "report_version", "report_sha256", "evaluation_source",
                                    "evaluation_version", "evaluation_snapshot_sha256")}
    p = report["provenance"]
    common.update(source_report_sha256=p["source_report_sha256"], source_files=p["source_files"],
                  selection=report["selection"], human_review=p["human_review"], decision_status=report["decisions"]["status"])
    rows = []
    for condition in report["rows"]:
        for section in [dict(condition, goal_kind="combined_descriptive"), *condition["goal_groups"]]:
            for metric, values in section["metrics"].items():
                rows.append({**common, "condition_id": condition["condition_id"],
                    "display_condition": condition["display_condition"], "goal_kind": section["goal_kind"],
                    "inference_status": report["selection"]["inference_status"] if section["goal_kind"] == "combined_descriptive"
                                        else "family_independence_not_validated_small_strata",
                    "run_ids": section["run_ids"], "source_group_ids": section["source_group_ids"],
                    "metric": metric, "metric_source": p["metric_sources"][metric], **values})
    return rows


def get_csv(report):
    response, error = _request("GET", PATHS["ORIGINAL_ATTACKS_CSV"])
    if error:
        return None, error
    if response.headers.get("X-Report-SHA256") != report["report_sha256"]:
        return None, api_error(code="SNAPSHOT_MISMATCH", message="CSV와 화면의 보고서 해시가 다릅니다.")
    error = csv_error(response.content, expected_csv_rows(report), identity=("condition_id", "goal_kind", "metric"),
                      json_fields=("source_files", "selection", "run_ids", "source_group_ids", "excluded", "ci95"))
    return (None, error) if error else (response.content, None)


def rows(report, *, goals=False):
    result = []
    for condition in report["rows"]:
        for section in condition["goal_groups"] if goals else [condition]:
            row = {"방어 조건": condition["display_condition"]}
            if goals:
                row["공격 목표"] = goal_text(section["goal_kind"])
            row.update({label: research_cell(section["metrics"][key]) for key, label in METRICS.items()})
            result.append(row)
    return result
