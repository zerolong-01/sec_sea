"""사용 안내 (#72 화면 정리): 하고 싶은 일 → 들어갈 곳 → 누를 것. 버튼·탭 이름은 지금 화면 그대로 적는다.

안내만 한다. 서버나 모델을 부르지 않는다.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_style as ui  # noqa: E402

st.set_page_config(page_title="보안바다 · 사용 안내", layout="wide")
ui.apply()

ui.block('<div class="ss-kicker">사용 안내</div><div class="ss-h1">처음 오셨나요?</div>'
         '<div class="ss-lead">하고 싶은 일을 찾아서, 적힌 순서대로 눌러 보세요. 처음이라면 <b>①번</b>부터 시작하면 돼요.</div>')

ui.block('<div class="ss-h2">화면 지도</div>')
ui.block(
    '<div class="ss-map">'
    '<div class="m"><div class="t">홈</div><div class="d">무엇을 하는 곳인지 소개</div></div>'
    '<div class="m main"><div class="t">한눈에 보기 · 처음이라면 여기</div>'
    '<div class="d">1. 질문 고르기 → 2. 방어 4가지로 실행 → 3. 결과 → 왜 이런 결과가?</div></div>'
    '<div class="m"><div class="t">자세히 비교하기 · 숫자로 깊게 볼 때</div>'
    '<div class="d">질문 하나(방어 모드 실행 · trace 확인) · 여러 질문(배치 대시보드) · 여러 모델(모델 비교) · '
    '보고서 사례(보고서 원본 공격 비교) · AI 판정(연구 판정 보기)</div></div>'
    '</div>'
)

ROWS = [
    ("①", "방어 4가지가 어떻게 다른지 직접 보고 싶어요", "한눈에 보기", "질문 고르기 → 방어 방법 4가지로 실행"),
    ("②", "왜 막혔는지, 왜 실패인지 알고 싶어요", "한눈에 보기 › 3. 결과", "'왜 이런 결과가?' 탭 → 방어 이름 선택"),
    ("③", "답변이 원래 요청을 해냈는지 확인하고 싶어요", "한눈에 보기 › 3. 결과",
     "답변 4개 모두 AI로 확인하기 (이미 확인했다면 저장된 결과 불러오기)"),
    ("④", "원하는 질문을 검색해서 고르고 싶어요", "자세히 비교하기 › 1 · 질문 하나", "케이스 찾기 탭 → 검색 → 선택"),
    ("⑤", "여러 질문을 한꺼번에 돌린 결과를 보고 싶어요", "자세히 비교하기 › 2 · 여러 질문",
     "배치 선택 (미리 실행해 저장한 결과만 볼 수 있어요)"),
    ("⑥", "AI 모델끼리 결과를 비교하고 싶어요", "자세히 비교하기 › 3 · 여러 모델", "실험 선택"),
    ("⑦", "결과를 파일로 내보내 과제로 내고 싶어요", "자세히 비교하기 › 각 화면", "CSV 준비 → CSV 다운로드"),
]
ui.block('<div class="ss-h2">이걸 하고 싶다면</div>')
rows = "".join(f'<tr><td class="name">{ui.esc(n)}</td><td>{ui.esc(want)}</td><td><b>{ui.esc(where)}</b></td><td>{ui.esc(press)}</td></tr>'
               for n, want, where, press in ROWS)
ui.block(f'<table class="ss-table"><tr><th></th><th>하고 싶은 일</th><th>들어갈 곳</th><th>누를 것</th></tr>{rows}</table>')

WORDS = [
    ("good", "막음", "bad", "뚫림", "숨은 명령을 막았는지, 속아 넘어갔는지"),
    ("good", "답함", "bad", "못 함", "원래 질문에 답했는지"),
    ("pending", "판정 전", None, None, "아직 확인하지 않았어요. AI로 확인하거나 사람이 봐야 해요"),
    ("na", "해당 없음", None, None, "평가할 대상이 없어요 (예: 정상 질문의 공격 성공)"),
    ("error", "실행 오류", None, None, "실행 중 문제가 생겨 결과를 판단할 수 없어요"),
]
ui.block('<div class="ss-h2">화면에 나오는 말</div>')
rows = "".join(
    f'<tr><td class="name">{ui.chip(t1, w1)} {ui.chip(t2, w2) if t2 else ""}</td><td>{ui.esc(meaning)}</td></tr>'
    for t1, w1, t2, w2, meaning in WORDS)
rows += ('<tr><td class="name">사람 확인 필요</td><td>근거가 애매해서 사람이 다시 봐야 해요</td></tr>'
         '<tr><td class="name">연습용 고정 응답</td><td>실습용으로 미리 정해 둔 답이에요. 실제 AI 모델 결과와 다를 수 있어요</td></tr>'
         '<tr><td class="name">AI 연구 판정</td><td>AI가 내린 판정이에요. 사람이 확인한 결과는 아니에요</td></tr>')
ui.block(f'<table class="ss-table"><tr><th>표시</th><th>뜻</th></tr>{rows}</table>')

ui.link("pages/0_한눈에_보기.py", "①번부터 시작하기", icon=":material/play_arrow:")
