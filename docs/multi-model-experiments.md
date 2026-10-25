# 여러 모델 일괄 실험

하나의 실험 명세로 2–16개 대상 모델에 같은 데이터·방어 조건을 실행한다.
모델마다 독립 배치를 만들고 ASR, 정상 작업 성공률, 정상/hard-negative 오탐률,
지연, 토큰, 비용을 같은 조건의 행으로 비교한다. 프론트엔드는 변경하지 않았다.

## 빠른 검증

실제 API 키 없이 두 로컬 HTTP 모델과 공통 탐지기로 전체 흐름을 검증한다.

```text
python -m scripts.verify_model_experiment --output runs/model-comparison-demo
```

두 모델 × 3개 케이스 × 6개 방어 조건 × 3회 = 108회 실행이다.
한 모델은 공격에 취약하지만 정상 작업을 수행하고, 다른 모델은 합성 비밀을 출력하지 않는
대신 정상 작업에 실패하도록 응답을 고정했다. 두 모델에 다른 합성 단가도 적용한다.
실제 모델 품질이나 실제 가격을 평가하는 검증은 아니다.

검증은 계획 생성, API 키 누락 사전 검사, 5건 실행 후 재개, 중복 호출 방지,
전송 프롬프트 일치, 공통 탐지기, 모델별 보안성·정상 기능·비용 차이,
CLI/API/CSV 일치, 키 없는 저장 결과 조회와 근거 자료 불변을 확인한다.
결과는 출력 폴더의 `verification-report.json`, 비교 파일은 `export/`에 저장한다.

## 실제 모델 설정

[설정 예시](../configs/model-experiment.example.json)를 복사하고 다음 값을 수정한다.

- `models`: 모델별 `model_key`, 실제 `model_id`, `base_url`, `api_key_env`
- `detector`: D2를 사용하는 모든 모델에 적용할 공통 탐지기
- `batch.sources`, `conditions`, `repeats`: 모든 대상 모델에 공유할 실험 설계
- `evaluation_rules_file`: 사후 평가 규칙
- `pricing_file`: 모든 대상 모델과 탐지기의 단가를 포함하는 가격표

HTTP 모델은 기존 OpenAI 호환 Chat Completions 전송 형식을 지원해야 한다.
네이티브 전용 API 형식의 별도 adapter는 포함하지 않는다. 예시의 모델 이름과 endpoint는
자리표시자다. 모델별 생성 파라미터는 따로 지정하지 않고 계획 생성 당시 공통
`MODEL_TEMPERATURE`, `MODEL_MAX_TOKENS`, timeout과 D2 정책을 동결한다.

키 값은 명세에 넣지 않는다. `api_key_env`에는 환경 변수 이름만 기록한다.
저장소 루트의 Git 제외 `.env` 또는 프로세스 환경 변수에 값을 설정한다.

```dotenv
MODEL_A_API_KEY=your-model-a-key
MODEL_B_API_KEY=your-model-b-key
EXPERIMENT_DETECTOR_API_KEY=your-detector-key
```

D2가 포함된 실험은 공통 탐지기와 탐지기 전용 `api_key_env`를 반드시 지정한다.
이는 탐지기를 대상 모델마다 바꾸는 혼동과 대상 모델의 키를 탐지기에 전달하는 일을 막는다.
키가 필요 없는 로컬 탐지기 검증에는 별도의 합성 키를 사용한다. D2가 없는 실험은
`detector`를 생략한다. 실제 키가 필요 없는 대상 HTTP 모델은 `api_key_env`를 생략할 수 있다.

현재 명세는 development split만 지원한다. demo·fixture·실제 모델을 한 실험에 섞지 않는다.
holdout 실행과 최종 서비스 후보 확정은 이 기능의 범위에 포함하지 않는다.

## 계획 생성·실행·재개

```text
python -m scripts.model_experiment create --spec configs/model-experiment.example.json
```

`create`는 모델을 호출하지 않는다. 데이터와 설정을 모델별 배치에 복사하고 공통 해시를
대조한다. 조건 또는 원본 데이터가 복사 도중 달라지면 실험 생성을 거부한다.
출력의 `experiment_id`를 다음 명령의 `EXPERIMENT_ID` 자리에 넣는다.
기본 저장소는 `runs/`이며 전역 `--runs-dir PATH` 옵션을 명령 앞에 지정할 수 있다.

```text
python -m scripts.model_experiment show EXPERIMENT_ID
python -m scripts.model_experiment run EXPERIMENT_ID --max-items 5
python -m scripts.model_experiment run EXPERIMENT_ID
python -m scripts.model_experiment list
```

모델은 명세 순서대로 순차 실행한다. 각 모델 안의 케이스·조건 순서는 같은 seed로 섞는다.
하위 모델이 실행 중이면 상태 API도 `running`을 반환하고, 실제로 중단한 경우에는 `paused`를 반환한다.
`--max-items`는 선택한 모델 전체에서 새로 시도할 실행 수다. 완료된 실행은 재전송하지 않는다.
키는 실행 직전 선택한 미완료 모델 전체에 대해 먼저 검사한다. 뒤 모델의 키가 없다고
앞 모델부터 호출하는 일을 방지한다. 재개는 원래 데이터 경로나 현재 `.env`의 생성 설정이
아닌 동결된 배치 snapshot을 사용하고 키만 환경 변수에서 다시 읽는다.

```text
python -m scripts.model_experiment run EXPERIMENT_ID --models model-b
python -m scripts.model_experiment run EXPERIMENT_ID --retry-failed
python -m scripts.model_experiment run EXPERIMENT_ID --retry-uncertain
python -m scripts.model_experiment run EXPERIMENT_ID --stop-on-error
```

모델 하나의 실패는 기본적으로 다른 모델 실행을 막지 않는다. `--stop-on-error`는 첫 실행
실패에서 멈춘다. 전송 결과를 모르는 `uncertain`은 자동 재호출하지 않고 일괄 실행을 멈춘다.
`--retry-uncertain`은 중복 과금 가능성을 명시적으로 받아들이는 기존 배치 옵션이며 이전
예약을 보존한다. 두 일괄 실행이 같은 실험을 동시에 소유할 수 없고 각 하위 배치도 기존
작성자 잠금을 사용한다.

종료 코드는 성공/조회 `0`, 미완료 실행 `2`, 잘못된 입력·환경·근거 자료 `1`이다.
실행 구현이 바뀌면 재개를 거부하므로 새 실험을 생성한다. 저장된 결과의 조회는 계속 가능하다.

## 유료 API를 사용하는 검증

[`model-experiment.openai-live.json`](../configs/model-experiment.openai-live.json)은 GPT-4.1 mini와
GPT-4.1의 고정 버전, 공통 GPT-4.1 mini 탐지기, 합성 RAG·이메일을 사용한다.
2개 모델 × 2개 앱 × 3개 케이스 × 6개 조건 × 3회 = 216회 실행이다.
키는 기존 `.env`의 `MODEL_API_KEY`와 `D2_API_KEY`에서 읽고 명세에는 저장하지 않는다.
단가는 [GPT-4.1 mini 공식 문서](https://developers.openai.com/api/docs/models/gpt-4.1-mini)와
[GPT-4.1 공식 문서](https://developers.openai.com/api/docs/models/gpt-4.1)를 기준으로
[`pricing-openai-2026-10-25.json`](../configs/pricing-openai-2026-10-25.json)에 고정했다.

```text
python -m scripts.week2_data prepare-email --output runs/model-live-prepared/email
python -m scripts.verify_real_model_experiment --spec configs/model-experiment.openai-live.json --output runs/model-live-verification --max-total-usd 0.96
```

위 검증 도구는 기본적으로 계획과 저장 결과만 검사한다. 새 실험은 `incomplete`/종료 코드 2를
반환하며 모델을 호출하지 않는다. `--execute`를 넣을 때만 유료 호출을 시작한다.
모델 하나당 최대 0.48달러, 두 모델 합계 최대 0.96달러의 예약 한도를 적용한다.
이 금액 제한은 해당 실험의 모든 재시도와 미확인 예약을 포함한다.

```text
python -m scripts.verify_real_model_experiment --spec configs/model-experiment.openai-live.json --output runs/model-live-verification --max-total-usd 0.96 --execute --max-items 4
python -m scripts.verify_real_model_experiment --spec configs/model-experiment.openai-live.json --output runs/model-live-verification --max-total-usd 0.96 --execute
python -m scripts.verify_real_model_experiment --spec configs/model-experiment.openai-live.json --output runs/model-live-verification --max-total-usd 0.96
```

같은 출력 폴더의 checkpoint를 사용하므로 마지막 명령은 새 호출 없이 재검증한다.
실행 중 오류가 나면 멈추고 실패한 실행을 자동 재시도하지 않는다. 같은 명세·구현에서
오류 원인을 해결한 뒤 `--execute --retry-failed`로 명시적으로 재시도할 수 있다.
전송 결과가 불확실한 실행은 별도 `--retry-uncertain`이 필요하며 이전 예약을 보존한다.

검증은 원시 응답·공개 trace·예약 ledger 사이의 모델/호출 수·실제 HTTP 상태·관측 토큰·
추정 비용을 대조한다. 모델 간 실제 전송된 메시지와 파라미터도 공통 실행 단위별로 비교한다.
탐지 결과로 한쪽만 생성하지 않은 실행은 별도로 집계한다. JSON/CSV·API 및 모든 실제 trace를
재조회하는 동안 모델 전송 함수는 차단하므로 조회로 추가 요금이 발생하지 않는다.
실험 생성 시점의 평가 규칙과 draft/수동 검토 상태를 유지하며 사람이 독립 검토하거나
모델의 품질 우열을 확정한 결과로 해석하지 않는다.

## 예산과 비용

`batch.budget`은 **모델 하나당** 예산이다. 모델 사이에 남은 예산을 옮기지 않는다.
계획 응답은 모델별 제한과 전체 최대 호출 수·예약 토큰·금액을 함께 제공한다.
예를 들어 2개 모델에 `max_calls=180`이면 전체 최대 호출 수는 360이다.
시간 제한은 모델별 실행 시간이며 `max_execution_seconds_sum`은 그 합계이고, 계획·보고서
생성과 프로세스 기동 시간을 포함한 전체 벽시계 제한은 아니다.

기존의 호출 전 예약, 오류·재시도 비용 포함, 알 수 없는 사용량의 예약 유지 규칙을 재사용한다.
금액 상한은 검증된 모델·탐지기 단가가 모두 있어야 보장한다. `unknown_price_policy=calls_tokens`는
호출·토큰만 제한한다. 가격표가 없거나 사용량이 미확인이면 비용은 `null`로 남기며 0원으로
취급하지 않는다. 가격표를 넣어도 계산 결과는 고정 단가에 따른 추정 비용이다.

## 비교 리포트·API

```text
python -m scripts.model_experiment report EXPERIMENT_ID
python -m scripts.model_experiment report EXPERIMENT_ID --filters filters.json
python -m scripts.model_experiment export EXPERIMENT_ID --output runs/model-comparison-export
```

보고서와 export는 키·현재 모델 설정 없이 저장 결과만 읽으며 추가 모델 호출은 없다.
`filters.json`은 기존 `BatchFilters` 계약을 사용한다. 빈 문자열도 필터로 보존한다.
내보내기는 새 디렉터리만 허용하고 다음 세 파일을 완성한 후 게시한다.

- `report.json`: 모델별 지표·분모·제외 사유·정상 benchmark 참조·예산·원평가 보고서 해시
- `metrics.csv`: 같은 지표와 보고서 해시, 빈 선택에도 남는 metadata 행
- `export-manifest.json`: JSON/CSV 파일 해시와 원본 자료 inventory 해시

기존 API 서버에서 다음 읽기 전용 경로를 제공한다. 실행은 명시적인 로컬 CLI로 수행한다.

| 메서드 | 경로 | 내용 |
| --- | --- | --- |
| GET | `/api/v1/model-experiments` | 실험 목록 |
| GET | `/api/v1/model-experiments/{id}` | 모델별 진행·예산과 전체 합계 |
| POST | `/api/v1/model-experiments/{id}/report` | 필터를 적용한 비교 JSON |
| POST | `/api/v1/model-experiments/{id}/export.csv` | 동일 보고서의 CSV |

POST 본문에는 `{}` 또는 필터 객체를 보낸다. CSV의 `X-Report-SHA256` 헤더로 JSON과
같은 보고서인지 확인할 수 있다. ID 형식 오류는 422, 없는 실험은 404,
손상·변경된 근거는 `INVALID_MODEL_EXPERIMENT` 코드와 422를 반환한다.
읽는 도중 근거 파일이 달라져도 불완전한 비교 결과를 반환하지 않는다.

비교는 같은 source·조건·목표·언어·평가/가격 버전끼리 연결하고 각 모델의 분모와
제외 사유를 유지한다. 정상 기능과 오탐은 해당 조건의 정상 benchmark를 참조한다.
정상 benchmark를 여러 공격 목표가 공유해도 독립 표본으로 합산하지 않는다.
미평가 결과·없는 가격·검토 대기 항목은 `null`과 제외 사유로 표시한다.
하위 배치의 `run_id`로 평가·gold를 등록하고 `batch_id`와 `run_id`로 과잉 변형 검토를
등록하면 비교에도 반영된다.

이는 기술 비교 리포트이며 모델 간 paired 유의성 검정이나 자동 최종 순위를 제공하지 않는다.
모델 순서에 따른 시간 변화·제공자 캐시·환경 차이는 지연 비교에 영향을 줄 수 있다.
실행 계약과 기존 배치 계약은 유지하고 새 계약은
[`model-experiment-v0.1.schema.json`](../contracts/model-experiment-v0.1.schema.json)으로 분리했다.

## 개발 검증 기록

2026-10-25, macOS arm64 / Python 3.11.17에서 다음을 확인했다.

| 검증 | 결과 |
| --- | --- |
| 백엔드 전체 회귀 | 160개 통과, 새 모델 실험 테스트 15개 포함 |
| 프로젝트 전체 회귀 | 239개 통과 |
| 두 모델 통합 실행 | 108회 실행, 로컬 HTTP 호출 198회 |
| 같은 프롬프트·공통 탐지기·키 분리 | 통과 |
| 재개 중복 호출·키 누락 시 호출·조회 시 호출 | 모두 0회 |
| 다른 응답과 합성 단가의 보안성·정상 기능·비용 차이 | 보존 |
| CLI/API/JSON/CSV 및 빈 필터·원본 자료 유지 | 일치 |
| 잘못된 실제 모델 환경 설정을 주입한 fixture 검증 | 통과 |

로컬 결과는 `runs/model-experiment-development/isolated-final/verification-report.json`에 있다.
위 fixture 검증은 유료 모델을 호출하지 않는다. 후속 실제 API 검증과 수정 기록은 아래와 같다.

## 실제 API 검증 결과와 보완

2026-10-25 실제 OpenAI API에서 216회 본 실험을 완료했다.
[공개 검증 기록](examples/model-experiment-live/verification-report.json)은 입력·원시 응답·키를
포함하지 않고 실행 수, 관측 토큰, 추정 비용, HTTP 상태와 근거 해시를 제공한다.
원시 자료와 마스킹된 전체 보고서는 Git 제외 `runs/real-model-experiment-20261025/`에 보관한다.

| 대상 모델 | 실제 API 호출 | 관측 입력/출력 토큰 | 본 실험 추정 비용 |
| --- | ---: | ---: | ---: |
| GPT-4.1 mini | 198 | 50,739 / 13,277 | $0.0415388 |
| GPT-4.1 | 198 | 50,739 / 13,542 | $0.1483852 |

각 행의 토큰·비용은 해당 대상 모델 배치의 생성 호출과 공통 D2 탐지기 호출을 모두 포함한다.
공개 검증 JSON에는 실제 호출 모델·용도별 사용량과 비용도 분리해 기록했다.

본 실험 396개 호출은 모두 HTTP 200이며, 미확인 호출·API 오류·중복 실행은 0개다.
실제 전송 메시지·파라미터 198쌍이 모델 간 일치한다. 4개 실행에서 중단한 뒤 같은
checkpoint로 재개했고, 완료 후 실행 명령을 다시 호출해도 추가 모델 호출이 없음을 확인했다.
API·JSON·CSV·공개 trace 재조회도 원본 자료 변경과 추가 호출 없이 일치한다.

예비 인증/호환성 2회와 상태 수정 후 확인 2회를 합하면 실제 호출은 총 400회다.
전체 사용량 기준 추정 비용은 $0.1918584로 설정한 $1 상한 이내다.
이 값은 동결된 표준 비캐시 단가에 따른 추정치이며 계정 청구서를 조회한 값은 아니다.
정상 작업의 의미 평가·독립 사람 검토 대기 상태는 기존 정책대로 유지했다.
이 소형 dev 검증으로 모델 품질 순위나 holdout 결론을 확정하지 않는다.

실검증 중 발견하고 수정한 항목은 다음과 같다.

- 비공개 raw 파일명 요청은 엄격한 ID 검증으로 422를 반환하지만 기존 CI는 404만 기대했다.
  원시 파일 접근을 계속 금지하면서 두 거부 응답을 검증하고 응답의 canary 노출도 검사한다.
- `--retry-failed --stop-on-error`가 실패 항목을 재시도하지 않고 즉시 반환하던 문제를 수정했다.
  이전 실패·비용 예약은 보존하며 명시적으로 허용한 재시도만 수행한다.
- 실행 중인 하위 배치를 실험 요약이 `paused`로 표시하던 문제를 수정했다.
  두 실제 모델의 HTTP 응답을 받는 시점에 요약과 상태 API가 모두 `running`을 반환함을 확인했다.

최종 로컬 회귀는 백엔드 163개와 프로젝트 243개, 합계 406개가 통과했다.
기존 CI 계약 수정 커밋 `ce170f8`의 [Ubuntu/Windows 실행](https://github.com/zerolong-01/sec_sea/actions/runs/40168211827)은
두 운영체제에서 모두 통과했다. 최신 커밋의 원격 검증 상태는 PR #53에서 확인한다.
