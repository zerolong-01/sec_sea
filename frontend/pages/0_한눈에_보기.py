"""한눈에 보기: 첫 페이지의 '4개 모드 비교'와 같은 실험을, 결과를 쉬운 말로 풀어 보여 준다.

질문 하나를 고르면 방어 방식 4가지로 실행하고, 방식마다 '막음/뚫림/괜히 막음' 같은 한 단어 결론과 한 문장 풀이를 보여 준다.
판정은 서버 trace의 값을 그대로 옮긴다 (easy_core).
"""
import json
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import case_browser as cb  # noqa: E402
import easy_core as ez  # noqa: E402
from ui_core import BOTH, ROOT, label_of, run_case  # noqa: E402

DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
MANIFEST_PATH = Path(os.environ.get("MVP_MANIFEST", DATA_DIR / "mvp-manifest.v0.1.json"))

st.set_page_config(page_title="한눈에 보기", layout="wide")
st.title("한눈에 보기")
st.write("AI 챗봇을 속이려는 질문을 넣어 보고, 방어 방법에 따라 **공격을 막는지**와 **정상 질문에는 제대로 답하는지** 비교합니다.")

st.subheader("방어 방법")
st.dataframe([{"방어 방법": name, "설명": text} for name, text in ez.MODES.values()], hide_index=True)

# 1. 질문 고르기
st.subheader("1. 질문 고르기")
cases_path = DATA_DIR / "cases.v0.1.jsonl"
cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()] \
    if cases_path.exists() else []
options = ez.selectable_cases(cases)
if not options:
    st.info("실험할 질문 파일이 없습니다.")
    st.stop()
by_id = {c["case_id"]: c for c in options}
ids = list(by_id)
case_id = st.selectbox("질문", ids, index=ids.index("a006") if "a006" in ids else 0,
                       format_func=lambda i: ez.case_option(by_id[i]), key="easy_case")
case = by_id[case_id]
kind, kind_text = ez.kind_of(case)
with st.container(border=True):
    st.markdown(f"**{kind}** · {label_of('scenarios', case.get('scenario'))}")
    st.caption(kind_text)
    st.write(cb.mask(case.get("user_input")))

# 2. 실행
st.subheader("2. 방어 방법 4가지로 실행")
manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {}
if st.button("실행", type="primary", key="easy_run"):
    results = []
    progress = st.progress(0.0, text="실행 준비")
    for index, mode in enumerate(ez.MODES):
        progress.progress(index / len(ez.MODES), text=f"{ez.mode_name(mode)} 실행 중")
        trace, error = run_case(case_id, case.get("scenario"), case.get("source_version"),
                                manifest.get("corpus_version"), mode, BOTH)
        results.append({"mode": mode, "trace": trace, "error": error})
    progress.empty()
    st.session_state["easy_results"] = {"case_id": case_id, "label": case.get("label"), "results": results}

# 3. 결과
saved = st.session_state.get("easy_results")
if saved and saved["case_id"] == case_id:
    st.subheader("3. 결과")
    judged = [(r["mode"], *ez.verdict(saved["label"], r["trace"], r["error"])) for r in saved["results"]]
    with st.container(border=True):
        st.markdown(f"**{ez.headline(saved['label'], judged)}**")
        st.write(ez.takeaway(saved["label"], judged))
    columns = st.columns(len(judged))
    for col, item, (mode, tone, word, sentence) in zip(columns, saved["results"], judged):
        with col.container(border=True):
            st.markdown(f"**{ez.mode_name(mode)}**")
            st.markdown(ez.badge(word, tone))
            st.write(sentence)
            st.caption("AI 답변")
            st.text(ez.answer_excerpt(item["trace"]))
            st.caption(f"걸린 시간 {ez.seconds_text(item['trace'])}")
    scopes = {((r["trace"] or {}).get("manifest") or {}).get("execution_scope") for r in saved["results"]}
    if scopes & {"fixture", "demo"}:
        st.caption("지금은 연습용 고정 응답으로 실행했습니다. 실제 AI 모델 결과와 다를 수 있습니다.")
    st.caption("단계별 기록과 판정 근거는 첫 페이지의 '4개 모드 비교' 탭에서 볼 수 있습니다.")
elif saved:
    st.caption("질문을 바꿨습니다. 실행을 누르면 새 결과가 나옵니다.")
