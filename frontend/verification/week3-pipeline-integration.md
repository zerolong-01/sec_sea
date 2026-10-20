# 최신 dev와 실제 파이프라인 통합 검증

PR #40 및 수정 PR #42가 머지된 dev `bad02b6`를 `feat/week3-live-pipeline`에 통합했다. 공통 집계 v0.3과 새 대시보드의 조회·필터·내보내기·trace 경로를 연결하며, 새로운 실제 모델 실행은 하지 않았다.

## 저장된 실제 결과 대조

- 기존 배치 `batch-bd093a919251`: 계획 324건, 생성 완료 251건, 방어 차단 73건. 이는 과거 실행 결과이며 이번 통합으로 재생성한 관측이 아니다.
- 전체 66개 그룹, payload 비교 78행, CSV 지표 726행을 현재 집계로 재생했다.
- RAG 출처 필터는 60개 그룹·payload 비교 42행, 이메일 출처는 6개 그룹·36행이다.
- FastAPI의 실제 조회·집계·CSV 라우트를 Streamlit AppTest에 연결했다. 화면 비교표·payload 신뢰구간과 표본 상태, JSON·CSV 다운로드, 출처별 공개 trace를 저장 결과와 대조했다.
- 실제 배치의 검증 API 요청은 13회, 공개 trace 대조는 3회다. 추가 모델 호출 0회, 외부 네트워크 0회이며 배치 manifest는 변경되지 않았다.
- 기존 `ui-verification-report.json`은 보존하고 대시보드 검증은 로컬 `dashboard-verification-report.json`으로 분리했다. 원시 출력이나 인증키는 공개 자료에 추가하지 않았다.

## 실행 경로 보완

- `mvp serve --pipeline-output`은 기존 checkpoint와 배치에 고정된 입력·설정 snapshot을 검사한 뒤 올바른 데이터·runs·평가·가격·공통 정책 경로를 자식 서버에 전달한다. 원본이나 `prepared` 폴더와 독립적으로 저장된 배치를 열며 이전 셸에 남은 다른 경로보다 명시한 pipeline을 우선한다.
- `week3_pipeline --report-only`는 저장 모델 설정과 고정 snapshot을 사용한다. 현재 API 키·가격 파일·Python/OS 설정에 의존하지 않으며, 입력·원시 trace·ledger의 무결성 검사는 유지한다.
- `verify_real_ui --dashboard-only`는 실제 배치 API와 대시보드를 오프라인으로 교차 검증한다. 현재 환경이 잘못된 경우도 별도 새 Python 프로세스에서 검증했다.

## 재현과 범위

```text
python -m scripts.week3_pipeline --output runs/week3-live-2026-10-20 --report-only
python -m scripts.verify_real_ui --runs-dir runs/week3-live-2026-10-20/runs --batch-id batch-bd093a919251 --dashboard-only
python -m scripts.mvp serve --pipeline-output runs/week3-live-2026-10-20
```

자동 회귀는 `test_pipeline_services`, `test_week3_offline_replay`, `test_verify_batch_ui`와 기존 실행·재개/대시보드 회귀로 확인한다. CI의 모델 결과는 fixture/demo이며 실제 방어 성능의 근거로 사용하지 않는다. 사람의 의미 평가·D2 gold·팀 정책 확정은 계속 대기 상태다. 이번 작업에서는 holdout을 실행하지 않았다.
