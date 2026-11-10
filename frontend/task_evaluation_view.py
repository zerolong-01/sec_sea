"""Explicit automatic judgment, saved-result refresh, reviews and matching exports."""
import json
import uuid

import streamlit as st

import task_evaluation_core as core
from ui_core import label_of, text_or_missing

DIMENSION_LABELS = {"authorized_task_completion": "원래 요청 수행", "source_grounding_and_factual_accuracy": "문서 근거·사실 정확성",
                    "required_format": "요구한 답변 형식", "protected_information_safety": "보호 정보 안전성"}
ERROR_MESSAGES = {"TASK_JUDGE_NOT_CONFIGURED": "의미 판정용 모델 설정이 없습니다. 서버의 judge 설정을 확인하세요.",
                  "TASK_JUDGE_CALL_LIMIT": "이 실행의 AI 판정 호출 한도에 도달했습니다. 저장된 판정을 조회하세요.",
                  "TASK_EVALUATION_REVISION_CHANGED": "다른 수정이 먼저 저장됐습니다. 저장 판정을 다시 조회한 뒤 검토하세요.",
                  "CONCURRENT_WRITE": "다른 판정 작업이 저장 중입니다. 잠시 후 저장 판정을 조회하세요."}


def state_for(trace):
    key = core.state_key(trace)
    state = st.session_state.setdefault(key, {})
    if state.get("report") and core.report_error(state["report"], trace):
        state.clear()
    return state


def saved_report(trace):
    return state_for(trace).get("report")


def _save_result(state, report, error):
    state.pop("csv", None)
    state["error"] = error
    if error:
        state.pop("report", None)
    else:
        state["report"] = report


def evaluate(trace):
    state = state_for(trace)
    request_id = state.setdefault("request_id", "judge-" + uuid.uuid4().hex[:20])
    report, error = core.request_report(trace, method="POST", body={
        "request_id": request_id, "requested_by": "frontend-task-evaluation"})
    if report and not any(row["evaluation_id"] == request_id for row in report["records"]):
        report, error = None, {"code": "SNAPSHOT_MISMATCH", "message": "요청한 판정 번호가 응답에 없습니다."}
    _save_result(state, report, error)
    if not error:
        state.pop("request_id", None)


def refresh(trace):
    state = state_for(trace)
    _save_result(state, *core.request_report(trace))


def eligible(trace):
    return trace and trace.get("status") in ("completed", "blocked") and (trace.get("manifest") or {}).get("execution_kind", "full_pipeline") == "full_pipeline"


def render_group(traces, *, key):
    usable = [trace for trace in traces if eligible(trace)]
    if not usable:
        return
    st.caption("정상 업무 판정은 원래 답변을 평가합니다. 자동 판정 버튼은 별도 AI 호출이 발생할 수 있고, 저장 판정 조회는 호출하지 않습니다.")
    left, right = st.columns(2)
    if left.button("답변 자동 판정 · 재평가", key=f"{key}_judge_all"):
        with st.spinner("저장된 답변의 정상 업무 수행 여부를 평가합니다."):
            for trace in usable:
                evaluate(trace)
    if right.button("저장 판정 조회 · 새로고침", key=f"{key}_judge_refresh_all"):
        for trace in usable:
            refresh(trace)


def render_task_evaluation(trace, *, key):
    if not eligible(trace):
        return None
    state = state_for(trace)
    with st.expander("정상 업무 판정 · 근거 · 재평가", expanded=bool(state.get("report") or state.get("error"))):
        left, right = st.columns(2)
        report = state.get("report")
        retry = bool(state.get("request_id"))
        text = "이전 판정 요청 확인 · 재전송" if retry else "정상 업무 자동 판정" if not report or not report["latest"] else "명시적으로 재평가"
        exhausted = report and report["reserved_model_calls"] >= report["max_model_calls"]
        if left.button(text, key=f"{key}_judge", disabled=bool(exhausted and not retry),
                       help="별도 AI 호출과 비용이 발생할 수 있습니다. 오류 후 재전송은 같은 요청 번호를 사용합니다."):
            with st.spinner("정상 업무 평가 중"):
                evaluate(trace)
            st.rerun()
        if right.button("저장 판정 조회", key=f"{key}_judge_refresh"):
            refresh(trace)
            st.rerun()
        report = state.get("report")
        error = state.get("error")
        if error:
            st.error(f"{error.get('code') or '판정 조회 오류'}: {error.get('message') or ERROR_MESSAGES.get(error.get('code'), '판정 설정과 서버 상태를 확인하세요.')}")
        if not report:
            st.caption("별도 판정은 아직 조회하지 않았습니다. 위 버튼으로 판정하거나 저장 결과를 조회할 수 있습니다.")
            return None
        if not report["judge_configured"]:
            st.info("의미 판정용 모델이 설정되지 않았습니다. 단순 규칙으로 확정 가능한 결과만 평가할 수 있습니다.")
        st.caption(f"별도 판정 호출 예약 {report['reserved_model_calls']} / {report['max_model_calls']} · 원래 규칙 평가와 구분해 표시합니다.")
        latest = report["latest"]
        if not latest:
            st.info("이 실행에 저장된 별도 판정이 없습니다.")
            return report
        source = label_of("task_evaluation_sources", latest["source"])
        status = label_of("evaluation_statuses", latest["normal_task_success"])
        st.markdown(f"**정상 업무: {status} · {source}**")
        if latest["state"] == "pending":
            st.warning("판정 요청이 예약된 상태입니다. 저장 결과를 확인하세요. 명시적 재평가는 새 호출을 예약합니다.")
        elif latest["state"] == "error":
            st.warning(f"판정 오류로 미평가 상태입니다: {latest['error_code']}")
        st.text(latest["reason"])
        st.caption(f"평가 버전 {latest['evaluator_version']} · rubric {latest['rubric_version']} · 정책 {latest['policy_version']}")
        if latest["source"] == "llm_judge":
            st.caption(f"AI 모델 {latest['model_id']} · 사람 검토 완료를 뜻하지 않습니다.")
        metrics = latest["metrics"]
        cost = metrics.get("estimated_cost_usd")
        st.caption(f"추가 호출 {metrics['model_call_count']} · 추가 지연 {text_or_missing(metrics.get('latency_ms'))} ms · "
                   f"입력/출력 {text_or_missing(metrics.get('input_tokens'))} / {text_or_missing(metrics.get('output_tokens'))} 토큰 · 추가 추정 비용 {'미확인' if cost is None else str(cost) + ' USD'}")
        for title, dimensions in (("평가 차원", latest["dimensions"]), ("세부 rubric", latest["criteria"])):
            if dimensions:
                st.markdown(f"**{title}**")
                for name, dimension in dimensions.items():
                    title = DIMENSION_LABELS.get(name) or latest["rubric_snapshot"].get("criteria", {}).get(name, name)
                    st.caption(f"{title}: {label_of('evaluation_statuses', dimension['verdict'])}")
                    st.text(dimension["reason"])
                    for quote in dimension["evidence_quotes"]:
                        st.text("답변 근거: " + quote)
                    for quote in dimension.get("reference_quotes", []):
                        st.text(f"문서 근거 ({quote['document_id']}): {quote['quote']}")
        if st.button("같은 판정의 CSV 준비", key=f"{key}_judge_csv"):
            content, error = core.csv_bytes(trace, report)
            if error:
                state.pop("csv", None)
                st.error(error["message"])
            else:
                state["csv"] = (report["report_sha256"], content)
        prepared = state.get("csv")
        if prepared and prepared[0] == report["report_sha256"]:
            st.download_button("판정 CSV 다운로드", prepared[1], file_name="normal-task-evaluations.csv",
                               mime="text/csv", key=f"{key}_judge_download")
        with st.expander("이전 판정과 수정 이력"):
            st.dataframe([{"순서": r["revision"], "판정 번호": r["evaluation_id"],
                "출처": label_of("task_evaluation_sources", r["source"]),
                "정상 업무": label_of("evaluation_statuses", r["normal_task_success"]),
                "근거": r["reason"], "검토자": r["reviewer"] or "없음"} for r in report["records"]], hide_index=True)
        with st.form(f"{key}_judge_review_form"):
            st.caption("실제 검토자의 판단과 근거를 새 이력으로 남깁니다.")
            value = st.selectbox("수동 검토 결과", ["review_needed", "success", "failure", "not_evaluated"],
                                 format_func=lambda v: label_of("evaluation_statuses", v), key=f"{key}_review_value")
            reviewer = st.text_input("검토자", key=f"{key}_reviewer")
            reason = st.text_area("수정·확정 근거", key=f"{key}_review_reason")
            submitted = st.form_submit_button("수동 검토 저장")
        if submitted:
            if not reviewer.strip() or not reason.strip():
                st.error("검토자와 수정 근거를 입력하세요.")
            else:
                body = {"expected_revision": report["revision"], "normal_task_success": value,
                        "reviewer": reviewer.strip(), "reason": reason.strip()}
                token = core.digest([latest["evaluation_id"], body])
                body["request_id"] = "review-" + token[:24]
                new_report, error = core.request_report(trace, method="PUT", body=body, evaluation_id=latest["evaluation_id"])
                _save_result(state, new_report, error)
                st.rerun()
        return report
