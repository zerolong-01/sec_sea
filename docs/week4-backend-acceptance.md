# 4주차 백엔드 기술 검증 기록

이슈 #47, 작업 브랜치 `feat/week4-backend-reproducibility`, 기준 dev `0e2f35d`.
2026-10-22 작업 환경은 macOS arm64/Python 3.11.17이다. 이 기록은 실제 사람 A/B/C 인수 서명이 아니다.

후보 코드 `188a9f5`를 `/private/tmp/sec-sea-week4-checkout`에 별도 clone하고 키·기존 runs 없이
새 가상환경에서 백엔드 114개 회귀와 두 앱 통합 검증을 수행했다.
[깨끗한 checkout 증빙](examples/week4/clean-checkout-verification.v0.1.json)은 이 기술 재현 결과이며
다른 사람의 공동 인수 기록을 대신하지 않는다.
해당 checkout의 전체 root 회귀는 215개가 통과했다. 이전 214개 기록 이후 추가된 CSV 출처 검증을 포함한다.

## 구현·검증 범위

| 항목 | 결과·증거 |
| --- | --- |
| 의존성 재현 | 새 `/private/tmp/sec-sea-week4-clean` venv에서 `pip install --require-hashes -r requirements.lock` 성공 |
| 기존 회귀 | root 214개·backend 114개 통과, 최종 소비자/실행기/재현 관련 33개 추가 회귀 통과(중복 포함) |
| 공개 연구 근거 | 출력648 + target621 =1,269 membership, 168 공개 cohort; 원자료 hash 검증 |
| HTTP 계약 | 원평가/연구판 별도 경로, 불명판·미지원 차원422, 없는batch404, 빈cohort 명시 |
| JSON/CSV/decision | 같은 report hash·snapshot·filter·분모·제외; CI/null/review_needed 보존 |
| 원본 불변 | fixture 저장 trace/raw/manifest/검토/ledger/과거export 전체 hash 전후 일치 |
| 모델 호출0 재생성 | 원평가 반복export 및 공개overlay 재생성에서 provider 함수 차단·호출0 확인 |
| 동시 변경/덮어쓰기 | 입력 변경·기존 출력·원본과 겹친 경로 거부, 불완전 결과 미게시 |
| API/UI 기동 | 새 lock 환경에서 실제 로컬 HTTP와 Streamlit health 통과 |
| 예산/재개 | 2앱×3종×6조건×3반복=108 fixture 실행, 7건 중단 후 재개·중복호출0 |
| 공개 마스킹 | 공개 멤버에는 typed consensus/ID/hash만 포함, 원문·자유문 votes/reason 제외 |
| C 소비 경계 | shared-variables/schema/sample/문서 제공, 기존 다운로드가 v0.5 report hash·평가 출처 대조 |
| 별도 탐색 inventory | #41의 공개 근거 9파일 hash 대조, 6batch ID 확보, JSON 8파일의 CRLF/LF hash 차이 확인·별도 기록 |

최초 sandbox에서는 로컬 socket bind가 거부돼 fixture가 실패했다. 허용된 로컬 실행으로 다시 검증했다.
최초 인수 실행에서는 기존 서비스 실행기가 원본 디렉터리에 기동 로그를 추가하는 것을 발견했다.
`--service-logs-dir`/`services(..., service_logs_dir=...)`로 로그를 출력 측에 분리했고 재검증했다.
이 두 실패를 모델 성능이나 원본 평가의 실패로 계산하지 않는다.

## 실행 기록과 재현

로컬 ignored 증빙:

- `runs/week4-clean-verification-v0.1/verification-report.json`: 새 lock 환경의 통합 결과.
- `runs/week4-final-verification-v0.1/verification-report.json`: 최종 HTTP/CSV/재생성 재검증 결과.
- `runs/week4-real/`: 고정 코드 `188a9f5`의 실제 API 대표 검증 시도. 첫 D2 요청이 HTTP401로 실패해
  1실패·107대기이며, 원본 보존·조회/export·모델 호출0 재생성은 별도로 통과했다.
  [안전 요약](examples/week4/real-attempt-status.v0.1.json)에 실제 시도와 비용 미확인을 기록했다.
- 같은 디렉터리의 `release-manifest.json`, `original-first/`, `original-second/`, `overlay/`, `service-logs/`.
- `runs/week4-verification-v0.1/fixture/verification-report.json`: 두 앱의 108 실행과 호출ledger 대조.
- `docs/examples/week4/`: 공개 가능한 계약 예시·안전 검증 요약. 원시 모델 출력은 포함하지 않는다.

현재 commit과 코드/자료 hash는 새 경로의 inventory로 확인한다:

```bash
python -m scripts.week4_package inventory --output runs/week4-final-inventory-v1
python -m unittest discover -s tests -v
python -m unittest discover -s backend/tests -t backend -v
python -m scripts.verify_week4 --output runs/week4-final-acceptance-v1
```

설치와 OS별 Python 경로는 [실행 가이드](week4-backend.md)를 따른다.
CI는 `.github/workflows/mvp-integration.yml`에서 같은 lock과 기존 검증 + week4 검증을 실행한다.
Ubuntu/Windows의 최신 후보 head Checks는 원격 브랜치/PR에서 별도 확인해야 한다.
과거 `63ef871` 통과나 로컬 macOS 결과를 두 OS 통과로 기록하지 않는다.

## 별도 증거가 필요한 항목

- 과거648 실모델 실행의 private trace/raw/store는 현재 checkout에 없다. 공개overlay 재생성과 구분하며,
  원래 실배치 재생성은 원담당자의 제한 전송 후 release index의manifest SHA부터 확인한다.
- 다른 담당자의 새 환경 실행, A의 최종 보고판 확인, C의 실제 화면/보고서 대조와 A/B/C 사람 인수는 대기다.
- `configs/week4-representative.batch.json`으로 별도 dev 대표 실행을 시도했으나 D2 인증 오류가 남았다.
  유효한 키를 확인한 뒤 기존 attempt·예약 비용을 보존하는 명시적 재시도로 이어간다.
  401 실패를 모델 평가 결과나 공격 방어 성공으로 집계하지 않는다.
- 연구overlay의 정상benchmark/paired/자원·D2율은 미지원 사유와null을 반환한다. 원래 자동평가를 변경하지 않는다.
- 추천deferred·사람 검토미실시·부족family/CI=null·holdout 미실행을 유지한다.
- 고객 PoC·상용 운영 승인·성능 우월성·3분 데모 리허설은 이 백엔드 검증의 결과가 아니다.
