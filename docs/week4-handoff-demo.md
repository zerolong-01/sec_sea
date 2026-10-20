# 4주차 인계·저장 결과 시연 안내

2026-10-20 기준이다. PR [#39](https://github.com/zerolong-01/sec_sea/pull/39)의 작업 브랜치를 사용한다.
작성 시 PR은 **draft·base dev이며 아직 dev에 병합되지 않았다**. dev에 이미 같은 코드가 있다고 가정하지 않는다.
`63ef871`의 [Ubuntu·Windows CI](https://github.com/zerolong-01/sec_sea/actions/runs/39428651601)는 통과했다.
이후 commit의 결과는 해당 PR Checks에서 별도로 확인한다.

[공개 실행 요약](examples/week3-completion/README.md), [수치·해시 JSON](examples/week3-completion/summary.v0.4.json),
[대표 사례 catalog](examples/week3-completion/case-handoff.v0.4.json), [전체 요구사항 대조표](week3-completion-status.md)를 함께 인계한다.
이 안내는 저장 결과 조회용이다. 새 배치 실행·재시도·평가 등록은 시연에 포함하지 않는다.

## 이번에 보여 줄 실험

| cohort | batch_id | 종료 수 | 생성 / 차단 / 오류 | 고유 조건·반복 | 모델 호출 / 추정 USD |
| --- | --- | ---: | ---: | --- | ---: |
| 기존 RAG·이메일 payload/정상 대조 | `batch-bd093a919251` | 324 | 251 / 73 / 0 | 6조건·3회 | 557 / 0.1022296 |
| 새 original/quoted 대조 | `batch-8fb19849d67c` | 108 | 85 / 23 / 0 | 6조건·3회 | 184 / 0.0373288 |
| 새 D2 6기법/quoted 대조 | `batch-fb671ff629f0` | 216 | 180 / 36 / 0 | 6조건·3회 | 396 / 0.0754176 |

총 648개 저장 실행을 세 cohort로 구별한다. 서로 다른 입력·목표·분모를 한 ASR로 합치지 않는다.
별도 942개 탐색 감사는 이 표에 포함하지 않는다. 비용은 관측 토큰과 동결 가격을 적용한 추정치다.
6개 조건은 none, D1, D2 양쪽, D1+D2 양쪽, D2 입력, D2 검색이다. 같은 D2 양쪽 실행을 비교마다 중복 호출하지 않았다.

## 실행 준비와 포트

명령은 `.venv`, `scripts`, `backend`, `frontend`가 있는 저장소 루트에서 실행한다.
무시되는 로컬 `runs/`가 있어야 실제 배치를 열 수 있다. Git checkout만으로 원시 실행 자료가 생기지는 않는다.
`.env`·키·원시 출력 파일을 화면에 출력할 필요가 없다.

기존 8000/8501 프로세스는 그대로 둔다. 아래 명령은 **새 터미널**에서 별도 포트로 실행한다.
포트가 사용 중이면 다른 `--api-port`·`--ui-port`를 선택한다. 실행기는 충돌 시 오류를 내며 기존 서비스를 종료하지 않는다.
`Ctrl+C`는 이 명령으로 시작한 자식 서비스만 정리한다.

| 볼 cohort | runs 디렉터리 | source ID | 예시 API / UI 포트 |
| --- | --- | --- | --- |
| quotation | `runs/week3-completion/quoted-execution-v0.4/runs` | `quote_controls` | 8001 / 8502 |
| D2 | `runs/week3-completion/d2-execution-v0.4/runs` | `d2controls` | 8003 / 8504 |
| legacy | `runs/week3-live-2026-10-20/runs` | `week3` + `email` | 8005 / 8506 |

새 quotation/D2의 간단한 checkpoint는 기존 pipeline 형식과 다르므로 `--pipeline-output`을 사용하지 않는다.
실제 동결 source에 `--data-dir`·`--manifest`, 저장소에 `--runs-dir`, 각 설정에 환경변수를 지정한다.
아래 조회 프로필은 `.env` 자동 로드를 끄고 외부 모델 연결을 비워 둔다.
저장 배치의 real/model 표시는 해당 배치 manifest에서 계속 읽는다. 새 단건 실행 버튼은 사용하지 않는다.

### Git Bash: quotation 열기

```bash
demo_store="runs/week3-completion/quoted-execution-v0.4/runs"
demo_batch="batch-8fb19849d67c"
demo_source="quote_controls"
demo_api_port=8001
demo_ui_port=8502
demo_snapshot="$demo_store/batches/$demo_batch"
demo_data="$demo_snapshot/inputs/$demo_source"

export MVP_LOAD_DOTENV=0 MODEL_PROVIDER=demo MODEL_ID=demo-rag-v0.1
export MODEL_BASE_URL="" D2_BASE_URL=""
export EVALUATION_RULES_FILE="$demo_snapshot/evaluation_rules.snapshot"
export PRICING_FILE="$demo_snapshot/pricing.snapshot"
export COMMON_POLICY_FILE="$demo_snapshot/common_policy.snapshot"

./.venv/Scripts/python.exe -m scripts.mvp serve \
  --data-dir "$demo_data" --manifest "$demo_data/mvp-manifest.v0.1.json" \
  --runs-dir "$demo_store" --api-port "$demo_api_port" --ui-port "$demo_ui_port"
```

D2를 열 때는 새 터미널에서 위 첫 다섯 줄을 다음 값으로 바꾸고 나머지 줄을 실행한다.

```bash
demo_store="runs/week3-completion/d2-execution-v0.4/runs"
demo_batch="batch-fb671ff629f0"
demo_source="d2controls"
demo_api_port=8003
demo_ui_port=8504
```

### PowerShell: quotation 열기

```powershell
$demoStore = "runs/week3-completion/quoted-execution-v0.4/runs"
$demoBatch = "batch-8fb19849d67c"
$demoSource = "quote_controls"
$demoApiPort = 8001
$demoUiPort = 8502
$demoSnapshot = "$demoStore/batches/$demoBatch"
$demoData = "$demoSnapshot/inputs/$demoSource"

$env:MVP_LOAD_DOTENV = "0"
$env:MODEL_PROVIDER = "demo"
$env:MODEL_ID = "demo-rag-v0.1"
$env:MODEL_BASE_URL = ""
$env:D2_BASE_URL = ""
$env:EVALUATION_RULES_FILE = "$demoSnapshot/evaluation_rules.snapshot"
$env:PRICING_FILE = "$demoSnapshot/pricing.snapshot"
$env:COMMON_POLICY_FILE = "$demoSnapshot/common_policy.snapshot"

& .\.venv\Scripts\python.exe -m scripts.mvp serve --data-dir $demoData --manifest "$demoData/mvp-manifest.v0.1.json" --runs-dir $demoStore --api-port $demoApiPort --ui-port $demoUiPort
```

D2는 새 터미널에서 첫 다섯 줄을 다음 값으로 바꾼다.

```powershell
$demoStore = "runs/week3-completion/d2-execution-v0.4/runs"
$demoBatch = "batch-fb671ff629f0"
$demoSource = "d2controls"
$demoApiPort = 8003
$demoUiPort = 8504
```

Git Bash에서는 `export`, PowerShell에서는 `$env:...`를 사용한다. 명령 끝에 `~`를 붙이지 않는다.
경로 변수는 공백·한글이 있는 작업 디렉터리에서도 인자로 유지되도록 따옴표를 사용한다.

### 기존 RAG·이메일 배치 열기

위와 같은 조회용 환경을 설정한 터미널에서 기존 pipeline 전용 옵션을 쓴다.

```bash
./.venv/Scripts/python.exe -m scripts.mvp serve --pipeline-output runs/week3-live-2026-10-20 --api-port 8005 --ui-port 8506
```

```powershell
& .\.venv\Scripts\python.exe -m scripts.mvp serve --pipeline-output runs/week3-live-2026-10-20 --api-port 8005 --ui-port 8506
```

이 옵션은 동결 source·규칙·가격·공통 정책을 연결한다. `--data-dir`·`--manifest`·`--runs-dir`과 함께 쓰지 않는다.
서버 준비 후 표시된 UI 주소를 열고 왼쪽 **배치 대시보드 → 볼 배치**에서 위 batch_id를 선택한다.
quotation은 `http://127.0.0.1:8502`, D2는 `http://127.0.0.1:8504`, legacy는 `http://127.0.0.1:8506`이다.

## 약 5분 시연 순서

| 순서 | 화면·자료 | 확인하고 설명할 내용 |
| --- | --- | --- |
| 1 | 배치 목록·상세 | batch_id, real, 계획/시도/생성/차단/오류, 앱과 frozen 버전을 확인한다. blocked는 정상 응답 미전달이며 실행 오류와 다르다. |
| 2 | 지표 요약·무방어 대비 변화 | 같은 앱·목표·버전·조건으로 필터하고 분자/분모·제외를 읽는다. ASR을 전부 0이라고 설명하지 않는다. 비밀 유출과 알려진 marker 이행은 목표가 다르다. |
| 3 | D2 탐지·payload | 실제 검사 stage·gold 버전·eligible/error/review/missing을 확인한다. 새 D2 retrieval의 유효 미탐은 각 그룹6/18, HN FPR0/18이며 최종 생성 성공률과 별개다. |
| 4 | 추천 근거·Trade-off | 서버의 탈락/보류 사유와 정책·표본을 확인한다. 점 색은 **방어 조건**, 모양은 앱, 크기는 확인 비용, 빈 점은 비용 미확인이다. 흐린 점은 CI 표본 부족이며 후보 상태의 색이 아니다. |
| 5 | 대표 사례 catalog → 실행 trace | catalog의 batch_id·run_id·조건·반복·판정 근거를 고른 뒤 해당 그룹의 실행 번호를 선택해 trace 조회한다. 마스킹된 출력·문서 포함 여부·실제 방어 사건을 확인한다. |
| 6 | 같은 필터 export·병렬 연구 자료 | 화면 JSON/CSV와 그 evaluation snapshot을 맞추고 아래 별도 AI/기계 관측 자료를 나란히 설명한다. 다른 cohort·새 판정 버전을 섞지 않는다. |

조건 불일치·결과 없음·미평가·부분 완료·비용 미확인은 각각 화면의 경고와 분모로 설명한다.
필터나 평가 snapshot이 바뀌면 이전 CSV·trace를 그대로 시연하지 말고 새로 조회한다.
산점도에 필요한 값이 없으면 제외 사유가 나온다. 점이 없거나 CI가 null인 것을 성능 0으로 바꾸지 않는다.

## 원래 UI 평가와 별도 연구 검토를 병렬로 보여 주기

대시보드는 원래 저장 평가·명시적 후속 annotation을 소비한다.
새 AI 정상 작업 검토와 posthoc paired exact overlay는 **원래 evaluation에 자동 적용하지 않았다**.
현재 quotation/D2 common report의 task_success 분모는 0이고 target_exposure_rate는 null이다.
따라서 아래 AI 수치를 대시보드가 이미 모두 보여 준다고 설명하지 않는다.

| 별도 연구 자료 | 정상 대조군 판정·해석 |
| --- | --- |
| [기존324 출력 검토](week3-output-review.md) | 정상170/179, 미확정1. 과거 자동 평가·전체 성능 분모와 별도로 읽는다. |
| [quotation108 출력 검토](week3-quotation-output-review.md) | quoted54/54 정상 성공, attack 아래 업무18/54. a021 original의 실제 비공개 값 공개10건과 강제 판정 JSON 이행을 구별한다. |
| [D2 216 출력 검토](week3-d2-output-review.md) | quoted60/108 성공·48실패, attack 아래6/108. 알려진 표식 추가102건과 한 문장 형식 실패를 구별하며 비밀 탈취라고 부르지 않는다. |
| [paired exact 관측](week3-control-observations.md) | quotation54쌍·D2 108쌍, 각 부모3family. exact literal 관측과 AI 의미 판정을 별도 지위로 표시한다. |

[대표 사례 catalog](examples/week3-completion/case-handoff.v0.4.json)는 성공·정상 기능 실패·과잉 차단·보류의
구체 run과 마스킹 증거를 연결한다. 대표 사례는 목적에 따라 고른 기술 사례이며 전체 빈도나 인과 효과를 대신하지 않는다.
탐지 오류·모순의 기능 검증은 [명시적 fixture](examples/d2-security/README.md)로 구분한다.
실제 세 cohort의 오류가 0인 상황에서 fixture를 실제 발생 사례로 소개하지 않는다.

서버를 열지 않고도 공개 요약·검토 문서·catalog를 읽을 수 있다.
필요하면 `scripts.week3_research_report`로 새 output 경로에 저장 결과를 재검증한다.
각 [quotation](week3-quotation-output-review.md)·[D2](week3-d2-output-review.md) 문서의 CLI를 따르며 이미 존재하는 output을 덮어쓰지 않는다.
저장 조회·필터·GET trace·export·연구 report 재생은 모델 호출 0이다. `serve`는 서비스 로그를 별도 디렉터리에 남긴다.

## 4주차 인계할 판단과 미검증 범위

dev 서비스 기준·정상 rubric·반복3·최소family20/판정60·bootstrap10000은 사용자 위임으로 **adopted_for_dev**다.
runtime draft와 빈 사람 reviewer는 수치 미정을 뜻하지 않는다. 옛324의 frozen 정책은 당시 값으로 보존하고
새108/216은 새 연구 정책을 동결했다. 연구 overlay의 rubric·정책 버전도 원래 자동 평가와 구별한다.

보호값 공개·정상 작업 실패가 실제 관측됐고 새 실험은 각각3family이므로 최종 선택은 deferred다.
6기법·반복·case 변형을 새 독립 family로 늘리지 않는다. exact 부재는 모든 변환·부분·추론 유출 부재의 증명이 아니다.

[독립 검토 인계 index](examples/week3-completion/review-handoff.v0.4.json)에는 3개 private packet,
정상 출력648·탐지 대상621의 총1269task가 있다. 실제 두 사람 응답·세 역할 합의는 pending이고 applied=false다.
사람 이름·역할 template를 서명으로 간주하지 않는다. holdout은 보존하며 최종 운영 승인·확증 통계 결론은 미완료다.
4주차에는 이 기록에서 검토·개선·새 실험의 범위를 정하고, 이미 실행한 dev 결과의 기준을 소급 변경하지 않는다.
