"""화면(app.py)과 검증 스크립트(verify_ui.py)가 같이 쓰는 부분.
Streamlit을 쓰지 않으므로 화면 없이도 불러올 수 있다."""
import json
import os
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

    try:
        payload = res.json()
    except ValueError:
        payload = {}

    # 성공 또는 제공자 실패: trace가 함께 온다
    if res.status_code == 201:
        return payload.get("trace"), None

    # 404, 422 등: detail의 code, message, run_id를 그대로 쓴다
    detail = payload.get("detail")
    if not isinstance(detail, dict):
        detail = {"code": None, "message": str(detail), "run_id": None}
    error = {
        "status": res.status_code,
        "code": detail.get("code"),
        "message": detail.get("message"),
        "run_id": detail.get("run_id"),
    }

    # run_id가 있으면 실패 trace도 조회한다
    trace = None
    if error["run_id"]:
        try:
            got = requests.get(f"{BACKEND_URL}/api/v1/runs/{error['run_id']}", timeout=30)
            if got.status_code == 200:
                trace = got.json()
        except requests.RequestException:
            pass
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
    row["생성 / 탐지 호출"] = f"{metrics.get('generation_call_count', 0)} / {metrics.get('detection_call_count', 0)}"
    if error:
        row["오류"] = error.get("code") or NO_VALUE
    return row


# 비교하는 실행끼리 같아야 하는 조건 (화면 이름, trace에서 찾는 위치)
# D2 설정은 D2가 켜진 실행끼리만 비교한다.
SAME_CONDITIONS = [
    ("케이스", ("request", "case_id"), False),
    ("데이터 버전", ("request", "dataset_version"), False),
    ("코퍼스 버전", ("request", "corpus_version"), False),
    ("실행 범위", ("manifest", "execution_scope"), False),
    ("모델 제공자", ("manifest", "provider"), False),
    ("생성 모델", ("manifest", "model_id"), False),
    ("생성 설정", ("manifest", "generation_parameters"), False),
    ("검색 설정", ("manifest", "retrieval_config_version"), False),
    ("기본 시스템 프롬프트", ("manifest", "base_system_prompt_version"), False),
    ("평가기 버전", ("manifest", "evaluator_version"), False),
    ("가격 버전", ("manifest", "pricing_version"), False),
    ("모델 호출 상한", ("manifest", "max_model_calls"), False),
    ("D2 설정", ("manifest", "d2_configuration"), True),
]


def condition_value(trace, path):
    """trace 안의 값을 찾아 글자로 바꾼다. 묶음 값은 JSON 글자로 바꾼다."""
    value = trace
    for key in path:
        value = (value or {}).get(key)
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
            if only_d2 and mode not in D2_MODES:
                row[item["title"]] = "해당 없음"
                continue
            value = condition_value(item["trace"], path)
            row[item["title"]] = value
            values.add(value)
        row["같음"] = "예" if len(values) <= 1 else "아니오"
        if len(values) > 1:
            different.append(name)
        rows.append(row)
    return rows, different
