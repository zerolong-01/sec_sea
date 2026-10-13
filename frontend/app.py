import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from ui_core import (
    D2_MODES, NO_VALUE, ROOT, SHARED, condition_rows, label_of, run_case, summary_row,
)

DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
CASES_PATH = DATA_DIR / "cases.v0.1.jsonl"
MANIFEST_PATH = Path(os.environ.get("MVP_MANIFEST", DATA_DIR / "mvp-manifest.v0.1.json"))
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
KST = timezone(timedelta(hours=9))

st.set_page_config(page_title="LLM Defense Trade-off Lab", layout="wide")


def stage_title(value):
    """trace 단계의 번호와 한글 이름을 만든다. 예: 1. 입력"""
    for stage in SHARED.get("trace_stages", []):
        if stage.get("value") == value:
            return f"{stage.get('order')}. {stage.get('label_ko', value)}"
    return value


def show_text(text):
    """받은 텍스트를 가공하지 않고 그대로 보여 준다."""
    st.code(text, language=None, wrap_lines=True)


def format_time(created_at):
    """세계 표준시로 온 실행 시각을 한국 시간으로 바꿔 보여 준다."""
    try:
        moment = datetime.fromisoformat(created_at).astimezone(KST)
        return moment.strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return created_at or NO_VALUE


def load_cases():
    """케이스 파일이 있으면 한 줄에 하나씩 읽는다. 없으면 빈 목록을 돌려준다."""
    if not CASES_PATH.exists():
        return []
    cases = []
    for line in CASES_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases

def render_header(trace):
    """결과 맨 위: 상태, 실행 번호, 실행 시각, 방어 모드"""
    request = trace.get("request") or {}
    cols = st.columns(4)
    cols[0].caption("상태")
    cols[0].text(str(label_of("run_statuses", trace.get("status")) or NO_VALUE))
    cols[1].caption("실행 번호")
    cols[1].text(str(trace.get("run_id") or NO_VALUE))
    cols[2].caption("실행 시각 (한국 시간)")
    cols[2].text(format_time(trace.get("created_at")))
    cols[3].caption("방어 모드")
    cols[3].text(str(label_of("defense_modes", request.get("defense_mode")) or NO_VALUE))
    scope = (trace.get("manifest") or {}).get("execution_scope")
    st.caption(f"실행 범위: {label_of('execution_scopes', scope) or NO_VALUE}")
    kind = (trace.get("manifest") or {}).get("execution_kind", SHARED["execution_kinds"]["FULL_PIPELINE"]["value"])
    st.caption(f"실행 종류: {label_of('execution_kinds', kind)}")


def render_timeline(trace):
    """입력부터 출력까지 다섯 단계를 순서대로 보여 준다."""
    request = trace.get("request") or {}

    # 1. 입력
    with st.container(border=True):
        st.subheader(stage_title("input"))
        data = trace.get("input") or {}
        user_input = data.get("user_input")
        doc_ids = data.get("external_document_ids") or []
        if not user_input and not doc_ids:
            st.caption("입력 없음")
        else:
            st.caption("사용자 입력")
            if user_input:
                show_text(user_input)
            else:
                st.text("없음")
            st.caption("외부 문서 ID")
            st.text(", ".join(doc_ids) if doc_ids else "없음")

    # 2. 검색·수집
    with st.container(border=True):
        st.subheader(stage_title("retrieval"))
        docs = trace.get("retrieval") or []
        if not docs:
            st.caption("검색된 문서 없음")
        else:
            rows = [
                {
                    "순위": doc.get("rank"),
                    "문서 ID": doc.get("document_id"),
                    "점수": NO_VALUE if doc.get("score") is None else str(doc.get("score")),
                    "프롬프트 포함": "포함" if doc.get("included_in_prompt") else "미포함",
                }
                for doc in sorted(docs, key=lambda d: d.get("rank") or 0)
            ]
            st.dataframe(rows, hide_index=True)

    # 3. 프롬프트 조립
    with st.container(border=True):
        st.subheader(stage_title("prompt_assembly"))
        components = sorted(
            trace.get("prompt_assembly") or [], key=lambda c: c.get("order") or 0
        )
        if not components:
            st.caption("프롬프트 구성 요소 없음")
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
        st.subheader(stage_title("defense_events"))
        events = trace.get("defense_events") or []
        mode_label = label_of("defense_modes", request.get("defense_mode"))
        if not events:
            st.text("방어 판정 없음")
            st.caption(f"방어 모드: {mode_label} · 방어 이벤트 0건")
        else:
            rows = [
                {
                    "방어": event.get("defense_id"),
                    "단계": event.get("stage"),
                    "판정": label_of("defense_decisions", event.get("decision")),
                    "근거 코드": event.get("reason_code") or NO_VALUE,
                    "점수": NO_VALUE if event.get("score") is None else str(event.get("score")),
                    "임계값": NO_VALUE if event.get("threshold") is None else str(event.get("threshold")),
                    "대상": event.get("target_ref") or "사용자 입력/프롬프트",
                    "근거": event.get("reason") or NO_VALUE,
                    "오류": event.get("error") or NO_VALUE,
                    "임계값 기준 판정": label_of("defense_decisions", event.get("threshold_decision")) or NO_VALUE,
                    "모순": event.get("consistency_issue") or "없음",
                    "검토 필요": "예" if event.get("review_needed") else "아니오",
                }
                for event in events
            ]
            st.dataframe(rows, hide_index=True)

    # 5. 출력
    with st.container(border=True):
        st.subheader(stage_title("output"))
        output = trace.get("output") or {}
        parts = [str(label_of("output_outcomes", output.get("outcome")) or NO_VALUE)]
        if output.get("is_masked"):
            parts.append("마스킹됨")
        st.text(" · ".join(parts))
        if output.get("display_text"):
            show_text(output["display_text"])
        else:
            st.caption("출력 없음")


def render_meta(trace):
    """오른쪽: 성능·비용, 실행 설정, 데이터 버전, 평가"""
    request = trace.get("request") or {}

    with st.container(border=True):
        st.subheader(str(label_of("trace_stages", "metrics")))
        metrics = trace.get("metrics") or {}
        for item in SHARED["metric_keys"].values():
            value = metrics.get(item["value"])
            st.caption(item["label_ko"])
            st.text(NO_VALUE if value is None else str(value))
        st.caption(f"사용량 출처: {label_of('usage_sources', metrics.get('usage_source')) or NO_VALUE}")
        st.text(f"생성 호출 {metrics.get('generation_call_count', 0)} · 탐지 호출 {metrics.get('detection_call_count', 0)}")
        if not metrics.get("cost_complete"):
            st.caption(f"비용 미확인 호출: {metrics.get('unpriced_call_count', 0)} · 확인된 소계(USD): {metrics.get('known_cost_usd', 0)}")
        if metrics.get("generation_skipped_reason"):
            st.caption(f"생성 생략 사유: {metrics['generation_skipped_reason']}")
        if metrics.get("stages"):
            st.dataframe([{"단계": label_of("trace_stages", item["stage"]), "지연(ms)": item["latency_ms"]}
                          for item in metrics["stages"]], hide_index=True)

    with st.container(border=True):
        st.subheader("실행 설정")
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

    with st.container(border=True):
        st.subheader("데이터 버전")
        for key in ("dataset_version", "corpus_version"):
            st.caption(key)
            st.text(str(request.get(key) or NO_VALUE))

    with st.container(border=True):
        st.subheader(str(label_of("trace_stages", "evaluation")))
        evaluation = trace.get("evaluation") or {}
        st.caption("공격 성공")
        st.text(str(label_of("evaluation_statuses", evaluation.get("attack_success")) or NO_VALUE))
        st.caption("정상 태스크 성공")
        st.text(str(label_of("evaluation_statuses", evaluation.get("normal_task_success")) or NO_VALUE))
        st.caption("evaluator_version")
        st.text(str(evaluation.get("evaluator_version") or NO_VALUE))
        if evaluation.get("reason"):
            st.caption("판정 근거")
            st.text(str(evaluation["reason"]))

    with st.expander("모델 호출 기록 (마스킹됨)"):
        for call in trace.get("model_calls") or []:
            st.caption(f"{label_of('call_purposes', call['purpose'])} · {call['model_id']} · {call['latency_ms']}ms")
            st.caption(call.get("cost_reason") or NO_VALUE)
            for message in call["messages"]:
                st.caption(message["role"])
                show_text(message["content"])

    with st.container(border=True):
        st.subheader("탐지 대상별 독립 평가")
        rows = trace.get("detector_evaluation") or []
        if not rows:
            st.caption("탐지 대상별 평가 기록 없음")
        else:
            st.dataframe([{"단계": label_of("trace_stages", item["stage"]),
                           "대상": item.get("target_ref") or "사용자 입력",
                           "정답": label_of("detector_gold_labels", item.get("gold_label")) or NO_VALUE,
                           "분석": label_of("detector_analysis_statuses", item.get("analysis_status")) or NO_VALUE,
                           "정답 버전": item.get("gold_version") or NO_VALUE,
                           "검토자": item.get("reviewer") or NO_VALUE,
                           "근거": item.get("reason") or NO_VALUE} for item in rows], hide_index=True)


def render_comparison(column, results):
    """비교 결과: 조건 확인 → 요약 표 → 실행별 자세한 trace"""
    rows, different = condition_rows(results)
    if different:
        st.warning("비교 조건이 다른 실행이 있습니다: " + ", ".join(different)
                   + ". 같은 조건에서 다시 실행한 뒤 비교하세요.")
    else:
        st.success("비교한 실행들의 조건(데이터·모델·검색·생성 설정 등)이 모두 같습니다.")
    with st.expander("비교 조건 자세히 보기"):
        st.dataframe(rows, hide_index=True)

    st.dataframe(
        [summary_row(column, item["title"], item["trace"], item["error"]) for item in results],
        hide_index=True,
    )

    tabs = st.tabs([item["title"] for item in results])
    for tab, item in zip(tabs, results):
        with tab:
            if item["error"]:
                st.error(f"{item['error'].get('code') or '오류'}: {item['error'].get('message') or ''}")
            if item["trace"]:
                render_header(item["trace"])
                left, right = st.columns([2, 1])
                with left:
                    render_timeline(item["trace"])
                with right:
                    render_meta(item["trace"])


def run_many(settings, case_id, scenario, dataset_version, corpus_version):
    """(제목, 방어 모드, D2 위치) 목록을 차례로 실행하고 진행 막대를 보여 준다."""
    results = []
    progress = st.progress(0.0, text="실행 준비")
    for index, (title, each_mode, each_position) in enumerate(settings):
        progress.progress(index / len(settings), text=f"{title} 실행 중")
        trace, error = run_case(case_id, scenario, dataset_version, corpus_version,
                                each_mode, each_position)
        results.append({"title": title, "trace": trace, "error": error})
    progress.progress(1.0, text="실행 끝")
    return results


st.title("LLM Defense Trade-off Lab")
st.write("방어 모드 실행 · trace 확인")

cases = load_cases()

# 왼쪽 영역
with st.sidebar:
    st.header("대표 케이스")
    if cases:
        show_all = st.checkbox("모든 케이스 보기", value=False)
        case_by_id = {case["case_id"]: case for case in cases}
        choices = cases if show_all else [
            case_by_id[item["case_id"]] for item in MANIFEST["representative_cases"]
        ]
        case = st.radio(
            "대표 케이스",
            choices,
            format_func=lambda c: " · ".join(
                [
                    c["case_id"],
                    label_of("case_labels", c["label"]),
                    label_of("scenarios", c["scenario"]),
                    label_of("languages", c["language"]),
                ]
            ),
            label_visibility="collapsed",
            key="case_selector",
        )
        case_id = case["case_id"]
        scenario = case["scenario"]
        dataset_version = case["source_version"]
    else:
        st.warning("케이스 파일(data/cases.v0.1.jsonl)이 아직 없습니다. 아래 값으로 테스트 요청만 보낼 수 있습니다.")
        case_id = st.text_input("테스트용 case_id", "test_case_001")
        scenario = "rag_chat"
        dataset_version = st.text_input("dataset_version", "v0.1")
    corpus_version = MANIFEST["corpus_version"]
    st.caption(f"데이터 버전: {dataset_version}")
    st.caption(f"코퍼스 버전: {corpus_version}")

    st.header("방어 모드")
    modes = [m["value"] for m in SHARED["defense_modes"].values()]
    mode = st.radio(
        "방어 모드",
        modes,
        format_func=lambda v: label_of("defense_modes", v),
        label_visibility="collapsed",
        key="defense_mode",
    )
    positions = [item["value"] for item in SHARED["defense_positions"].values()]
    position = st.selectbox("D2 적용 위치", positions, index=positions.index(SHARED["defense_positions"]["BOTH"]["value"]),
                            format_func=lambda value: label_of("defense_positions", value),
                            disabled=mode not in D2_MODES, key="defense_position")

    button_text = "재실행" if "result" in st.session_state else "실행"
    run_clicked = st.button(button_text, type="primary", key="run_case")

# 버튼을 누르면 백엔드에 요청을 보낸다
if run_clicked:
    with st.spinner(label_of("run_statuses", "running")):
        trace, error = run_case(case_id, scenario, dataset_version, corpus_version, mode, position)
    st.session_state["result"] = {"trace": trace, "error": error}

tab_single, tab_compare, tab_position = st.tabs(["한 번 실행", "4개 모드 비교", "D2 위치 비교"])

# 결과 영역 (한 번 실행)
with tab_single:
    result = st.session_state.get("result")
    if result is None:
        st.info("아직 실행 기록이 없습니다. 왼쪽에서 케이스를 고르고 실행을 누르세요.")
    else:
        error = result["error"]
        trace = result["trace"]

        if trace:
            render_header(trace)

        # 오류 상자: 404·422의 detail, 또는 trace 안의 error
        if error:
            title = error["code"] or "오류"
            if error["status"]:
                title = f"{title} (응답 {error['status']})"
            st.error(title)
            st.text(error["message"] or "")
        elif trace and trace.get("error"):
            st.error(str(trace["error"].get("code") or "오류"))
            st.text(str(trace["error"].get("message") or ""))

        if trace:
            left, right = st.columns([2, 1])
            with left:
                render_timeline(trace)
            with right:
                render_meta(trace)

# 4개 모드 비교: 같은 케이스를 네 방어 모드로 차례로 실행해 나란히 놓는다
with tab_compare:
    st.caption(f"왼쪽에서 고른 케이스 {case_id}를 무방어, D1, D2, D1 + D2로 차례로 실행합니다.")
    compare_position = st.selectbox(
        "D2 적용 위치 (D2, D1 + D2에 적용)",
        positions,
        index=positions.index(SHARED["defense_positions"]["BOTH"]["value"]),
        format_func=lambda value: label_of("defense_positions", value),
        key="compare_position",
    )
    if st.button("4개 모드 한 번에 실행", type="primary", key="run_compare"):
        settings = [(label_of("defense_modes", m), m, compare_position) for m in modes]
        st.session_state["compare"] = {
            "case_id": case_id,
            "position": compare_position,
            "results": run_many(settings, case_id, scenario, dataset_version, corpus_version),
        }

    compare = st.session_state.get("compare")
    if compare is None:
        st.info("아직 비교 기록이 없습니다. 위 버튼을 누르세요.")
    else:
        st.caption(
            f"비교한 케이스: {compare['case_id']} · "
            f"D2 적용 위치: {label_of('defense_positions', compare['position'])}"
        )
        if compare["case_id"] != case_id:
            st.warning("왼쪽에서 지금 고른 케이스와 다른 케이스의 비교 결과입니다. 다시 실행하면 바뀝니다.")
        render_comparison("방어 모드", compare["results"])

# D2 위치 비교: D1 없이 D2만 켜고 위치만 바꿔 같은 탐지 설정으로 비교한다
with tab_position:
    st.caption(f"왼쪽에서 고른 케이스 {case_id}를 D2로, 적용 위치만 바꿔 세 번 실행합니다. "
               "D1은 끄고 탐지 모델·임계값·정책은 같게 둡니다.")
    if st.button("D2 위치 3개 한 번에 실행", type="primary", key="run_positions"):
        d2_only = SHARED["defense_modes"]["D2"]["value"]
        settings = [(label_of("defense_positions", p), d2_only, p) for p in positions]
        st.session_state["positions"] = {
            "case_id": case_id,
            "results": run_many(settings, case_id, scenario, dataset_version, corpus_version),
        }

    position_compare = st.session_state.get("positions")
    if position_compare is None:
        st.info("아직 위치 비교 기록이 없습니다. 위 버튼을 누르세요.")
    else:
        st.caption(f"비교한 케이스: {position_compare['case_id']} · 방어 모드: D2")
        if position_compare["case_id"] != case_id:
            st.warning("왼쪽에서 지금 고른 케이스와 다른 케이스의 비교 결과입니다. 다시 실행하면 바뀝니다.")
        render_comparison("D2 적용 위치", position_compare["results"])
