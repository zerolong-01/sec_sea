# 4주차 프론트엔드 통합 인수 기록 (#48)

이 문서는 **작업자(C)와 다른 담당자**가 깨끗한 checkout에서 문서만 보고 설치 → 기동 → 대표 케이스 확인 → 저장 조회 → 집계·내보내기를 해 본 기록이다.
빈칸은 실제로 해 본 사람이 채운다. 해 보지 않은 항목은 "미수행"으로 남기고 지어서 쓰지 않는다.

설치·기동 명령은 [4주차 백엔드 안내](../../docs/week4-backend.md)를 따른다. 이 문서는 화면 쪽 확인 항목만 정리한다.

## 1. 수행 정보

| 항목 | 작업자 (C) | 다른 담당자 |
| --- | --- | --- |
| 이름 / 역할 | | |
| 날짜·시각 (KST) | | |
| OS | | |
| Python (`py -3.11 --version`) | | |
| commit (`git rev-parse --short HEAD`) | | |
| dirty 여부 (`git status --short` 결과 없음 = clean) | | |
| 새 폴더에 clone 했는가 | | |

## 2. 설치와 기동 (외부 모델 없음)

PowerShell, 저장소 루트에서:

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
$env:MVP_LOAD_DOTENV = "0"
$env:MODEL_PROVIDER = "demo"
& .\.venv\Scripts\python.exe -m scripts.mvp check
& .\.venv\Scripts\python.exe -m scripts.mvp serve --fixture-model --runs-dir runs/week4-demo --api-port 8001 --ui-port 8502
```

| 확인 | 작업자 | 다른 담당자 |
| --- | --- | --- |
| `pip install` 성공 | | |
| `mvp check` 성공 | | |
| http://127.0.0.1:8502 화면이 열림 | | |
| 문제와 해결 (있으면) | | |

## 3. 첫 페이지 케이스 찾기 → 실행 (fixture 모델)

| 확인 | 기대 | 작업자 | 다른 담당자 |
| --- | --- | --- | --- |
| 케이스 찾기 탭에 전체 건수와 페이지가 보임 | 한 페이지 10건, 긴 목록 없음 | | |
| 검색어 `a006` | 1건 | | |
| 검색어 `zzzz` | 0건 안내 + 필터 초기화 | | |
| 앱·라벨·언어 필터를 같이 걸고 초기화 | 원래대로 돌아옴 | | |
| 정렬·페이지 이동 후에도 왼쪽 "실행할 케이스"가 그대로 | 선택 유지 | | |
| 선택한 케이스가 필터에서 빠지면 노란 안내 | 안내 문구 | | |
| attack / benign / hard-negative 각 1건 선택 → 실행 | 결과 화면의 케이스 ID = 고른 ID | | |
| 검색·필터·페이지·미리보기만 할 때 서버 실행 요청 없음 | 서버 로그에 POST /api/v1/runs 없음 | | |
| 미리보기에 보호값이 `[MASKED_CANARY]`로 가려짐 (a006 등) | 원문 노출 없음 | | |
| holdout 포함을 켜고 holdout 케이스 선택 | 실행 버튼 3개 모두 비활성 | | |
| 이메일: `--data-dir runs/week4-email-demo-data`로 켜서 대표 3종 실행 | 위와 같음 | | |

## 4. 저장 결과 조회·집계·내보내기 (모델 호출 0)

| 확인 | 기대 | 작업자 | 다른 담당자 |
| --- | --- | --- | --- |
| `python -m scripts.verify_week4 --output runs/week4-acceptance-v1` | 통과 | | |
| 배치 대시보드 위쪽 평가 출처 칸 | "원래 자동 평가", 사람 검토 "하지 않음", 리포트 해시 | | |
| 지표 요약·Trade-off·추천 근거·trace 탭 | 빨간 오류 없음 | | |
| 내보내기: CSV 준비 | 화면과 같은 해시일 때만 내려받기 버튼 | | |
| 필터를 바꾼 뒤 이전 CSV·trace가 남지 않음 | 다시 준비하라는 안내 | | |

## 5. AI 연구 판정 보기 (공개 파일만, 모델 호출 0)

왼쪽 메뉴 **연구 판정 보기**. 원래 실행 기록이 없는 PC에서도 열린다.

| 확인 | 기대 | 작업자 | 다른 담당자 |
| --- | --- | --- | --- |
| 맨 위 경고 | "원래 자동 평가가 아닙니다" | | |
| batch-8fb19849d67c, 방어 조건 D2-input | 출력 그룹·정답 건수 표가 보임 | | |
| 출처 표시 | 사람 검토 하지 않음 · 원래 평가에 적용 안 함 · 추천 보류 | | |
| 연구 CSV 준비 | "화면 보고서와 같습니다" 후 내려받기 | | |
| 내려받은 CSV를 [v0.2 샘플](../../docs/examples/week4/v0.2/metrics.csv)과 비교 (같은 필터) | 같음 | | |
| 실행별 판정에서 trace 조회 | 원래 기록이 없으면 "이 PC에는 원래 실행 기록이 없어" 안내 | | |
| 원래 대시보드 KPI 숫자가 연구 판정 때문에 바뀌지 않음 | 그대로 | | |

## 6. 수치 대조 (같은 batch·필터·평가 버전)

| 값 | 보고서 (A) | API/CSV (B) | 화면 (C) | 같음? |
| --- | --- | --- | --- | --- |
| | | | | |

A의 [최종 보고서](../../data/week4/final-report.md)·[결과 검산](../../data/week4/result-check.md)와 B의 export에서 2~3개 핵심 값을 골라 같은 조건으로 화면 값과 맞춘다.

## 7. 남은 것 · 미수행

- 실제 모델 대표 실행 (설정·예산 확정 후. 하지 않았으면 "미수행")
- private 원래 실행 기록(648건)이 있는 PC에서의 원래 평가 화면 대조
- 사람 검토, holdout: 팀 결정(#43·#45)에 따라 이번 인수 범위 밖
