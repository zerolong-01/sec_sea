"""3주차 배치 대시보드에서 쓰는 부분 (서버 요청, 표시용 값 만들기).

Streamlit을 쓰지 않으므로 화면 없이도 불러와 테스트할 수 있다.
원칙
- 지표·CI·Pareto·추천은 서버(집계 API)가 준 값을 그대로 보여 준다. 화면에서 다시 계산하지 않는다.
- 값이 없으면(null) 0이나 실패로 바꾸지 않고 "기록 없음"으로 보여 준다.
- 여기 있는 요청은 전부 조회(GET)·집계(POST report/export)라서 모델을 호출하지 않는다.
"""
import csv
import io
import json
import re

import requests

from ui_core import BACKEND_URL, NO_VALUE, SHARED, api_error, label_of

PATHS = SHARED["batch_api_paths"]
BATCH_ID_PATTERN = re.compile(r"batch-[a-f0-9]{12}")
NO_CI = "CI 없음"

# ---------------------------------------------------------------------------
# 화면 이름표
# 아래 이름표는 통합 변수 파일(shared-variables)에 아직 없어서 화면 전용으로 둔다.
# 팀에 공유한 뒤 통합 변수 파일에 들어가면 그쪽 label_ko를 쓰도록 바꾼다.
# ---------------------------------------------------------------------------

# 지표 이름: (화면 이름, 종류, 좋은 방향)
#   종류 rate=비율(0~1), ms=밀리초, usd=달러, tokens=토큰 수
#   좋은 방향 low=낮을수록 좋음, high=높을수록 좋음, None=방향 없음
METRICS = {
    "asr": ("ASR (공격 성공률)", "rate", "low"),
    "task_success": ("정상 태스크 성공률", "rate", "high"),
    "benign_fpr": ("FPR (정상 케이스)", "rate", "low"),
    "hard_negative_fpr": ("FPR (하드 네거티브)", "rate", "low"),
    "target_exposure_rate": ("목표값 노출률", "rate", "low"),
    "latency_p50_ms": ("지연 p50 (ms)", "ms", "low"),
    "latency_p95_ms": ("지연 p95 (ms)", "ms", "low"),
    "run_failure_rate": ("실행 실패율", "rate", "low"),
    "cost_per_request_usd": ("요청당 비용 (USD)", "usd", "low"),
    "input_tokens": ("요청당 입력 토큰", "tokens", None),
    "output_tokens": ("요청당 출력 토큰", "tokens", None),
}

# README 대시보드 구상의 KPI 카드 5개 (FPR은 두 종류를 한 카드에)
KPI_METRICS = ["asr", "benign_fpr", "hard_negative_fpr", "task_success", "latency_p95_ms", "cost_per_request_usd"]

# 비교표에 넣을 지표 (순서대로)
TABLE_METRICS = ["asr", "task_success", "benign_fpr", "hard_negative_fpr", "target_exposure_rate",
                 "latency_p50_ms", "latency_p95_ms", "run_failure_rate", "cost_per_request_usd",
                 "input_tokens", "output_tokens"]

# 지표 칸의 excluded(제외된 실행 수)에 나오는 사유
EXCLUDED_LABELS = {
    "not_attack": "공격 케이스 아님",
    "not_normal": "정상 케이스 아님",
    "other_label": "다른 라벨",
    "not_evaluated": "미평가",
    "review_needed": "검토 필요",
    "not_applicable": "해당 없음",
    "detector_error": "탐지기 오류",
    "excessive_transformation_review_pending": "과도 변환 검토 대기",
    "execution_invalid_or_detector_only": "실행 무효·탐지 전용",
    "execution_invalid": "실행 무효",
    "target_exposure_review_pending": "목표값 노출 검토 대기",
    "missing": "기록 없음",
    "unresolved_attempts": "결과 미확정 시도",
    "not_attempted": "미실행",
    "missing_baseline_pair": "무방어 짝 없음",
    "missing_baseline_or_resource_pair": "무방어 짝·사용량 없음",
    "missing_review_or_pair": "검토·짝 없음",
    "missing_review_or_variant": "검토·변형 없음",
    "missing_comparison_pair_identity": "비교 짝 식별자가 없어 짝을 확정할 수 없음",
    "ambiguous_payload_pairing": "같은 비교 짝·변형·반복에 여러 케이스가 있음",
}

INFERENCE_LABELS = {
    "available": "CI 계산됨",
    "insufficient_sample": "표본 부족",
}

# 추천 판단(decisions)의 상태
DECISION_STATUS_LABELS = {
    "deferred": "추천 보류",
    "evaluated": "판정 완료",
    "eligible": "기준 통과",
    "rejected": "탈락",
    "pareto": "Pareto 후보",
    "dominated": "다른 구성보다 열세",
    "provisional_tied": "잠정 동률 (근거 더 필요)",
    "recommended_candidate": "추천 후보",
}

# 추천 판단의 사유 코드. "앞부분:뒷부분" 형태면 앞부분으로 찾는다.
REASON_LABELS = {
    "non_real_execution": "실제 모델 실행이 아님 (데모·샘플)",
    "evaluation_policy_not_reviewed_and_frozen": "평가·서비스 정책이 팀 검토·고정 전",
    "statistics_policy_not_reviewed_and_frozen": "통계 방법이 팀 검토·고정 전",
    "thresholds_incomplete": "합격 기준값이 다 정해지지 않음",
    "rate_threshold_out_of_range": "비율 기준값이 0~1 범위 밖",
    "priority_not_fixed": "지표 우선순위가 정해지지 않음",
    "detector_only_not_final_recommendation": "탐지 전용 실행은 최종 추천 대상 아님",
    "incomplete_batch_group": "이 그룹에 미완료·불확실 실행 있음",
    "unavailable_or_insufficient": "값 없음 또는 표본 부족",
    "evaluation_review_pending": "평가·검토 대기",
    "incomplete_resource_coverage": "비용 기록이 다 모이지 않음",
    "paired_task_baseline_missing": "무방어와 짝지은 정상 성공률 비교 없음",
    "paired_task_baseline_insufficient": "무방어와 짝지은 비교의 표본 부족",
    "attack_goal_or_severity_unreviewed": "공격 목표·심각도 분류 검토 전",
    "threshold_violation": "합격 기준 위반",
    "critical_goal_success_observed": "치명적 공격 성공이 관측됨",
    "priority_metric_uncertainty_requires_more_evidence": "우선 지표의 CI가 겹쳐 근거 더 필요",
    "not_selected_by_prefixed_priority": "우선순위에서 밀림",
    "priority_lexicographic": "적용한 우선순위",
    "batch_not_completed": "배치에 아직 끝나지 않은 실행이 있음",
    "trace_integrity_failure": "계획과 맞지 않는 trace가 있음",
    "batch_resource_coverage_incomplete": "정산되지 않았거나 비용을 모르는 호출이 있음",
    "protected_value_exposure_observed": "보호값 노출이 관측되어 추천 대상에서 제외",
    "asr_unavailable": "공격 성공률을 계산할 평가값이 없음",
    "detector_only_not_tradeoff": "탐지 전용 실행은 Trade-off 대상이 아님",
    "normal_benchmark_missing": "같은 비교 조건의 정상 기준이 없음",
    "normal_task_evaluation_pending": "정상 태스크 평가가 끝나지 않음",
    "missing_comparison_pair_identity": "비교 짝 식별자가 없어 짝을 확정할 수 없음",
    "ambiguous_payload_pairing": "같은 비교 짝·변형·반복에 여러 케이스가 있음",
}

ANALYSIS_FILTERS = [
    # (필터 이름, 화면 이름, 한글 이름을 찾을 통합 변수 묶음)
    ("source_id", "데이터 출처", None),
    ("scenario", "앱", "scenarios"),
    ("language", "언어", "languages"),
    ("split", "데이터 구분", "splits"),
    ("condition_id", "방어 조건", None),
    ("comparison", "비교 종류", None),
    ("label", "케이스 라벨", "case_labels"),
    ("attack_type", "공격 유형", None),
    ("family_id", "공격 family", None),
    ("goal_kind", "공격 목표", None),
    ("severity", "심각도", None),
    ("execution_kind", "실행 종류", "execution_kinds"),
    ("model_id", "모델", None),
    ("evaluator_version", "평가기 버전", None),
    ("evaluation_policy_version", "평가 정책 버전", None),
    ("pricing_version", "가격 버전", None),
]

# payload 변형 (docs/week3-live-pipeline.md 기준). 모르는 이름은 코드 그대로 보여 준다.
#   A/C: 공격 지시 있음/없음, 뒤 숫자 1/0: 목표 정보 있음/없음
VARIANT_LABELS = {
    "original": "원본",
    "instruction_removed": "지시 제거",
    "d2_instruction_removed": "D2 조작 문구 제거",
    "all_attack_removed": "공격 전체 제거",
    "quoted": "인용형",
    "benign_control": "정상 대조",
    "hard_negative_control": "하드 네거티브 대조",
    "A11": "A11 공격 지시·목표 있음",
    "A10": "A10 공격 지시·목표 없음",
    "C01": "C01 지시 없음·목표 있음",
    "C00": "C00 지시 없음·목표 없음",
}


def variant_text(variant):
    if not variant:
        return NO_VALUE
    label = VARIANT_LABELS.get(variant)
    return label if label else variant


# 공격 목표 (배치 metadata의 goal_kind). 모르는 값은 그대로 보여 준다.
GOAL_KIND_LABELS = {
    "marker": "마커 출력",
    "secret_leak": "보호값 유출",
    "normal": "정상 작업",
    "unspecified": "미분류",
}


def goal_text(goal):
    return GOAL_KIND_LABELS.get(goal, goal) if goal else NO_VALUE


COMPARISON_LABELS = {
    "technique": "방어 기법 비교",
    "position": "D2 위치 비교",
    "payload": "payload 비교",
    "detector": "탐지 전용",
}


# ---------------------------------------------------------------------------
# 서버 요청
# ---------------------------------------------------------------------------

def _request(method, path, body=None):
    """서버에 요청하고 (응답, 오류) 중 하나를 채워 돌려준다."""
    try:
        res = requests.request(method, f"{BACKEND_URL}{path}", json=body, timeout=60)
    except requests.RequestException:
        return None, api_error(code="CONNECTION_ERROR", message="서버에 연결할 수 없습니다. 백엔드가 켜져 있는지 확인하세요.")
    if res.status_code == 200:
        return res, None
    try:
        detail = res.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, dict):
        return None, api_error(res.status_code, detail.get("code"), detail.get("message"))
    if res.status_code == 404:
        return None, api_error(404, "NOT_FOUND", "서버에 배치 API가 없습니다. 최신 dev 백엔드인지 확인하세요.")
    return None, api_error(res.status_code, "HTTP_ERROR", str(detail or "서버 요청이 실패했습니다."))


def _json(res, error, expect):
    if error:
        return None, error
    try:
        data = res.json()
    except ValueError:
        return None, api_error(res.status_code, "INVALID_RESPONSE", "서버 응답이 JSON이 아닙니다.")
    if not isinstance(data, expect):
        return None, api_error(res.status_code, "INVALID_RESPONSE", "서버 응답 형식이 예상과 다릅니다.")
    return data, None


def check_batch_id(batch_id):
    if not BATCH_ID_PATTERN.fullmatch(batch_id or ""):
        return api_error(code="INVALID_BATCH_ID", message="올바른 배치 번호(batch-...)가 아닙니다.")
    return None


def list_batches():
    """저장된 배치 목록 (GET). 새 배치가 위로 오게 정렬한다."""
    data, error = _json(*_request("GET", PATHS["LIST"]), list)
    if data is not None:
        data = sorted(data, key=lambda b: b.get("created_at") or "", reverse=True)
    return data, error


def get_batch(batch_id):
    """배치 상세 (GET): 계획·상태·예산·조건·실행 번호 연결."""
    error = check_batch_id(batch_id)
    if error:
        return None, error
    return _json(*_request("GET", PATHS["GET"].format(batch_id=batch_id)), dict)


def get_report(batch_id, filters=None):
    """필터를 적용한 집계 리포트 (POST). 저장된 결과만 다시 집계하며 모델을 부르지 않는다."""
    error = check_batch_id(batch_id)
    if error:
        return None, error
    body = clean_filters(filters)
    report, error = _json(*_request("POST", PATHS["REPORT"].format(batch_id=batch_id), body), dict)
    if report is not None and report.get("batch_id") != batch_id:
        return None, api_error(code="INVALID_RESPONSE", message="요청한 배치와 리포트의 배치 번호가 다릅니다.")
    return report, error


def get_csv(batch_id, filters=None):
    """같은 필터의 지표 CSV (POST). 바이트로 돌려준다."""
    error = check_batch_id(batch_id)
    if error:
        return None, error
    res, error = _request("POST", PATHS["CSV"].format(batch_id=batch_id), clean_filters(filters))
    if error:
        return None, error
    return res.content, None


def clean_filters(filters):
    """빈 값(None, "")은 빼서 서버에 보낸다. 아무것도 없으면 {}."""
    return {k: v for k, v in (filters or {}).items() if v not in (None, "")}


def report_json_bytes(report):
    """화면에 보이는 리포트 그대로 JSON 파일로 내려받기 위한 바이트."""
    return json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")


def csv_report_error(content, report):
    """새로 집계된 CSV가 현재 화면의 리포트와 같은 스냅샷인지 확인한다."""
    invalid = api_error(code="INVALID_RESPONSE", message="CSV의 평가 정보를 확인할 수 없습니다. 배치 목록을 새로고침한 뒤 다시 준비하세요.")
    expected = {key: report.get(key) for key in ("batch_id", "report_version", "evaluation_snapshot_sha256")}
    calculation = (report.get("provenance") or {}).get("calculation_implementation_sha256")
    if calculation:
        expected["calculation_implementation_sha256"] = calculation
    for key in ("report_sha256", "evaluation_source"):
        value = (report.get("provenance") or {}).get(key)
        if value:
            expected[key] = value
    if not all(expected.values()):
        return invalid
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        if not set(expected).union({"filters"}).issubset(reader.fieldnames or []):
            return invalid
        found = False
        for row in reader:
            found = True
            filters = json.loads(row["filters"])
            if not isinstance(filters, dict):
                return invalid
            if (any(row[key] != value for key, value in expected.items()) or
                    {k: v for k, v in filters.items() if v is not None} !=
                    {k: v for k, v in (report.get("filters") or {}).items() if v is not None}):
                return api_error(code="SNAPSHOT_MISMATCH", message="화면과 CSV의 평가 스냅샷·버전 또는 필터가 다릅니다. 배치 목록을 새로고침한 뒤 CSV를 다시 준비하세요.")
        # v0.6의 빈 선택도 metadata 행에 출처를 남긴다. 헤더만으로는 검증할 수 없다.
        return None if found else invalid
    except (UnicodeError, csv.Error, ValueError, TypeError):
        return invalid


def research_csv_report_error(content, report):
    """Validate the explicit v0.2 research download without changing original KPIs."""
    invalid = api_error(code="INVALID_RESPONSE", message="연구 CSV 계약을 확인할 수 없습니다.")
    mismatch = api_error(code="SNAPSHOT_MISMATCH", message="연구 보고서와 CSV의 버전·필터·근거 또는 값이 다릅니다.")
    contract = SHARED["research_export"]
    if report.get("report_version") != contract["report_version"]:
        return invalid
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        if reader.fieldnames != contract["csv_fields"]:
            return invalid
        expected = {("report_metadata", "", "", ""): None}
        for group in report["groups"]:
            for name, metric in group["metrics"].items():
                expected[("final_output_metric", group["group_id"], name, "")] = (group, metric)
        for group in report["target_gold_groups"]:
            for label, count in group["fresh_ai_gold_counts"].items():
                expected[("target_gold_count", group["group_id"], "fresh_ai_target_gold_count", label)] = (group, count)
        seen = set()
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                return invalid
            identity = tuple(row[k] for k in ("row_kind", "group_id", "metric", "gold_label"))
            if identity not in expected or identity in seen:
                return mismatch
            seen.add(identity)
            if (any(row[k] != report[k] for k in ("batch_id", "report_version", "report_sha256",
                    "evaluation_source", "evaluation_version", "evaluation_snapshot_sha256")) or
                    json.loads(row["filters"]) != {k: v for k, v in report["filters"].items() if v is not None} or
                    json.loads(row["counts"]) != report["counts"] or
                    json.loads(row["capabilities"]) != report["capabilities"] or
                    json.loads(row["source_files"]) != report["provenance"]["source_files"] or
                    json.loads(row["research_policy_versions"]) != report["provenance"]["research_decision"] or
                    row["human_review"] != report["provenance"]["human_review"] or
                    row["decision_status"] != report["decisions"]["status"]):
                return mismatch
            if identity[0] == "report_metadata":
                continue
            group, value = expected[identity]
            if (json.loads(row["cohort"]) != group["cohort"] or json.loads(row["run_ids"]) != group["run_ids"]):
                return mismatch
            if identity[0] == "final_output_metric":
                if any(row[k] != (str(value[k]) if value[k] is not None else "") for k in
                       ("value", "numerator", "denominator", "selected_count", "unique_case_count",
                        "recorded_family_count", "coverage_status", "inference_status")):
                    return mismatch
                if (json.loads(row["excluded"]) != value["excluded"] or json.loads(row["ci95"]) != value["ci95"] or
                        row["metric_source"] != report["provenance"]["metric_sources"][identity[2]]):
                    return mismatch
            elif (row["gold_count"] != str(value) or row["target_observations"] != str(group["target_observations"]) or
                  any(row[k] for k in ("value", "numerator", "denominator")) or
                  any(row[k] != str(group[k]) for k in ("unique_case_count", "recorded_family_count")) or
                  row["ci95"] != "null" or
                  row["metric_source"] != "ai_research_target_gold"):
                return mismatch
        return None if seen == set(expected) else mismatch
    except (UnicodeError, csv.Error, ValueError, TypeError, KeyError):
        return invalid


# ---------------------------------------------------------------------------
# 값 → 화면 글자
# ---------------------------------------------------------------------------

def fmt_value(value, kind):
    """숫자 하나를 종류에 맞게 글자로. None이면 '기록 없음'."""
    if value is None:
        return NO_VALUE
    if kind == "rate":
        return f"{value * 100:.1f}%"
    if kind == "ms":
        return f"{value:,.0f} ms"
    if kind == "usd":
        return f"${value:.6f}" if value < 0.01 else f"${value:,.4f}"
    if kind == "tokens":
        return f"{value:,.1f}"
    if kind == "pp":
        return f"{value:+.1f}%p"
    if kind == "pct":
        return f"{value:+.1f}%"
    return str(value)


def fmt_ci(ci, kind):
    if not ci or len(ci) != 2 or ci[0] is None or ci[1] is None:
        return NO_CI
    return f"95% CI {fmt_value(ci[0], kind)} ~ {fmt_value(ci[1], kind)}"


def fmt_excluded(excluded):
    """{'not_evaluated': 3} → '미평가 3'. 비어 있으면 빈 글자."""
    parts = [f"{EXCLUDED_LABELS.get(k, label_of('evaluation_statuses', k))} {v}"
             for k, v in sorted((excluded or {}).items()) if v]
    return " · ".join(parts)


def fraction(metric):
    """비율 지표의 '분자/분모'. 서버가 분자를 안 주면 분모만."""
    denominator = metric.get("denominator")
    numerator = metric.get("numerator")
    if denominator is None:
        return ""
    if numerator is None:
        return f"n={denominator}"
    return f"{numerator}/{denominator}"


def metric_cell(metric, kind):
    """비교표 한 칸: '33.3% (1/3)'. 값이 없으면 '기록 없음'."""
    if not isinstance(metric, dict):
        return NO_VALUE
    text = fmt_value(metric.get("value"), kind)
    if metric.get("value") is not None and kind == "rate":
        text += f" ({fraction(metric)})"
    return text


def metric_detail(metric, kind):
    """KPI 카드·도움말용 자세한 설명 (분모, family 수, CI, 제외 사유)."""
    if not isinstance(metric, dict):
        return "서버 응답에 이 지표가 없습니다."
    lines = []
    if kind == "rate":
        lines.append(f"분자/분모: {fraction(metric) or NO_VALUE}")
    else:
        lines.append(f"집계한 실행 수: {metric.get('denominator', NO_VALUE)}")
    lines.append(f"family 수: {metric.get('family_count', NO_VALUE)}")
    if metric.get("unique_case_count") is not None:
        lines.append(f"고유 케이스: {metric['unique_case_count']}")
    if metric.get("repeat_count") is not None:
        lines.append(f"반복 수: {metric['repeat_count']}")
    lines.append(fmt_ci(metric.get("ci95"), kind))
    status = metric.get("inference_status")
    if status:
        lines.append(INFERENCE_LABELS.get(status, status))
    excluded = fmt_excluded(metric.get("excluded"))
    if excluded:
        lines.append(f"제외: {excluded}")
    return " · ".join(lines)


def reason_text(code):
    """사유 코드를 한글로. 예: 'unavailable_or_insufficient:asr' → '값 없음 또는 표본 부족: ASR (공격 성공률)'."""
    head, _, tail = code.partition(":")
    text = REASON_LABELS.get(head, head)
    if tail:
        names = [METRICS.get(part, POLICY_THRESHOLDS.get(part, (part,)))[0] for part in tail.split(",")]
        text += ": " + ", ".join(names)
    return text


def decision_status_text(status):
    return DECISION_STATUS_LABELS.get(status, status or NO_VALUE)


def batch_status_text(status):
    return label_of("batch_statuses", status) if status else NO_VALUE


def scope_text(scope):
    return label_of("execution_scopes", scope) if scope else NO_VALUE


# 배치 계획 항목에만 나오는 상태 (통합 변수 파일의 run_statuses에 없음)
ENTRY_STATUS_LABELS = {
    "pending": "미실행",
    "uncertain": "호출 결과 확인 필요",
    "cancelled_before_transport": "전송 전 취소",
}

# 위쪽 큰 숫자 칸에 들어가는 짧은 이름 (긴 이름은 잘려 보이므로)
SHORT_STATUS_LABELS = {"completed": "완료", "blocked": "차단", "failed": "실패", "pending": "미실행",
                       "running": "실행 중", "uncertain": "확인 필요"}


def status_counts_text(counts, short=False):
    """{'completed': 9, 'blocked': 3} → '완료 9 · 방어로 차단됨 3' (short면 '완료 9 · 차단 3')."""
    parts = []
    for status, count in sorted((counts or {}).items(), key=lambda kv: (-kv[1], kv[0])):
        if short and status in SHORT_STATUS_LABELS:
            label = SHORT_STATUS_LABELS[status]
        elif status in ENTRY_STATUS_LABELS:
            label = ENTRY_STATUS_LABELS[status]
        else:
            label = label_of("run_statuses", status)
            if label == status:
                label = label_of("batch_statuses", status)
        parts.append(f"{label} {count}")
    return " · ".join(parts) or NO_VALUE


def md_safe(text):
    """Streamlit 글자(caption·markdown·help)에서 $가 수식으로 바뀌지 않게 막는다."""
    return str(text).replace("$", "\\$")


# ---------------------------------------------------------------------------
# 그룹(조건) 이름 붙이기
# ---------------------------------------------------------------------------

def condition_text(condition):
    """조건 dict → 'D2 · 사용자 입력' 처럼 사람이 읽는 이름."""
    if not isinstance(condition, dict):
        return NO_VALUE
    mode = condition.get("defense_mode")
    text = label_of("defense_modes", mode) if mode else condition.get("condition_id", NO_VALUE)
    if mode in ("D2", "D1+D2"):
        text += " · " + label_of("defense_positions", condition.get("defense_position"))
    if condition.get("execution_kind") == "detector_only":
        text += " (탐지 전용)"
    return text


def group_title(group, with_source=True):
    """그룹 하나의 이름: 'RAG 챗봇 · 한국어 · D2 · 사용자 입력'."""
    parts = []
    if with_source:
        if group.get("source_id"):
            parts.append(str(group["source_id"]))
        parts.append(label_of("scenarios", group.get("scenario")))
        parts.append(label_of("languages", group.get("language")))
    parts.append(condition_text(group.get("condition") or {"condition_id": group.get("condition_id")}))
    variant = group.get("ablation_variant")
    if variant and variant != "original":
        parts.append(f"변형 {variant_text(variant)}")
    if group.get("goal_kind"):
        parts.append(goal_text(group["goal_kind"]))
    return " · ".join(p for p in parts if p)


def decision_by_group(report):
    """group_id → 추천 판단 기록."""
    records = (report.get("decisions") or {}).get("records") or []
    return {r.get("group_id"): r for r in records}


# ---------------------------------------------------------------------------
# 화면 표 만들기
# ---------------------------------------------------------------------------

def summary_rows(batches):
    """배치 목록 표."""
    rows = []
    for b in batches or []:
        budget = b.get("budget") or {}
        rows.append({
            "배치 번호": b.get("batch_id"),
            "만든 시각": b.get("created_at"),
            "실행 범위": scope_text(b.get("execution_scope")),
            "배치 상태": batch_status_text(b.get("status")),
            "계획 / 시도": f"{b.get('planned_count', NO_VALUE)} / {b.get('attempt_count', NO_VALUE)}",
            "실행 결과": status_counts_text(b.get("status_counts")),
            "조건 수": len(b.get("conditions") or []),
            "총비용(USD)": fmt_value(budget.get("total_cost_usd"), "usd"),
        })
    return rows


def budget_rows(summary):
    """배치 예산·사용량."""
    budget = summary.get("budget") or {}
    items = [
        ("모델 호출 수", budget.get("admitted_calls")),
        ("관측 입력 토큰", budget.get("observed_input_tokens")),
        ("관측 출력 토큰", budget.get("observed_output_tokens")),
        ("확인된 비용 소계(USD)", fmt_value(budget.get("known_cost_usd"), "usd")),
        ("총비용(USD)", fmt_value(budget.get("total_cost_usd"), "usd") if budget.get("total_cost_usd") is not None
         else "미확인 (가격 미확정 호출 포함)"),
        ("결과 미확정 호출", budget.get("unresolved_calls")),
        ("걸린 시간(초)", None if budget.get("elapsed_seconds") is None else round(budget["elapsed_seconds"], 1)),
    ]
    # This is a heterogeneous display column (counts, currency, seconds).
    # Keep its cells textual; the API budget retains its numeric values.
    return [{"항목": k, "값": NO_VALUE if v is None else str(v)} for k, v in items]


def condition_rows(summary):
    rows = []
    for c in summary.get("conditions") or []:
        rows.append({
            "조건 ID": c.get("condition_id"),
            "방어": condition_text(c),
            "실행 종류": label_of("execution_kinds", c.get("execution_kind")),
            "들어가는 비교": ", ".join(COMPARISON_LABELS.get(x, x) for x in c.get("comparisons") or []),
        })
    return rows


def filter_options(summary, report=None):
    """배치 계획에서 고를 수 있는 필터 값들을 모은다."""
    plan = summary.get("plan") or []
    conditions = summary.get("conditions") or []
    options = {key: set() for key, _, _ in ANALYSIS_FILTERS}
    for entry in plan:
        meta = entry.get("metadata") or {}
        for key in ("source_id", "scenario", "language", "split", "label", "attack_type", "condition_id"):
            if entry.get(key) is not None:
                options[key].add(entry[key])
        for key in ("family_id", "goal_kind", "severity"):
            if meta.get(key) is not None:
                options[key].add(meta[key])
    for c in conditions:
        options["condition_id"].add(c.get("condition_id"))
        options["execution_kind"].add(c.get("execution_kind"))
        options["comparison"].update(c.get("comparisons") or [])
    extra = (report or {}).get("provenance", {}).get("filter_options") or summary.get("filter_options") or {}
    for key, values in extra.items():
        if key in options:
            options[key].update(value for value in values if value is not None)
    return {key: sorted(v for v in values if v is not None) for key, values in options.items()}


def option_text(key, value, summary=None):
    """필터 선택지에 보일 글자."""
    for name, _, group in ANALYSIS_FILTERS:
        if name == key and group:
            return label_of(group, value)
    if key == "comparison":
        return COMPARISON_LABELS.get(value, value)
    if key == "goal_kind":
        return goal_text(value)
    if key == "condition_id" and summary:
        for c in summary.get("conditions") or []:
            if c.get("condition_id") == value:
                return f"{condition_text(c)} ({value})"
    return str(value)


def comparison_rows(report):
    """조건별 비교표. 칸 값은 서버 지표를 글자로만 바꾼 것."""
    decisions = decision_by_group(report)
    rows = []
    for g in report.get("groups") or []:
        metrics = g.get("metrics") or {}
        row = {
            "데이터 출처": g.get("source_id", NO_VALUE),
            "앱": label_of("scenarios", g.get("scenario")),
            "언어": label_of("languages", g.get("language")),
            "방어 조건": condition_text(g.get("condition")),
            "변형": variant_text(g.get("ablation_variant")),
            "공격 목표": goal_text(g.get("goal_kind")),
            "계획 / 시도": f"{g.get('planned_count', NO_VALUE)} / {g.get('attempt_count', NO_VALUE)}",
            "실행 결과": status_counts_text(g.get("status_counts")),
        }
        for key in TABLE_METRICS:
            label, kind, _ = METRICS[key]
            row[label] = metric_cell(metrics.get(key), kind)
        row["비용 합계(USD)"] = (fmt_value(g.get("total_cost_usd"), "usd") if g.get("total_cost_usd") is not None
                             else f"미확인 (확인된 소계 {fmt_value(g.get('known_cost_usd'), 'usd')})")
        row["추천 판단"] = decision_status_text((decisions.get(g.get("group_id")) or {}).get("status"))
        row["group_id"] = g.get("group_id")
        rows.append(row)
    return rows


def metric_rows(group):
    """모든 지표의 서버 분모·CI·제외 내역을 한 표로 제공한다."""
    return [{"지표": title, "값": metric_cell((group.get("metrics") or {}).get(key), kind),
             "집계·불확실성": metric_detail((group.get("metrics") or {}).get(key), kind)}
            for key, (title, kind, _) in METRICS.items()]


def sample_rows(group):
    sample = group.get("sample_counts") or {}
    evaluation = sample.get("evaluation_status_counts") or {}
    items = [("계획 요청", sample.get("planned_requests", group.get("planned_count"))),
             ("고유 케이스", sample.get("unique_case_count", group.get("unique_case_count"))),
             ("family", sample.get("family_count", group.get("family_count"))),
             ("반복 수", sample.get("repeat_count"))]
    for axis, statuses in evaluation.items():
        name = {"attack_success": "공격 성공 평가", "normal_task_success": "정상 태스크 평가",
                "target_exposure": "목표값 노출 검토"}.get(axis, axis)
        status_labels = {"exposed": "노출", "not_exposed": "미노출", "review_pending": "검토 대기",
                         "execution_unavailable": "유효 실행 없음"}
        items.extend((f"{name} · {status_labels.get(status, label_of('evaluation_statuses', status))}", count)
                     for status, count in statuses.items())
    return [{"표본·평가": name, "수": value, "기록 상태": "기록됨" if value is not None else NO_VALUE}
            for name, value in items]


POLICY_THRESHOLDS = {
    "ASR_MAX": ("ASR 최대", "rate", "≤"),
    "FPR_BENIGN_MAX": ("정상 FPR 최대", "rate", "≤"),
    "FPR_HARD_NEGATIVE_MAX": ("하드 네거티브 FPR 최대", "rate", "≤"),
    "TASK_SUCCESS_MIN": ("정상 성공률 최소", "rate", "≥"),
    "TASK_SUCCESS_DROP_MAX_PP": ("정상 성공률 감소 최대", "pp", "≤"),
    "P95_LATENCY_MAX": ("지연 p95 최대", "ms", "≤"),
    "COST_PER_REQUEST_MAX": ("요청당 비용 최대", "usd", "≤"),
    "RUN_FAILURE_RATE_MAX": ("실행 실패율 최대", "rate", "≤"),
}


def policy_rows(report):
    policy = (report.get("decisions") or {}).get("evaluation_policy") or {}
    thresholds = policy.get("thresholds") or {}
    return [{"기준": title, "방향": direction,
             "정책값": fmt_value(thresholds.get(key), kind), "코드": key}
            for key, (title, kind, direction) in POLICY_THRESHOLDS.items()]


def kpi_cards(group):
    """KPI 카드에 쓸 (이름, 큰 글자, 도움말) 목록."""
    metrics = group.get("metrics") or {}
    cards = []
    for key in KPI_METRICS:
        label, kind, _ = METRICS[key]
        metric = metrics.get(key)
        value = metric.get("value") if isinstance(metric, dict) else None
        cards.append((label, fmt_value(value, kind), metric_detail(metric, kind)))
    return cards


def baseline_rows(report):
    """무방어 대비 변화. ASR은 (무방어 - 방어), 나머지는 (방어 - 무방어), 단위 %p."""
    rows = []
    for g in report.get("groups") or []:
        if (g.get("condition") or {}).get("defense_mode") == "none":
            continue
        changes = g.get("baseline_changes_pp") or {}
        resources = g.get("baseline_resource_changes") or {}
        row = {"그룹": group_title(g)}
        for key in ("asr", "task_success", "benign_fpr", "hard_negative_fpr"):
            item = changes.get(key)
            label = METRICS[key][0]
            if key == "asr":
                label = "ASR 감소폭"
            row[label] = _delta_cell(item, "pp")
        for key in ("latency_p95_ms", "cost_per_request_usd"):
            item = resources.get(key)
            row[METRICS[key][0] + " 증가율"] = _delta_cell(item, "pct", value_key="increase_pct")
        rows.append(row)
    return rows


def _delta_cell(item, kind, value_key="value"):
    if not isinstance(item, dict) or item.get(value_key) is None:
        return NO_VALUE
    text = fmt_value(item[value_key], kind)
    if item.get("ci95") and kind == "pp":
        text += f" [{item['ci95'][0]:+.1f} ~ {item['ci95'][1]:+.1f}]"
    if item.get("inference_status") == "insufficient_sample":
        text += " · 표본 부족"
    return text


def scatter_points(report):
    """Trade-off 산점도 점 목록과, 점을 못 찍은 그룹(이유 포함)을 돌려준다.

    x = 정상 태스크 성공률, y = 1 - ASR (공격 차단율), 크기 = 요청당 비용.
    점의 상태(추천 후보·Pareto 등)는 서버의 추천 판단을 그대로 쓴다.
    """
    decisions = decision_by_group(report)
    points, skipped = [], []
    candidates = report.get("tradeoff_points") if "tradeoff_points" in report else report.get("groups")
    for g in candidates or []:
        title = group_title(g)
        if g.get("execution_kind") not in (None, "full_pipeline"):
            skipped.append({"그룹": title, "이유": "탐지 전용 실행은 산점도에서 제외"})
            continue
        metrics = g.get("metrics") or {}
        reference = g.get("utility_reference") or {}
        coverage = reference.get("evaluation_coverage") or {}
        task = (metrics.get("task_success") or {}).get("value")
        asr = (metrics.get("asr") or {}).get("value")
        missing = [k for k, v in (("task_success", task), ("asr", asr)) if v is None]
        if missing:
            # 왜 비었는지(예: 검토 필요 6)도 같이 적어 둔다
            parts = []
            for key in missing:
                why = fmt_excluded((metrics.get(key) or {}).get("excluded"))
                parts.append(METRICS[key][0] + (f" ({why})" if why else ""))
            skipped.append({"그룹": title, "이유": "값 없음: " + ", ".join(parts),
                            "정상 기준": reference.get("benchmark_id") or NO_VALUE})
            continue
        cost = (metrics.get("cost_per_request_usd") or {}).get("value")
        attack = metrics.get("asr") or {}
        normal = metrics.get("task_success") or {}
        block = metrics.get("attack_block_rate")
        status = (decisions.get(g.get("group_id")) or {}).get("status")
        enough = all((metrics.get(k) or {}).get("inference_status") == "available" for k in ("task_success", "asr"))
        points.append({
            "그룹": title,
            "앱": label_of("scenarios", g.get("scenario")),
            "방어 조건": condition_text(g.get("condition")),
            "정상 태스크 성공률": task,
            "공격 차단율 (1-ASR)": block.get("value") if isinstance(block, dict) else 1 - asr,
            "요청당 비용": cost,
            "비용 표시": fmt_value(cost, "usd") if cost is not None else "미확인",
            "비용 상태": "확인됨" if cost is not None else "미확인",
            "ASR 95% CI": fmt_ci(attack.get("ci95"), "rate"),
            "정상 성공률 95% CI": fmt_ci(normal.get("ci95"), "rate"),
            "공격 차단율 95% CI": fmt_ci((block or {}).get("ci95"), "rate"),
            "공격 평가 수": attack.get("denominator"),
            "정상 평가 수": normal.get("denominator"),
            "공격 family 수": attack.get("family_count"),
            "정상 family 수": normal.get("family_count"),
            "공격 평가 제외": fmt_excluded(attack.get("excluded")) or "없음",
            "정상 평가 제외": fmt_excluded(normal.get("excluded")) or "없음",
            "평가 상태": "일부 평가 제외" if any((attack.get("excluded") or {}).values()) or
                        any((normal.get("excluded") or {}).values()) else "선택 범위 평가됨",
            "데이터 출처": g.get("source_id", NO_VALUE),
            "데이터 구분": label_of("splits", g.get("split")),
            "대표 실행 번호": next(iter(g.get("run_ids") or []), NO_VALUE),
            "정상 기준": reference.get("benchmark_id") or NO_VALUE,
            "정상 기준 평가 완료": "완료" if g.get("normal_evaluation_complete") is True else
                                   "일부 평가" if g.get("normal_evaluation_complete") is False else NO_VALUE,
            "정상 기준 평가/계획": f"{coverage['evaluated_requests']}/{coverage['planned_requests']}" if
                                     coverage.get("evaluated_requests") is not None and coverage.get("planned_requests") is not None else NO_VALUE,
            "정상 기준 제외 수": coverage.get("excluded_requests") if coverage.get("excluded_requests") is not None else NO_VALUE,
            "정상 기준 공유 범위": str(reference.get("shared_scope") or NO_VALUE),
            "정상 기준 실행 번호": ", ".join(reference.get("run_ids") or []) or NO_VALUE,
            "비용 범위": "공격 목표 그룹의 요청" if g.get("cost_scope") == "security_goal_group_only" else NO_VALUE,
            "추천 판단": decision_status_text(status),
            "표본": "CI 계산됨" if enough else "표본 부족",
            "group_id": g.get("group_id"),
        })
    # 같은 자리에 찍히는 점은 겹쳐서 하나로 보이므로 몇 개가 겹쳤는지 적어 둔다
    spots = {}
    for p in points:
        spots.setdefault((p["정상 태스크 성공률"], p["공격 차단율 (1-ASR)"]), []).append(p["그룹"])
    for p in points:
        same = spots[(p["정상 태스크 성공률"], p["공격 차단율 (1-ASR)"])]
        p["같은 자리 그룹"] = ", ".join(same) if len(same) > 1 else ""
    return points, skipped


def decision_rows(report):
    """추천·탈락·보류 사유 표."""
    groups = {g.get("group_id"): g for g in report.get("groups") or []}
    rows = []
    for r in (report.get("decisions") or {}).get("records") or []:
        g = groups.get(r.get("group_id"), {})
        rows.append({
            "그룹": group_title(g) if g else r.get("condition_id"),
            "판단": decision_status_text(r.get("status")),
            "사유": [reason_text(code) for code in r.get("reasons") or []],
            "사유 코드": list(r.get("reasons") or []),
            "이 구성보다 나은 구성": [group_title(groups[x]) if x in groups else x for x in r.get("dominated_by") or []],
            "실행 수": len(r.get("run_ids") or []),
            "group_id": r.get("group_id"),
        })
    return rows


def common_reasons(report):
    """모든 그룹에 똑같이 붙은 사유 (배치 전체 이유). 화면 위쪽에 한 번만 보여 준다."""
    records = (report.get("decisions") or {}).get("records") or []
    if not records:
        return []
    shared = set(records[0].get("reasons") or [])
    for r in records[1:]:
        shared &= set(r.get("reasons") or [])
    return sorted(shared)


def detector_rows(report):
    """D2 탐지기 대상별 지표 (최종 ASR과 별도)."""
    rows = []
    for d in (report.get("detector_report") or {}).get("groups") or []:
        c = d.get("conditions") or {}
        def rate(key):
            item = d.get(key) or {}
            if item.get("value") is None:
                return f"{NO_VALUE} ({item.get('numerator', 0)}/{item.get('denominator', 0)})"
            return f"{item['value'] * 100:.1f}% ({item.get('numerator')}/{item.get('denominator')})"
        rows.append({
            "앱": label_of("scenarios", c.get("scenario")),
            "검사 위치": label_of("trace_stages", c.get("stage")) if c.get("stage") else NO_VALUE,
            "방어 조건": condition_text(c),
            "검사 대상 수": d.get("inspected_target_count"),
            "정답 있는 대상": d.get("eligible_target_count"),
            "탐지 오류": d.get("detector_error_count"),
            "탐지 모순": d.get("contradiction_count") if d.get("contradiction_count") is not None else NO_VALUE,
            "검토 필요": d.get("review_needed_count"),
            "정답 미등록": d.get("not_evaluated_count"),
            "FNR (놓친 공격)": rate("fnr"),
            "FPR (오탐)": rate("fpr"),
        })
    return rows


def payload_rows(report, *, by_family=False):
    """payload 짝 비교 (목표값 노출 차이). ASR·FPR과 다른 값이다."""
    rows = []
    comparisons = report.get("payload_comparisons") or []
    if by_family:
        comparisons = [{**comparison, **family} for comparison in comparisons
                       for family in comparison.get("family_details") or []]
    for p in comparisons:
        delta = p.get("target_exposure_delta") or {}
        interval = delta.get("ci95")
        interval_text = NO_CI
        if interval and len(interval) == 2 and all(bound is not None for bound in interval):
            # 서버의 차이·CI는 비율 단위이므로 화면에서는 모두 %p로 표시한다.
            interval_text = fmt_ci([bound * 100 for bound in interval], "pp")
        status = delta.get("inference_status")
        rows.append({
            "데이터 출처": p.get("source_id"),
            "조건": p.get("condition_id"),
            "언어": label_of("languages", p.get("language")),
            "공격 목표": goal_text(p.get("goal_kind")),
            **({"family": p.get("family_id", NO_VALUE)} if by_family else {}),
            "공격 변형 vs 대조": f"{variant_text(p.get('attack_variant'))} vs {variant_text(p.get('control_variant'))}",
            "공격 변형 노출률": metric_cell(p.get("attack_exposure"), "rate"),
            "대조 변형 노출률": metric_cell(p.get("control_exposure"), "rate"),
            "공격 노출률 95% CI": fmt_ci((p.get("attack_exposure") or {}).get("ci95"), "rate"),
            "대조 노출률 95% CI": fmt_ci((p.get("control_exposure") or {}).get("ci95"), "rate"),
            "공격 제외": fmt_excluded((p.get("attack_exposure") or {}).get("excluded")),
            "대조 제외": fmt_excluded((p.get("control_exposure") or {}).get("excluded")),
            "노출 차이": metric_cell(delta, "rate") if delta.get("value") is None else
                        f"{delta['value'] * 100:+.1f}%p (n={delta.get('denominator')})",
            "비교 짝 수": delta.get("denominator") if delta.get("denominator") is not None else NO_VALUE,
            "family 수": delta.get("family_count") if delta.get("family_count") is not None else NO_VALUE,
            "95% CI": interval_text,
            "통계 상태": INFERENCE_LABELS.get(status, status) if status else NO_VALUE,
            "제외": fmt_excluded(delta.get("excluded")),
        })
    return rows


def plan_rows_for_runs(summary, run_ids):
    """그룹의 run_id들을 배치 계획 항목(케이스·반복·시도)과 연결한다."""
    wanted = set(run_ids or [])
    rows = []
    for entry in (summary or {}).get("plan") or []:
        for attempt in entry.get("attempts") or []:
            if attempt.get("run_id") in wanted:
                rows.append({
                    "실행 번호": attempt.get("run_id"),
                    "케이스": entry.get("case_id"),
                    "원본 케이스": (entry.get("metadata") or {}).get("parent_case_id") or NO_VALUE,
                    "변형": variant_text((entry.get("metadata") or {}).get("ablation_variant")),
                    "family": (entry.get("metadata") or {}).get("family_id") or NO_VALUE,
                    "공격 목표": goal_text((entry.get("metadata") or {}).get("goal_kind")),
                    "라벨": label_of("case_labels", entry.get("label")),
                    "반복": entry.get("repeat"),
                    "시도 상태": label_of("run_statuses", attempt.get("status")),
                    "오류 코드": attempt.get("error_code") or "",
                })
    order = {run_id: i for i, run_id in enumerate(run_ids or [])}
    rows.sort(key=lambda r: (r["케이스"] or "", r["반복"] or 0, order.get(r["실행 번호"], 0)))
    found = {r["실행 번호"] for r in rows}
    for run_id in run_ids or []:
        if run_id not in found:
            rows.append({"실행 번호": run_id, "케이스": NO_VALUE, "라벨": NO_VALUE, "반복": None,
                         "시도 상태": "배치 계획에서 못 찾음", "오류 코드": ""})
    return rows


def warnings_for(summary, report):
    """화면 위쪽에 띄울 주의 문구."""
    notes = []
    scope = (summary or {}).get("execution_scope") or ((report or {}).get("provenance") or {}).get(
        "execution_settings", {}).get("execution_scope")
    if scope and scope != "real":
        notes.append(f"이 배치는 {scope_text(scope)} 결과입니다. 실제 모델 성능이 아닙니다.")
    status = (summary or {}).get("status")
    if status and status != "completed":
        notes.append(f"배치 상태가 '{batch_status_text(status)}'입니다. 아직 모든 계획 항목이 끝나지 않았습니다.")
    stats = (report or {}).get("statistics") or {}
    if stats.get("status") and stats.get("status") != "frozen":
        notes.append("통계 방법이 초안(draft)입니다. CI는 참고용입니다.")
    invalid = ((report or {}).get("counts") or {}).get("invalid_traces") or []
    if invalid:
        notes.append(f"조건이 계획과 맞지 않아 집계에서 뺀 trace가 {len(invalid)}개 있습니다.")
    return notes
