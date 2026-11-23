"""홈 (#72 화면 정리): 누가 쓰는지, 무엇을 넣으면 무엇이 나와 무엇을 말해 주는지 한 화면에 보여 준다.

이 화면은 소개만 한다. 실행·조회는 하지 않으므로 모델이나 서버를 부르지 않는다.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_style as ui  # noqa: E402

st.set_page_config(page_title="보안바다 · 홈", layout="wide")
ui.apply()

ui.block(
    '<div class="ss-hero">'
    '<div class="ss-kicker">한국어 LLM 보안 실습·비교 도구</div>'
    '<div class="ss-h1">공격을 막아도<br><em>원래 질문에 답하지 못하면</em><br>좋은 방어일까요?</div>'
    '<div class="ss-lead">같은 질문을 방어 방법 4가지로 실행해 보고, <b>막았는지</b>와 <b>제대로 답했는지</b>를 한 화면에서 비교해요.</div>'
    '</div>'
)
cta = st.columns([1.3, 1, 3])
with cta[0]:
    ui.link("pages/0_한눈에_보기.py", "질문 하나로 실습 시작하기", icon=":material/play_arrow:")
with cta[1]:
    ui.link("guide.py", "처음이라면 사용 안내", icon=":material/help:")

ui.block('<div class="ss-h2">프롬프트 인젝션이란?</div>')
ui.block(
    '<div class="ss-figure">'
    '<div class="box"><div class="t">사용자 질문</div><div class="d">"교육 일정 알려줘"</div></div>'
    '<div class="arrow">→</div>'
    '<div class="box"><div class="t">AI 챗봇</div><div class="d">문서를 찾아 읽고 답해요</div></div>'
    '<div class="arrow">→</div>'
    '<div class="box bad"><div class="t">명령을 따른 답변</div><div class="d">숨겨야 할 정보를 말하거나 엉뚱한 일을 함</div></div>'
    '</div>'
    '<div class="ss-warn">질문이나 AI가 읽는 <b>참고 문서에 숨은 명령</b>이 있으면, AI가 속아서 원래 지시 대신 그 명령을 따를 수 있어요. '
    '이것이 프롬프트 인젝션이에요.</div>'
)

ui.block('<div class="ss-h2">좋은 방어는 두 가지를 모두 해내야 해요</div>')
ui.block(
    '<div class="ss-grid ss-g2">'
    '<div class="ss-card"><span class="ss-icon">🛡️</span><div class="t">공격을 막았나?</div><div class="d">숨은 명령에 속지 않았는지</div></div>'
    '<div class="ss-card"><span class="ss-icon">💬</span><div class="t">원래 질문에 답했나?</div><div class="d">정상 질문까지 막지 않았는지</div></div>'
    '</div>'
    '<div class="ss-info">방어를 세게 걸면 공격은 줄지만 정상 답변까지 막힐 수 있어요. '
    f'<b>{ui.esc(ui.BRAND)}</b>는 두 가지를 따로, 함께 보여 줍니다.</div>'
)

ui.block('<div class="ss-h2">이렇게 사용해요</div>')
ui.block(
    '<div class="ss-grid ss-g3">'
    '<div class="ss-card"><span class="ss-tag">1단계</span><div class="t">질문 고르기</div>'
    '<div class="d">공격 질문, 정상 질문, 보안 용어가 섞인 정상 질문 중 하나</div></div>'
    '<div class="ss-card"><span class="ss-tag">2단계</span><div class="t">방어 4가지로 실행</div>'
    '<div class="d">버튼 한 번으로 4가지 결과를 나란히</div></div>'
    '<div class="ss-card"><span class="ss-tag">3단계</span><div class="t">결과와 이유 보기</div>'
    '<div class="d">막았나 · 답했나를 표로, 왜 그런지 그림으로</div></div>'
    '</div>'
)

ui.block('<div class="ss-h2">대학·교육기관·연구실을 위한 도구입니다</div>')
ui.block(
    '<div class="ss-grid ss-g3">'
    '<div class="ss-card"><span class="ss-icon">🎓</span><div class="t">학생</div><div class="d">예측하고, 실행하고, 결과를 근거로 설명해요</div></div>'
    '<div class="ss-card"><span class="ss-icon">🧑‍🏫</span><div class="t">교수자</div><div class="d">준비된 사례로 환경 준비 없이 수업해요</div></div>'
    '<div class="ss-card"><span class="ss-icon">🔬</span><div class="t">연구원</div><div class="d">같은 조건으로 비교하고 근거를 내보내요</div></div>'
    '</div>'
)

ui.block('<div class="ss-h2">더 깊게 보고 싶다면</div>')
ui.block('<div class="ss-lead">여러 질문·여러 모델의 결과를 숫자로 비교하고, 하나하나의 근거와 CSV까지 확인할 수 있어요.</div>')
ui.link("app.py", "자세히 비교하기", icon=":material/table_chart:")
