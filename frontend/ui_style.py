"""보안바다 화면 공통 모양 (#72 화면 정리).

모양과 안내 글만 담당한다. 실행·판정 값은 바꾸지 않는다.
HTML은 한 줄로 만들어 st.markdown(unsafe_allow_html=True)로 넣는다 (빈 줄이 있으면 markdown으로 바뀜).
화면에 넣는 글자는 모두 esc()를 거친다.
"""
import html

import streamlit as st

BRAND = "보안바다"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800&display=swap');
:root{--ss-ink:#0F1B2D;--ss-sub:#4A5A6E;--ss-line:#D9E3EA;--ss-ground:#F6F9FB;--ss-teal:#0B6E79;--ss-teal-dark:#08505A;
--ss-teal-soft:#E3F2F3;--ss-orange:#9A3A0B;--ss-orange-soft:#FCEBDD;--ss-orange-line:#C2551A;--ss-red:#B42318;--ss-red-soft:#FDE8E7;
--ss-green:#11724A;--ss-green-soft:#E3F4EC;--ss-gray-soft:#EEF2F5;--ss-amber:#8A5A00;--ss-amber-soft:#FFF4D6;}
html, body, .stApp, .stMarkdown, button, input, textarea, select{font-family:'Noto Sans KR','Noto Sans CJK KR',system-ui,sans-serif;}
.stApp{background:var(--ss-ground);color:var(--ss-ink);}
.block-container{padding-top:4.2rem;max-width:1180px;}
[data-testid="stBaseButton-primary"]{background:var(--ss-teal);border-color:var(--ss-teal);border-radius:10px;font-weight:700;}
[data-testid="stBaseButton-primary"]:hover{background:var(--ss-teal-dark);border-color:var(--ss-teal-dark);}
[data-testid="stBaseButton-secondary"]{border-radius:10px;}
[data-testid="stPageLink"] a{border:1px solid var(--ss-line);border-radius:10px;background:#fff;padding:.35rem .8rem;}
[data-testid="stPageLink"] a:hover{border-color:var(--ss-teal);}
.ss-kicker{color:var(--ss-teal);font-weight:700;font-size:.95rem;letter-spacing:.02em;margin:0 0 .3rem;}
.ss-h1{font-size:2.2rem;line-height:1.3;font-weight:800;margin:0 0 .6rem;color:var(--ss-ink);}
.ss-h1 em{font-style:normal;color:var(--ss-orange-line);}
.ss-h2{font-size:1.35rem;font-weight:800;margin:1.6rem 0 .6rem;color:var(--ss-ink);}
.ss-lead{font-size:1.08rem;color:var(--ss-sub);line-height:1.7;margin:0 0 1rem;}
.ss-lead b{color:var(--ss-ink);}
.ss-hero{background:linear-gradient(135deg,#fff 0%,var(--ss-teal-soft) 100%);border:1px solid var(--ss-line);border-radius:20px;padding:2.2rem 2.4rem;margin-bottom:1.2rem;}
.ss-grid{display:grid;gap:14px;margin:.4rem 0 1rem;}
.ss-g2{grid-template-columns:repeat(2,minmax(0,1fr));}
.ss-g3{grid-template-columns:repeat(3,minmax(0,1fr));}
.ss-g4{grid-template-columns:repeat(4,minmax(0,1fr));}
.ss-g5{grid-template-columns:repeat(5,minmax(0,1fr));}
.ss-g6{grid-template-columns:repeat(6,minmax(0,1fr));}
@media (max-width:900px){.ss-g3,.ss-g4,.ss-g5,.ss-g6{grid-template-columns:repeat(2,minmax(0,1fr));}.ss-h1{font-size:1.7rem;}}
.ss-card{background:#fff;border:1px solid var(--ss-line);border-radius:14px;padding:1rem 1.1rem;}
.ss-card.on{border:2px solid var(--ss-teal);box-shadow:0 4px 14px rgba(11,110,121,.12);}
.ss-card.off{opacity:.62;}
.ss-card .t{font-weight:800;font-size:1.02rem;margin-bottom:.35rem;color:var(--ss-ink);}
.ss-card .d{color:var(--ss-sub);font-size:.92rem;line-height:1.6;}
.ss-card .q{color:var(--ss-ink);font-size:.92rem;background:var(--ss-gray-soft);border-radius:8px;padding:.45rem .6rem;margin:.4rem 0;}
.ss-card .k{display:block;color:var(--ss-teal);font-weight:700;font-size:.82rem;margin-top:.5rem;}
.ss-icon{font-size:1.6rem;line-height:1;margin-bottom:.5rem;display:block;}
.ss-tag{display:inline-block;font-size:.78rem;font-weight:700;border-radius:999px;padding:.12rem .55rem;background:var(--ss-teal);color:#fff;margin-bottom:.4rem;}
.ss-steps{display:flex;gap:8px;align-items:center;margin:.2rem 0 1.2rem;flex-wrap:wrap;}
.ss-steps .s{display:flex;align-items:center;gap:8px;color:var(--ss-sub);font-weight:600;font-size:.95rem;}
.ss-steps .n{width:26px;height:26px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;background:var(--ss-gray-soft);color:var(--ss-sub);font-weight:800;font-size:.85rem;}
.ss-steps .s.on{color:var(--ss-ink);}
.ss-steps .s.on .n{background:var(--ss-teal);color:#fff;}
.ss-steps .s.done .n{background:var(--ss-teal-soft);color:var(--ss-teal);}
.ss-steps .bar{width:36px;height:2px;background:var(--ss-line);}
.ss-big{font-size:1.65rem;font-weight:800;line-height:1.4;margin:.2rem 0 0;color:var(--ss-ink);}
.ss-big2{font-size:1.65rem;font-weight:800;line-height:1.4;margin:0 0 1rem;color:var(--ss-orange-line);}
table.ss-table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border:1px solid var(--ss-line);border-radius:14px;overflow:hidden;margin:.3rem 0 1rem;}
table.ss-table th{background:var(--ss-gray-soft);text-align:left;font-size:.9rem;color:var(--ss-sub);padding:.7rem .9rem;font-weight:700;}
table.ss-table td{padding:.8rem .9rem;border-top:1px solid var(--ss-line);font-size:.95rem;vertical-align:middle;color:var(--ss-ink);}
table.ss-table td.name{font-weight:800;white-space:nowrap;}
.ss-chip{display:inline-block;border-radius:999px;padding:.2rem .7rem;font-weight:800;font-size:.9rem;white-space:nowrap;}
.ss-chip.good{background:var(--ss-green-soft);color:var(--ss-green);}
.ss-chip.bad{background:var(--ss-red-soft);color:var(--ss-red);}
.ss-chip.na{background:var(--ss-gray-soft);color:var(--ss-sub);}
.ss-chip.pending{background:var(--ss-amber-soft);color:var(--ss-amber);}
.ss-chip.error{background:var(--ss-red-soft);color:var(--ss-red);border:1px dashed var(--ss-red);}
.ss-dark{background:var(--ss-ink);color:#fff;border-radius:14px;padding:1.1rem 1.3rem;margin:.4rem 0 1rem;}
.ss-dark .t{color:#9FD8DD;font-weight:700;font-size:.9rem;margin-bottom:.3rem;}
.ss-dark .d{font-size:1.02rem;line-height:1.7;}
.ss-info{background:var(--ss-teal-soft);border-radius:12px;padding:.8rem 1rem;color:var(--ss-ink);font-size:.95rem;line-height:1.6;margin:.2rem 0 1rem;}
.ss-info b{color:var(--ss-teal-dark);}
.ss-warn{background:var(--ss-orange-soft);border-radius:12px;padding:.8rem 1rem;color:var(--ss-orange);font-size:.95rem;line-height:1.6;margin:.2rem 0 1rem;}
.ss-flow{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:.4rem 0 1rem;}
@media (max-width:900px){.ss-flow{grid-template-columns:repeat(2,minmax(0,1fr));}}
.ss-flow .f{background:#fff;border:1px solid var(--ss-line);border-radius:12px;padding:.8rem .8rem;position:relative;}
.ss-flow .f .t{font-weight:800;font-size:.92rem;margin-bottom:.3rem;}
.ss-flow .f .d{font-size:.85rem;color:var(--ss-sub);line-height:1.5;}
.ss-flow .f.bad{border:2px solid var(--ss-orange-line);background:var(--ss-orange-soft);}
.ss-flow .f.good{border:2px solid var(--ss-teal);background:var(--ss-teal-soft);}
.ss-flow .f .h{display:inline-block;font-size:.72rem;font-weight:800;border-radius:999px;padding:.08rem .45rem;margin-bottom:.35rem;}
.ss-flow .f.bad .h{background:var(--ss-orange-line);color:#fff;}
.ss-flow .f.good .h{background:var(--ss-teal);color:#fff;}
.ss-map{display:flex;gap:10px;flex-wrap:wrap;align-items:stretch;margin:.4rem 0 1rem;}
.ss-map .m{background:#fff;border:1px solid var(--ss-line);border-radius:12px;padding:.7rem .9rem;min-width:150px;flex:1;}
.ss-map .m .t{font-weight:800;}
.ss-map .m .d{font-size:.85rem;color:var(--ss-sub);margin-top:.2rem;line-height:1.5;}
.ss-map .m.main{border:2px solid var(--ss-teal);}
.ss-figure{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:.3rem 0 .6rem;}
.ss-figure .box{background:#fff;border:1px solid var(--ss-line);border-radius:12px;padding:.8rem 1rem;flex:1;min-width:160px;}
.ss-figure .box.bad{border:2px solid var(--ss-orange-line);background:var(--ss-orange-soft);}
.ss-figure .box .t{font-weight:800;}
.ss-figure .box .d{font-size:.88rem;color:var(--ss-sub);margin-top:.2rem;}
.ss-figure .arrow{font-size:1.4rem;color:var(--ss-sub);}
.ss-foot{color:var(--ss-sub);font-size:.85rem;margin-top:1.4rem;}
</style>
"""

# 성적표 칸의 아이콘 (색만으로 뜻을 전하지 않도록 글자·아이콘을 함께 쓴다, #48)
CHIP_ICONS = {"good": "✓", "bad": "✗", "na": "—", "pending": "⏳", "error": "!"}

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


def esc(text):
    """HTML에 넣을 글자. markdown 수식·문법으로 바뀌지 않게 $, [, ], *, _ 도 막는다."""
    value = html.escape(str(text if text is not None else ""))
    return (value.replace("$", "&#36;").replace("[", "&#91;").replace("]", "&#93;")
            .replace("*", "&#42;").replace("_", "&#95;"))


def apply():
    """페이지마다 맨 위에서 한 번 부른다."""
    st.html(CSS)


def block(markup):
    """한 줄 HTML 조각을 화면에 넣는다."""
    st.markdown(" ".join(markup.split("\n")), unsafe_allow_html=True)


def chip(tone, text):
    return f'<span class="ss-chip {esc(tone)}">{CHIP_ICONS.get(tone, "")} {esc(text)}</span>'


def steps(labels, current):
    """1 · 2 · 3 단계 막대. current는 지금 단계 번호(1부터)."""
    parts = []
    for index, label in enumerate(labels, start=1):
        state = "on" if index == current else ("done" if index < current else "")
        if index > 1:
            parts.append('<span class="bar"></span>')
        parts.append(f'<span class="s {state}"><span class="n">{index}</span>{esc(label)}</span>')
    block(f'<div class="ss-steps">{"".join(parts)}</div>')


def link(page, label, icon=None, **kwargs):
    """다른 화면으로 가는 버튼. 테스트처럼 페이지 목록이 없는 실행에서는 글자 안내로 바꾼다."""
    try:
        st.page_link(page, label=label, icon=icon, **kwargs)
        return True
    except Exception:  # noqa: BLE001 — 페이지를 못 찾는 실행 환경(단독 실행·테스트)
        st.caption(f"메뉴에서 '{label}'을(를) 여세요.")
        return False


def detail_header(page):
    """자세히 비교하기 안의 화면 위쪽: 탭 5개 + '이 화면에서 보는 것' 한 줄."""
    apply()
    current = next((item for item in DETAIL_PAGES if item[0] == page), None)
    block(f'<div class="ss-kicker">자세히 비교하기 · {esc(BRAND)}</div>')
    columns = st.columns(len(DETAIL_PAGES))
    for column, (path, short, name, _) in zip(columns, DETAIL_PAGES):
        with column:
            if path == page:
                block(f'<div class="ss-card on" style="padding:.45rem .7rem"><div class="t" style="font-size:.9rem;margin:0">'
                      f'{esc(short)}</div><div class="d" style="font-size:.8rem">{esc(name)}</div></div>')
            else:
                try:
                    st.page_link(path, label=f"{short} · {name}")
                except Exception:  # noqa: BLE001
                    block(f'<div class="ss-card off" style="padding:.45rem .7rem"><div class="t" style="font-size:.9rem;margin:0">'
                          f'{esc(short)}</div><div class="d" style="font-size:.8rem">{esc(name)}</div></div>')
    if current:
        block(f'<div class="ss-info"><b>이 화면에서 보는 것</b> · {esc(current[3])}</div>')
