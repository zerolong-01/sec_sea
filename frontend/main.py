"""보안바다 실행 시작 파일 (#72 화면 정리).

위쪽 메뉴: 홈 · 한눈에 보기 · 사용 안내 · 자세히 비교하기(화면 5개).
각 화면 파일(app.py, pages/*.py)은 그대로 두고 메뉴로 묶기만 한다. 기능과 테스트 경로는 바뀌지 않는다.
실행: py -m streamlit run frontend\\main.py
"""
from pathlib import Path

import streamlit as st

import ui_style as ui

ASSETS = Path(__file__).resolve().parent / "assets"

st.set_page_config(page_title=ui.BRAND, page_icon=str(ASSETS / "icon.svg"), layout="wide")
# 위쪽 메뉴 왼쪽의 로고 (#72 콘티: 방패 + 보안바다)
st.logo(str(ASSETS / "logo.svg"), size="large")

home = st.Page("home.py", title="홈", icon=":material/home:", default=True)
menu = {
    "": [
        home,
        st.Page("pages/0_한눈에_보기.py", title="한눈에 보기", icon=":material/visibility:", url_path="easy"),
        st.Page("guide.py", title="사용 안내", icon=":material/help:", url_path="guide"),
    ],
    "자세히 비교하기": [
        st.Page(path, title=f"{short} — {name}", url_path=slug)
        for (path, short, name, _), slug in zip(ui.DETAIL_PAGES, ("single", "batch", "models", "report", "research"))
    ],
}
st.navigation(menu, position="top").run()
