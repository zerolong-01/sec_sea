"""사용 안내 (#72 화면 정리): 하고 싶은 일 → 들어갈 곳 → 누를 것.

모양과 글은 콘티 '⑥ 사용 안내'를 그대로 옮긴 storyboard/guide.html 이다. 서버나 모델을 부르지 않는다.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_style as ui  # noqa: E402

st.set_page_config(page_title="보안바다 · 사용 안내", layout="wide")
ui.apply()
ui.storyboard("guide.html")
