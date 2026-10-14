"""화면(app.py)과 검증 스크립트(verify_ui.py)가 같이 쓰는 부분.
Streamlit을 쓰지 않으므로 화면 없이도 불러올 수 있다."""
import json
import os
import re
from pathlib import Path

import requests

# 통합 변수 파일을 읽어 온다 (화면 글자는 여기의 label_ko를 쓴다)
ROOT = Path(__file__).resolve().parent.parent
SHARED = json.loads(
    (ROOT / "contracts" / "shared-variables-v0.1.json").read_text(encoding="utf-8")
)
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
NO_VALUE = "기록 없음"
D2_MODES = tuple(SHARED["defense_modes"][name]["value"] for name in ("D2", "D1_D2"))
BOTH = SHARED["defense_positions"]["BOTH"]["value"]


def api_error(status=None, code=None, message=None, run_id=None):
    return {"status": status, "code": code, "message": message, "run_id": run_id}


def read_response(res, expected_status, wrapped=False):
    """API 오류와 잘못된 JSON/빈 응답을 화면에서 표시할 오류로 바꾼다."""
    try:
        payload = res.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return None, api_error(res.status_code, "INVALID_RESPONSE", "서버 응답이 JSON 객체가 아닙니다.")
    if res.status_code == expected_status:
        trace = payload.get("trace") if wrapped else payload
        if not isinstance(trace, dict) or not trace.get("run_id"):
            return None, api_error(res.status_code, "INVALID_RESPONSE", "서버 응답에 실행 기록이 없습니다.")
        return trace, None
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return None, api_error(res.status_code, detail.get("code"), detail.get("message"), detail.get("run_id"))
    return None, api_error(res.status_code, "HTTP_ERROR", str(detail or "서버 요청이 실패했습니다."))


def load_run(run_id):
    """표시용 저장 trace만 GET 조회한다. 모델 실행을 요청하지 않는다."""
    run_id = run_id.strip()
    if not re.fullmatch(r"run-[a-z0-9_-]{1,60}", run_id):
        return None, api_error(code="INVALID_RUN_ID", message="올바른 실행 번호(run-...)를 입력하세요.")
    try:
        res = requests.get(f"{BACKEND_URL}/api/v1/runs/{run_id}", timeout=30)
    except requests.RequestException:
        return None, api_error(code="CONNECTION_ERROR", message="저장 결과를 조회할 수 없습니다. 서버 연결을 확인하세요.", run_id=run_id)
    trace, error = read_response(res, 200)
    if error:
        error["run_id"] = run_id
    if trace and trace["run_id"] != run_id:
        return None, api_error(code="INVALID_RESPONSE", message="요청한 실행 번호와 조회 결과가 다릅니다.", run_id=run_id)
    return trace, error


def label_of(group, value):
    """value에 해당하는 한글 이름을 찾는다. 없으면 value를 그대로 돌려준다."""
    items = SHARED.get(group, {})
    if isinstance(items, dict):
        items = items.values()
    for item in items:
        if item.get("value") == value:
            return item.get("label_ko", value)
    return value

def run_case(case_id, scenario, dataset_version, corpus_version, mode,
             defense_position=SHARED["defense_positions"]["BOTH"]["value"]):
    """백엔드에 실행을 요청하고 (trace, 오류)를 돌려준다."""
    body = {
        "schema_version": SHARED["execution_contract_version"],
        "artifact_type": SHARED["artifact_types"]["RUN_REQUEST"]["value"],
        "case_id": case_id,
        "scenario": scenario,
        "defense_mode": mode,
        "defense_position": defense_position,
        "dataset_version": dataset_version,
        "corpus_version": corpus_version,
        "requested_by": "frontend-ui",
    }
    try:
        res = requests.post(f"{BACKEND_URL}/api/v1/runs", json=body, timeout=120)
    except requests.RequestException:
        return None, {
            "status": None,
            "code": None,
            "message": "백엔드에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요.",
            "run_id": None,
        }

    trace, error = read_response(res, 201, wrapped=True)
    if error and error["run_id"]:
        trace, _ = load_run(error["run_id"])
    return trace, error

def text_or_missing(value):
    """값이 없으면 '기록 없음', 있으면 글자로 바꾼다. (표 안의 칸을 모두 글자로 맞춘다)"""
    return NO_VALUE if value is None else str(value)


def count_decisions(trace):
    """방어 판정을 종류별로 세어 '허용 1 · 격리 1'처럼 만든다."""
    counts = {}
    for event in trace.get("defense_events") or []:
        name = label_of("defense_decisions", event.get("decision"))
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return "방어 판정 없음"
    return " · ".join(f"{name} {count}" for name, count in counts.items())


def summary_row(column, title, trace, error):
    """비교 표의 한 줄. 서버가 준 값만 옮기고, 화면에서 새로 계산하지 않는다.
    column은 첫 칸의 제목(예: 방어 모드), title은 그 값(예: D1)이다."""
    row = {column: title}
    if not trace:
        # 실행 자체가 안 된 경우: 오류만 보여 준다
        row["실행 번호"] = (error or {}).get("run_id") or NO_VALUE
        row["상태"] = (error or {}).get("code") or "실행 안 됨"
        return row

    output = trace.get("output") or {}
    evaluation = trace.get("evaluation") or {}
    metrics = trace.get("metrics") or {}
    docs = trace.get("retrieval") or []
    included = sum(1 for doc in docs if doc.get("included_in_prompt"))

    row["실행 번호"] = trace.get("run_id") or NO_VALUE
    row["상태"] = label_of("run_statuses", trace.get("status"))
    row["출력 결과"] = label_of("output_outcomes", output.get("outcome")) or NO_VALUE
    row["공격 성공"] = label_of("evaluation_statuses", evaluation.get("attack_success")) or NO_VALUE
    row["정상 태스크 성공"] = label_of("evaluation_statuses", evaluation.get("normal_task_success")) or NO_VALUE
    row["방어 판정"] = count_decisions(trace)
    row["프롬프트 포함 문서"] = f"{included} / {len(docs)}"
    for item in SHARED["metric_keys"].values():
        value = metrics.get(item["value"])
        if item["value"] == "estimated_cost_usd" and value is None:
            row[item["label_ko"]] = "미확인"
        else:
            row[item["label_ko"]] = text_or_missing(value)
    row["사용량 출처"] = label_of("usage_sources", metrics.get("usage_source")) or NO_VALUE
    row["생성 / 탐지 호출"] = f"{text_or_missing(metrics.get('generation_call_count'))} / {text_or_missing(metrics.get('detection_call_count'))}"
    trace_error = error or trace.get("error")
    if trace_error:
        row["오류"] = trace_error.get("code") or NO_VALUE
    return row


# 비교하는 실행끼리 같아야 하는 조건 (화면 이름, trace에서 찾는 위치)
# D2 설정은 D2가 켜진 실행끼리만 비교한다.
SAME_CONDITIONS = [
    ("케이스", ("request", "case_id"), False),
    ("앱", ("request", "scenario"), False),
    ("데이터 버전", ("request", "dataset_version"), False),
    ("코퍼스 버전", ("request", "corpus_version"), False),
    ("실행 범위", ("manifest", "execution_scope"), False),
    ("실행 종류", ("manifest", "execution_kind"), False),
    ("모델 제공자", ("manifest", "provider"), False),
    ("생성 모델", ("manifest", "model_id"), False),
    ("생성 설정", ("manifest", "generation_parameters"), False),
    ("검색 설정", ("manifest", "retrieval_config_version"), False),
    ("기본 시스템 프롬프트", ("manifest", "base_system_prompt_version"), False),
    ("평가기 버전", ("manifest", "evaluator_version"), False),
    ("가격 버전", ("manifest", "pricing_version"), False),
    ("가격표", ("manifest", "pricing_snapshot"), False),
    ("모델 호출 상한", ("manifest", "max_model_calls"), False),
    ("D2 설정", ("manifest", "d2_configuration"), True),
    ("D1 버전", ("manifest", "defense_config_versions", "D1"), "D1"),
]


def raw_condition(trace, path):
    value = trace
    for key in path:
        value = (value or {}).get(key)
    # 0.2 계약은 실행 종류가 없으며 전체 파이프라인만 지원했다.
    if path == ("manifest", "execution_kind") and value is None and trace.get("schema_version") == "0.2":
        return SHARED["execution_kinds"]["FULL_PIPELINE"]["value"]
    return value


def condition_value(trace, path):
    """trace 안의 값을 찾아 글자로 바꾼다. 묶음 값은 JSON 글자로 바꾼다."""
    value = raw_condition(trace, path)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text_or_missing(value)


def condition_rows(results):
    """조건 표를 만들고, 값이 서로 다른 항목 이름 목록도 돌려준다."""
    rows, different = [], []
    for name, path, only_d2 in SAME_CONDITIONS:
        row = {"조건": name}
        values = set()
        for item in results:
            if not item["trace"]:
                row[item["title"]] = "실행 안 됨"
                continue
            mode = (item["trace"].get("request") or {}).get("defense_mode")
            if (only_d2 is True and mode not in D2_MODES or
                    only_d2 == "D1" and mode not in ("D1", "D1+D2")):
                row[item["title"]] = "해당 없음"
                continue
            value = condition_value(item["trace"], path)
            row[item["title"]] = value
            values.add(value)
        if not values or NO_VALUE in values:
            row["같음"] = "확인 불가"
        else:
            row["같음"] = "예" if len(values) == 1 else "아니오"
        if len(values) > 1:
            different.append(name)
        rows.append(row)
    return rows, different


# 비교 판정 결과 (화면과 검증 스크립트가 같이 쓴다)
COMPARE_UNAVAILABLE = "비교 불가"
COMPARE_DIFFERENT = "조건 다름"
COMPARE_SAME = "조건 같음"


def compare_verdict(results, experiment=None):
    """비교할 수 있는지, 조건이 같은지 판정한다. (판정, 설명, 조건 표)를 돌려준다.
    trace가 없는 실행이 하나라도 있거나 실행이 2개 미만이면 비교 불가다."""
    rows, different = condition_rows(results)
    missing = [item["title"] for item in results if not item["trace"]]
    if len(results) < 2 or missing:
        if missing:
            message = "결과를 받지 못한 실행이 있습니다: " + ", ".join(missing)
        else:
            message = "비교하려면 실행 결과가 2개 이상 필요합니다."
        return COMPARE_UNAVAILABLE, message, rows
    invalid = []
    for item in results:
        trace = item["trace"]
        if (item.get("error") or trace.get("error") or
                trace.get("status") not in {SHARED["run_statuses"][name]["value"] for name in ("COMPLETED", "BLOCKED")} or
                any(e.get("error") for e in trace.get("defense_events") or [])):
            invalid.append(item["title"])
    if invalid:
        return COMPARE_UNAVAILABLE, "실패하거나 끝나지 않은 실행이 있습니다: " + ", ".join(invalid), rows
    incomplete = [row["조건"] for row in rows if any(
        row.get(item["title"]) in (NO_VALUE, "") or
        row["조건"] in ("D2 설정", "가격표") and row.get(item["title"]) == "{}"
        for item in results)]
    if incomplete:
        return COMPARE_UNAVAILABLE, "확인할 수 없는 비교 조건: " + ", ".join(incomplete), rows
    if experiment == "modes":
        modes = [(item["trace"].get("request") or {}).get("defense_mode") for item in results]
        if sorted(modes) != sorted(m["value"] for m in SHARED["defense_modes"].values()):
            return COMPARE_UNAVAILABLE, "네 방어 모드의 결과가 각각 한 개씩 필요합니다.", rows
        if any((item["trace"].get("manifest") or {}).get("defense_position") != BOTH
               for item in results if item["trace"]["request"]["defense_mode"] in D2_MODES):
            return COMPARE_DIFFERENT, "기법 비교의 D2 위치는 입력 + 검색 문서여야 합니다.", rows
    if experiment == "positions":
        positions = [(item["trace"].get("manifest") or {}).get("defense_position") for item in results]
        if (any((item["trace"].get("request") or {}).get("defense_mode") != "D2" for item in results) or
                sorted(str(p) for p in positions) != sorted(p["value"] for p in SHARED["defense_positions"].values())):
            return COMPARE_UNAVAILABLE, "D1 없이 D2만 적용한 세 위치의 결과가 각각 필요합니다.", rows
    if different:
        return COMPARE_DIFFERENT, "비교 조건이 다른 항목: " + ", ".join(different), rows
    return COMPARE_SAME, "비교한 실행들의 조건(데이터·모델·검색·생성 설정 등)이 모두 같습니다.", rows
