"""홈 (#72 화면 정리): 누가 쓰는지, 무엇을 넣으면 무엇이 나와 무엇을 말해 주는지 한 화면에 보여 준다.

모양과 글은 콘티 '① 홈'을 그대로 옮긴 storyboard/home.html 이다. 실행·조회는 하지 않는다.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_style as ui  # noqa: E402

st.set_page_config(page_title="보안바다 · 홈", layout="wide")
ui.apply()
ui.storyboard("home.html")
