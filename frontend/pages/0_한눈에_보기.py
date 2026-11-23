"""한눈에 보기: 첫 페이지의 '4개 모드 비교'와 같은 실험을, 결과를 쉬운 말로 풀어 보여 준다.

#72 화면 정리: 콘티 ②~④의 모양을 그대로 옮겼다.
1. 질문 고르기(종류 카드) → 2. 방어 4가지로 실행 → 3. 결과(방어별 성적표) → 왜 이런 결과가?(쉬운 trace)
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
STEPS = ["질문 고르기", "방어 4가지로 실행", "결과"]

# 질문 종류 카드: 종류마다 좋은 방어가 해야 할 일 (콘티 ② 문구)
KIND_GOALS = {"attack": "숨은 명령은 막고, 원래 질문에는 답해요.",
              "benign": "막지 말고 제대로 답해요.",
              "hard_negative": "겉모습만 보고 막지 말아요."}
TONE_BOX = {"bad": ("#FCEBDD", "#9A3A0B"), "good": ("#E3F2F3", "#08505A"),
            "pending": ("#FFF4DC", "#7A4A06"), "neutral": ("#EEF2F7", "#475569")}


def pick_case(case_id):
    """종류 카드의 버튼: 그 종류의 질문을 고르고 이전 결과 보기 상태를 처음으로 돌린다."""
    st.session_state["easy_case"] = case_id
    st.session_state["easy_view"] = "result"


def set_view(view):
    st.session_state["easy_view"] = view


def start_over():
    st.session_state.pop("easy_results", None)
    st.session_state["easy_view"] = "result"


st.set_page_config(page_title="한눈에 보기", layout="wide")
ui.apply()
step_slot = st.empty()
ui.heading("어떤 질문으로 해 볼까요?", "카드 하나를 고르세요. 질문마다 좋은 방어가 해야 할 일이 달라요.")

# 1. 질문 고르기
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
chosen = by_id.get(st.session_state.get("easy_case")) or by_id.get("a006") or options[0]
first_of = {}
for item in options:
    first_of.setdefault(item.get("label"), item)
first_of[chosen.get("label")] = chosen

columns = st.columns(len(ez.KINDS))
for column, (label, (name, _)) in zip(columns, ez.KINDS.items()):
    example = first_of.get(label)
    selected = example is chosen
    with column:
        border = ("border: 2px solid #0B6E79; box-shadow: 0 14px 32px rgba(11,110,121,0.12)" if selected
                  else "border: 1px solid #E2E8F0")
        badge = ('<span style="display: flex; align-items: center; gap: 6px; font-size: 14px; color: #0B6E79; font-weight: 700">'
                 '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0B6E79" stroke-width="2.6" stroke-linecap="round" '
                 'stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5 L10 17 L19 7"/></svg>선택됨</span>') if selected else ""
        quote = f'"{ui.esc(cb.summary(example, 60, redactor=redactor))}"' if example else "이 종류의 질문이 없습니다."
        ui.show(f'<div style="background: #FFFFFF; {border}; border-radius: 22px; padding: 26px; display: flex; flex-direction: column; '
                f'gap: 16px; min-height: 290px">'
                f'<div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px">{ui.icon_box(label)}{badge}</div>'
                f'<div style="font-size: 22px; font-weight: 800">{ui.esc(name)}</div>'
                f'<div style="font-size: 17px; line-height: 1.55; background: #F8FAFC; border-radius: 12px; padding: 14px">{quote}</div>'
                f'<div style="display: flex; gap: 10px; align-items: flex-start; font-size: 15px; line-height: 1.6; color: #334155">'
                f'<b style="flex: 0 0 auto; color: #0B6E79">좋은 방어는</b>{ui.esc(KIND_GOALS[label])}</div></div>')
        if example and not selected:
            st.button(f"{name}로 해 보기", key=f"easy_kind_{label}", on_click=pick_case, args=(example["case_id"],),
                      use_container_width=True)

case_id = st.selectbox("같은 종류의 다른 질문 고르기 (종류 · 번호 · 내용)", ids, index=ids.index("a006") if "a006" in ids else 0,
                       format_func=lambda i: ez.case_option(by_id[i], redactor=redactor), key="easy_case")
case = by_id[case_id]
kind, kind_text = ez.kind_of(case)
with st.container(border=True):
    st.markdown(f"**{kind}** · {label_of('scenarios', case.get('scenario'))}")
    st.caption(kind_text)
    st.text(cb.mask(case.get("user_input"), redactor=redactor))

# 2. 실행
ui.section_title("비교할 방어 방법 4가지")
tiles = "".join(
    '<div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 18px; padding: 20px; display: flex; flex-direction: column; gap: 12px">'
    f'<div style="display: flex; gap: 6px">{"".join(ui.icon_box(i, box=48, size=26 if len(ui.MODE_ICONS[mode]) == 1 else 24, radius=14) for i in ui.MODE_ICONS[mode])}</div>'
    f'<div style="font-size: 18px; font-weight: 800">{ui.esc(name)}</div>'
    f'<div style="font-size: 15px; line-height: 1.6; color: #475569">{ui.esc(text)}</div></div>'
    for mode, (name, text) in ez.MODES.items())
ui.show(f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px">{tiles}</div>')
manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {}
scope = digest([ui_core.BACKEND_URL, str(DATA_DIR), case, manifest])
if st.button("방어 방법 4가지로 실행 →", type="primary", key="easy_run"):
    results = []
    progress = st.progress(0.0, text="실행 준비")
    for index, mode in enumerate(ez.MODES):
        progress.progress(index / len(ez.MODES), text=f"{ez.mode_name(mode)} 실행 중")
        trace, error = run_case(case_id, case.get("scenario"), case.get("source_version"),
                                manifest.get("corpus_version"), mode, BOTH)
        results.append({"mode": mode, "trace": trace, "error": error})
    progress.empty()
    st.session_state["easy_results"] = {"case_id": case_id, "scope": scope, "label": case.get("label"), "results": results}
    st.session_state["easy_view"] = "result"

# 3. 결과
saved = st.session_state.get("easy_results")
shown = bool(saved and saved["case_id"] == case_id and saved.get("scope") == scope)
with step_slot:
    ui.steps(STEPS, 3 if shown else 1)


def render_result_view(saved, traces, judged, scores):
    """콘티 ③ 결과: 한 줄 결론 → 방어별 성적표 → 이 결과가 말하는 것 → 다음 할 일."""
    label = saved["label"]
    ui.show(f'<div style="font-size: 15px; color: #64748B; margin-top: 24px">{ui.esc(kind)} · '
            f'"{ui.esc(cb.summary(case, 60, redactor=redactor))}"</div>')
    second = ez.answer_line(label, scores)
    tail = f'<br><span style="color: #9A3A0B">{ui.esc(second)}</span>' if second else ""
    st.markdown(f'<div style="font-size: 30px; line-height: 1.45; font-weight: 800; margin: 4px 0 8px">'
                f'{ui.esc(ez.headline(label, judged))}{tail}</div>', unsafe_allow_html=True)

    rows = []
    for (mode, _, _, sentence), (attack, answer) in zip(judged, scores):
        best = attack[0] in ("good", "na") and answer[0] == "good"
        rows.append(f'<tr style="border-top: 1px solid #E2E8F0{"; background: #F2FAFA" if best else ""}">'
                    f'<th scope="row" style="padding: 20px 24px; text-align: left; font-size: 17px">{ui.esc(ez.mode_name(mode))}</th>'
                    f'<td style="padding: 20px 16px; text-align: center">{ui.chip(*attack)}</td>'
                    f'<td style="padding: 20px 16px; text-align: center">{ui.chip(*answer)}</td>'
                    f'<td style="padding: 20px 24px; font-size: 15px; line-height: 1.6; color: #334155">{ui.esc(sentence)}</td></tr>')
    head = "".join(f'<th scope="col" style="padding: 12px {pad}; font-size: 14px; color: #475569; font-weight: 700; text-align: {align}">{t}</th>'
                   for t, pad, align in (("방어 방법", "24px", "left"), ("공격을 막았나?", "16px", "center"),
                                         ("원래 질문에 답했나?", "16px", "center"), ("한 줄 설명", "24px", "left")))
    ui.show('<div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 22px; overflow-x: auto">'
            '<table style="width: 100%; border-collapse: collapse; min-width: 760px">'
            '<caption style="text-align: left; padding: 20px 24px 8px; font-size: 18px; font-weight: 800">방어별 성적표</caption>'
            f'<thead><tr style="text-align: left">{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    ui.dark("이 결과가 말하는 것", ez.takeaway(label, judged))
    if label != "attack" and not any(saved_report(r["trace"]) for r in saved["results"] if r["trace"]) \
            and any(answer[0] == "good" for _, answer in scores):
        ui.note("한 번 더 확인해 보세요", "여기서 '답함'은 꼭 들어가야 할 단어가 있는지 규칙으로 본 결과예요. "
                "아래 '답변 4개 모두 AI로 확인하기'를 누르면 내용까지 제대로 설명했는지 AI가 다시 확인해요.")

    left, right = st.columns([1.4, 1])
    left.button("왜 그렇게 됐는지 보기 →  단계별 기록과 판정 근거", type="primary", key="easy_go_reason",
                on_click=set_view, args=("reason",), use_container_width=True)
    right.button("다른 질문으로 · 1단계로 돌아가기", key="easy_again", on_click=start_over, use_container_width=True)
    with st.container(border=True):
        ui.show('<div style="font-size: 18px; font-weight: 800">답변 4개 모두 AI로 확인하기</div>'
                '<div style="font-size: 14px; color: #64748B; margin-top: 4px">원래 요청을 해냈는지 AI가 한 번 더 확인해요.</div>')
        render_group([r["trace"] for r in saved["results"]], key="easy_tasks", simple=True)

    ui.section_title("AI 답변 원문 · 확인 기록")
    cols = st.columns(len(judged))
    for col, item, (mode, tone, word, sentence) in zip(cols, saved["results"], judged):
        with col.container(border=True):
            st.markdown(f"**{ez.mode_name(mode)}**")
            st.markdown(ez.badge(word, tone))
            st.write(sentence)
            st.caption("AI 답변")
            st.text(ez.answer_excerpt(item["trace"], redactor=redactor))
            st.caption(f"걸린 시간 {ez.seconds_text(item['trace'])}")
            if item["trace"]:
                render_task_evaluation(item["trace"], key=f"easy_task_{mode}_{item['trace']['run_id']}", simple=True)

    ui.show('<div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; padding: 18px 24px; '
            'border-radius: 16px; background: #EEF2F7; margin-top: 12px"><span style="font-size: 16px; line-height: 1.6">'
            '<b>질문 하나가 아니라 여러 질문·여러 모델로도 같은지 궁금하다면</b> — 저장된 실험 결과를 숫자로 비교해요</span></div>')
    ui.link("app.py", "자세히 비교하기 →")


def render_reason_view(saved, traces, judged):
    """콘티 ④ 왜 이런 결과가?: 처리 흐름 그림 → 판정 결과 두 칸 → 이유."""
    label = saved["label"]
    st.button("← 결과로 돌아가기", key="easy_back", on_click=set_view, args=("result",))
    ui.heading("왜 이런 결과가 나왔을까요?", "질문이 들어가서 판정이 나오기까지, 한 단계씩 따라가 봐요.", size=32)
    pick = st.radio("방어 방법", list(range(len(saved["results"]))), horizontal=True, key="easy_reason_mode",
                    format_func=lambda i: ez.mode_name(saved["results"][i]["mode"]), label_visibility="collapsed")
    item, trace = saved["results"][pick], traces[pick]
    if not trace:
        ui.note("실행 오류", judged[pick][3])
        return
    cards, tones = [], set()
    for stage, text, tone in ez.flow(label, item["trace"]):
        tones.add(tone)
        if stage == "evaluation":
            style, title_color = "background: #0F1B2D; color: #FFFFFF", "#7DD3DB"
            box = ui.icon_box("judge", box=44, size=24, radius=12)
        elif tone == "bad":
            style, title_color = "background: #FFF6EE; border: 2px solid #E08A4F", "#9A3A0B"
            box = ui.icon_box(ui.STAGE_ICONS[stage], box=44, size=24, radius=12, bg="#FCEBDD", stroke="#9A3A0B")
        elif tone == "good":
            style, title_color = "background: #F2FAFA; border: 2px solid #0B6E79", "#08505A"
            box = ui.icon_box(ui.STAGE_ICONS[stage], box=44, size=24, radius=12, bg="#E3F2F3", stroke="#0B6E79")
        else:
            style, title_color = "background: #F8FAFC; border: 1px solid #E2E8F0", "#64748B"
            box = ui.icon_box(ui.STAGE_ICONS[stage], box=44, size=24, radius=12)
        cards.append(f'<li style="flex: 1 1 150px; display: flex; flex-direction: column; gap: 10px; padding: 16px; border-radius: 16px; {style}">'
                     f'{box}<div style="font-size: 13px; color: {title_color}; font-weight: 700">{ui.esc(stage_title(stage))}</div>'
                     f'<div style="font-size: 15px; line-height: 1.5">{ui.esc(text)}</div></li>')
    legend = ""
    if "bad" in tones:
        legend += ('<span style="display: inline-flex; align-items: center; gap: 8px"><span style="width: 14px; height: 14px; border-radius: 4px; '
                   'border: 2px solid #E08A4F; background: #FFF6EE"></span>문제가 생긴 단계</span>')
    if "good" in tones:
        legend += ('<span style="display: inline-flex; align-items: center; gap: 8px; color: #08505A"><span style="width: 14px; height: 14px; '
                   'border-radius: 4px; border: 2px solid #0B6E79; background: #F2FAFA"></span>방어가 막은 단계</span>')
    ui.show('<figure style="margin: 0; background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 22px; padding: 28px; display: flex; '
            'flex-direction: column; gap: 20px"><figcaption style="font-size: 18px; font-weight: 800">처리 흐름</figcaption>'
            f'<ol style="list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; align-items: stretch; gap: 10px">{"".join(cards)}</ol>'
            f'<div style="display: flex; gap: 20px; font-size: 14px; color: #9A3A0B">{legend}</div></figure>')

    evaluation = trace.get("evaluation") or {}
    boxes = []
    for title, key, kind_name in (("공격 성공", "attack_success", "attack"), ("정상 태스크 성공", "normal_task_success", "normal")):
        value = evaluation.get(key)
        bg, fg = TONE_BOX.get(ss.evaluation_tone(kind_name, value), TONE_BOX["neutral"])
        meaning = ss.evaluation_meaning(kind_name, value) or ""
        boxes.append(f'<div style="border-radius: 16px; background: {bg}; padding: 18px; display: flex; flex-direction: column; gap: 6px">'
                     f'<div style="font-size: 14px; color: {fg}">{title}</div>'
                     f'<div style="font-size: 22px; font-weight: 800; color: {fg}">{ui.esc(label_of("evaluation_statuses", value) or "기록 없음")}</div>'
                     f'<div style="font-size: 14px; color: {fg}">{ui.esc(meaning)}</div></div>')
    reasons = ez.reason_sentences(item["trace"], SIMPLE_RULE_REASONS)
    reason = (f'<div style="display: flex; flex-direction: column; gap: 6px; border-top: 1px solid #E2E8F0; padding-top: 16px">'
              f'<div style="font-size: 14px; color: #64748B">이유</div>'
              f'<div style="font-size: 17px; line-height: 1.6; font-weight: 700">{ui.esc(" ".join(reasons))}</div>'
              '<div style="display: inline-flex; align-self: flex-start; padding: 6px 12px; border-radius: 999px; background: #EEF2F7; '
              'font-size: 14px; color: #334155">정해진 규칙으로 자동 확인했습니다.</div></div>') if reasons else ""
    legend_rows = "".join(f"<div><b>{a}</b> · {b}</div>" for a, b in (
        ("원래 요청을 잘 해냄", "성공"), ("원래 요청을 제대로 못 함", "실패"), ("사람 확인 필요", "검토 필요"),
        ("아직 확인 못 함", "미평가"), ("해당 없음", "평가할 대상이 없음")))
    ui.show('<div style="display: flex; flex-wrap: wrap; gap: 20px">'
            '<div style="flex: 2 1 520px; min-width: 0; background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 22px; padding: 28px; '
            'display: flex; flex-direction: column; gap: 18px"><div style="font-size: 18px; font-weight: 800">판정 결과</div>'
            f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px">{"".join(boxes)}</div>{reason}</div>'
            '<div style="flex: 1 1 300px; min-width: 0; display: flex; flex-direction: column; gap: 12px">'
            '<div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 22px; padding: 22px; display: flex; flex-direction: column; gap: 12px">'
            '<div style="font-size: 16px; font-weight: 800">판정은 두 가지를 따로 봐요</div>'
            '<div style="display: flex; gap: 10px; font-size: 15px; line-height: 1.6"><b>공격 성공</b><span style="color: #475569">숨은 명령대로 했나?</span></div>'
            '<div style="display: flex; gap: 10px; font-size: 15px; line-height: 1.6"><b>정상 태스크 성공</b><span style="color: #475569">원래 요청을 해냈나?</span></div></div>'
            '<details style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 16px; padding: 16px 20px">'
            '<summary style="font-weight: 700; cursor: pointer">판정 결과 읽는 법</summary>'
            f'<div style="padding-top: 12px; display: flex; flex-direction: column; gap: 8px; font-size: 14px; line-height: 1.6">{legend_rows}</div>'
            '</details></div></div>')
    if saved_report(item["trace"]):
        st.caption("AI로 확인한 결과가 있으면 '정상 태스크 성공'은 그 결과를 따릅니다. 이유는 결과 화면의 'AI 답변 원문 · 확인 기록'에서 볼 수 있습니다.")
    ui.info("전문가용 세부 정보", "판정 근거 원문·평가 버전·지연 시간·토큰·비용·모델 호출 기록은 자세히 비교하기 › 1 · 질문 하나의 '4개 모드 비교' 탭에서 볼 수 있어요.")


if shown:
    traces = [effective_trace(r["trace"], saved_report(r["trace"])) if r["trace"] else None for r in saved["results"]]
    judged = [(r["mode"], *ez.verdict(saved["label"], trace, r["error"])) for r, trace in zip(saved["results"], traces)]
    scores = [ez.scorecard(saved["label"], trace, r["error"]) for r, trace in zip(saved["results"], traces)]
    if st.session_state.get("easy_view") == "reason":
        render_reason_view(saved, traces, judged)
    else:
        render_result_view(saved, traces, judged, scores)
    scopes = {((r["trace"] or {}).get("manifest") or {}).get("execution_scope") for r in saved["results"]}
    if scopes & {"fixture", "demo"}:
        st.caption("지금은 연습용 고정 응답으로 실행했습니다. 실제 AI 모델 결과와 다를 수 있습니다.")
elif saved:
    st.caption("질문을 바꿨습니다. 실행을 누르면 새 결과가 나옵니다.")
