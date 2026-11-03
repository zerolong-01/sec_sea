"""?? API trace? ?? ??. ?? ?? ??? ???? ??? ???? ???."""
from datetime import datetime, timedelta, timezone
import json

import streamlit as st
import status_style as ss
from ui_core import D2_MODES, NO_VALUE, SHARED, count_decisions, label_of, load_run, text_or_missing

PREVIEW_LENGTH = 300
KST = timezone(timedelta(hours=9))


def render_saved_trace(run_ids, *, key, report_key, expected_cases=None):
    """현재 보고서에 속한 실행만 조회하고 보고서/선택 변경 시 이전 trace를 숨긴다."""
    if not run_ids:
        st.info("이 선택에 연결된 실행 기록이 없습니다.")
        return
    run_id = st.selectbox("마스킹된 trace를 볼 실행 번호", run_ids, key=f"{key}_run")
    if st.button("trace 조회", key=f"{key}_load_trace"):
        st.session_state[f"{key}_trace"] = (report_key, run_id, load_run(run_id))
    loaded = st.session_state.get(f"{key}_trace")
    if not loaded or loaded[0] != report_key or loaded[1] != run_id:
        return
    trace, error = loaded[2]
    if error:
        if error.get("status") == 404:
            st.info("이 저장소에는 원래 실행 기록이 없습니다. 해당 배치의 runs 폴더로 서버를 기동하세요.")
        st.error(error.get("code") or "조회 오류")
        if error.get("message"):
            st.text(error["message"])
    elif trace:
        if expected_cases and (trace.get("request") or {}).get("case_id") != expected_cases[run_id]:
            st.error("선택한 보고서와 trace의 케이스가 다릅니다 (SNAPSHOT_MISMATCH).")
            return
        st.caption("아래 trace의 평가는 저장된 원래 자동 평가입니다. AI 연구 판정과 별도로 읽습니다.")
        render_result(trace)


def stage_title(value):
    """trace 단계의 번호와 한글 이름을 만든다. 예: 1. 입력"""
    for stage in SHARED.get("trace_stages", []):
        if stage.get("value") == value:
            return f"{stage.get('order')}. {stage.get('label_ko', value)}"
    return value

def show_text(text):
    """받은 텍스트를 가공하지 않고 그대로 보여 준다."""
    st.code(text, language=None, wrap_lines=True)

def show_long_text(text, title):
    """긴 글은 앞부분만 보여 주고 전체는 펼쳐 보게 한다. 짧으면 그대로 보여 준다."""
    if len(text) <= PREVIEW_LENGTH:
        show_text(text)
        return
    show_text(text[:PREVIEW_LENGTH] + " …")
    with st.expander(f"{title} 전체 보기 ({len(text)}자)"):
        show_text(text)

def box_title(text):
    """테두리 상자 안의 제목. 큰 제목이 너무 많지 않게 굵은 글씨로 통일한다."""
    st.markdown(f"**{ss.md_text(text)}**")

def format_time(created_at):
    """세계 표준시로 온 실행 시각을 한국 시간으로 바꿔 보여 준다."""
    try:
        moment = datetime.fromisoformat(created_at).astimezone(KST)
        return moment.strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return created_at or NO_VALUE

def render_header(trace):
    """① 실행 조건·상태: 상태, 실행 번호, 실행 시각, 방어 모드와 케이스·범위"""
    request = trace.get("request") or {}
    manifest = trace.get("manifest") or {}
    with st.container(border=True):
        cols = st.columns(4)
        cols[0].caption("실행 상태")
        cols[0].markdown(ss.badge(label_of("run_statuses", trace.get("status")) or NO_VALUE, ss.run_tone(trace.get("status"))))
        cols[1].caption("실행 번호")
        cols[1].text(str(trace.get("run_id") or NO_VALUE))
        cols[2].caption("실행 시각 (한국 시간)")
        cols[2].text(format_time(trace.get("created_at")))
        cols[3].caption("방어 모드")
        cols[3].text(str(label_of("defense_modes", request.get("defense_mode")) or NO_VALUE))
        kind = manifest.get("execution_kind")
        if kind is None and trace.get("schema_version") == "0.2":
            kind = SHARED["execution_kinds"]["FULL_PIPELINE"]["value"]
        st.caption(f"케이스: {request.get('case_id') or NO_VALUE} · 앱: {label_of('scenarios', request.get('scenario')) or NO_VALUE} · "
                   f"실행 범위: {label_of('execution_scopes', manifest.get('execution_scope')) or NO_VALUE} · "
                   f"실행 종류: {label_of('execution_kinds', kind) or NO_VALUE}")
        if request.get("defense_mode") in D2_MODES:
            st.caption(f"요청한 D2 위치: {label_of('defense_positions', request.get('defense_position')) or NO_VALUE} · "
                       f"저장된 D2 위치: {label_of('defense_positions', manifest.get('defense_position')) or NO_VALUE}")
        error = trace.get("error")
        if error:
            st.error(f"{error.get('code') or '오류'}: {error.get('message') or ''}")

def render_summary(trace):
    """② 출력과 평가 요약: 결과를 먼저 한눈에. 값은 trace 그대로 옮긴다 (새로 계산하지 않음)."""
    output = trace.get("output") or {}
    evaluation = trace.get("evaluation") or {}
    metrics = trace.get("metrics") or {}
    decisions = [event.get("decision") for event in trace.get("defense_events") or []]
    with st.container(border=True):
        cols = st.columns(4)
        cards = [
            ("출력 결과", label_of("output_outcomes", output.get("outcome")) or NO_VALUE,
             ss.output_tone(output.get("outcome")), None),
            ("방어 판정", count_decisions(trace), ss.decision_tone(decisions), None),
        ]
        for title, kind, key in (("공격 성공", "attack", "attack_success"),
                                 ("정상 태스크 성공", "normal", "normal_task_success")):
            value = evaluation.get(key)
            cards.append((title, label_of("evaluation_statuses", value) or NO_VALUE,
                          ss.evaluation_tone(kind, value), ss.evaluation_meaning(kind, value)))
        for col, (title, text, tone, note) in zip(cols, cards):
            col.caption(title)
            col.markdown(ss.badge(text, tone))
            if note:
                col.caption(note)

        cols = st.columns(4)
        cost = metrics.get("estimated_cost_usd")
        values = [
            ("응답 지연 시간(ms)", text_or_missing(metrics.get("latency_ms"))),
            ("입력 / 출력 토큰", f"{text_or_missing(metrics.get('input_tokens'))} / {text_or_missing(metrics.get('output_tokens'))}"),
            ("추정 비용(USD)", "미확인" if cost is None else str(cost)),
            ("사용량 출처", label_of("usage_sources", metrics.get("usage_source")) or NO_VALUE),
        ]
        for col, (title, value) in zip(cols, values):
            col.caption(title)
            col.markdown(f"**{ss.md_text(value)}**")

        if output.get("display_text"):
            st.caption("출력 미리보기 (전체는 아래 ③의 5. 출력)")
            show_text(output["display_text"][:PREVIEW_LENGTH] + (" …" if len(output["display_text"]) > PREVIEW_LENGTH else ""))

def render_result(trace):
    """결과 읽는 순서: ① 실행 조건·상태 → ② 출력과 평가 요약 → ③ 단계별 trace·판정 근거"""
    st.markdown("##### ① 실행 조건·상태")
    render_header(trace)
    st.markdown("##### ② 출력과 평가 요약")
    render_summary(trace)
    st.markdown("##### ③ 단계별 trace·판정 근거")
    left, right = st.columns([2, 1])
    with left:
        render_timeline(trace)
    with right:
        render_meta(trace)

def render_timeline(trace):
    """입력부터 출력까지 다섯 단계를 순서대로 보여 준다."""
    request = trace.get("request") or {}

    # 1. 입력
    with st.container(border=True):
        box_title(stage_title("input"))
        data = trace.get("input") or {}
        user_input = data.get("user_input")
        doc_ids = data.get("external_document_ids") or []
        if not user_input and not doc_ids:
            st.caption("입력 없음")
        else:
            st.caption("사용자 입력")
            if user_input:
                show_long_text(user_input, "입력")
            else:
                st.text("없음")
            st.caption("외부 문서 ID")
            st.text(", ".join(doc_ids) if doc_ids else "없음")

    # 2. 검색·수집
    with st.container(border=True):
        box_title(stage_title("retrieval"))
        docs = trace.get("retrieval") or []
        if not docs:
            st.caption("검색된 문서 없음")
        else:
            rows = [
                {
                    "순위": doc.get("rank"),
                    "문서 ID": doc.get("document_id"),
                    "점수": NO_VALUE if doc.get("score") is None else str(doc.get("score")),
                    "프롬프트 포함": NO_VALUE if doc.get("included_in_prompt") is None else ("포함" if doc["included_in_prompt"] else "미포함"),
                }
                for doc in sorted(docs, key=lambda d: d.get("rank") or 0)
            ]
            st.dataframe(rows, hide_index=True)

    # 3. 프롬프트 조립
    with st.container(border=True):
        box_title(stage_title("prompt_assembly"))
        components = sorted(
            trace.get("prompt_assembly") or [], key=lambda c: c.get("order") or 0
        )
        if not components:
            st.caption("프롬프트 구성 요소 없음")
        else:
            names = [str(label_of("prompt_component_types", c.get("component_type"))) for c in components]
            st.caption(f"구성 요소 {len(components)}개: " + " → ".join(names))
            with st.expander("조립된 프롬프트 펼쳐 보기"):
                for comp in components:
                    parts = [
                        str(comp.get("order")),
                        str(label_of("prompt_component_types", comp.get("component_type"))),
                    ]
                    if comp.get("source_ref"):
                        parts.append(f"출처 {comp['source_ref']}")
                    if comp.get("is_masked"):
                        parts.append("마스킹됨")
                    st.text(" · ".join(parts))
                    show_text(comp.get("display_text") or "")

    # 4. 방어 판정
    with st.container(border=True):
        box_title(stage_title("defense_events"))
        events = trace.get("defense_events") or []
        mode_label = label_of("defense_modes", request.get("defense_mode"))
        if not events:
            st.text("방어 판정 없음")
            st.caption(f"방어 모드: {mode_label} · 방어 이벤트 0건")
        else:
            rows = [
                {
                    "방어": event.get("defense_id"),
                    "방어 버전": event.get("defense_version") or NO_VALUE,
                    "정책 버전": event.get("policy_version") or NO_VALUE,
                    "단계": label_of("trace_stages", event.get("stage")),
                    "판정": label_of("defense_decisions", event.get("decision")),
                    "근거 코드": event.get("reason_code") or NO_VALUE,
                    "점수": NO_VALUE if event.get("score") is None else str(event.get("score")),
                    "임계값": NO_VALUE if event.get("threshold") is None else str(event.get("threshold")),
                    "대상": event.get("target_ref") or "사용자 입력/프롬프트",
                    "근거": event.get("reason") or NO_VALUE,
                    "오류": event.get("error") or NO_VALUE,
                    "임계값 기준 판정": label_of("defense_decisions", event.get("threshold_decision")) or NO_VALUE,
                    "모순": event.get("consistency_issue") or "없음",
                    "검토 필요": NO_VALUE if event.get("review_needed") is None else ("예" if event["review_needed"] else "아니오"),
                }
                for event in events
            ]
            st.dataframe(rows, hide_index=True)

    # 5. 출력
    with st.container(border=True):
        box_title(stage_title("output"))
        output = trace.get("output") or {}
        parts = [str(label_of("output_outcomes", output.get("outcome")) or NO_VALUE)]
        if output.get("is_masked"):
            parts.append("마스킹됨")
        st.text(" · ".join(parts))
        if output.get("display_text"):
            show_long_text(output["display_text"], "출력")
        else:
            st.caption("출력 없음")

def render_meta(trace):
    """오른쪽: 평가 근거 → 성능·비용 → 탐지 대상별 평가 → (펼쳐 보기) 실행 설정·데이터 버전·모델 호출"""
    request = trace.get("request") or {}

    with st.container(border=True):
        box_title(label_of("trace_stages", "evaluation"))
        evaluation = trace.get("evaluation") or {}
        st.caption("공격 성공")
        st.text(str(label_of("evaluation_statuses", evaluation.get("attack_success")) or NO_VALUE))
        st.caption("정상 태스크 성공")
        st.text(str(label_of("evaluation_statuses", evaluation.get("normal_task_success")) or NO_VALUE))
        if evaluation.get("reason"):
            st.caption("판정 근거")
            st.text(str(evaluation["reason"]))
        for key, title in (("evaluator_version", "evaluator_version"), ("policy_version", "평가 정책"),
                           ("reviewer", "검토자"), ("evaluated_at", "평가 시각")):
            st.caption(title)
            st.text(text_or_missing(evaluation.get(key)))

    with st.container(border=True):
        box_title(label_of("trace_stages", "metrics"))
        metrics = trace.get("metrics") or {}
        for item in SHARED["metric_keys"].values():
            value = metrics.get(item["value"])
            st.caption(item["label_ko"])
            st.text(("미확인" if item["value"] == "estimated_cost_usd" else NO_VALUE) if value is None else str(value))
        st.caption(f"사용량 출처: {label_of('usage_sources', metrics.get('usage_source')) or NO_VALUE}")
        st.text(f"생성 호출 {text_or_missing(metrics.get('generation_call_count'))} · 탐지 호출 {text_or_missing(metrics.get('detection_call_count'))}")
        if not metrics.get("cost_complete"):
            st.caption(f"비용 미확인 호출: {text_or_missing(metrics.get('unpriced_call_count'))} · 확인된 소계(USD): {text_or_missing(metrics.get('known_cost_usd'))}")
        if metrics.get("generation_skipped_reason"):
            st.caption(f"생성 생략 사유: {metrics['generation_skipped_reason']}")
        if metrics.get("stages"):
            st.dataframe([{"단계": label_of("trace_stages", item.get("stage")), "지연(ms)": text_or_missing(item.get("latency_ms"))}
                          for item in metrics["stages"]], hide_index=True)

    with st.container(border=True):
        box_title("탐지 대상별 독립 평가")
        rows = trace.get("detector_evaluation") or []
        if not rows:
            st.caption("탐지 대상별 평가 기록 없음")
        else:
            st.dataframe([{"단계": label_of("trace_stages", item.get("stage")),
                           "대상": item.get("target_ref") or "사용자 입력",
                           "정답": label_of("detector_gold_labels", item.get("gold_label")) or NO_VALUE,
                           "분석": label_of("detector_analysis_statuses", item.get("analysis_status")) or NO_VALUE,
                           "정답 버전": item.get("gold_version") or NO_VALUE,
                           "검토자": item.get("reviewer") or NO_VALUE,
                           "근거": item.get("reason") or NO_VALUE} for item in rows], hide_index=True)

    with st.expander("실행 설정·데이터 버전"):
        st.caption("dataset_version · corpus_version")
        st.text(f"{request.get('dataset_version') or NO_VALUE} · {request.get('corpus_version') or NO_VALUE}")
        manifest = trace.get("manifest") or {}
        if not manifest:
            st.caption(NO_VALUE)
        for key, value in manifest.items():
            st.caption(key)
            if value in ({}, [], None, ""):
                st.text("없음")
            elif isinstance(value, (dict, list)):
                st.text(json.dumps(value, ensure_ascii=False))
            else:
                st.text(str(value))

    with st.expander("모델 호출 기록 (마스킹됨)"):
        for call in trace.get("model_calls") or []:
            st.caption(f"{label_of('call_purposes', call.get('purpose')) or NO_VALUE} · {call.get('model_id') or NO_VALUE} · {text_or_missing(call.get('latency_ms'))}ms")
            st.caption(f"사용량 출처: {label_of('usage_sources', call.get('usage_source')) or NO_VALUE} · "
                       f"입력/출력 토큰: {text_or_missing(call.get('input_tokens'))} / {text_or_missing(call.get('output_tokens'))} · "
                       f"비용(USD): {text_or_missing(call.get('estimated_cost_usd'))}")
            st.caption(call.get("cost_reason") or NO_VALUE)
            if call.get("error_code"):
                st.error(call["error_code"])
            for message in call.get("messages") or []:
                st.caption(message.get("role") or NO_VALUE)
                show_text(message.get("content") or "")
