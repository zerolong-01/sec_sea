"""저장된 다중 모델 실험 → cohort별 수치 → CSV → 실행 trace. 모델 호출 없음."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import experiment_core as ec
from batch_core import METRICS, md_safe, metric_detail, option_text, report_json_bytes, scope_text
from trace_view import render_saved_trace

st.set_page_config(page_title="모델 비교", layout="wide")
st.title("저장된 모델 비교")
st.info("같은 동결 입력·조건의 모델별 원래 자동 평가를 비교합니다. AI 연구 판정과 섞지 않으며, 모델 간 우월성 검정·최종 추천은 수행하지 않습니다.")

def show_error(error):
    st.error(error.get("code") or "조회 오류")
    if error.get("message"):
        st.text(error["message"])


if st.button("실험 목록 새로고침", key="experiment_reload") or "experiment_list" not in st.session_state:
    st.session_state["experiment_list"] = ec.list_experiments()
    for key in ("experiment_cache", "experiment_csv", "experiment_trace"):
        st.session_state.pop(key, None)
experiments, error = st.session_state["experiment_list"]
if error:
    show_error(error)
    st.stop()
if not experiments:
    st.info("이 저장소에 다중 모델 실험이 없습니다. 기존 실험이 있는 runs 폴더로 서버를 기동하세요.")
    st.code("python -m scripts.verify_model_experiment --output runs/model-demo\n"
            "python -m scripts.mvp serve --fixture-model --runs-dir runs/model-demo/runs", language=None)
    st.stop()

experiment_id = st.selectbox("실험", [r["experiment_id"] for r in experiments], key="experiment_id")
cache = st.session_state.setdefault("experiment_cache", {})
filters_by_id = st.session_state.setdefault("experiment_filters", {})
filters = filters_by_id.get(experiment_id, {})

def fetch(selected_filters):
    key = (experiment_id, tuple(sorted(selected_filters.items())))
    if key not in cache:
        cache[key] = ec.get_report(experiment_id, selected_filters)
    return cache[key]


base, error = fetch({})
if error:
    show_error(error)
    st.stop()
with st.form("experiment_filters_form"):
    selected = {}
    columns = st.columns(3)
    for i, (key, values) in enumerate((k, v) for k, v in ec.options(base).items() if v):
        values = [None] + values
        current = filters.get(key)
        selected[key] = columns[i % 3].selectbox(ec.FILTERS[key], values,
            index=values.index(current) if current in values else 0,
            format_func=lambda v, k=key: "전체" if v is None else option_text(k, v),
            key=f"experiment_{experiment_id}_{key}")
    if st.form_submit_button("필터 적용"):
        filters_by_id[experiment_id] = ec.body(selected)
        for key in ("experiment_csv", "experiment_trace"):
            st.session_state.pop(key, None)
        st.rerun()

report, error = fetch(filters)
if error:
    show_error(error)
    st.stop()
report_key = (experiment_id, report["report_sha256"])
summary = report["summary"]
st.caption(f"상태 {summary['status']} · 계획 {summary['planned_count']}건 · 시도 {summary['attempt_count']}건 · "
           f"평가 출처: 원래 자동 평가 · 보고서 {report['report_version']}")
st.caption("보고서 해시: " + report["report_sha256"])
st.caption("실행 범위: " + " · ".join(f"{m['model_key']}: {scope_text(m['execution_scope'])}" for m in summary["models"]))
st.caption("지연·비용은 실패·재시도를 포함한 관측입니다. 모델은 순서대로 실행되어 시간대·제공자 상태의 영향이 있을 수 있습니다.")

rows = ec.rows(report)
if not rows:
    st.info("이 필터에 맞는 결과가 없습니다. 분모 0·미평가·가격 미확인은 0이나 성공으로 채우지 않습니다.")
else:
    st.dataframe([{k: v for k, v in row.items() if k != "row_id"} for row in rows], hide_index=True)
    selected_row = st.selectbox("지표 상세·trace를 볼 행", [row["row_id"] for row in rows], key="experiment_row",
        format_func=lambda value: next(" · ".join(str(r[k]) for k in ("모델", "방어 조건", "앱", "공격 목표", "변형"))
                                       for r in rows if r["row_id"] == value))
    row = next(r for r in report["rows"] if r["row_id"] == selected_row)
    with st.expander("분자/분모·제외·family·CI·평가 출처"):
        for name, metric in row["metrics"].items():
            st.markdown(f"**{METRICS[name][0]}** — {md_safe(metric_detail(metric, METRICS[name][1]))}")
        st.json({"cohort": row["cohort"], "normal_benchmark_id": row["normal_benchmark_id"],
                 "normal_benchmark_coverage": row["normal_benchmark_coverage"], "cost_scope": row["cost_scope"],
                 "source_report": report["provenance"]["batch_reports"][row["model_key"]]})
    with st.expander("선택한 모델·조건의 원래 trace·판정 근거"):
        render_saved_trace(row["run_ids"], key="experiment", report_key=(*report_key, selected_row))

with st.expander("비교 조건의 모델 소속·누락"):
    st.dataframe([{"비교 ID": r["comparison_id"], "모델 소속": ", ".join(r["model_rows"]),
                   "누락 모델": ", ".join(r["missing_models"]) or "없음", "상태": r["status"]}
                  for r in report["comparisons"]], hide_index=True)

st.download_button("모델 비교 JSON 내려받기", report_json_bytes(report), mime="application/json",
                   file_name=f"{experiment_id}-{report['report_sha256'][:12]}.json", key="experiment_json")
if st.button("모델 비교 CSV 준비", key="experiment_csv_prepare"):
    st.session_state["experiment_csv"] = (report_key, *ec.get_csv(experiment_id, filters, report))
prepared = st.session_state.get("experiment_csv")
if prepared and prepared[0] == report_key:
    if prepared[2]:
        show_error(prepared[2])
    else:
        st.success("CSV의 해시·필터·모델 소속·지표 값이 화면과 같습니다.")
        st.download_button("모델 비교 CSV 내려받기", prepared[1], mime="text/csv",
                           file_name=f"{experiment_id}-{report['report_sha256'][:12]}.csv", key="experiment_csv_download")
