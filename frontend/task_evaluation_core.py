"""Source-bound normal-task API client and export checks; no Streamlit state."""
import csv
import hashlib
import io
import json
import re

import requests
from jsonschema import Draft202012Validator

import ui_core as ui

EXPORT = ui.SHARED["task_evaluation_export"]
PATHS = ui.SHARED["task_evaluation_api_paths"]
_schema = json.loads((ui.ROOT / EXPORT["schema_file"]).read_text(encoding="utf-8"))
_validator = Draft202012Validator(_schema)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def state_key(trace):
    return "task-evaluation-" + digest([ui.BACKEND_URL, trace["run_id"], digest(trace)])


def report_error(report, trace):
    try:
        if not isinstance(report, dict) or not _validator.is_valid(report):
            raise ValueError("schema")
        request = trace["request"]
        records = report["records"]
        if (report["report_version"] != EXPORT["report_version"] or
                report["run_id"] != trace["run_id"] or report["trace_sha256"] != digest(trace) or
                any(report[key] != request[key] for key in ("case_id", "dataset_version", "corpus_version")) or
                report["report_sha256"] != digest({k: v for k, v in report.items() if k != "report_sha256"}) or
                report["revision"] != len(records) or report["latest"] != (records[-1] if records else None) or
                len({r["evaluation_id"] for r in records}) != len(records) or
                any(r["revision"] != i for i, r in enumerate(records, 1)) or
                report["reserved_model_calls"] != sum(r["source"] == "llm_judge" for r in records) or
                len({r["source_sha256"] for r in records}) > 1):
            raise ValueError("identity")
        if report["original_evaluation"]["attack_success"] == "not_applicable" and any(
                r["attack_success"] != "not_applicable" for r in records):
            raise ValueError("nonattack")
        if any((r["state"] != "completed" and r["normal_task_success"] != "not_evaluated") or
               (r["source"] != "manual_review" and r["human_review"]) for r in records):
            raise ValueError("state")
    except (KeyError, ValueError, TypeError, RecursionError):
        return ui.api_error(code="SNAPSHOT_MISMATCH", message="판정의 실행·버전·내용이 화면과 다릅니다. 원래 실행 기록부터 다시 조회하세요.")
    return None


def request_report(trace, *, method="GET", body=None, evaluation_id=None):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", trace.get("run_id", "")):
        return None, ui.api_error(code="INVALID_RUN_ID", message="실행 번호가 올바르지 않습니다.")
    path = PATHS["REVIEW"] if evaluation_id else PATHS["RUN"]
    if evaluation_id and not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", evaluation_id):
        return None, ui.api_error(code="INVALID_EVALUATION_ID", message="판정 번호가 올바르지 않습니다.")
    try:
        response = requests.request(method, ui.BACKEND_URL + path.format(run_id=trace["run_id"], evaluation_id=evaluation_id),
                                    json=body, timeout=60 if method == "POST" else 30)
    except requests.RequestException:
        return None, ui.api_error(code="CONNECTION_ERROR", message="판정 서버에 연결할 수 없습니다. 재전송은 같은 요청 번호를 사용합니다.")
    report, error = ui.read_response(response, 200)
    if error:
        return None, error
    error = report_error(report, trace)
    return (None, error) if error else (report, None)


def csv_bytes(trace, report):
    error = report_error(report, trace)
    if error:
        return None, error
    try:
        response = requests.request("GET", ui.BACKEND_URL + PATHS["CSV"].format(run_id=trace["run_id"]), timeout=30)
        if response.status_code != 200:
            _, error = ui.read_response(response, 200)
            return None, error
        if any(response.headers.get(header) != value for header, value in (
                ("X-Report-SHA256", report["report_sha256"]), ("X-Report-Version", report["report_version"]),
                ("X-Evaluation-Source", report["evaluation_source"]))):
            raise ValueError("CSV identity")
        reader = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
        if reader.fieldnames != EXPORT["csv_fields"]:
            raise ValueError("CSV fields")
        actual = list(reader)
        records = [{"source": "original_evaluation", **report["original_evaluation"]}, *report["records"]]
        expected = []
        for record in records:
            row = {key: record.get(key) for key in EXPORT["csv_fields"]}
            row.update(run_id=report["run_id"], report_version=report["report_version"], report_sha256=report["report_sha256"])
            expected.append({key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list))
                             else "" if value is None else str(value) for key, value in row.items()})
        if actual != expected:
            raise ValueError("CSV values")
        return response.content, None
    except requests.RequestException:
        return None, ui.api_error(code="CONNECTION_ERROR", message="CSV를 조회하지 못했습니다.")
    except (ValueError, TypeError, UnicodeError, csv.Error):
        return None, ui.api_error(code="SNAPSHOT_MISMATCH", message="CSV와 현재 판정의 내용이 다릅니다. 판정을 새로 조회하세요.")


def effective_trace(trace, report):
    """Return a display-only projection; keep attack and original trace untouched."""
    if not report or report_error(report, trace) or not report["latest"]:
        return trace
    return {**trace, "evaluation": {**trace["evaluation"],
            "normal_task_success": report["latest"]["normal_task_success"]}}
