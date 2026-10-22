# 4주차 백엔드 기술 검증 기록

이슈 #47, 작업 브랜치 `feat/week4-backend-reproducibility`, 기준 dev `0e2f35d`.
2026-10-22 작업 환경은 macOS arm64/Python 3.11.17이다. 이 기록은 실제 사람 A/B/C 인수 서명이 아니다.

후보 코드 `188a9f5`를 `/private/tmp/sec-sea-week4-checkout`에 별도 clone하고 키·기존 runs 없이
새 가상환경에서 백엔드 114개 회귀와 두 앱 통합 검증을 수행했다.
[깨끗한 checkout 증빙](examples/week4/clean-checkout-verification.v0.1.json)은 이 기술 재현 결과이며
다른 사람의 공동 인수 기록을 대신하지 않는다.
해당 checkout의 전체 root 회귀는 215개가 통과했다. 이전 214개 기록 이후 추가된 CSV 출처 검증을 포함한다.

## 후속 백엔드 보완 v0.2

연구 CSV에서 JSON의 target gold 분포가 빠지던 문제와 빈 선택에서 식별 정보가 사라지던 문제를 수정했다.
평가판은 유지하고 보고/CSV 형식만 `week4-public-overlay-v0.2`로 올렸다. 구형 파일·schema·renderer는 보존한다.
새 `week4_package verify`는 전달받은 패키지의 파일·artifact/canonical hash·JSON/CSV/decision 일치를 검사한다.
원본/환경/키/Git/네트워크가 필요 없으며 검사 결과는 원시 증거 재검증·발신자 인증과 구별한다.
inventory도 완료 smoke·최초 실패·clean checkout·탐색 index의 공개 참조 hash를 확인하도록 보완했다.

- 회귀: root 230개·backend 114개, 총 344개 통과. 기존 329개에 무결성·소비자 검증 15개를 추가했다.
- 실제 로컬 API/UI 통합: metadata·출력 지표·target gold·빈 선택 및 전송 패키지 검사 통과.
- 기존 실제108의 새 v0.2 패키지 반복 재생성: report hash `d2092568bcb00f35fa7a1adca43507237561cc3c601388539687b4c0e57f3e03`
  유지, JSON/CSV/decision 바이트 hash 일치, 원본 불변, 모델 호출0.
- 로컬 증빙: `runs/week4-hardening-v0.2/integration/`, `runs/week4-hardening-v0.2/saved-real/`,
  `runs/week4-hardening-v0.2/d2-input-package/`. 공개 계약 예시는 [v0.2](examples/week4/v0.2/README.md)다.
- 새 커밋의 Ubuntu/Windows CI는 해당 정확한 head에서 확인한다. 아래 이전 CI 기록과 구별한다.

후속 최초 CI `2d346f1`의 Ubuntu는 통과했으나 Windows에서는 추가 테스트 4개의 JSON 읽기가
기본 cp1252를 사용해 실패했다([실행 기록](https://github.com/zerolong-01/sec_sea/actions/runs/39728858509)).
해당 테스트의 텍스트 인코딩을 UTF-8로 명시했다. 기본 로케일 US-ASCII·UTF-8 mode=0에서
집중 검증 23개가 통과했으며 수정 후보의 두 OS CI도 확인한다.

이 보완은 방어 동작·과거 평가·통계 정책을 바꾸거나 모델을 새로 호출하지 않는다.
과거648 원시 부재·A/C 사람 인수 대기는 아래와 같이 유지한다.

## 구현·검증 범위

| 항목 | 결과·증거 |
| --- | --- |
| 의존성 재현 | 새 `/private/tmp/sec-sea-week4-clean` venv에서 `pip install --require-hashes -r requirements.lock` 성공 |
| 기존 회귀 | 깨끗한 checkout에서 root 215개·backend 114개, 총 329개 통과 |
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
| 실제 API 대표 실행 | 2앱×3종×6조건×3반복=108개 완료: 응답90·차단18·최종실패0, 과거401 시도는 보존 |
| 실제 저장 결과 대조 | 109시도·199호출의 raw/trace/ledger/가격 대조, API·대시보드·CSV 일치, 반복export hash 일치·추가호출0 |

최초 sandbox에서는 로컬 socket bind가 거부돼 fixture가 실패했다. 허용된 로컬 실행으로 다시 검증했다.
최초 인수 실행에서는 기존 서비스 실행기가 원본 디렉터리에 기동 로그를 추가하는 것을 발견했다.
`--service-logs-dir`/`services(..., service_logs_dir=...)`로 로그를 출력 측에 분리했고 재검증했다.
이 두 실패를 모델 성능이나 원본 평가의 실패로 계산하지 않는다.

## 실행 기록과 재현

로컬 ignored 증빙:

- `runs/week4-clean-verification-v0.1/verification-report.json`: 새 lock 환경의 통합 결과.
- `runs/week4-final-verification-v0.1/verification-report.json`: 최종 HTTP/CSV/재생성 재검증 결과.
- `runs/week4-real/`: 고정 코드 `188a9f5`의 실제 API 대표 검증. 키 수정과 명시적 재시도·잔여107개 실행 승인 후
  108개가 종료됐다. [완료 안전 요약](examples/week4/real-reproduction.v0.3.json)은 응답90·방어차단18,
  198회 HTTP200 및 최초 HTTP401 1회를 기록한다. 과거 [인증 실패 요약](examples/week4/real-attempt-status.v0.1.json)은 보존했다.
- `runs/week4-real/final-audit-v0.3/complete-verification.json`: 실제 raw/trace/ledger/API 및
  대시보드 전체·RAG·이메일의 세 필터 대조. `final-replay-v0.3-a/`와 `final-replay-v0.3-b/`의 report·CSV·decision hash가 같고,
  검증 전후 원본 전체 파일 hash도 같다. 추가 모델 호출0이다.
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
`1b1d674`의 [Ubuntu/Windows 실행](https://github.com/zerolong-01/sec_sea/actions/runs/39722841342)은 양쪽 모두 통과했다.
이 문서·완료 요약을 추가한 다음 후보도 해당 head의 workflow 결과로 확인한다.
과거 `63ef871` 통과나 로컬 macOS 결과를 새 후보의 두 OS 통과로 기록하지 않는다.

실제 대표 실행의 확인된 추정 비용은 USD 0.041702, 누적 예약액은 USD 0.0552188이며
승인 상한 USD 0.25·600호출·600초 안에서 끝났다(199호출·약270초).
최초401의 사용량/비용은 미확인이므로 전체 `total_cost_usd`와 token 합계는 null을 유지한다.
예약액을 실제 청구액으로 해석하지 않는다. 실패 시도를 지우거나 성공·방어차단으로 바꾸지 않았다.

## 별도 증거가 필요한 항목

- 과거648 실모델 실행의 private trace/raw/store는 사용자가 현재 환경에 없다고 확인했다. 공개overlay 및 새108 smoke와 구분하며,
  원래 실배치 재생성은 원담당자의 제한 전송 후 release index의manifest SHA부터 확인한다.
- 다른 담당자의 새 환경 실행, A의 최종 보고판 확인, C의 실제 화면/보고서 대조와 A/B/C 사람 인수는 대기다.
- 새108 smoke는 실행·저장 재현 기술 증거이며 과거648의 원시 재생성이나 의미 판정·최종 성능을 대신하지 않는다.
- 연구overlay의 정상benchmark/paired/자원·D2율은 미지원 사유와null을 반환한다. 원래 자동평가를 변경하지 않는다.
- 추천deferred·사람 검토미실시·부족family/CI=null·holdout 미실행을 유지한다.
- 고객 PoC·상용 운영 승인·성능 우월성·3분 데모 리허설은 이 백엔드 검증의 결과가 아니다.
