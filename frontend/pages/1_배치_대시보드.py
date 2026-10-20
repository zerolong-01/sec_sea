"""3주차 배치 대시보드 (이슈 #35).

저장된 배치 결과를 조회만 한다. 이 화면의 어떤 버튼도 모델을 호출하지 않는다.
지표·CI·추천 판단은 서버 집계 API 값을 그대로 보여 준다 (batch_core.py 참고).
"""
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # frontend 폴더의 모듈을 불러오기 위해

from batch_core import (  # noqa: E402
    ANALYSIS_FILTERS, METRICS, NO_VALUE, budget_rows, common_reasons, comparison_rows, condition_rows,
    decision_rows, decision_status_text, detector_rows, filter_options, get_batch, get_csv, get_report,
    group_title, kpi_cards, md_safe, list_batches, option_text, payload_rows, plan_rows_for_runs, reason_text,
    report_json_bytes, baseline_rows, scatter_points, scope_text, batch_status_text, status_counts_text,
    summary_rows, warnings_for,
)
from ui_core import label_of, load_run  # noqa: E402

st.set_page_config(page_title="배치 대시보드", layout="wide")
st.title("배치 대시보드")
st.caption("저장된 배치 실험 결과를 조회합니다. 조회·필터·내보내기는 모델을 다시 호출하지 않습니다.")


def show_error(error):
    title = error.get("code") or "오류"
    if error.get("status"):
        title += f" (응답 {error['status']})"
    st.error(title)
    if error.get("message"):
        st.text(error["message"])


def table(rows, **kwargs):
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, **kwargs)
    else:
        st.info("표시할 항목이 없습니다.")


# ---------------------------------------------------------------------------
# 1. 배치 목록
# ---------------------------------------------------------------------------
if st.button("배치 목록 새로고침", key="reload_batches") or "batches" not in st.session_state:
    with st.spinner("배치 목록 조회 중"):
        st.session_state["batches"] = list_batches()
    st.session_state.pop("report_cache", None)

batches, list_error = st.session_state["batches"]
if list_error:
    show_error(list_error)
    st.stop()
if not batches:
    st.info("저장된 배치가 없습니다. 배치는 백엔드 명령으로 만듭니다. 연습용(가짜 모델) 배치는 아래처럼 만들 수 있습니다.")
    st.code("python -m scripts.verify_week3 --output runs/week3-handoff\n"
            "python -m scripts.mvp serve --fixture-model --runs-dir runs/week3-handoff/runs", language=None)
    st.stop()

with st.expander(f"저장된 배치 {len(batches)}개", expanded=len(batches) > 1):
    table(summary_rows(batches))

batch_ids = [b["batch_id"] for b in batches]
batch_id = st.selectbox(
    "볼 배치",
    batch_ids,
    format_func=lambda i: next(f"{b['batch_id']} · {scope_text(b.get('execution_scope'))} · "
                               f"{batch_status_text(b.get('status'))} · {b.get('created_at', '')[:19]}"
                               for b in batches if b["batch_id"] == i),
    key="batch_id",
)

# ---------------------------------------------------------------------------
# 2. 배치 상세 + 필터 → 집계 리포트
# ---------------------------------------------------------------------------
cache = st.session_state.setdefault("report_cache", {})
filters = st.session_state.setdefault("filters", {}).get(batch_id, {})
cache_key = (batch_id, tuple(sorted(filters.items())))

if cache_key not in cache:
    with st.spinner("배치 상세·집계 조회 중"):
        summary, summary_error = get_batch(batch_id)
        report, report_error = get_report(batch_id, filters) if summary else (None, None)
    cache[cache_key] = (summary, summary_error, report, report_error)
summary, summary_error, report, report_error = cache[cache_key]

if summary_error:
    show_error(summary_error)
    st.stop()

for note in warnings_for(summary, report):
    st.warning(note)

cols = st.columns(4)
cols[0].metric("배치 상태", batch_status_text(summary.get("status")))
cols[1].metric("실행 범위", scope_text(summary.get("execution_scope")))
cols[2].metric("계획 / 시도", f"{summary.get('planned_count')} / {summary.get('attempt_count')}")
cols[3].metric("실행 결과", status_counts_text(summary.get("status_counts"), short=True),
                help=md_safe(status_counts_text(summary.get("status_counts"))))
if summary.get("reason"):
    st.caption(md_safe(f"상태 사유: {summary['reason']}"))

with st.expander("배치 정보 (예산·조건·데이터 출처·고정 해시)"):
    left, right = st.columns(2)
    with left:
        st.markdown("**예산·사용량**")
        table(budget_rows(summary))
    with right:
        st.markdown("**방어 조건**")
        table(condition_rows(summary))
    st.markdown("**데이터 출처**")
    table([{"출처": s.get("source_id"), "앱": label_of("scenarios", s.get("scenario")),
            "데이터 구분": label_of("splits", s.get("split")), "데이터 버전": s.get("dataset_version"),
            "코퍼스 버전": s.get("corpus_version"), "케이스": ", ".join(s.get("case_ids") or [])}
           for s in summary.get("sources") or []])
    st.markdown("**고정 해시 (재현성 확인용)**")
    st.json(summary.get("configuration_hashes") or {}, expanded=False)

# 필터
options = filter_options(summary)
with st.form("filters_form"):
    st.markdown("**필터** — 바꾸면 서버가 같은 저장 결과로 다시 집계합니다 (모델 호출 없음)")
    chosen = {}
    columns = st.columns(4)
    shown = [f for f in ANALYSIS_FILTERS if options.get(f[0])]
    for i, (key, title, _) in enumerate(shown):
        values = [None] + options[key]
        current = filters.get(key)
        chosen[key] = columns[i % 4].selectbox(
            title, values,
            index=values.index(current) if current in values else 0,
            format_func=lambda v, k=key: "전체" if v is None else option_text(k, v, summary),
            key=f"filter_{batch_id}_{key}",
        )
    applied = st.form_submit_button("필터 적용")
if applied:
    st.session_state["filters"][batch_id] = {k: v for k, v in chosen.items() if v is not None}
    st.rerun()
if filters:
    st.caption("적용 중인 필터: " + " · ".join(f"{dict((f[0], f[1]) for f in ANALYSIS_FILTERS)[k]}={option_text(k, v, summary)}"
                                          for k, v in filters.items()))

if report_error:
    show_error(report_error)
    st.stop()
if not report.get("groups"):
    st.info("이 필터에 맞는 실행이 없습니다. 필터를 넓혀 보세요.")
    st.stop()

st.caption(f"리포트 버전 {report.get('report_version')} · 평가 스냅샷 {str(report.get('evaluation_snapshot_sha256'))[:12]}… · "
           f"통계 {report.get('statistics', {}).get('version')} ({report.get('statistics', {}).get('status')})")

groups = report["groups"]
group_ids = [g["group_id"] for g in groups]
group_by_id = {g["group_id"]: g for g in groups}

tab_kpi, tab_tradeoff, tab_decision, tab_baseline, tab_detector, tab_trace, tab_export = st.tabs(
    ["지표 요약", "Trade-off", "추천 근거", "무방어 대비 변화", "D2 탐지·payload", "실행 trace", "내보내기"])

# ---------------------------------------------------------------------------
# 3. 지표 요약: 그룹 하나의 KPI 카드 + 전체 비교표
# ---------------------------------------------------------------------------
with tab_kpi:
    selected = st.selectbox("그룹 (앱·언어·방어 조건)", group_ids, format_func=lambda i: group_title(group_by_id[i]),
                            key="kpi_group")
    cards = kpi_cards(group_by_id[selected])
    for start in range(0, len(cards), 3):
        cols = st.columns(3)
        for col, (label, value, detail) in zip(cols, cards[start:start + 3]):
            col.metric(label, value, help=md_safe(detail))
            col.caption(md_safe(detail))
    st.caption("값이 '기록 없음'이면 분모가 0이거나 평가가 끝나지 않은 것입니다. 0%나 실패로 바꾸지 않았습니다.")

    st.subheader("조건별 비교표")
    rows = comparison_rows(report)
    table([{k: v for k, v in r.items() if k != "group_id"} for r in rows])
    st.caption("비율 칸은 '값 (분자/분모)'입니다. CI·제외 사유는 위 KPI 카드나 내보내기 파일에서 볼 수 있습니다.")

# ---------------------------------------------------------------------------
# 4. Trade-off 산점도
# ---------------------------------------------------------------------------
with tab_tradeoff:
    st.caption("x축: 정상 태스크 성공률 (오른쪽일수록 좋음) · y축: 공격 차단율 = 1 − ASR (위쪽일수록 좋음) · "
               "점 크기: 요청당 비용. 점 색은 서버의 추천 판단입니다. Pareto는 화면에서 다시 계산하지 않습니다.")
    points, skipped = scatter_points(report)
    if points:
        data = pd.DataFrame(points)
        has_cost = data["요청당 비용"].notna().any()
        base = alt.Chart(data).encode(
            x=alt.X("정상 태스크 성공률:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
            y=alt.Y("공격 차단율 (1-ASR):Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
            color=alt.Color("추천 판단:N"),
            shape=alt.Shape("앱:N"),
            opacity=alt.Opacity("표본:N", scale=alt.Scale(domain=["충분", "표본 부족"], range=[0.9, 0.35])),
            tooltip=["그룹", "추천 판단", "표본", alt.Tooltip("정상 태스크 성공률:Q", format=".1%"),
                     alt.Tooltip("공격 차단율 (1-ASR):Q", format=".1%"), "비용 표시", "같은 자리 그룹"],
        )
        if has_cost:
            chart = base.mark_point(filled=True).encode(size=alt.Size("요청당 비용:Q", title="요청당 비용"))
        else:
            chart = base.mark_point(filled=True, size=140)
            st.caption("비용이 모두 미확인이라 점 크기를 같게 그렸습니다.")
        st.altair_chart(chart)
        st.caption("흐린 점은 표본이 부족해 CI가 없는 값입니다. 점에 마우스를 올리면 같은 자리에 겹친 그룹도 보입니다.")
        table([{k: v for k, v in p.items() if k not in ("group_id", "요청당 비용")} for p in points])
    else:
        st.info("산점도에 찍을 수 있는 그룹이 없습니다. 정상 성공률과 ASR이 둘 다 있어야 점을 찍습니다.")
    if skipped:
        with st.expander(f"점을 못 찍은 그룹 {len(skipped)}개", expanded=not points):
            table(skipped)

# ---------------------------------------------------------------------------
# 5. 추천 근거
# ---------------------------------------------------------------------------
with tab_decision:
    decisions = report.get("decisions") or {}
    cols = st.columns(3)
    cols[0].metric("전체 판단", decision_status_text(decisions.get("status")))
    cols[1].metric("추천 후보", "없음" if decisions.get("no_candidate") else "있음")
    cols[2].metric("평가 정책", decisions.get("evaluation_policy_version") or NO_VALUE)
    st.caption("판단 순서 (서버): 합격 기준으로 탈락 → 남은 구성끼리 전체 지표 Pareto → 미리 정한 우선순위.")

    shared = common_reasons(report)
    if shared:
        st.markdown("**모든 그룹에 공통인 보류 사유** (배치 전체의 이유)")
        for code in shared:
            st.markdown(f"- {reason_text(code)}  `{code}`")
    st.markdown("**그룹별 판단**")
    for row in decision_rows(report):
        own = [reason_text(code) for code in row["사유 코드"] if code not in shared]
        with st.expander(f"{row['그룹']} — {row['판단']} (실행 {row['실행 수']}건)"):
            if own:
                for text in own:
                    st.markdown(md_safe(f"- {text}"))
            else:
                st.caption("공통 사유 외 추가 사유 없음")
            if row["이 구성보다 나은 구성"]:
                st.markdown("이 구성보다 모든 지표가 같거나 나은 구성: " + ", ".join(row["이 구성보다 나은 구성"]))

# ---------------------------------------------------------------------------
# 6. 무방어 대비 변화
# ---------------------------------------------------------------------------
with tab_baseline:
    st.caption("같은 케이스·반복끼리 짝지어 계산한 값입니다 (서버 계산). "
               "ASR 감소폭 = 무방어 − 방어 (클수록 공격을 더 막음). 정상 성공률·FPR = 방어 − 무방어. 단위 %p. "
               "지연·비용은 무방어 대비 증가율입니다.")
    table(baseline_rows(report))

# ---------------------------------------------------------------------------
# 7. D2 탐지 지표, payload 비교
# ---------------------------------------------------------------------------
with tab_detector:
    st.markdown("**D2 탐지기 대상별 지표** — 탐지기가 검사한 입력·문서 단위의 값이라 최종 ASR과 다릅니다.")
    table(detector_rows(report))
    st.markdown("**payload 짝 비교** — 같은 family에서 공격 부분만 바꾼 변형끼리의 목표값 노출 차이입니다.")
    rows = payload_rows(report)
    if rows:
        table(rows)
    else:
        st.info("이 배치에는 payload 비교 데이터가 없습니다.")

# ---------------------------------------------------------------------------
# 8. 그룹 → 실행 번호 → trace
# ---------------------------------------------------------------------------
with tab_trace:
    selected = st.selectbox("그룹", group_ids, format_func=lambda i: group_title(group_by_id[i]), key="trace_group")
    runs = plan_rows_for_runs(summary, group_by_id[selected].get("run_ids"))
    table(runs)
    run_ids = [r["실행 번호"] for r in runs]
    if run_ids:
        run_id = st.selectbox("자세히 볼 실행 번호", run_ids, key="trace_run")
        if st.button("trace 조회", key="load_trace"):
            with st.spinner("저장 trace 조회 중"):
                st.session_state["batch_trace"] = load_run(run_id)
        loaded = st.session_state.get("batch_trace")
        if loaded:
            trace, error = loaded
            if error:
                show_error(error)
            if trace:
                evaluation = trace.get("evaluation") or {}
                output = trace.get("output") or {}
                metrics = trace.get("metrics") or {}
                cols = st.columns(4)
                cols[0].metric("상태", label_of("run_statuses", trace.get("status")))
                cols[1].metric("출력 결과", label_of("output_outcomes", output.get("outcome")))
                cols[2].metric("공격 성공", label_of("evaluation_statuses", evaluation.get("attack_success")))
                cols[3].metric("정상 태스크", label_of("evaluation_statuses", evaluation.get("normal_task_success")))
                st.caption(f"실행 번호 {trace.get('run_id')} · 케이스 {(trace.get('request') or {}).get('case_id')} · "
                           f"지연 {metrics.get('latency_ms', NO_VALUE)} ms")
                events = trace.get("defense_events") or []
                if events:
                    table([{"단계": label_of("trace_stages", e.get("stage")),
                            "판정": label_of("defense_decisions", e.get("decision")),
                            "방어": e.get("defense_id") or e.get("defense_mode") or NO_VALUE,
                            "오류": e.get("error") or ""} for e in events])
                st.markdown("**출력 (마스킹된 공개 trace)**")
                st.code(output.get("display_text") or NO_VALUE, language=None, wrap_lines=True)
                if evaluation.get("reason"):
                    st.caption(md_safe(f"평가 사유: {evaluation['reason']}"))
                with st.expander("trace 전체 (JSON)"):
                    st.json(trace, expanded=False)
                st.caption("단계별 화면은 첫 페이지의 '한 번 실행' 탭에서 같은 실행 번호로 조회하면 볼 수 있습니다.")

# ---------------------------------------------------------------------------
# 9. 내보내기: 지금 화면과 같은 필터·스냅샷
# ---------------------------------------------------------------------------
with tab_export:
    st.caption("지금 적용 중인 필터로 서버가 만든 파일입니다. 원시 로그·보호값·인증키는 들어가지 않습니다.")
    name = f"{batch_id}-{str(report.get('evaluation_snapshot_sha256'))[:12]}"
    st.download_button("리포트 JSON 내려받기", report_json_bytes(report), file_name=f"{name}-report.json",
                       mime="application/json", key="download_json")
    if st.button("지표 CSV 준비", key="prepare_csv"):
        with st.spinner("CSV 만드는 중"):
            st.session_state["batch_csv"] = (cache_key, *get_csv(batch_id, filters))
    prepared = st.session_state.get("batch_csv")
    if prepared and prepared[0] == cache_key:
        _, content, error = prepared
        if error:
            show_error(error)
        else:
            st.download_button("지표 CSV 내려받기", content, file_name=f"{name}-metrics.csv", mime="text/csv",
                               key="download_csv")
    elif prepared:
        st.caption("필터나 배치가 바뀌었습니다. CSV를 다시 준비하세요.")
