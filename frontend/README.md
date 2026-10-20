# 프론트엔드 (Streamlit)

방어 모드를 실행하고, 결과를 나란히 비교하는 화면입니다.

## 1. 켜기

저장소 맨 위 폴더(sec_sea)에서 실행합니다.

```text
python -m scripts.mvp setup                    # 처음 한 번만 (필요한 프로그램 설치)
python -m scripts.mvp serve --fixture-model    # 서버 + 화면 켜기 (가짜 모델)
```

- 화면 주소: http://127.0.0.1:8501
- 끄기: Ctrl+C
- 실제 모델로 켜기: `.env`에 모델 설정을 넣고 `python -m scripts.mvp serve` ([2주차 백엔드 안내](../docs/week2-backend.md) 참고)
- 2주차 데이터로 켜기: 명령 뒤에 `--data-dir data/week2` 추가

> Windows에서 `python`이 안 되면 `py`로 바꿔서 실행하세요.

## 2. 화면 구성

탭이 3개 있습니다. 케이스는 왼쪽에서 고릅니다 (기본: a006, b006, h007).

**한 번 실행**
- 고른 방어 모드로 1건 실행
- 입력 → 검색 → 프롬프트 조립 → 방어 판정 → 출력 순서로 보여 줌
- 오른쪽에 지연·토큰·비용, 실행 설정, 평가 결과
- `실행 번호로 저장 결과 조회`에 run_id를 넣으면 기존 trace를 GET으로 조회
- `표시 중인 결과 새로고침`으로 저장된 최신 평가를 반영. 조회 실패 시 기존 결과와 오류를 함께 표시

**4개 모드 비교**
- 같은 케이스를 무방어, D1, D2, D1 + D2로 한 번에 실행
- D2 위치는 **입력 + 검색 문서**로 고정 (왼쪽의 단일 실행 위치와 독립)
- 결과를 표 한 장에 나란히 보여 줌
- 표 아래 탭에서 모드별 자세한 내용 확인

**D2 위치 비교**
- D1은 끄고 D2만 켠 채, 검사 위치만 바꿔 3번 실행
- 위치: 입력만 / 문서만 / 입력 + 문서

두 비교 탭의 `저장 결과 새로고침`은 같은 run_id들을 GET으로 조회합니다.
조회·새로고침은 모델을 재호출하지 않습니다. 새 실험은 실행 버튼으로 시작합니다.

## 3. 공정한 비교인지 자동 확인

비교 탭은 실행들의 조건이 같은지 먼저 확인합니다.

- 모두 같으면: 초록 상자
- 하나라도 다르면: 노란 경고 + 다른 항목 이름
- 결과 누락·실행 실패·진행 중·trace/탐지 오류·필수 설정 누락은: 빨간 상자 **비교 불가**
- 미평가·검토 필요·평가 기록 누락은 별도 경고. 조건 일치는 평가 완료나 공격/정상 태스크 성공을 뜻하지 않음

같아야 하는 조건은 다음과 같습니다.

- 케이스, 앱, 데이터 버전, 코퍼스 버전
- 모델, 모델 제공자, 실행 범위(demo / fixture / real), 실행 종류(full_pipeline / detector_only)
- 생성 설정, 검색 설정, 기본 시스템 프롬프트
- 평가기 버전, 가격 버전·가격표, 모델 호출 상한
- D2 설정 (D2를 켠 실행끼리만)
- D1 버전 (D1을 켠 실행끼리만)

기법 비교는 네 모드가 각각 한 개씩 있고 D2 위치가 양쪽인지 확인합니다.
위치 비교는 D1 없이 D2만 적용한 세 위치가 각각 있는지 확인합니다.
D2 요청 위치와 저장 manifest 위치가 다르면 경고합니다.
0.2 trace는 계약상 전체 파이프라인으로 읽으며, 0.3의 실행 종류 누락은 기록 없음으로 표시합니다.

## 4. 비교 표의 각 칸은 어디서 오나

화면은 서버가 준 값을 **그대로** 보여 줍니다. 성공 여부나 지표를 화면에서 새로 계산하지 않습니다.
한글 이름은 `contracts/shared-variables-v0.1.json`의 label_ko를 씁니다.

| 화면 칸 | trace 필드 |
| --- | --- |
| 실행 번호 | `run_id` |
| 상태 | `status` |
| 출력 결과 | `output.outcome` |
| 공격 성공 | `evaluation.attack_success` |
| 정상 태스크 성공 | `evaluation.normal_task_success` |
| 방어 판정 | `defense_events`의 판정을 종류별로 센 것 (예: 허용 1 · 격리 1) |
| 프롬프트 포함 문서 | `retrieval`에서 프롬프트에 들어간 문서 수 / 전체 문서 수 |
| 응답 지연 시간(ms) | `metrics.latency_ms` |
| 입력 토큰 / 출력 토큰 | `metrics.input_tokens` / `metrics.output_tokens` |
| 추정 비용(USD) | `metrics.estimated_cost_usd` |
| 사용량 출처 | `metrics.usage_source` |
| 생성 / 탐지 호출 | `metrics.generation_call_count` / `metrics.detection_call_count` |

값이 없을 때는 이렇게 보입니다.

- 대부분의 칸: **기록 없음**
- 비용: **미확인** (가격이 확정되지 않았거나 사용량을 모를 때)
- 실행 자체가 안 됐을 때: 상태 칸에 **오류 코드** (예: ARTIFACT_NOT_FOUND)
- 누락된 생성/탐지 호출 수·비용 소계·문서 포함 여부도 **기록 없음**. 서버가 명시한 0만 0으로 표시

상세 화면은 요청한 위치와 manifest 위치, 방어/정책 버전, 평가 정책·검토자·시각,
호출별 사용량 출처·토큰·비용·오류를 표시합니다. 문서 ID는 프롬프트 구성 요소의 `source_ref`와 대조할 수 있습니다.
본문·출력·모델 메시지는 공개 API의 마스킹된 trace만 코드 영역에 표시하며 원시 파일은 읽지 않습니다.

**헷갈리기 쉬운 점:** 상태, 출력 결과, 평가는 서로 다른 값입니다.

- 상태가 "완료"여도 정상 태스크는 "실패"일 수 있습니다.
- D2 탐지기에 오류가 나면 상태는 "실행 실패", 출력은 "차단됨"입니다.

표를 만드는 코드는 `ui_core.py`의 `summary_row`입니다.

## 5. 통합 검증

화면에 보이는 값이 서버 값과 정말 같은지 자동으로 확인합니다.
서버를 켜 둔 채 **다른 창**에서 실행하세요.

```text
.venv\Scripts\python frontend\verify_ui.py     # Windows
.venv/bin/python frontend/verify_ui.py         # macOS·Linux
```

**하는 일**

- 대표 3건 × 4개 모드 = 12건 실행
- 공격 케이스(a006)는 D2 위치 3개도 실행
- 표의 값을 세 곳에서 만들어 비교: 실행 응답 / 서버 재조회 / 저장된 trace 파일. 상세 trace 전체도 대조
- 요청한 방어(D1, D2)와 D2 위치가 실제로 적용됐는지 확인
- 비교 조건이 같은지 확인 (비교 불가도 문제로 기록)
- 실행 상태 확인: **완료**와 **방어로 차단됨**(정상적인 방어 동작)은 통과, **실행 실패**(failed)·trace 오류·방어 판정 오류는 문제로 기록

**결과**

- 마지막에 "전체 통과"가 나오면 성공, 문제가 하나라도 있으면 "문제 N건"과 함께 종료 코드 1
- 기록 파일: [verification/week2-ui-verification.md](verification/week2-ui-verification.md)
- trace 파일은 `runs/`에 내 컴퓨터에만 남습니다 (Git에 안 올라감)

> fixture(가짜 모델) 검증은 화면·서버·저장 연결을 확인한 것이고, 실제 모델 성능이 아닙니다.
> 실제 모델로 켠 뒤 같은 스크립트를 다시 실행하면 실제 모델 검증 기록이 됩니다.

서버 기동·종료와 비교 버튼·저장 조회까지 한 번에 확인하려면 다음 명령을 사용하세요.

```text
python -m unittest discover -s tests -p test_frontend_ui.py -v
python -m scripts.mvp verify-week2
```

`verify-week2`는 대표 12건, 화면 비교 버튼 15건(3종 × 4모드 + D2 세 위치),
저장 조회·새로고침의 모델 호출 수 불변, 갱신된 평가 표시를 확인하고 `verify_ui.py`도 실행합니다.
상태 샘플과 마스킹·부분 trace·잘못된 응답·연결 실패는 회귀 테스트로 확인합니다.

## 6. 배치 대시보드 (3주차, #35)

왼쪽 메뉴의 **배치 대시보드** 페이지입니다. 백엔드 배치 명령(`scripts.week3_batch`)으로 저장한 결과를 **조회만** 합니다.
목록·상세·필터·내보내기 어느 것도 모델을 다시 호출하지 않습니다. 새 배치 실행은 화면이 아니라 백엔드 명령으로 합니다 ([3주차 백엔드 안내](../docs/week3-backend.md)).

### 연습용 배치로 켜기

```text
python -m scripts.verify_week3 --output runs/week3-handoff                        # 가짜 모델로 108건 배치 생성
python -m scripts.mvp serve --fixture-model --runs-dir runs/week3-handoff/runs     # 그 배치를 읽는 서버 + 화면
```

실제 모델 배치를 보려면 그 배치가 저장된 runs 폴더를 `--runs-dir`로 지정합니다.
`week3_pipeline`으로 실행한 배치는 `python -m scripts.mvp serve --pipeline-output runs/week3-live-2026-10-20`으로 고정 입력과 평가·가격·정책 설정을 함께 연결할 수 있습니다 ([통합 실행 안내](../docs/week3-live-pipeline.md)).

### 화면 구성

| 영역 | 내용 | 서버 API |
| --- | --- | --- |
| 배치 목록 | 저장된 배치, 실행 범위(데모·샘플·실제), 상태, 계획/시도 수, 총비용 | `GET /api/v1/batches` |
| 배치 정보 | 예산·사용량, 6개 방어 조건, 데이터 출처, 고정 해시 | `GET /api/v1/batches/{batch_id}` |
| 필터 | 출처·앱·언어·데이터 구분·조건·비교 종류·라벨·공격 유형·family·목표·심각도·실행 종류·모델·평가/정책/가격 버전 | 아래 리포트 요청의 본문 |
| 지표 요약 | 그룹 하나의 KPI 카드 + 조건별 비교표 | `POST .../report` → `groups[].metrics` |
| Trade-off | x 정상 태스크 성공률, y 1 − ASR, 색 방어 구성·검사 위치, 채운 점 크기 요청당 비용, 빈 점 비용 미확인 | `groups[].metrics`, `decisions.records` |
| 추천 근거 | 정책 기준값·우선순위·검토 상태, 전체 판단, 공통 보류 사유, 그룹별 추가 사유·열세 관계 | `decisions.evaluation_policy`, `decisions.records` |
| 무방어 대비 변화 | 짝지은 %p 변화와 지연·비용 증가율 | `groups[].baseline_changes_pp`, `baseline_resource_changes` |
| D2 탐지·payload | 탐지기 대상별 FNR/FPR·오류·모순, family별 공격/대조 노출률·짝 차이·CI | `detector_report`, `payload_comparisons[].family_details` |
| 실행 trace | 그룹 → 실행 번호(케이스·반복·시도) → 마스킹된 trace | `plan[].attempts[].run_id`, `GET /api/v1/runs/{run_id}` |
| 내보내기 | 화면과 같은 필터의 리포트 JSON, 지표 CSV | 리포트 응답 그대로, `POST .../export.csv` |

### 지표 칸은 어디서 오나

화면은 서버 집계 값을 **그대로** 글자로만 바꿉니다. 지표·CI·Pareto·추천을 화면에서 다시 계산하지 않습니다.
(산점도는 2개 축만 보이지만 Pareto 판단은 서버가 6개 지표 전체로 한 결과입니다.)

| 화면 이름 | 리포트 필드 (`groups[].metrics.*`) | 표시 |
| --- | --- | --- |
| ASR (공격 성공률) | `asr` | 비율 (분자/분모) |
| 정상 태스크 성공률 | `task_success` | 비율 (분자/분모) |
| FPR (정상 케이스) / (하드 네거티브) | `benign_fpr` / `hard_negative_fpr` | 비율 (분자/분모) |
| 목표값 노출률 | `target_exposure_rate` | 비율 |
| 지연 p50 / p95 (ms) | `latency_p50_ms` / `latency_p95_ms` | 밀리초 |
| 실행 실패율 | `run_failure_rate` | 비율 |
| 요청당 비용 (USD) | `cost_per_request_usd` | 달러 |
| 요청당 입력 / 출력 토큰 | `input_tokens` / `output_tokens` | 평균 토큰 수 |
| KPI 카드 도움말 | 각 지표의 `numerator`, `denominator`, `family_count`, `ci95`, `inference_status`, `excluded` | 분자/분모 · family 수 · 95% CI · 표본 부족 여부 · 제외 사유 |
| payload 짝 비교 | `payload_comparisons[].target_exposure_delta` | 노출 차이(%p) · 비교 짝 수 · family 수 · 95% CI(%p) · 통계 상태 · 제외 사유 |
| 추천 판단 | `decisions.records[].status`, `reasons`, `dominated_by` | 한글 사유 (원래 코드도 함께) |

값이 없을 때는 이렇게 보입니다.

- 지표 값이 null (분모 0, 미평가 등): **기록 없음**. 0%나 실패로 바꾸지 않음
- CI가 null: **CI 없음**, 그리고 **표본 부족** 표시. 산점도에서는 흐린 점
- 비용 합계가 null: **미확인 (확인된 소계 …)**
- ASR이나 정상 성공률이 없는 그룹: 산점도에 찍지 않고 "점을 못 찍은 그룹"에 이유와 함께 표시
- 비용을 아는 점과 모르는 점이 섞여도 모두 표시. 미확인 비용은 고정 크기 빈 점이며 0원으로 계산하지 않음
- 같은 자리에 겹친 점: 점 위 도움말과 아래 표의 "같은 자리 그룹"에 표시

점의 도움말과 아래 표에서 ASR·정상 성공률의 95% CI, 평가 수·family 수, 데이터 출처·split과 서버 추천 판단을 확인합니다.
점을 선택한 뒤 **선택한 점의 대표 trace 조회**를 누르면 **실행 trace** 탭에 같은 그룹의 저장 실행을 GET으로 불러옵니다.
KPI 아래 **선택 그룹의 표본·평가 수와 모든 지표의 불확실성**에는 전체 11개 지표와 고유 케이스·반복·평가 대기 수가 나옵니다.
공격 목표가 다른 marker 출력과 보호값 유출은 서버의 별도 그룹을 사용합니다.
산점도는 서버의 `tradeoff_points`를 사용합니다. 각 공격 목표의 ASR에 연결한 정상 기준의 ID·공유 범위·실행 번호와 평가 수를 표시합니다.
일반 집계 그룹의 분모를 화면에서 합치지 않습니다. 비용 범위는 각 공격 목표 그룹이며 정상 기준 전체의 비용과 혼동하지 않습니다.
정상 기준의 평가/계획 수·제외 수·평가 완료 여부도 표시합니다. 일부 차단 결과만 평가되고 나머지가 검토 대기라면 점은 일부 관측값이며,
CI가 계산되었다고 모든 평가가 끝난 것으로 해석하지 않습니다.

**배치 정보**의 가격표는 저장된 스냅샷을 표시합니다. **추천 근거**의 정책값이 비어 있으면 기록 없음으로 두며,
정책 검토자나 기준값을 화면에서 만들어 채우지 않습니다. 과거 리포트에 없는 새 필드도 기록 없음으로 표시합니다.

화면 전용 한글 이름(지표 이름, 추천 판단 상태, 사유, 제외 사유)은 아직 통합 변수 파일에 없어서 `batch_core.py` 위쪽에 모아 두었습니다.
팀에서 정하면 통합 변수 파일로 옮깁니다.

### 조회 결과와 다운로드의 일치

- 배치·필터·그룹·실행 번호가 바뀌면 이전 선택의 trace를 표시하지 않습니다. 새 선택에서 **trace 조회**를 누르세요.
- **배치 목록 새로고침**은 집계 리포트와 준비된 CSV, 조회한 trace를 함께 갱신합니다.
- CSV의 모든 행에서 배치 번호·리포트 버전·평가 스냅샷·필터가 현재 화면과 같은지 확인한 뒤 다운로드를 제공합니다. v0.3 리포트가 계산 구현 해시를 제공하면 그 값도 확인합니다.
- 실행 완료나 평가 변경으로 CSV가 화면보다 최신이면 다운로드를 보류하고 새로고침을 안내합니다. 목록을 새로고침한 뒤 **지표 CSV 준비**를 다시 누르세요.

### 확인한 것

```text
python -m unittest discover -s tests -p "test_batch_*.py" -v
```

공개 fixture(`docs/examples/week3`)로 표·산점도·추천 사유·실행 번호 연결·필터·오류 처리를 확인합니다.
streamlit이 설치된 환경에서는 화면 테스트(정상, 연결 실패, 빈 목록)도 실행합니다.
값이 채워진 경우는 fixture를 복사해 일부만 바꾼 합성 값이며 실제 결과가 아닙니다.

## 7. 파일 구성

| 파일 | 역할 |
| --- | --- |
| `app.py` | 화면 (한 번 실행, 4개 모드 비교, D2 위치 비교) |
| `pages/1_배치_대시보드.py` | 배치 대시보드 화면 (3주차) |
| `ui_core.py` | 화면과 검증이 같이 쓰는 부분 (서버 요청, 비교 표, 조건 확인) |
| `batch_core.py` | 배치 대시보드의 서버 요청과 표시용 값 만들기 |
| `verify_ui.py` | 통합 검증 스크립트 |
| `verification/` | 검증 기록 |

### 검증 기록과 데모

- 실제 모델 배치로 화면 JSON·CSV를 CLI 리포트·export와 대조한 기록: [verification/week3-ui-verification.md](verification/week3-ui-verification.md)
- 차트·정책·특수 상태 보완의 오프라인 검증: [verification/week3-dashboard-completion.md](verification/week3-dashboard-completion.md)
- 3분 시연 순서: [verification/week3-demo-guide.md](verification/week3-demo-guide.md)

## 8. 사람의 확인이 필요한 일

- 평가 담당의 정상 성공·과도 변환·목표값 노출·D2 정답 검토
- 팀의 서비스 기준값·우선순위·통계 정책 합의. 동결 전에는 최종 추천을 내리지 않음

수동 검토 입력(`PUT .../reviews/{run_id}`) 전용 화면은 선택 기능입니다. #35 필수 범위의 저장 결과 조회·필터·내보내기와 구분합니다.
전부 실패·빈/한 결과·부분 완료·비용 미확인·탈락/동률은 공개 fixture·합성 리포트로 검증하며 실제 모델 실험과 혼동하지 않습니다.

---

> VS Code에서 이 파일을 열었다면 **Ctrl + Shift + V**를 눌러 편하게 보시면 좋을 것 같습니다.
