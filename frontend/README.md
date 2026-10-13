# Streamlit MVP

저장소 루트에서 아래 명령으로 백엔드와 화면을 함께 실행한다.

```text
python -m scripts.mvp setup
python -m scripts.mvp serve
```

네 방어 모드·D2 적용 위치를 외부 모델 없이 시연하려면 `python -m scripts.mvp serve --fixture-model`을 사용한다.
실제 모델 연결과 임시 설정은 [2주차 실행 안내](../docs/week2-backend.md)를 따른다.

화면: http://127.0.0.1:8501. Ctrl+C로 두 서버를 종료한다.
대표 케이스와 코퍼스 버전은 data/mvp-manifest.v0.1.json에서 읽는다.
기본 목록은 a006, b006, h007이며 '모든 케이스 보기'로 나머지 케이스도 실행할 수 있다.
평가 항목은 백엔드 trace를 그대로 표시하며 화면에서 성공 여부를 계산하지 않는다.
UI는 실행 계약 v0.2로 요청한다. D2 점수·임계값·근거·대상, 문서 포함 여부,
단계별 지연, 생성/탐지 호출 수, 사용량 출처와 비용 미확인 사유를 표시한다.
모델 호출 메시지는 마스킹된 API 결과로 확인한다. 실행 범위에 표시되는 demo/fixture/real을 구분한다.

별도 서버에 연결할 때는 BACKEND_URL을 지정하고 .venv의 Python으로 실행한다.

```text
python -m streamlit run frontend/app.py
```

DATA_DIR과 MVP_MANIFEST로 데이터·manifest 경로를 함께 지정할 수 있다.
전체 API·UI 검증은 루트에서 python -m scripts.mvp verify로 수행한다.
2주차 모드·위치·실패·평가 상태 인계 검증은 `python -m scripts.mvp verify-week2`로 수행한다.
비교 대시보드와 통계 집계는 #24/3주차 범위다.
