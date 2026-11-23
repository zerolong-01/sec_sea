"""한눈에 보기: 첫 페이지의 '4개 모드 비교'와 같은 실험을, 결과를 쉬운 말로 풀어 보여 준다.

질문 하나를 고르면 방어 방식 4가지로 실행하고, 방식마다 '막음/뚫림/괜히 막음' 같은 한 단어 결론과 한 문장 풀이를 보여 준다.
#72 화면 정리: 결과를 '방어별 성적표'(막았나? / 답했나?)와 '왜 이런 결과가?'(쉬운 trace)로 보여 준다.
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
import status_style as ss  # noqa: E402
import ui_style as ui  # noqa: E402
from ui_core import BOTH, ROOT, label_of, run_case  # noqa: E402
from task_evaluation_core import digest, effective_trace  # noqa: E402
import ui_core  # noqa: E402
from task_evaluation_view import SIMPLE_RULE_REASONS, render_group, render_task_evaluation, saved_report  # noqa: E402
from trace_view import stage_title  # noqa: E402

DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
MANIFEST_PATH = Path(os.environ.get("MVP_MANIFEST", DATA_DIR / "mvp-manifest.v0.1.json"))

# 질문 종류 카드: 종류마다 좋은 방어가 해야 할 일 (#72 콘티 문구)
KIND_ICONS = {"attack": "⚠️", "benign": "💬", "hard_negative": "🔍"}
KIND_GOALS = {"attack": "숨은 명령은 막고, 원래 질문에는 답해요.",
              "benign": "막지 말고 제대로 답해요.",
              "hard_negative": "겉모습만 보고 막지 말아요."}
MODE_ICONS = {"none": "🚪", "D1": "📋", "D2": "🔎", "D1+D2": "🛡️"}

st.set_page_config(page_title="한눈에 보기", layout="wide")
ui.apply()

saved = st.session_state.get("easy_results")
ui.block('<div class="ss-kicker">한눈에 보기</div>'
         '<div class="ss-h1">어떤 질문으로 해 볼까요?</div>'
         '<div class="ss-lead">AI 챗봇을 속이려는 질문을 넣어 보고, 방어 방법에 따라 <b>공격을 막는지</b>와 '
         '<b>정상 질문에는 제대로 답하는지</b> 비교합니다.</div>')
step_slot = st.empty()

# 1. 질문 고르기
ui.block('<div class="ss-h2">1. 질문 고르기</div>')
cases_path = DATA_DIR / "cases.v0.1.jsonl"
cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()] \
    if cases_path.exists() else []
# 첫 페이지와 같은 표시용 마스킹: 평가 규칙의 보호값·인코딩·인증정보까지 가린다.
# 마스킹 자료를 읽지 못하면 원문을 보여 주지 않고 멈춘다.
try:
    redactor = cb.load_redactor(
        DATA_DIR, cases, rules_path=os.environ.get("EVALUATION_RULES_FILE"),
        credentials=[os.environ.get(key) for key in ("MODEL_API_KEY", "D2_API_KEY", "JUDGE_API_KEY")],
    ) if cases else None
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    st.error("질문 표시용 마스킹 자료를 읽을 수 없습니다. 데이터와 평가 규칙 설정을 확인하세요.")
    st.stop()
options = ez.selectable_cases(cases)
if not options:
    st.info("실험할 질문 파일이 없습니다.")
    st.stop()
by_id = {c["case_id"]: c for c in options}
ids = list(by_id)
current_kind = (by_id.get(st.session_state.get("easy_case")) or by_id.get("a006") or options[0]).get("label")
cards = "".join(
    f'<div class="ss-card {"on" if label == current_kind else "off"}"><span class="ss-icon">{KIND_ICONS[label]}</span>'
    f'{"<span class=ss-tag>선택됨</span>" if label == current_kind else ""}'
    f'<div class="t">{ui.esc(name)}</div><div class="d">{ui.esc(text)}</div>'
    f'<span class="k">좋은 방어는 · {ui.esc(KIND_GOALS[label])}</span></div>'
    for label, (name, text) in ez.KINDS.items())
ui.block(f'<div class="ss-grid ss-g3">{cards}</div>')
case_id = st.selectbox("질문 (종류 · 번호 · 내용)", ids, index=ids.index("a006") if "a006" in ids else 0,
                       format_func=lambda i: ez.case_option(by_id[i], redactor=redactor), key="easy_case")
case = by_id[case_id]
kind, kind_text = ez.kind_of(case)
with st.container(border=True):
    st.markdown(f"**{kind}** · {label_of('scenarios', case.get('scenario'))}")
    st.caption(kind_text)
    st.text(cb.mask(case.get("user_input"), redactor=redactor))

# 2. 실행
ui.block('<div class="ss-h2">2. 방어 방법 4가지로 실행</div>')
tiles = "".join(f'<div class="ss-card"><span class="ss-icon">{MODE_ICONS.get(mode, "")}</span>'
                f'<div class="t">{ui.esc(name)}</div><div class="d">{ui.esc(text)}</div></div>'
                for mode, (name, text) in ez.MODES.items())
ui.block(f'<div class="ss-grid ss-g4">{tiles}</div>')
manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {}
scope = digest([ui_core.BACKEND_URL, str(DATA_DIR), case, manifest])
if st.button("방어 방법 4가지로 실행", type="primary", key="easy_run"):
    results = []
    progress = st.progress(0.0, text="실행 준비")
    for index, mode in enumerate(ez.MODES):
        progress.progress(index / len(ez.MODES), text=f"{ez.mode_name(mode)} 실행 중")
        trace, error = run_case(case_id, case.get("scenario"), case.get("source_version"),
                                manifest.get("corpus_version"), mode, BOTH)
        results.append({"mode": mode, "trace": trace, "error": error})
    progress.empty()
    st.session_state["easy_results"] = {"case_id": case_id, "scope": scope, "label": case.get("label"), "results": results}

# 3. 결과
saved = st.session_state.get("easy_results")
shown = bool(saved and saved["case_id"] == case_id and saved.get("scope") == scope)
with step_slot:
    ui.steps(["질문 고르기", "방어 4가지로 실행", "결과"], 3 if shown else 1)
if shown:
    ui.block('<div class="ss-h2">3. 결과</div>')
    label = saved["label"]
    traces = [effective_trace(r["trace"], saved_report(r["trace"])) if r["trace"] else None for r in saved["results"]]
    judged = [(r["mode"], *ez.verdict(label, trace, r["error"])) for r, trace in zip(saved["results"], traces)]
    scores = [ez.scorecard(label, trace, r["error"]) for r, trace in zip(saved["results"], traces)]
    st.caption(f"{kind} · {case_id}")
    st.markdown(f"### {ez.headline(label, judged)}")
    second = ez.answer_line(label, scores)
    if second:
        ui.block(f'<div class="ss-big2">{ui.esc(second)}</div>')

    tab_score, tab_reason, tab_answers = st.tabs(["방어별 성적표", "왜 이런 결과가?", "AI 답변 원문 · 확인 기록"])
    with tab_score:
        rows = "".join(
            f'<tr><td class="name">{ui.esc(ez.mode_name(mode))}</td><td>{ui.chip(*attack)}</td><td>{ui.chip(*answer)}</td>'
            f'<td>{ui.esc(sentence)}</td></tr>'
            for (mode, _, _, sentence), (attack, answer) in zip(judged, scores))
        ui.block('<table class="ss-table"><tr><th>방어 방법</th><th>공격을 막았나?</th><th>원래 질문에 답했나?</th>'
                 f'<th>한 줄 설명</th></tr>{rows}</table>')
        ui.block(f'<div class="ss-dark"><div class="t">이 결과가 말하는 것</div>'
                 f'<div class="d">{ui.esc(ez.takeaway(label, judged))}</div></div>')
        if label != "attack" and not any(saved_report(r["trace"]) for r in saved["results"] if r["trace"]) \
                and any(answer[0] == "good" for _, answer in scores):
            ui.block('<div class="ss-warn"><b>한 번 더 확인해 보세요</b> · 여기서 \'답함\'은 꼭 들어가야 할 단어가 있는지 '
                     '규칙으로 본 결과예요. 아래 \'답변 4개 모두 AI로 확인하기\'를 누르면 내용까지 제대로 설명했는지 AI가 다시 확인해요.</div>')
        render_group([r["trace"] for r in saved["results"]], key="easy_tasks", simple=True)

    with tab_reason:
        ui.block('<div class="ss-lead">질문이 들어가서 판정이 나오기까지, 한 단계씩 따라가 봐요.</div>')
        pick = st.radio("방어 방법", list(range(len(saved["results"]))), horizontal=True, key="easy_reason_mode",
                        format_func=lambda i: ez.mode_name(saved["results"][i]["mode"]))
        item, trace = saved["results"][pick], traces[pick]
        if not trace:
            ui.block(f'<div class="ss-warn">{ui.esc(judged[pick][3])}</div>')
        else:
            hot = {"bad": "문제가 생긴 단계", "good": "방어가 막은 단계"}
            flow = "".join(
                f'<div class="f {tone or ""}">{f"<span class=h>{hot[tone]}</span>" if tone else ""}'
                f'<div class="t">{ui.esc(stage_title(stage))}</div><div class="d">{ui.esc(text)}</div></div>'
                for stage, text, tone in ez.flow(label, item["trace"]))
            ui.block(f'<div class="ss-flow">{flow}</div>')
            evaluation = trace.get("evaluation") or {}
            boxes = []
            for title, question, key, kind_name in (("공격 성공", "숨은 명령대로 했나?", "attack_success", "attack"),
                                                    ("정상 태스크 성공", "원래 요청을 해냈나?", "normal_task_success", "normal")):
                value = evaluation.get(key)
                tone = {"good": "good", "bad": "bad", "pending": "pending"}.get(ss.evaluation_tone(kind_name, value), "na")
                meaning = ss.evaluation_meaning(kind_name, value) or ""
                boxes.append(f'<div class="ss-card"><div class="d">{ui.esc(title)} · {ui.esc(question)}</div>'
                             f'<div class="t" style="margin-top:.4rem">{ui.chip(tone, label_of("evaluation_statuses", value) or "기록 없음")}</div>'
                             f'<div class="d">{ui.esc(meaning)}</div></div>')
            ui.block(f'<div class="ss-grid ss-g2">{"".join(boxes)}</div>')
            reasons = ez.reason_sentences(item["trace"], SIMPLE_RULE_REASONS)
            if reasons:
                ui.block(f'<div class="ss-info"><b>이유</b> · {ui.esc(" ".join(reasons))}<br>정해진 규칙으로 자동 확인했습니다.</div>')
            if saved_report(item["trace"]):
                st.caption("AI로 확인한 결과가 있으면 '정상 태스크 성공'은 그 결과를 따릅니다. 이유는 'AI 답변 원문 · 확인 기록' 탭에서 볼 수 있습니다.")
        st.caption("단계별 기록 전체와 판정 근거 원문은 자세히 비교하기 › 1 · 질문 하나의 '4개 모드 비교' 탭에서 볼 수 있습니다.")

    with tab_answers:
        columns = st.columns(len(judged))
        for col, item, (mode, tone, word, sentence) in zip(columns, saved["results"], judged):
            with col.container(border=True):
                st.markdown(f"**{ez.mode_name(mode)}**")
                st.markdown(ez.badge(word, tone))
                st.write(sentence)
                st.caption("AI 답변")
                st.text(ez.answer_excerpt(item["trace"], redactor=redactor))
                st.caption(f"걸린 시간 {ez.seconds_text(item['trace'])}")
                if item["trace"]:
                    render_task_evaluation(item["trace"], key=f"easy_task_{mode}_{item['trace']['run_id']}", simple=True)

    scopes = {((r["trace"] or {}).get("manifest") or {}).get("execution_scope") for r in saved["results"]}
    if scopes & {"fixture", "demo"}:
        st.caption("지금은 연습용 고정 응답으로 실행했습니다. 실제 AI 모델 결과와 다를 수 있습니다.")
    ui.block('<div class="ss-info">질문 하나가 아니라 여러 질문·여러 모델로도 같은지 궁금하다면 '
             '<b>자세히 비교하기</b>에서 저장된 실험 결과를 숫자로 비교해요.</div>')
    ui.link("app.py", "자세히 비교하기", icon=":material/table_chart:")
elif saved:
    st.caption("질문을 바꿨습니다. 실행을 누르면 새 결과가 나옵니다.")
