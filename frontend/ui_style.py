"""보안바다 화면 공통 모양 (#72 화면 정리, 콘티 'Vb4JC49xDoKaHnZnsTPpW3'의 모양을 그대로 옮김).

모양과 안내 글만 담당한다. 실행·판정 값은 바꾸지 않는다.
- 고정 화면(홈·사용 안내)은 storyboard/*.html 을 그대로 보여 준다.
- 바뀌는 화면(한눈에 보기 등)은 아래 함수가 콘티와 같은 HTML을 만든다. 글자는 모두 esc()를 거친다.
"""
import base64
import hashlib
import html
import re
from pathlib import Path

import streamlit as st

BRAND = "보안바다"
STORYBOARD = Path(__file__).resolve().parent / "storyboard"
FONT = "font-family: 'Noto Sans KR', system-ui, sans-serif; color: #0F1B2D"

# 자세히 비교하기 탭 5개 (#72 영상 흐름: 단건 → 배치 → 모델 → 보고서 근거 → AI 판정)
DETAIL_PAGES = [
    ("app.py", "1 · 질문 하나", "방어 모드 실행 · trace 확인",
     "질문 하나를 골라 방어 모드별로 실행하고, 단계별 trace와 판정 근거를 모두 봅니다."),
    ("pages/1_배치_대시보드.py", "2 · 여러 질문", "배치 대시보드",
     "미리 실행해 저장한 여러 질문의 결과를 숫자로 비교합니다. 이 화면은 모델을 호출하지 않습니다."),
    ("pages/4_모델_비교.py", "3 · 여러 모델", "모델 비교",
     "같은 질문·조건에서 AI 모델끼리 결과가 어떻게 다른지 저장된 실험으로 비교합니다."),
    ("pages/3_보고서_원본공격_비교.py", "4 · 보고서 사례", "보고서 원본 공격 비교",
     "최종 보고서에 쓴 원본 공격의 방어별 결과를 봅니다. 공격 목표 달성률이 같아도 업무 손실은 다릅니다."),
    ("pages/2_연구_판정_보기.py", "5 · AI 판정", "연구 판정 보기",
     "AI가 내린 연구 판정을 원래 자동 평가와 따로 봅니다. 사람이 확인한 결과는 아닙니다."),
]

_TAB_CSS = "".join(
    f'.st-key-ss_detail_tabs [data-testid="stColumn"]:nth-child({i}) [data-testid="stPageLink"] a::before'
    f'{{content:"{short}";display:block;font-size:13px;color:#64748B;font-weight:400;margin-bottom:4px}}'
    for i, (_, short, _, _) in enumerate(DETAIL_PAGES, start=1))

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800&display=swap');
html, body, .stApp, .stMarkdown, button, input, textarea, select{font-family:'Noto Sans KR',system-ui,sans-serif;}
.stApp{background:#F6F9FB;color:#0F1B2D;}
header[data-testid="stHeader"]{background:#FFFFFF;border-bottom:1px solid #E2E8F0;}
.block-container{padding-top:5rem;max-width:1200px;}
[data-testid="stBaseButton-primary"]{background:#0B6E79;border-color:#0B6E79;border-radius:12px;font-weight:700;}
[data-testid="stBaseButton-primary"]:hover{background:#08505A;border-color:#08505A;color:#FFFFFF;}
[data-testid="stBaseButton-secondary"]{border-radius:12px;border-color:#CBD5E1;background:#FFFFFF;}
.st-key-easy_run button{padding:18px 30px;font-size:18px;border-radius:14px;}
.st-key-easy_run button p{font-size:18px;font-weight:700;}
.st-key-easy_go_reason button, .st-key-easy_back button, .st-key-easy_again button{padding:18px 22px;border-radius:16px;justify-content:flex-start;text-align:left;}
.st-key-easy_go_reason button p, .st-key-easy_back button p, .st-key-easy_again button p{font-size:17px;font-weight:700;}
.st-key-ss_detail_tabs [data-testid="stPageLink"] a{display:block;border:1px solid #CBD5E1;border-radius:14px;background:#FFFFFF;padding:14px 16px;}
.st-key-ss_detail_tabs [data-testid="stPageLink"] a:hover{border-color:#0B6E79;}
.st-key-ss_detail_tabs [data-testid="stPageLink"] p{font-size:15px;font-weight:700;color:#0F1B2D;}
[data-testid="stHeading"] h1{font-size:28px;font-weight:800;letter-spacing:-0.3px;color:#0F1B2D;}
[data-testid="stHeading"] h2{font-size:22px;font-weight:800;color:#0F1B2D;}
[data-testid="stHeading"] h3{font-size:19px;font-weight:800;color:#0F1B2D;}
[data-testid="stCaptionContainer"]{color:#64748B;}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:18px;}
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]){background:#FFFFFF;border-color:#E2E8F0;}
[data-baseweb="tab-list"]{gap:8px;flex-wrap:wrap;}
button[data-baseweb="tab"]{background:#FFFFFF;border:1px solid #CBD5E1;border-radius:12px;padding:10px 18px;height:auto;}
button[data-baseweb="tab"] p{font-size:15px;font-weight:600;color:#0F1B2D;}
button[data-baseweb="tab"][aria-selected="true"]{background:#E3F2F3;border:2px solid #0B6E79;}
button[data-baseweb="tab"][aria-selected="true"] p{color:#08505A;font-weight:800;}
[data-baseweb="tab-highlight"],[data-baseweb="tab-border"]{display:none;}
[data-testid="stExpander"] details{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:16px;}
[data-testid="stExpander"] summary p{font-weight:700;}
[data-testid="stAlert"]{border-radius:16px;}
[data-testid="stDataFrame"], [data-testid="stTable"]{border:1px solid #E2E8F0;border-radius:14px;overflow:hidden;background:#FFFFFF;}
[data-testid="stMetric"]{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:16px;padding:16px 18px;}
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="textarea"]{border-radius:12px;background:#FFFFFF;}
[data-testid="stSidebar"]{background:#FFFFFF;border-right:1px solid #E2E8F0;}
[data-testid="stCode"] pre, [data-testid="stText"]{border-radius:12px;}
.st-key-easy_reason_mode [role="radiogroup"]{gap:8px;flex-wrap:wrap;}
.st-key-easy_reason_mode [role="radiogroup"] label{border:1px solid #CBD5E1;border-radius:12px;padding:10px 16px;background:#FFFFFF;margin:0;}
.st-key-easy_reason_mode [role="radiogroup"] label:has(input:checked){border:2px solid #0B6E79;background:#E3F2F3;}
[class*="st-key-easy_kind_"] button{border-radius:12px;}
[class*="st-key-ss_link"] [data-testid="stPageLink"] a{border:1px solid #CBD5E1;border-radius:12px;background:#FFFFFF;padding:10px 16px;}
""" + _TAB_CSS + """
</style>
"""

# 성적표 표시 (콘티 ⑦ 성적표 표시 5가지)
CHIP_STYLE = {"good": ("#D5EEF0", "#08505A", ""), "bad": ("#FCEBDD", "#9A3A0B", ""),
              "na": ("#EEF2F7", "#475569", ""), "pending": ("#FFF4DC", "#7A4A06", ""),
              "error": ("#FDE8E7", "#B42318", "border: 1px dashed #B42318;")}
_ICON = {
    "check": '<path d="M5 12.5 L10 17 L19 7"/>',
    "x": '<path d="M6 6 L18 18 M18 6 L6 18"/>',
    "dash": '<path d="M6 12 H18"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 8 V12 L15 14"/>',
    "alert": '<path d="M12 7 V13 M12 16.5 V16.6"/><circle cx="12" cy="12" r="9"/>',
}
CHIP_ICON = {"good": "check", "bad": "x", "na": "dash", "pending": "clock", "error": "alert"}

# 콘티의 선 아이콘 (svg 안쪽만)
ICONS = {
    "attack": ('<path d="M12 3 L22 20 H2 Z"/><path d="M12 10 V14 M12 16.8 V17"/>', "#9A3A0B", "#FCEBDD"),
    "benign": ('<path d="M4 5 H20 V16 H11 L6 20 V16 H4 Z"/>', "#0B6E79", "#E3F2F3"),
    "hard_negative": ('<path d="M3 6 L12 3 L21 6 V12 C21 17 16.5 20 12 21 C7.5 20 3 17 3 12 Z"/>'
                      '<path d="M9.5 10 C9.5 8.5 10.6 7.5 12 7.5 C13.4 7.5 14.5 8.5 14.5 9.8 C14.5 11.5 12 11.8 12 13.5 M12 15.8 V16"/>',
                      "#5B21B6", "#EDE9FE"),
    "none": ('<circle cx="12" cy="12" r="8"/><path d="M6.5 6.5 L17.5 17.5"/>', "#64748B", "#EEF2F7"),
    "rule": ('<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4 V3 H15 V4 M8.5 10 H15.5 M8.5 14 H13"/>', "#0B6E79", "#E3F2F3"),
    "scan": ('<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15 L20 20"/>', "#0B6E79", "#E3F2F3"),
    "person": ('<circle cx="12" cy="8" r="4"/><path d="M4 21 C4 16.5 7.5 14 12 14 C16.5 14 20 16.5 20 21"/>', "#0F1B2D", "#EEF2F7"),
    "doc": ('<path d="M6 3 H14 L19 8 V21 H6 Z"/><path d="M14 3 V8 H19"/>', "#0F1B2D", "#EEF2F7"),
    "layers": ('<rect x="4" y="4" width="16" height="5" rx="1.5"/><rect x="4" y="10.5" width="16" height="4" rx="1.5"/>'
               '<rect x="4" y="16" width="16" height="4" rx="1.5"/>', "#0F1B2D", "#EEF2F7"),
    "shield": ('<path d="M12 3 L20 7 V12 C20 17 16.5 20 12 21 C7.5 20 4 17 4 12 V7 Z"/>', "#0F1B2D", "#EEF2F7"),
    "chat": ('<path d="M4 5 H20 V16 H11 L6 20 V16 H4 Z"/>', "#0F1B2D", "#EEF2F7"),
    "judge": ('<path d="M12 3 L20 7 V12 C20 17 16.5 20 12 21 C7.5 20 4 17 4 12 V7 Z"/><path d="M8.5 12 L11 14.5 L15.5 10"/>',
              "#7DD3DB", "#1B2A40"),
    "bulb": ('<path d="M9 18 H15 M10 21 H14"/><path d="M12 3 C8.5 3 6 5.6 6 8.8 C6 11 7.2 12.6 8.6 13.8 C9.2 14.3 9.5 15 9.5 15.6 '
             'V16 H14.5 V15.6 C14.5 15 14.8 14.3 15.4 13.8 C16.8 12.6 18 11 18 8.8 C18 5.6 15.5 3 12 3 Z"/>', "#7DD3DB", "#1B2A40"),
    "info": ('<circle cx="12" cy="12" r="9"/><path d="M12 11 V16 M12 8 V8.1"/>', "#08505A", "#E3F2F3"),
}
MODE_ICONS = {"none": ["none"], "D1": ["rule"], "D2": ["scan"], "D1+D2": ["rule", "scan"]}
STAGE_ICONS = {"input": "person", "retrieval": "doc", "prompt_assembly": "layers", "defense_events": "shield",
               "output": "chat", "evaluation": "judge"}


def esc(text):
    """HTML에 넣을 글자."""
    return html.escape(str(text if text is not None else ""))


def apply():
    """페이지마다 맨 위에서 한 번 부른다."""
    st.html(CSS)


_SVG = re.compile(r"<svg\b([^>]*)>(.*?)</svg>", re.S)


def _svg_to_img(match):
    """st.html은 <svg>를 지우므로 아이콘을 같은 모양의 <img>(data URI)로 바꿔 넣는다."""
    attrs, inner = match.group(1), match.group(2)
    if "xmlns=" not in attrs:
        attrs = ' xmlns="http://www.w3.org/2000/svg"' + attrs
    width = re.search(r'\bwidth="([^"]+)"', attrs)
    height = re.search(r'\bheight="([^"]+)"', attrs)
    style = re.search(r'\bstyle="([^"]+)"', attrs)
    data = base64.b64encode(f"<svg{attrs}>{inner}</svg>".encode("utf-8")).decode("ascii")
    size = "".join(f' {k}="{v.group(1)}"' for k, v in (("width", width), ("height", height)) if v)
    extra = f' style="{style.group(1)}"' if style else ' style="display: block"'
    return f'<img alt="" src="data:image/svg+xml;base64,{data}"{size}{extra}>'


def _html(markup):
    st.html(_SVG.sub(_svg_to_img, markup))


def show(markup):
    """콘티 모양 HTML 조각을 그대로 화면에 넣는다."""
    _html(f'<div style="{FONT}">{markup}</div>')


def storyboard(name):
    """홈·사용 안내처럼 바뀌지 않는 화면은 콘티 HTML 파일을 그대로 보여 준다."""
    _html((STORYBOARD / name).read_text(encoding="utf-8"))


def svg(name, size=24, stroke=None, width=1.8):
    path, color, _ = ICONS[name]
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{stroke or color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{path}</svg>')


def icon_box(name, box=56, size=30, radius=16, bg=None, stroke=None):
    _, _, background = ICONS[name]
    return (f'<div style="width: {box}px; height: {box}px; border-radius: {radius}px; background: {bg or background}; '
            f'display: flex; align-items: center; justify-content: center; flex: 0 0 auto">{svg(name, size, stroke)}</div>')


def chip(tone, text):
    bg, fg, extra = CHIP_STYLE.get(tone, CHIP_STYLE["na"])
    mark = (f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{fg}" stroke-width="3" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICON[CHIP_ICON.get(tone, "dash")]}</svg>')
    return (f'<span style="display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 999px; '
            f'background: {bg}; color: {fg}; font-weight: 700; white-space: nowrap; {extra}">{mark}{esc(text)}</span>')


def steps(labels, current):
    """콘티의 1 · 2 · 3 단계 알약. current는 지금 단계 번호(1부터). 지난 단계는 체크 표시."""
    check = ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5 L10 17 L19 7"/></svg>')
    parts = []
    for index, label in enumerate(labels, start=1):
        if index > 1:
            line = "#0B6E79" if index <= current else "#CBD5E1"
            parts.append(f'<li style="width: 24px; height: 2px; background: {line}" aria-hidden="true"></li>')
        dot = "width: 24px; height: 24px; border-radius: 12px; display: inline-flex; align-items: center; justify-content: center; font-size: 14px"
        if index == current:
            parts.append(f'<li style="display: flex; align-items: center; gap: 8px; padding: 10px 16px; border-radius: 999px; '
                         f'background: #0B6E79; color: #FFFFFF; font-weight: 700; font-size: 16px">'
                         f'<span style="{dot}; background: #FFFFFF; color: #0B6E79">{index}</span>{esc(label)}</li>')
        elif index < current:
            parts.append(f'<li style="display: flex; align-items: center; gap: 8px; padding: 10px 16px; border-radius: 999px; '
                         f'background: #E3F2F3; color: #08505A; font-size: 16px">'
                         f'<span style="{dot}; background: #0B6E79">{check}</span>{esc(label)}</li>')
        else:
            parts.append(f'<li style="display: flex; align-items: center; gap: 8px; padding: 10px 16px; border-radius: 999px; '
                         f'background: #FFFFFF; border: 1px solid #CBD5E1; color: #475569; font-size: 16px">'
                         f'<span style="{dot}; background: #E2E8F0">{index}</span>{esc(label)}</li>')
    show('<ol style="list-style: none; margin: 0 0 8px; padding: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 10px" '
         f'aria-label="실습 단계">{"".join(parts)}</ol>')


def heading(title, lead=None, size=36):
    text = f'<p style="margin: 0; font-size: 18px; color: #475569; line-height: 1.7">{lead}</p>' if lead else ""
    show(f'<div style="display: flex; flex-direction: column; gap: 8px; margin: 8px 0 4px">'
         f'<h1 style="margin: 0; font-size: {size}px; font-weight: 800; line-height: 1.35">{esc(title)}</h1>{text}</div>')


def section_title(title):
    show(f'<h2 style="margin: 20px 0 4px; font-size: 22px; font-weight: 800">{esc(title)}</h2>')


def info(label, text):
    show('<div style="background: #E3F2F3; border-radius: 16px; padding: 16px 20px; display: flex; gap: 14px; align-items: flex-start; margin: 4px 0 8px">'
         f'{svg("info", 24)}<div style="font-size: 16px; line-height: 1.7; color: #08505A"><b>{esc(label)}</b> · {esc(text)}</div></div>')


def note(title, text):
    show('<div style="background: #FFF6EE; border: 1px solid #F3C9A6; border-radius: 16px; padding: 16px 20px; font-size: 15px; '
         f'line-height: 1.7; color: #7A2E08"><b>{esc(title)}</b> · {esc(text)}</div>')


def dark(title, text):
    """콘티 '이 결과가 말하는 것' 검은 상자."""
    show('<div style="background: #0F1B2D; color: #FFFFFF; border-radius: 22px; padding: 28px 32px; display: flex; gap: 20px; align-items: flex-start">'
         f'{icon_box("bulb", box=48, size=26, radius=14)}<div style="display: flex; flex-direction: column; gap: 6px">'
         f'<div style="font-size: 15px; font-weight: 700; color: #7DD3DB">{esc(title)}</div>'
         f'<div style="font-size: 19px; font-weight: 700; line-height: 1.7">{esc(text)}</div></div></div>')


def link(page, label, icon=None):
    """다른 화면으로 가는 버튼. 페이지 목록이 없는 실행(단독 실행·테스트)에서는 글자 안내로 바꾼다."""
    key = "ss_link_" + hashlib.md5(f"{page}|{label}".encode("utf-8")).hexdigest()[:8]
    with st.container(key=key):
        try:
            st.page_link(page, label=label, icon=icon)
            return True
        except Exception:  # noqa: BLE001 — 페이지를 못 찾는 실행 환경
            st.caption(f"메뉴에서 '{label}'을(를) 여세요.")
            return False


def detail_header(page):
    """자세히 비교하기 안의 화면 위쪽: 콘티 ⑤의 제목, 탭 5개, '이 탭에서 보는 것'."""
    apply()
    current = next((item for item in DETAIL_PAGES if item[0] == page), None)
    heading("자세히 비교하기", "여러 질문·여러 모델의 결과를 숫자로 비교하고, 하나하나의 근거와 CSV까지 확인하는 곳이에요.", size=30)
    with st.container(key="ss_detail_tabs"):
        columns = st.columns(len(DETAIL_PAGES))
        for column, (path, short, name, _) in zip(columns, DETAIL_PAGES):
            with column:
                selected = path == page
                if not selected:
                    try:
                        st.page_link(path, label=name)
                        continue
                    except Exception:  # noqa: BLE001
                        pass
                border, background, color = (("2px solid #0B6E79", "#E3F2F3", "#08505A") if selected
                                             else ("1px solid #CBD5E1", "#FFFFFF", "#0F1B2D"))
                show(f'<div style="padding: 14px 16px; border-radius: 14px; border: {border}; background: {background}; color: {color}; '
                     f'display: flex; flex-direction: column; gap: 4px"><span style="font-size: 13px">{esc(short)}</span>'
                     f'<b style="font-size: 15px">{esc(name)}</b></div>')
    if current:
        info("이 탭에서 보는 것", current[3])
