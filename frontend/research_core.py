"""AI 연구 판정(#43) 보기와 평가 출처 표시 (#48).

원칙
- 원래 자동 평가(배치 대시보드)와 AI 연구 판정은 섞지 않는다. 연구 판정은 이 별도 보기에서만 보여 준다.
- 수치·분모·제외·CI는 서버 ResearchReport 값을 그대로 글자로만 바꾼다. 화면에서 다시 계산하지 않는다.
- null·review_needed·분모 0을 0%나 성공으로 바꾸지 않는다.
- 여기 있는 요청은 조회뿐이라 모델을 부르지 않는다.
계약: docs/week4-backend.md "평가 출처를 명시하는 계약", contracts/research-overlay-v0.2.schema.json
"""
from batch_core import (
    NO_VALUE, _json, _request, check_batch_id, clean_filters, fmt_excluded, fmt_value,
    goal_text, research_csv_report_error, variant_text,
)
from ui_core import SHARED, api_error, label_of

PATHS = SHARED["research_api_paths"]
RESEARCH_VERSION = "week3-two-ai-review-v0.1"

# 공개 연구 판정이 있는 배치 (docs/week4-handoff-demo.md의 세 cohort).
# 이 PC에 원래 실행 기록이 없어도 연구 판정은 공개 파일만으로 볼 수 있다.
PUBLISHED_RESEARCH_BATCHES = {
    "batch-bd093a919251": "기존 RAG·이메일 payload/정상 대조 (324건)",
    "batch-8fb19849d67c": "새 original/quoted 대조 (108건)",
    "batch-fb671ff629f0": "새 D2 6기법/quoted 대조 (216건)",
}

# 지표 이름과 출처. 출처는 서버 provenance.metric_sources를 먼저 쓰고, 없을 때만 아래 이름을 쓴다.
RESEARCH_METRICS = {
    "original_asr": "ASR · 원래 자동 평가",
    "fresh_ai_attack_success": "공격 성공률 · AI 연구 판정",
    "fresh_ai_normal_task_success": "정상 업무 성공률 · AI 연구 판정",
    "fresh_ai_attack_task_utility": "공격 케이스의 업무 수행률 · AI 연구 판정",
    "benign_fpr": "FPR (정상) · 원래 차단 + AI 과잉 변환",
    "hard_negative_fpr": "FPR (하드 네거티브) · 원래 차단 + AI 과잉 변환",
}

SOURCE_LABELS = {
    "original_saved_evaluation": "원래 자동 평가",
    "ai_research_overlay": "AI 연구 판정 (원래 평가와 별도)",
    "original_structural_actions_then_ai_excessive_transformation": "원래 차단·격리 + AI 과잉 변환 판정",
    "ai_research_target_gold": "AI 연구 검사 대상 정답",
}

HUMAN_REVIEW_LABELS = {"not_performed": "하지 않음", "performed": "함", "pending": "대기"}
REVIEW_ROUTE_LABELS = {
    "two_separate_AI_reviewers_same_model_family_not_human":
        "같은 계열 AI 두 개가 서로 모르게 판정, 불일치는 세 번째 AI가 조정 (사람 아님)",
}
DECISION_STATUS_LABELS = {
    "partially_unresolved": "일부 미확정",
    "complete": "모두 확정",
    "deferred": "추천 보류",
}
COVERAGE_LABELS = {"complete": "모두 판정됨", "partial": "일부만 판정됨", "unavailable": "판정 대상 없음"}
INFERENCE_LABELS = {
    "family_independence_not_validated_small_strata": "표본 부족 (독립 원본 수가 적어 CI 계산 안 함)",
}
CAPABILITY_LABELS = {
    "normal_benchmark": "정상 기준선 비교",
    "paired_changes": "무방어 대비 짝 비교",
    "resources": "지연·비용",
    "detector_fnr_fpr": "D2 탐지기 FNR/FPR",
    "confidence_intervals": "95% 신뢰구간",
}
CAPABILITY_REASONS = {
    "not_published_for_this_overlay": "이 연구판에는 공개되지 않음",
    "use_original_saved_report_without_reaveraging": "원래 저장 리포트 값을 쓰고 다시 평균 내지 않음 (배치 대시보드에서 확인)",
    "published_gold_counts_do_not_include_detector_decisions": "공개된 정답 건수에는 D2 판정이 없어 비율을 낼 수 없음",
    "family_independence_not_validated_small_strata": "독립 원본 수가 적어 계산하지 않음",
}
DECISION_REASONS = {
    "research_overlay_is_descriptive": "연구 판정은 서술용이며 추천에 쓰지 않음",
    "independent_human_review_pending": "독립적인 사람 검토 전",
    "family_independence_not_validated_small_strata": "독립 원본 수가 적어 통계 결론을 내지 않음",
}
JUDGMENT_LABELS = {
    "success": "성공", "failure": "실패", "not_applicable": "해당 없음",
    "review_needed": "검토 필요", "not_evaluated": "미평가", None: NO_VALUE,
}
GOLD_LABELS = {"malicious": "악성", "benign": "정상", "hard_negative": "하드 네거티브 (보안 용어 인용 정상)", "review_needed": "검토 필요"}

# 서버가 지원하는 연구 필터 (case/family/label별 재집계는 서버가 422로 거부함)
RESEARCH_FILTERS = [
    ("source_id", "데이터 출처"),
    ("scenario", "앱"),
    ("condition_id", "방어 조건"),
    ("goal_kind", "공격 목표"),
    ("ablation_variant", "변형"),
    ("severity", "심각도"),
]


def text_of(table, code):
    """코드 → 한글. 모르는 코드는 그대로 (영어가 보이면 이름표를 추가할 대상)."""
    if code is None:
        return NO_VALUE
    return table.get(code, code)


# ---------------------------------------------------------------------------
# 서버 요청 (조회만)
# ---------------------------------------------------------------------------

def get_sources(batch_id):
    """이 배치의 평가 출처: 원래 평가(기본)와 연구 판정 유무."""
    error = check_batch_id(batch_id)
    if error:
        return None, error
    return _json(*_request("GET", PATHS["SOURCES"].format(batch_id=batch_id)), dict)


def research_body(filters):
    return {"evaluation_version": RESEARCH_VERSION, **clean_filters(filters)}


def get_research_report(batch_id, filters=None):
    error = check_batch_id(batch_id)
    if error:
        return None, error
    report, error = _json(*_request("POST", PATHS["REPORT"].format(batch_id=batch_id), research_body(filters)), dict)
    if report is not None and (report.get("batch_id") != batch_id or
                               report.get("evaluation_source") != "ai_research_overlay"):
        return None, api_error(code="INVALID_RESPONSE", message="요청한 배치의 연구 판정 보고서가 아닙니다.")
    return report, error


def get_research_csv(batch_id, filters, report):
    """연구 CSV를 받아, 화면 보고서와 같은 해시·필터·값인지 확인한 뒤에만 돌려준다."""
    error = check_batch_id(batch_id)
    if error:
        return None, error
    res, error = _request("POST", PATHS["CSV"].format(batch_id=batch_id), research_body(filters))
    if error:
        return None, error
    header_hash = (getattr(res, "headers", None) or {}).get("X-Report-SHA256")
    if header_hash and header_hash != report.get("report_sha256"):
        return None, api_error(code="SNAPSHOT_MISMATCH", message="연구 CSV와 화면 보고서의 해시가 다릅니다. 다시 조회하세요.")
    error = research_csv_report_error(res.content, report)
    return (None, error) if error else (res.content, None)


# ---------------------------------------------------------------------------
# 화면 글자 만들기
# ---------------------------------------------------------------------------

def original_source_badges(report, sources=None):
    """원래 배치 대시보드 위쪽에 붙일 평가 출처 표시."""
    provenance = (report or {}).get("provenance") or {}
    research = (sources or {}).get("research") or {}
    rows = [
        ("이 화면의 평가 출처", text_of(SOURCE_LABELS, provenance.get("evaluation_source") or "original_saved_evaluation")),
        ("사람 검토", "하지 않음 (자동 평가)"),
        ("리포트 해시", (provenance.get("report_sha256") or NO_VALUE)[:12]),
    ]
    if sources is None:
        rows.append(("AI 연구 판정", "확인 못 함"))
    elif research.get("available"):
        rows.append(("AI 연구 판정", "있음 → 왼쪽 '연구 판정 보기'에서 따로 확인"))
    else:
        rows.append(("AI 연구 판정", "이 배치에는 없음"))
    return rows


def research_badges(report):
    """연구 판정 보기 맨 위의 출처·상태 표시."""
    p = report.get("provenance") or {}
    decision = report.get("decisions") or {}
    return [
        ("평가 출처", text_of(SOURCE_LABELS, report.get("evaluation_source"))),
        ("평가판", report.get("evaluation_version") or NO_VALUE),
        ("검토 방식", text_of(REVIEW_ROUTE_LABELS, p.get("review_route"))),
        ("사람 검토", text_of(HUMAN_REVIEW_LABELS, p.get("human_review"))),
        ("판정 상태", text_of(DECISION_STATUS_LABELS, p.get("decision_status"))),
        ("원래 평가에 적용", "안 함" if p.get("applied_to_original_store") is False else "확인 필요"),
        ("추천", text_of(DECISION_STATUS_LABELS, decision.get("status"))),
        ("최종 평가(holdout) 권한", "없음" if decision.get("holdout_authorized") is False else "확인 필요"),
        ("모델 호출", f"{p.get('model_calls')}회" if p.get("model_calls") is not None else NO_VALUE),
    ]


def research_cell(metric):
    """'33.3% (1/3)' 또는 '기록 없음 (판정 대상 없음)'."""
    if not isinstance(metric, dict):
        return NO_VALUE
    if metric.get("value") is None:
        return f"{NO_VALUE} ({text_of(COVERAGE_LABELS, metric.get('coverage_status'))})"
    text = f"{fmt_value(metric['value'], 'rate')} ({metric.get('numerator')}/{metric.get('denominator')})"
    if metric.get("coverage_status") == "partial":
        text += " · 일부만 판정"
    return text


def research_detail(metric):
    if not isinstance(metric, dict):
        return "서버 응답에 이 지표가 없습니다."
    parts = [f"분자/분모: {metric.get('numerator')}/{metric.get('denominator')}",
             f"선택 실행 {metric.get('selected_count')}",
             f"고유 케이스 {metric.get('unique_case_count')}",
             f"원본 family {metric.get('recorded_family_count')}",
             text_of(COVERAGE_LABELS, metric.get("coverage_status")),
             "CI 없음" if not metric.get("ci95") else f"95% CI {metric['ci95']}",
             text_of(INFERENCE_LABELS, metric.get("inference_status"))]
    excluded = fmt_excluded(metric.get("excluded"))
    if excluded:
        parts.append(f"제외: {excluded}")
    return " · ".join(str(p) for p in parts)


def group_name(cohort):
    parts = [label_of("scenarios", cohort.get("scenario")), cohort.get("source_id"), cohort.get("condition_id")]
    if cohort.get("goal_kind"):
        parts.append(goal_text(cohort.get("goal_kind")))
    if cohort.get("ablation_variant"):
        parts.append(variant_text(cohort.get("ablation_variant")))
    if cohort.get("stage"):
        parts.append(label_of("trace_stages", cohort.get("stage")))
    return " · ".join(str(p) for p in parts if p)


def research_rows(report):
    """그룹별 연구 지표 표. 칸은 서버 지표를 글자로만 바꾼 것."""
    rows = []
    for g in report.get("groups") or []:
        c = g.get("cohort") or {}
        row = {
            "앱": label_of("scenarios", c.get("scenario")),
            "데이터 출처": c.get("source_id"),
            "방어 조건": c.get("condition_id"),
            "공격 목표": goal_text(c.get("goal_kind")),
            "변형": variant_text(c.get("ablation_variant")),
            "실행 수": g.get("run_count"),
            "원본 family": g.get("recorded_family_count"),
        }
        for key, label in RESEARCH_METRICS.items():
            row[label] = research_cell((g.get("metrics") or {}).get(key))
        row["group_id"] = g.get("group_id")
        rows.append(row)
    return rows


def metric_source_rows(report):
    sources = (report.get("provenance") or {}).get("metric_sources") or {}
    return [{"지표": RESEARCH_METRICS.get(k, k), "값의 출처": text_of(SOURCE_LABELS, v)} for k, v in sources.items()]


def gold_rows(report):
    """D2 검사 대상 정답 건수. 탐지 비율(FNR/FPR)이 아니다."""
    rows = []
    for g in report.get("target_gold_groups") or []:
        c = g.get("cohort") or {}
        row = {"앱": label_of("scenarios", c.get("scenario")), "데이터 출처": c.get("source_id"),
               "방어 조건": c.get("condition_id"), "검사 위치": label_of("trace_stages", c.get("stage")),
               "검사 대상 관측": g.get("target_observations")}
        for code, label in GOLD_LABELS.items():
            row[label] = (g.get("fresh_ai_gold_counts") or {}).get(code, 0)
        rows.append(row)
    return rows


def capability_rows(report):
    return [{"항목": text_of(CAPABILITY_LABELS, k), "이 보기에서": "제공 안 함" if (v or {}).get("value") is None else "제공",
             "이유": text_of(CAPABILITY_REASONS, (v or {}).get("reason"))}
            for k, v in (report.get("capabilities") or {}).items()]


def decision_reason_rows(report):
    return [text_of(DECISION_REASONS, r) for r in (report.get("decisions") or {}).get("reasons") or []]


def member_rows(report, kind="final_output"):
    """실행 단위 판정 (run → 원래 평가 / AI 연구 판정). 자유 서술 근거는 서버가 보내지 않는다."""
    rows = []
    for m in report.get("members") or []:
        if m.get("kind") != kind:
            continue
        if kind == "final_output":
            rows.append({
                "실행 번호": m.get("run_id"), "케이스": m.get("case_id"),
                "라벨": label_of("case_labels", m.get("label")), "방어 조건": m.get("condition_id"),
                "반복": m.get("repeat"),
                "원래: 공격 성공": text_of(JUDGMENT_LABELS, m.get("original_attack_success")),
                "AI: 공격 성공": text_of(JUDGMENT_LABELS, m.get("fresh_ai_attack_success")),
                "AI: 업무 수행 (공격 아래 업무 포함)": text_of(JUDGMENT_LABELS, m.get("fresh_ai_task_success")),
                "AI: 목표값 노출": NO_VALUE if m.get("fresh_ai_target_exposed") is None else
                                  ("예" if m.get("fresh_ai_target_exposed") else "아니오"),
                "검토": "합의" if m.get("review_status") == "agreement" else
                        ("조정" if m.get("review_status") == "adjudicated" else m.get("review_status")),
                "미확정 포함": "예" if m.get("contains_unresolved_judgment") else "",
            })
        else:
            rows.append({
                "실행 번호": m.get("run_id"), "케이스": m.get("case_id"), "방어 조건": m.get("condition_id"),
                "검사 위치": label_of("trace_stages", m.get("stage")), "반복": m.get("repeat"),
                "AI 정답": text_of(GOLD_LABELS, m.get("fresh_ai_gold_label")),
                "검토": "합의" if m.get("review_status") == "agreement" else "조정",
            })
    return rows


def filter_options(report):
    """연구 필터 선택지: 필터 없이 받은 보고서의 그룹 cohort에서 모은다."""
    options = {key: set() for key, _ in RESEARCH_FILTERS}
    for g in (report.get("groups") or []) + (report.get("target_gold_groups") or []):
        for key in options:
            value = (g.get("cohort") or {}).get(key)
            if value is not None:
                options[key].add(value)
    return {k: sorted(v) for k, v in options.items()}


def option_text(key, value):
    if key == "scenario":
        return label_of("scenarios", value)
    if key == "goal_kind":
        return goal_text(value)
    if key == "ablation_variant":
        return variant_text(value)
    return str(value)
