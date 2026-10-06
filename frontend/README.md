# Streamlit MVP

저장소 루트에서 아래 명령으로 백엔드와 화면을 함께 실행한다.

```text
python -m scripts.mvp setup
python -m scripts.mvp serve
```

화면: http://127.0.0.1:8501. Ctrl+C로 두 서버를 종료한다.
대표 케이스와 코퍼스 버전은 data/mvp-manifest.v0.1.json에서 읽는다.
기본 목록은 a006, b006, h007이며 '모든 케이스 보기'로 나머지 케이스도 실행할 수 있다.
평가 항목은 백엔드 trace를 그대로 표시하며 화면에서 성공 여부를 계산하지 않는다.

별도 서버에 연결할 때는 BACKEND_URL을 지정하고 .venv의 Python으로 실행한다.

```text
python -m streamlit run frontend/app.py
```

DATA_DIR과 MVP_MANIFEST로 데이터·manifest 경로를 함께 지정할 수 있다.
전체 API·UI 검증은 루트에서 python -m scripts.mvp verify로 수행한다.
