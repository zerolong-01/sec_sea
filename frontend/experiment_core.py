"""다중 모델 결과를 같은 cohort·평가 snapshot으로 조회한다. 실행 API 없음."""
import re

from batch_core import METRICS, _json, _request, metric_cell, option_text
from report_integrity import csv_error, report_error
from ui_core import api_error, label_of

BASE = "/api/v1/model-experiments"
VERSION = "model-comparison-v0.1"
FILTERS = {"source_id": "데이터 출처", "scenario": "앱", "language": "언어",
           "condition_id": "방어 조건", "goal_kind": "공격 목표", "ablation_variant": "변형"}
CSV_FIELDS = ("row_kind", "experiment_id", "report_sha256", "source_inventory_sha256", "filters",
              "model_key", "model_id", "batch_id", "comparison_id", "cohort", "metric", "value",
              "numerator", "denominator", "ci95", "excluded", "normal_benchmark_id", "cost_scope", "summary")


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"experiment-[a-f0-9]{12}", value) is not None


def body(filters):
    return {key: value for key, value in (filters or {}).items() if value is not None}


def list_experiments():
    data, error = _json(*_request("GET", BASE), list)
    if data is not None:
        if any(not isinstance(row, dict) or not valid_id(row.get("experiment_id")) for row in data):
            return None, api_error(code="INVALID_RESPONSE", message="실험 목록의 식별 정보를 확인할 수 없습니다.")
        data = sorted(data, key=lambda row: row.get("created_at") or "", reverse=True)
    return data, error


def get_report(experiment_id, filters=None):
    if not valid_id(experiment_id):
        return None, api_error(code="INVALID_EXPERIMENT_ID", message="올바른 실험 번호가 아닙니다.")
    report, error = _json(*_request("POST", f"{BASE}/{experiment_id}/report", body(filters)), dict)
    if report is not None:
        error = report_error(report, version=VERSION, identifier="experiment_id", value=experiment_id,
                             source="original_saved_evaluation")
        if (error or body(report.get("filters")) != body(filters) or
                (report.get("summary") or {}).get("experiment_id") != experiment_id):
            return None, error or api_error(code="SNAPSHOT_MISMATCH", message="요청한 실험·필터와 보고서가 다릅니다.")
    return report, error


def expected_csv_rows(report):
    common = {field: "" for field in CSV_FIELDS}
    common.update(experiment_id=report["experiment_id"], report_sha256=report["report_sha256"],
                  source_inventory_sha256=report["provenance"]["source_inventory_sha256"], filters=body(report["filters"]))
    result = [{**common, "row_kind": "report_metadata", "summary": report["summary"]}]
    for row in report["rows"]:
        for name, metric in row["metrics"].items():
            result.append({**common, "row_kind": "model_metric",
                **{key: row[key] for key in ("model_key", "model_id", "batch_id", "comparison_id", "cohort",
                                            "normal_benchmark_id", "cost_scope")}, "metric": name,
                **{key: metric[key] for key in ("value", "numerator", "denominator", "ci95", "excluded")}})
    return result


def get_csv(experiment_id, filters, report):
    if not valid_id(experiment_id):
        return None, api_error(code="INVALID_EXPERIMENT_ID", message="올바른 실험 번호가 아닙니다.")
    response, error = _request("POST", f"{BASE}/{experiment_id}/export.csv", body(filters))
    if error:
        return None, error
    if response.headers.get("X-Report-SHA256") != report["report_sha256"]:
        return None, api_error(code="SNAPSHOT_MISMATCH", message="CSV와 화면의 보고서 해시가 다릅니다.")
    error = csv_error(response.content, expected_csv_rows(report),
                      identity=("row_kind", "model_key", "comparison_id", "metric"),
                      json_fields=("filters", "cohort", "ci95", "excluded", "summary"))
    return (None, error) if error else (response.content, None)


def options(report):
    return {key: sorted({r["cohort"][key] for r in report["rows"] if r["cohort"].get(key) is not None})
            for key in FILTERS}


def rows(report):
    result = []
    for row in report["rows"]:
        cohort = row["cohort"]
        item = {"모델": row["model_id"], "프로필": row["model_key"], "방어 조건": cohort["condition_id"],
                "앱": label_of("scenarios", cohort["scenario"]), "데이터 출처": cohort["source_id"],
                "공격 목표": option_text("goal_kind", cohort["goal_kind"]),
                "변형": option_text("ablation_variant", cohort["ablation_variant"])}
        item.update({METRICS[name][0]: metric_cell(metric, METRICS[name][1]) for name, metric in row["metrics"].items()})
        item.update({"정상 기준": row["normal_benchmark_id"], "비용 범위": row["cost_scope"],
                     "배치": row["batch_id"], "row_id": row["row_id"]})
        result.append(item)
    return result
