# 4주차 백엔드 재현·인계 패키지

대상은 [#47](https://github.com/zerolong-01/sec_sea/issues/47), 상위 계획 #45, 공통 계약 #10이다.
기준 dev는 `0e2f35d4e22d086876e7b04a6bd3ff9fc2e78353`이다. PR #39는 dev에,
PR #44는 main `77afde7`에 병합됐다. 이전 `63ef871`의 CI를 이번 후보의 검증으로 사용하지 않는다.
A/B/C의 실제 사람 인수·holdout·최종 추천 권한은 #43의 상태를 유지한다.

## 설치와 버전 고정

저장소 루트에서 **Python 3.11**을 사용한다. 전이 의존성의 버전·배포물 SHA256까지 고정한
[requirements.lock](../requirements.lock)을 새 환경과 Ubuntu/Windows CI에서 공통 사용한다.

macOS/Linux:

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install --require-hashes -r requirements.lock
export MVP_LOAD_DOTENV=0 MODEL_PROVIDER=demo
./.venv/bin/python -m scripts.mvp check
./.venv/bin/python -m scripts.week4_package inventory --output runs/week4-inventory-v1
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
$env:MVP_LOAD_DOTENV = "0"
$env:MODEL_PROVIDER = "demo"
& .\.venv\Scripts\python.exe -m scripts.mvp check
& .\.venv\Scripts\python.exe -m scripts.week4_package inventory --output runs/week4-inventory-v1
```

이후 `python`은 각 OS의 위 가상환경 Python 경로로 바꿔 실행한다.
`python -m scripts.mvp setup`도 Python 3.11 이상에서 같은 lock을 설치한다.
설정의 상대 경로는 저장소 루트, CLI 출력 경로는 현재 작업 디렉터리 기준이다.
공백·한글이 있는 경로는 따옴표로 감싼다.

`release-manifest.json`은 commit·dirty 상태·코드/데이터/설정/계약/공개 결과의 hash,
Python/OS/의존성과 release index를 연결한다. dirty이면 commit만으로 동일 코드라고 판단하지 않고
`code_and_data_inventory_sha256`도 확인한다. `.env`와 ignored runs는 수집하지 않는다.

## 원본 자료와 접근 범위

[release index](../configs/week4-release-index.v0.1.json)에 원래 manifest/JSON/CSV/decision record의
경로·SHA256을 기록했다. 공개 요약과 연구 overlay는 Git만으로 읽을 수 있다.

| cohort | batch_id | private runs 디렉터리 | 원래 결과 |
| --- | --- | --- | --- |
| regular legacy | `batch-bd093a919251` | `runs/week3-live-2026-10-20/runs` | 324실행 |
| regular quotation | `batch-8fb19849d67c` | `runs/week3-completion/quoted-execution-v0.4/runs` | 108실행 |
| regular D2 controls | `batch-fb671ff629f0` | `runs/week3-completion/d2-execution-v0.4/runs` | 216실행 |
| 별도 탐색 #41 | 별도 관리 | `runs/attack-audit-2026-10-20` | 942계획, regular와 합산 금지 |

private 자료는 ignored이며 checkout으로 생성되지 않는다. 원래 실행 담당자에게 접근 제한된
팀 내 파일 전송으로 디렉터리 전체를 받고 index의 manifest hash를 대조한다.
사용자가 현재 환경에 과거 원시 자료가 없다고 확인했다. 과거648의 원시 재생성은 미검증이다.
실제 제공되지 않은 공유 URL이나 접근 권한을 기재하지 않는다.
공개 JSON/CSV/연구 판정과 원문이 포함된 private archive는 분리해서 전달한다.
archive에는 `.env`·API 키·보호값 대응표를 동봉하지 않고 필요한 합성 원문·판정 증거만 제한 공유한다.

재집계에는 `batches/<id>/manifest.json`, `inputs/`, 설정 snapshot, trace, 평가/검토 이력이 필요하다.
raw는 원출력·관측 사용량 독립 대조와 완전한 보존 감사에 필요하고 ledger는 원manifest에 있다.
본문을 공개할 필요는 없다. 전체 저장 파일의 SHA를 재생 전후 대조하고 과거 export도 보존한다.

별도 탐색 #41의 [출처 index](examples/week4/exploratory-audit-index.v0.1.json)는 공개 근거 커밋
`79a4a26`의 6개 batch ID와 보고서·검증·성공 근거 SHA를 연결한다. 원래 artifact manifest의
JSON hash 8개는 Windows CRLF 작업 파일 기준이며 Git blob의 LF 바이트 hash와 다르다.
CRLF로 복원하면 선언 hash와 일치함을 확인했고, 원래 hash와 Git hash를 모두 보존했다.
이는 공개 자료의 바이트 대조이며 private 원시 943시도를 새로 검증한 기록이 아니다.
전달받은 원시 archive는 줄바꿈을 변환하지 않고 원래 hash로 확인한다.

## API/UI 기동과 외부 모델 없는 통합 검증

```bash
python -m scripts.mvp serve --fixture-model --runs-dir runs/week4-demo --api-port 8001 --ui-port 8502
```

API는 `http://127.0.0.1:8001/docs`, UI는 `http://127.0.0.1:8502`에서 연다.
RAG의 attack/benign/hard-negative와 네 모드를 선택할 수 있다. fixture는 고정 응답이며 실제 모델
정확도 검증이 아니다. 기동 터미널의 Ctrl+C로 종료한다. 포트 충돌 시 8003/8504 등으로 바꾼다.
기존 프로세스는 종료하지 않는다. PowerShell 환경 변수는 `$env:NAME = "value"`,
Git Bash/macOS/Linux에서는 `export NAME=value`를 사용한다.

이메일 단건 UI는 별도 source와 포트로 연다:

```bash
python -m scripts.week2_data prepare-email --output runs/week4-email-demo-data
python -m scripts.mvp serve --fixture-model --data-dir runs/week4-email-demo-data --runs-dir runs/week4-email-demo --api-port 8003 --ui-port 8504
```

이미 준비한 데이터 경로가 있으면 그 경로를 재사용한다.

2앱×대표3종×6고유조건×3반복 HTTP fixture, 중단/재개, 저장 조회, 집계/CSV와 API/UI 기동을 검증한다:

```bash
python -m scripts.verify_week4 --output runs/week4-acceptance-v1
```

이미 `scripts.verify_week3` 출력이 있으면 `--fixture-output PATH`로 재사용한다.
기동 로그는 출력 측 `service-logs/`에 분리한다. 종료 후 원본 전체의 추가·삭제·내용 변경이 없는지 대조한다.

## 평가 출처를 명시하는 계약

기존 `/report`는 저장된 원래 평가와 명시적인 기존 annotation을 읽는다.
`batch-cluster-summary-v0.6`는 산식을 유지하면서 provenance/CSV/decision record에
`evaluation_source=original_saved_evaluation`과 `report_sha256`을 추가했다.
report hash는 `provenance.report_sha256` 자체를 제외한 canonical JSON의 SHA256이다.
과거 v0.4/v0.5 export는 보존한다.

원평가 CSV도 일치하는 그룹이 없으면 `metric=report_metadata` 1행에 batch/report/hash·평가 출처·
필터·코드/설정 출처를 남긴다. 이 행의 지표 값·분자·분모는 빈 칸이며 0이 아니다.
그룹이 있는 CSV의 열·지표 행 구조는 유지한다. 명시적 빈 문자열 필터와 필터 생략을 구별한다.
`/export.csv` 응답에는 연구 CSV와 같은 `X-Report-SHA256`, `X-Report-Version`,
`X-Evaluation-Source` 헤더가 있다. v0.5 렌더러는 기존 빈 CSV까지 그대로 읽는다.

연구용은 별도 [ResearchReport v0.2 schema](../contracts/research-overlay-v0.2.schema.json)를 사용한다.
평가판은 `week3-two-ai-review-v0.1`을 유지하고 보고/CSV 형식만 `week4-public-overlay-v0.2`로 올렸다.
구형 [v0.1 schema](../contracts/research-overlay-v0.1.schema.json)와 sample·산출물은 보존한다.
API 경로는 [shared-variables](../contracts/shared-variables-v0.1.json)의 `research_api_paths`에 있다.

| API | 요청/결과 |
| --- | --- |
| `GET /api/v1/batches/{id}/evaluation-sources` | 원래 평가가 기본이며 연구판 유무·출처 hash·사람 검토 미실시를 반환 |
| `POST /api/v1/batches/{id}/report` | 기존 BatchFilters/BatchReport, private store 필요 |
| `POST /api/v1/batches/{id}/research/report` | ResearchFilters/별도 ResearchReport, 공개 파일만 필요 |
| `POST /api/v1/batches/{id}/research/export.csv` | 같은 ResearchFilters, 같은 report hash의 CSV |

연구 요청 예:

```json
{"evaluation_version":"week3-two-ai-review-v0.1","condition_id":"none","goal_kind":"secret_leak","ablation_variant":"original"}
```

지원 filter: `source_id, scenario, language, split=dev, condition_id, goal_kind, ablation_variant,
severity, attack_type, execution_kind, model_id, evaluator_version, evaluation_policy_version, pricing_version`.
`evaluation_version`은 연구판을 선택하고 `evaluator_version/evaluation_policy_version`은 원래 cohort의 버전을 선택한다.
**공개된 cohort 전체를 선택**하는 API다. case/family/label/comparison별 재집계는 미지원이며 422로 거부한다.
알 수 없는 연구판도 422, 공개 대상이 아닌 batch는 404, 일치 조건이 없으면 빈 배열과 count=0을 반환한다.
target cohort에 없는 goal/variant filter를 지정하면 target 그룹은 빈 배열이다. 전체 target 분모로 대체하지 않는다.

수치는 #43의 채택된 overlay를 그대로 사용한다. 새로운 사람 합의나 A의 최종 보고판 확정과 구분한다.

- `groups[].metrics.original_asr`는 원래 평가, `fresh_ai_*`는 두 AI·제3 조정 연구 판정이다.
- FPR은 원래 block/quarantine/redact를 먼저 적용하고 AI 과잉 변환 판정을 사용한다. 단순 업무 실패를 FPR로 세지 않는다.
- `selected_count, numerator, denominator, excluded, recorded_family_count, unique_case_count`를 함께 표시한다.
  `review_needed`와 분모0/null을 0%나 성공으로 바꾸지 않는다. 반복·번역을 독립 family로 세지 않는다.
- `members`가 batch/run/task/unit·원증거 SHA·판정 consensus를 연결한다. 자유문 reason/투표 본문은 복사하지 않는다.
  원래 마스킹 trace 조회에는 해당 private store가 필요하다.
- `target_gold_groups`는 AI target gold의 분포이며 D2 allow/오분류/최종 공격 성공의 비율이 아니다.
- 미제공 정상 benchmark·paired·자원 재집계·D2 FNR/FPR·CI는 `capabilities`에서 `value=null`과 사유를 반환한다.
  p95·비용 재평균이나 목표 간 정상 관측 중복 가산을 하지 않는다.
- 사람 검토는 `not_performed`, 연구 판정 일부는 미확정, 추천은 `deferred`, holdout 권한은 false다.

C는 명시적인 연구 보기로 연결하고 원래 KPI/Trade-off와 혼합하지 않는다. 버전/filter 변경 시 trace와
다운로드를 다시 조회하고 CSV 각 행의 report hash·snapshot·filters를 화면 JSON과 대조한다.
JSON/CSV/decision record에 같은 batch·run·정책판·출처 hash를 남긴다.
C 화면 연결과 A의 최종 보고판 선택은 각 담당자에게 인계할 인터페이스다.

### 연구 CSV v0.2

기존 v0.1은 JSON의 탐지 대상 gold 분포가 CSV에서 누락되고, 빈 선택에는 식별 정보가 남지 않았다.
새 CSV는 shared-variables의 `research_export.csv_fields/csv_row_kinds`를 사용한다.

| row_kind | 의미와 값 |
| --- | --- |
| `report_metadata` | 항상 1행. 보고서 해시·필터·counts·capabilities·검토/추천 상태. 빈 선택도 이 행을 반환 |
| `final_output_metric` | 기존 출력 지표의 분자·분모·제외·coverage·family·CI. JSON의 같은 metric과 일치 |
| `target_gold_count` | 그룹·stage별 `gold_label/gold_count/target_observations`. 비율·분자·분모 칸은 비워 두고 탐지 FNR/FPR로 해석하지 않음 |

모든 행이 같은 평가 출처·정책판·source hash·report hash를 가진다. 응답 헤더의
`X-Report-SHA256`, `X-Report-Version`, `X-Evaluation-Source`도 JSON과 대조할 수 있다.
빈 숫자 칸과 `ci95=null`은 0이 아니다. `target_observations`는 대상 관측 수이며 실행 수와 다를 수 있다.
`frontend.batch_core.research_csv_report_error(content, report)`는 별도 연구 다운로드의 식별자·지표·gold 건수와
행 누락/중복을 검사한다. 기존 `csv_report_error`와 KPI 경로는 유지한다.
[v0.2 sample](examples/week4/v0.2/README.md)은 출력 지표와 target gold가 함께 있는 D2-input 선택이다.

## 최종 보고서의 원본 공격 비교표 재현

`data/week4/final-report.md` 4.2절과 `data/week4/defense-comparison.md` 2.2절은
`week3`의 원본 3개 case와 `w3pv_a11`을 합친 비교다. 기본 `/report`는 저장된 원평가를
사용하므로 이 표의 AI 판정과 출처가 다르다. 공개 cohort 조회의 단일 variant 필터만으로도
`original`과 `A11`을 함께 선택할 수 없다. 다음 고정 선택 API에서 같은 표를 재현한다.

| API | 결과 |
| --- | --- |
| `GET /api/v1/research/week4-original-attacks` | 6조건의 AI 공격 목표 달성·공격 업무 수행, 목표별 내역, 72개 run/task/unit·원증거 해시 |
| `GET /api/v1/research/week4-original-attacks/export.csv` | 같은 report hash의 합산 기술통계와 목표별 지표 36행 |

계약은 [비교 보고서 v0.1 schema](../contracts/week4-original-attack-comparison-v0.1.schema.json)다.
보고 형식은 `week4-original-attack-comparison-v0.1`, 판정 버전은 `week3-two-ai-review-v0.1`,
평가 출처는 `ai_research_overlay`다. `selection`에 case 4개·조건 6개·repeat 0/1/2를 명시한다.
추가 query 필터는 422로 거부하므로 고정된 분모를 부분 선택 결과로 오인하지 않는다.
원평가·기존 overlay v0.1/v0.2 API와 보존된 export는 각 형식으로 조회한다.

`rows[].metrics.fresh_ai_attack_task_utility`는 공격 상황의 업무 수행이며 정상 요청의 성공률이 아니다.
합산 행은 목표가 다른 공격의 기술통계이고 최종 추천의 단일 ASR로 소비하지 않는다.
JSON `goal_groups`와 CSV `goal_kind`에서 표식/보호값 목표별 결과를 구분한다.
`combined_descriptive`는 CSV의 합산 행이다. `D1-D2` 원본 ID와 `D1+D2` 표시명을 함께 제공한다.
CI는 `null`, 사람 검토는 `not_performed`, 추천은 `deferred`, holdout 권한은 false다.

각 표는 공개 멤버 판정과 저장된 집계의 분자·분모·제외 수·case/family 수를 교차 검산한다.
누락·중복 실행이나 일부 cohort만 선택하는 상황은 오류로 처리한다. 미확정은 제외 사유로
남기고 분모 0의 값은 JSON `null`/CSV 빈 값으로 내보낸다. CSV 헤더의 `X-Report-SHA256`,
`X-Report-Version`, `X-Evaluation-Source`를 JSON과 대조할 수 있다.

키·private runs·추가 모델 호출 없이 문서를 검산하고 JSON/CSV를 생성한다:

```bash
python -m scripts.week4_report_comparison --check-docs --output runs/week4-original-attack-comparison
```

`--output`을 생략하면 파일 생성 없이 검산한다. 출력 폴더는 새 경로를 사용한다.
두 문서의 표·case 범위·지표 제목이 백엔드 결과와 다르면 종료 코드 1을 반환하며,
Ubuntu/Windows CI에서 같은 명령으로 문서와 백엔드 연결을 확인한다.

## 저장 결과를 새 패키지로 재생성

공개 AI 자료는 키·네트워크·private runs 없이 재생성할 수 있다:

```bash
python -m scripts.week4_package replay batch-8fb19849d67c --source overlay --output runs/week4-overlay-v1
```

원래 실제 실행 자료를 전달받은 후:

```bash
python -m scripts.week4_package replay batch-8fb19849d67c --source original --runs-dir runs/week3-completion/quoted-execution-v0.4/runs --output runs/week4-original-v1
```

`--filters path.json`으로 해당 filter JSON을 지정한다. 원래 평가·연구판은 별도 filter 계약을 사용한다.
출력은 `report.json, metrics.csv, decision-record.json, reproduction-manifest.json`이다.
기존 출력과 원본 store에 겹치는 경로는 거부한다. 원본 변경을 감지하면 미완성 패키지를 게시하지 않는다.
manifest에는 전체 원본 inventory SHA, 출력 hash, 환경, reader commit/구현 hash, 모델 호출0이 들어간다.
`created_at/environment`와 출력 절대경로는 환경 의존 값이다. report/snapshot/filter/hash·분모·핵심 값으로 대조한다.
모델 응답의 완전 일치는 별도 실제 모델 재실행의 재현 기준이 아니다.

전달받은 패키지는 원본 store·Git·환경 설정·키·네트워크 없이 검사한다:

```bash
python -m scripts.week4_package verify runs/week4-overlay-v1
```

별도 채널로 받은 manifest의 고정 hash가 있으면 다음 옵션으로 기대하는 보고서·원본 inventory도 확인한다:

```bash
python -m scripts.week4_package verify runs/week4-overlay-v1 --expected-report-sha256 REPORT_SHA256 --expected-source-inventory-sha256 SOURCE_INVENTORY_SHA256
```

검사는 정확한 4개 파일 목록, 세 artifact의 바이트 SHA, report의 canonical SHA, manifest/JSON/CSV/decision record의
식별·필터·값 일치를 확인한다. 누락·추가 파일·symlink·불일치 또는 검사 중 변경은 오류다.
새 replay는 게시 전 이 검사도 실행한다. 구형 package v0.1·연구 report v0.1도 읽으며 덮어쓰지 않는다.
기존 원평가 report 렌더러는 v0.5/v0.6을 지원하고 알 수 없는 형식은 거부한다.
검증 성공은 패키지 내부 일치의 증거다. 원본이 없는 검사이므로 `source_evidence_revalidated=false`이고,
자체 manifest만으로 발신자나 과거 원시 자료를 인증하지 않는다. 제한 전송 후 원본 재생성은 앞의 별도 절차를 따른다.

inventory는 연구 원자료뿐 아니라 완료 smoke·최초 실패·깨끗한 checkout·탐색 출처 index의 공개 참조 SHA도 확인한다.

저장 UI 기동은 [cohort별 가이드](week4-handoff-demo.md)를 따른다.
원본 외부에 로그를 쓰려면 `serve --service-logs-dir runs/week4-view-logs`도 지정한다.

## 조건부 실제 모델 대표 실행

새 dev smoke이며 과거648실행·별도 탐색942계획과 합산하지 않는다. holdout은 실행하지 않는다.
[대표 spec](../configs/week4-representative.batch.json)은 2앱×3라벨×6조건×3반복=108계획이다.
D2 양쪽은 한 실행을 기법/위치 비교에서 공유한다. 이메일 source를 준비한다:

```bash
python -m scripts.week2_data prepare-email --output runs/week4-prepared/email
```

`.env`에 키를 입력한 후 fixture용 `MVP_LOAD_DOTENV=0`을 해제한다.
macOS/Linux는 `unset MVP_LOAD_DOTENV MODEL_PROVIDER`, PowerShell은
`Remove-Item Env:MVP_LOAD_DOTENV, Env:MODEL_PROVIDER -ErrorAction SilentlyContinue`를 사용한다.
가격·규칙을 명시한다. macOS/Linux:

```bash
export PRICING_FILE=configs/pricing-openai-2026-10-20.json
export EVALUATION_RULES_FILE=configs/evaluation-week2.json
python -m scripts.week3_batch --runs-dir runs/week4-real/runs create --spec configs/week4-representative.batch.json
python -m scripts.week3_batch --runs-dir runs/week4-real/runs run BATCH_ID --max-items 1
python -m scripts.week3_batch --runs-dir runs/week4-real/runs run BATCH_ID
```

PowerShell은 `$env:PRICING_FILE = "configs/pricing-openai-2026-10-20.json"`과
`$env:EVALUATION_RULES_FILE = "configs/evaluation-week2.json"`을 설정하고 Python 경로를 바꾼다.
첫 출력의 batch_id를 BATCH_ID로 사용한다. 상한은 600호출/20,000,000예약 token/600초/USD0.25다.
미확인 가격이면 멈춘다. 모델·단가는 버전이 있는 snapshot을 사용한다.
2026-10-22에 [공식 GPT-4.1 mini 가격](https://developers.openai.com/api/docs/models/gpt-4.1-mini)을 확인했다.
가격·모델 이용 가능성은 실행 전에 확인한다. 비용은 관측 usage×표준 단가의 추정이며 청구 보장이 아니다.

`run`의 paused/partial은 종료 코드2다. show로 원인을 확인하고 완료 항목은 재호출하지 않는다.
실패·불확실한 시도의 재실행에는 각각 `--retry-failed/--retry-uncertain`이 필요하며 과거 예약·비용을 유지한다.
불확실한 응답을 자동 재전송하지 않는다. 새 코드로 이전 미완료 batch를 재개하지 않고 새 버전을 만든다.
완료 후 `week4_package replay --source original`로 추가 호출0의 결과를 새 경로에 생성한다.
의미 판정이 없는 원래 평가 항목은 미평가로 남긴다. smoke 통과를 최종 성능·사람 검토·인수로 바꾸지 않는다.

## 검증과 남은 인계

실행/저장 오류 처리도 다음과 같이 검증한다.

- 모델 HTTP 응답이 중간에 끊기거나 프로토콜 오류가 나면 실패 호출·HTTP 상태·미확인 사용량/비용을
  trace와 예약 ledger에 남긴다. 자동 재호출하지 않는다. `usage` 생략/null은 미확인으로,
  배열·문자열·숫자·bool은 잘못된 응답으로 구분한다.
- 저장소와 HTTP 경로는 실행 trace의 ID 형식을 검사한다. 파일의 run ID와 파일명,
  manifest의 batch ID와 디렉터리 이름이 다르면 조회·집계에 사용하지 않는다.
- trace/raw/평가 이력의 잘못된 UTF-8·JSON·자료형과 실행 파일 symlink를 거부한다.
  손상된 기존 파일을 덮어쓰지 않는다. 실행 조회·검토·탐지 보고는 `500/INVALID_TRACE`,
  배치 목록·조회·집계는 `422`와 `INVALID_BATCH_LIST`/`INVALID_BATCH`/`INVALID_BATCH_REPORT`를
  반환하며 원시 본문은 노출하지 않는다.

실제 API 대표108개는 응답90·차단18로 완료됐으며, 최초401 실패 이력을 포함한109시도·199호출을 보존했다.
[완료 요약](examples/week4/real-reproduction.v0.3.json)에 관측 사용량 기반 추정 비용 USD0.041702와
누적 예약액 USD0.0552188, API·대시보드·CSV 대조 및 모델 호출0 반복 재생성 증거를 기록했다.
최초401 비용 미확인 때문에 전체 비용은 null이다. 이 smoke는 과거648 재생성·사람 의미 검토와 구분한다.

[기술 검증 기록](week4-backend-acceptance.md), [공개 sample](examples/week4/README.md)을 참조한다.
CI는 이번 후보 commit의 Ubuntu/Windows Checks를 확인한다. 과거 head의 pass를 옮기지 않는다.
private 원결과 재생성·다른 담당자의 환경 실행·실제 A/B/C 인수·C 화면 대조는 각각 별도 증빙이 필요하다.
