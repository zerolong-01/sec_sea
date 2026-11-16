"""최종 보고서 4.2절과 같은 공개 AI 원본 공격 비교표. 모델 호출 없음."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import comparison_core as cc
from batch_core import md_safe, report_json_bytes
from research_core import research_detail
from trace_view import render_saved_trace

st.set_page_config(page_title="보고서 원본 공격 비교", layout="wide")
st.title("보고서 원본 공격 비교")
st.warning("최종 보고서 4.2절의 AI 연구 판정입니다. 원래 자동 평가와 별도이며, 사람 검토·최종 추천은 완료되지 않았습니다.")
if st.button("보고서 새로고침", key="comparison_reload"):
    for key in ("comparison_report", "comparison_csv", "comparison_trace"):
        st.session_state.pop(key, None)
if "comparison_report" not in st.session_state:
    st.session_state["comparison_report"] = cc.get_report()
report, error = st.session_state["comparison_report"]
if error:
    st.error(error.get("code") or "조회 오류")
    st.text(error.get("message") or "보고서를 조회할 수 없습니다.")
    st.stop()

report_key = report["report_sha256"]
st.caption("대상: " + ", ".join(report["selection"]["case_ids"]) + " · 6조건 × 3반복 · 72개 출력 실행")
st.caption(f"평가판 {report['evaluation_version']} · 보고서 {report['report_version']} · 해시 {report_key}")
st.info("합산값은 표식 이행과 보호값 노출을 합친 기술통계입니다. 목표별 표를 함께 확인하세요. 공격 상황 업무 성공은 정상 요청의 성공률과 다른 지표입니다.")
st.dataframe(cc.rows(report), hide_index=True)
with st.expander("공격 목표별 결과·분모·제외·표본 한계"):
    st.dataframe(cc.rows(report, goals=True), hide_index=True)
    for row in report["rows"]:
        for goal in row["goal_groups"]:
            for name, metric in goal["metrics"].items():
                st.caption(md_safe(f"{row['display_condition']} · {goal['goal_kind']} · {cc.METRICS[name]}: "
                                   + research_detail(metric)))
    st.write("추천 보류 · 독립 family 부족 · CI 없음 · holdout 미실행")

with st.expander("보고서 → 실행 번호 → 원래 trace·판정 근거"):
    members = report["members"]
    render_saved_trace([m["run_id"] for m in members], key="comparison", report_key=report_key,
                       expected_cases={m["run_id"]: m["case_id"] for m in members})

st.download_button("비교 보고서 JSON 내려받기", report_json_bytes(report), mime="application/json",
                   file_name=f"original-attacks-{report_key[:12]}.json", key="comparison_json")
if st.button("비교 CSV 준비", key="comparison_csv_prepare"):
    st.session_state["comparison_csv"] = (report_key, *cc.get_csv(report))
prepared = st.session_state.get("comparison_csv")
if prepared and prepared[0] == report_key:
    if prepared[2]:
        st.error(prepared[2]["message"])
    else:
        st.success("CSV의 보고서 해시·행 소속·분자/분모·근거가 화면과 같습니다.")
        st.download_button("비교 CSV 내려받기", prepared[1], mime="text/csv",
                           file_name=f"original-attacks-{report_key[:12]}.csv", key="comparison_csv_download")
