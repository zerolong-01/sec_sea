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
현재 checkout에는 이 전송 자료가 없다. 실제 제공되지 않은 공유 URL이나 접근 권한을 기재하지 않는다.
공개 JSON/CSV/연구 판정과 원문이 포함된 private archive는 분리해서 전달한다.
archive에는 `.env`·API 키·보호값 대응표를 동봉하지 않고 필요한 합성 원문·판정 증거만 제한 공유한다.

재집계에는 `batches/<id>/manifest.json`, `inputs/`, 설정 snapshot, trace, 평가/검토 이력이 필요하다.
raw는 원출력·관측 사용량 독립 대조와 완전한 보존 감사에 필요하고 ledger는 원manifest에 있다.
본문을 공개할 필요는 없다. 전체 저장 파일의 SHA를 재생 전후 대조하고 과거 export도 보존한다.

## API/UI 기동과 외부 모델 없는 통합 검증

```bash
python -m scripts.mvp serve --fixture-model --runs-dir runs/week4-demo --api-port 8001 --ui-port 8502
```

API는 `http://127.0.0.1:8001/docs`, UI는 `http://127.0.0.1:8502`에서 연다.
RAG의 attack/benign/hard-negative와 네 모드를 선택할 수 있다. fixture는 고정 응답이며 실제 모델
정확도 검증이 아니다. 기동 터미널의 Ctrl+C로 종료한다. 포트 충돌 시 8003/8504 등으로 바꾼다.
기존 프로세스는 종료하지 않는다. PowerShell 환경 변수는 `$env:NAME = "value"`,
Git Bash/macOS/Linux에서는 `export NAME=value`를 사용한다.

2앱×대표3종×6고유조건×3반복 HTTP fixture, 중단/재개, 저장 조회, 집계/CSV와 API/UI 기동을 검증한다:

```bash
python -m scripts.verify_week4 --output runs/week4-acceptance-v1
```

이미 `scripts.verify_week3` 출력이 있으면 `--fixture-output PATH`로 재사용한다.
기동 로그는 출력 측 `service-logs/`에 분리한다. 종료 후 원본 전체의 추가·삭제·내용 변경이 없는지 대조한다.

## 평가 출처를 명시하는 계약

기존 `/report`는 저장된 원래 평가와 명시적인 기존 annotation을 읽는다.
`batch-cluster-summary-v0.5`는 산식을 유지하면서 provenance/CSV/decision record에
`evaluation_source=original_saved_evaluation`과 `report_sha256`을 추가했다.
report hash는 `provenance.report_sha256` 자체를 제외한 canonical JSON의 SHA256이다.
과거 v0.4 export는 보존한다.

연구용은 별도 [ResearchReport schema](../contracts/research-overlay-v0.1.schema.json)를 사용한다.
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

[기술 검증 기록](week4-backend-acceptance.md), [공개 sample](examples/week4/README.md)을 참조한다.
CI는 이번 후보 commit의 Ubuntu/Windows Checks를 확인한다. 과거 head의 pass를 옮기지 않는다.
private 원결과 재생성·다른 담당자의 환경 실행·실제 A/B/C 인수·C 화면 대조는 각각 별도 증빙이 필요하다.
