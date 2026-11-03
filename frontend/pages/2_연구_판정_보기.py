"""AI 연구 판정 보기 (#48, 계약: docs/week4-backend.md).

원래 자동 평가(배치 대시보드)와 섞지 않는 별도 보기다. 공개된 연구 판정 파일만 읽으므로
이 PC에 원래 실행 기록이 없어도 볼 수 있다. 어떤 버튼도 모델을 호출하지 않는다.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import research_core as rc  # noqa: E402
from batch_core import list_batches, md_safe, report_json_bytes  # noqa: E402
from ui_core import load_run  # noqa: E402

st.set_page_config(page_title="연구 판정 보기", layout="wide")
st.title("AI 연구 판정 보기")
st.warning("이 화면은 **원래 자동 평가가 아닙니다.** 같은 계열 AI 두 개가 따로 판정하고 세 번째 AI가 불일치를 "
           "조정한 연구 판정(#43)입니다. 사람 검토는 하지 않았고, 원래 평가·배치 대시보드 수치에는 적용되지 않습니다.")


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


def badges(rows, per_row=3):
    for start in range(0, len(rows), per_row):
        cols = st.columns(per_row)
        for col, (name, value) in zip(cols, rows[start:start + per_row]):
            col.caption(name)
            col.markdown(f"**{md_safe(value)}**")


# 1. 배치 고르기: 공개 연구판 배치 + 이 PC에 저장된 배치 중 연구판이 있는 것
candidates = dict(rc.PUBLISHED_RESEARCH_BATCHES)
local, _ = list_batches()
for b in local or []:
    candidates.setdefault(b["batch_id"], "이 PC에 저장된 배치")
batch_id = st.selectbox("배치", list(candidates), format_func=lambda i: f"{i} · {candidates[i]}", key="research_batch")

sources_cache = st.session_state.setdefault("research_sources", {})
if batch_id not in sources_cache:
    sources_cache[batch_id] = rc.get_sources(batch_id)
sources, sources_error = sources_cache[batch_id]
if sources_error:
    show_error(sources_error)
    st.stop()
if not (sources.get("research") or {}).get("available"):
    st.info("이 배치에는 공개된 AI 연구 판정이 없습니다. 원래 자동 평가는 '배치 대시보드'에서 보세요.")
    st.stop()

# 2. 필터 (서버가 지원하는 cohort 필터만. 케이스·family·라벨별 재집계는 서버가 지원하지 않음)
filters_by_batch = st.session_state.setdefault("research_filters", {})
filters = filters_by_batch.get(batch_id, {})
cache = st.session_state.setdefault("research_cache", {})


def fetch(f):
    key = (batch_id, tuple(sorted(f.items())))
    if key not in cache:
        with st.spinner("연구 판정 조회 중"):
            cache[key] = rc.get_research_report(batch_id, f)
    return cache[key]


base, base_error = fetch({})
if base_error:
    show_error(base_error)
    st.stop()
options = rc.filter_options(base)
with st.form("research_filters_form"):
    st.markdown("**필터** — 공개된 묶음(cohort) 단위로만 고를 수 있습니다 (모델 호출 없음)")
    chosen, cols = {}, st.columns(3)
    for i, (key, title) in enumerate(f for f in rc.RESEARCH_FILTERS if options.get(f[0])):
        values = [None] + options[key]
        current = filters.get(key)
        chosen[key] = cols[i % 3].selectbox(title, values, index=values.index(current) if current in values else 0,
                                            format_func=lambda v, k=key: "전체" if v is None else rc.option_text(k, v),
                                            key=f"research_{batch_id}_{key}")
    if st.form_submit_button("필터 적용"):
        filters_by_batch[batch_id] = {k: v for k, v in chosen.items() if v is not None}
        for stale in ("research_csv", "research_trace"):
            st.session_state.pop(stale, None)
        st.rerun()

report, report_error = fetch(filters)
if report_error:
    show_error(report_error)
    st.stop()
report_key = (batch_id, report.get("report_sha256"))

# 3. 출처·상태 먼저
badges(rc.research_badges(report))
st.caption(f"보고서 {report.get('report_version')} · 해시 {str(report.get('report_sha256'))[:12]}… · "
           f"평가 스냅샷 {str(report.get('evaluation_snapshot_sha256'))[:12]}…")
reasons = rc.decision_reason_rows(report)
if reasons:
    st.caption("추천 보류 이유: " + " · ".join(reasons))

counts = report.get("counts") or {}
if not report.get("groups") and not report.get("target_gold_groups"):
    st.info("이 필터에 맞는 공개 연구 판정이 없습니다. 필터를 넓혀 보세요. (0건을 0%로 보여 주지 않습니다)")
    st.stop()

tab_metric, tab_gold, tab_runs, tab_limits, tab_export = st.tabs(
    ["최종 출력 지표", "D2 검사 대상 정답", "실행별 판정", "이 보기의 한계", "내보내기"])

with tab_metric:
    st.caption(f"출력 그룹 {counts.get('output_groups', 0)}개 · 출력 실행 {counts.get('output_runs', 0)}건 · "
               f"미확정 포함 {counts.get('unresolved_members', 0)}건. 칸은 '값 (분자/분모)'이며 값이 없으면 기록 없음입니다.")
    rows = rc.research_rows(report)
    table([{k: v for k, v in r.items() if k != "group_id"} for r in rows])
    if rows:
        group_by_id = {g["group_id"]: g for g in report["groups"]}
        picked = st.selectbox("자세히 볼 그룹", [r["group_id"] for r in rows],
                              format_func=lambda i: rc.group_name(group_by_id[i]["cohort"]), key="research_group")
        for key, label in rc.RESEARCH_METRICS.items():
            metric = (group_by_id[picked].get("metrics") or {}).get(key)
            st.markdown(f"**{label}** — {md_safe(rc.research_cell(metric))}")
            st.caption(md_safe(rc.research_detail(metric)))
    with st.expander("지표별 값의 출처"):
        table(rc.metric_source_rows(report))

with tab_gold:
    st.caption("D2가 실제로 검사한 입력·문서 하나하나에 AI가 붙인 정답의 **건수**입니다. "
               "D2가 맞혔는지(FNR/FPR)나 최종 공격 성공률이 아닙니다.")
    table(rc.gold_rows(report))

with tab_runs:
    st.caption("실행 번호별로 원래 자동 평가와 AI 연구 판정을 나란히 봅니다. 판정 이유 원문은 공개 파일에 넣지 않았습니다.")
    runs = rc.member_rows(report)
    table(runs)
    with st.expander("D2 검사 대상별 AI 정답"):
        table(rc.member_rows(report, kind="detector_target"))
    if runs:
        run_id = st.selectbox("마스킹된 trace를 볼 실행 번호", [r["실행 번호"] for r in runs], key="research_run")
        if st.button("trace 조회", key="research_load_trace"):
            st.session_state["research_trace"] = (report_key, run_id, load_run(run_id))
        loaded = st.session_state.get("research_trace")
        if loaded and loaded[0] == report_key and loaded[1] == run_id:
            trace, error = loaded[2]
            if error:
                st.info("이 PC에는 이 배치의 원래 실행 기록이 없어 trace를 볼 수 없습니다. "
                        "원래 실행 기록(runs 폴더)이 있는 PC에서 서버를 켜야 합니다.")
                show_error(error)
            elif trace:
                st.caption(f"상태 {trace.get('status')} · 케이스 {(trace.get('request') or {}).get('case_id')}")
                st.code((trace.get("output") or {}).get("display_text") or "기록 없음", language=None, wrap_lines=True)

with tab_limits:
    st.caption("이 연구판이 일부러 제공하지 않는 값입니다. 비어 있다고 0이나 '문제 없음'으로 읽지 않습니다.")
    table(rc.capability_rows(report))

with tab_export:
    st.caption("지금 필터의 연구 보고서입니다. 원래 자동 평가 다운로드(배치 대시보드)와 다른 파일입니다.")
    name = f"{batch_id}-research-{str(report.get('report_sha256'))[:12]}"
    st.download_button("연구 보고서 JSON 내려받기", report_json_bytes(report), file_name=f"{name}.json",
                       mime="application/json", key="research_json")
    if st.button("연구 CSV 준비", key="research_csv_prepare"):
        with st.spinner("CSV 받는 중 · 화면 보고서와 대조 중"):
            st.session_state["research_csv"] = (report_key, *rc.get_research_csv(batch_id, filters, report))
    prepared = st.session_state.get("research_csv")
    if prepared and prepared[0] == report_key:
        _, content, error = prepared
        if error:
            show_error(error)
        else:
            st.success("CSV의 해시·필터·값이 화면 보고서와 같습니다.")
            st.download_button("연구 CSV 내려받기", content, file_name=f"{name}.csv", mime="text/csv",
                               key="research_csv_download")
    elif prepared:
        st.caption("배치나 필터가 바뀌었습니다. CSV를 다시 준비하세요.")
