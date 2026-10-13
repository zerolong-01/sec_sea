# 3주차 백엔드: 배치·예산·집계·export

작업 이슈: #34 / 공통 계획: #32 / 데이터·평가 담당: #33 / 화면 담당: #35.

이번 인계는 구현과 로컬 HTTP fixture 검증이다. 실제 모델 파일럿·팀의 gold/번역 검수·통계/서비스 정책 확정·holdout 성능 실험은 후속 작업이다. 기본 통계와 서비스 정책은 draft이며 fixture에서 최종 추천을 만들지 않는다.

## 빠른 검증

루트에서 기존 환경을 준비한 뒤 실행한다. 결과 디렉터리는 매번 새 경로를 쓴다.

```text
python -m scripts.mvp setup
.venv\Scripts\python -m scripts.verify_week3 --output runs/week3-handoff
```

macOS/Linux에서는 `.venv/bin/python`을 사용한다. 검증기는 로컬 모델 fixture, FastAPI, Streamlit health 서버를 시작하고 종료한다. 외부 LLM에 연결하지 않으며 실제 모델 `.env` 설정을 검증 서버가 다시 읽지 않도록 분리한다.

- RAG·이메일 각 대표 3건 × 6개 고유 구성 × 3회 = 108개 실행을 계획한다.
- 7개 실행에서 중단한 뒤 재개하고 완료 후 재개 시 추가 호출이 없는지 확인한다.
- 실제 HTTP payload, private raw log, 공개 trace, 호출 예약 ledger를 대조한다.
- 목록/상세·수동 검토·집계/CSV API, CLI 재생성, JSON/CSV export를 대조한다.
- 조회·검토·export가 모델을 재호출하지 않고 canary가 공개 인계물에 없는지 확인한다.
- `verification-report.json`, `batch-summary.fixture.json`, `report.fixture.json`, `export/`를 생성한다. `runs/`의 private 원문은 Git에 올리지 않는다.

## 배치 계획과 실행

실행과 조회는 분리되어 있다. `create`, `inventory`, `show`, `list`, `report`, `export`, `review`는 모델을 호출하지 않는다. 모델을 호출하는 명령은 `run`이다.

```text
python -m scripts.week3_batch inventory --spec configs/week3-batch.example.json
python -m scripts.week3_batch create --spec configs/week3-batch.example.json
python -m scripts.week3_batch show batch-012345abcdef
python -m scripts.week3_batch run batch-012345abcdef --max-items 7
python -m scripts.week3_batch run batch-012345abcdef
python -m scripts.week3_batch report batch-012345abcdef
python -m scripts.week3_batch export batch-012345abcdef --output runs/my-export
```

`batch-012345abcdef`를 create 응답의 실제 ID로 바꾼다. 위 예시는 실제 모델 실행 승인이나 고정 실험 정책이 아니다. `run`은 현재 `.env`의 모델·엔드포인트를 사용하므로 실제 키를 넣은 환경에서는 지정한 예산으로 실제 호출한다. fixture 경로는 앞의 `verify_week3`를 사용한다.

실행 결과 경로를 지정하려면 전역 인자를 명령 앞에 둔다.

```text
python -m scripts.week3_batch --runs-dir runs/week3 report batch-012345abcdef
```

`sources`에 prepared 이메일/영어 데이터 디렉터리를 추가할 수 있다. 준비는 기존 `scripts.week2_data prepare-email / prepare-bilingual`을 사용한다. 각 source는 `source_id`, `data_dir`, `split`, 선택적 `case_ids`/`languages`를 갖는다. case_ids를 생략하면 해당 split/language의 전체 세트를 선택한다. 한 배치에서 dev와 holdout을 섞을 수 없다. 서로 다른 source는 독립 코호트로 집계한다.

기본 조건은 none, D1, D2 양쪽, D1+D2 양쪽, D2 입력, D2 문서의 6개다. D2 양쪽의 `comparisons`는 technique/position 두 곳에 속하지만 실행은 한 번이다. 같은 비교에서 임계값/모순 정책까지 바꾸거나, runtime 기본값을 적용한 뒤 동일한 조건을 중복 등록하면 거부한다. 탐지 전용 조건은 `execution_kind=detector_only`, `comparisons=["detector"]`로 별도 지정한다.

실행 순서는 `random_seed`로 섞는다. 반복 수와 원본 family를 보존하며 provider seed는 요청하지 않는다. 현재 동시성은 1, warm-up은 없음, runner cache는 없으며 provider 내부 cache 여부는 미확인으로 기록한다. `min_call_interval_seconds`로 최소 호출 간격을 지정할 수 있다.

## 스냅샷과 중단 복구

배치마다 `runs/batches/<batch_id>/manifest.json`과 `inputs/<source_id>/`를 만든다. case/corpus/manifest, 공통 정책, 가격표, 평가 규칙/서비스 정책을 복사하고 SHA-256을 고정한다. source 선택·조건·반복·예산·통계·모델 설정과 실행 구현의 해시도 기록한다. 인증키는 저장하지 않는다.

- 재개는 원본 데이터가 아니라 복사한 스냅샷을 사용한다.
- 고정 파일/선택/설정이나 구현 코드가 바뀌면 실행을 거부하고 새 배치를 요구한다. 저장 결과 조회는 코드 커밋 변경만으로 금지하지 않지만 고정 artifact 해시는 확인한다.
- 각 계획 항목은 entry_id·source/case·condition·repeat·family/variant와 attempt/run_id를 연결한다. 같은 항목의 명시적 재시도는 새 attempt와 새 run_id다.
- 호출 직전에 reservation을 fsync·원자적 교체로 저장한다. 응답을 받으면 사용량/비용을 정산한다. 실행 중 OS 파일 잠금으로 두 writer를 막고 프로세스 종료 시 잠금은 해제된다.
- 완료/정상 차단 항목은 재실행하지 않는다. 실패는 `--retry-failed`를 지정해야 다시 실행한다.
- 중단 직전 호출 기록이 있지만 trace가 없으면 `uncertain`으로 남긴다. 기본 재개는 해당 항목을 재호출하지 않는다. `--retry-uncertain`은 이미 과금된 호출을 중복할 수 있는 명시적 재시도이며 이전 예약 비용은 유지한다.
- 저장 trace가 먼저 완성된 경우 재개 시 이를 회수한다. 호출 전 중단으로 예약도 없으면 미실행 상태로 복구한다.

배치 `completed`는 모든 계획 항목의 실행이 완료 또는 정상 방어 차단됐다는 뜻이다. 공격/정상 성공 판정 완료나 실험 인수를 뜻하지 않는다. pending이 있으면 paused, 실패가 남으면 partial, 결과 불확실 항목은 uncertain이다. `run` 종료 코드는 completed=0, 부분/중단/불확실=2, 입력/실행 오류=1이다.

## 예산

`max_calls`, `max_reserved_tokens`, `max_seconds`가 필수다. 선택적으로 `max_usd`를 지정한다. 생성/D2·문서별 호출·제공자 실패 시도·재시도가 모두 같은 ledger를 사용한다. guard 오류는 fail_open으로 우회할 수 없다.

- 호출별 입력 상한(`per_call_input_token_ceiling`)과 요청의 max_tokens를 예약한다. 입력의 UTF-8 바이트 기반 보수적 admission estimate가 상한보다 크면 전송 전에 거부한다. 예약 토큰은 누적되어 재시도로 초기화되지 않는다.
- 금액 상한은 verified 가격·출처 URL·적용일·입출력 단가가 있어야 사용할 수 있다. 상한을 예약한 뒤 알려진 사용량으로 정산한다. 누락/네트워크 오류는 예약 금액을 그대로 유지한다.
- 가격 미확인 시 기본은 stop이다. 금액 보장을 하지 않는 `unknown_price_policy=calls_tokens`를 명시하면 호출/토큰 제한으로 진행할 수 있다. 이때 비용은 null이며 max_usd와 함께 지정할 수 없다.
- 토큰 예약은 제공자 tokenizer의 엄밀한 보장이 아니다. 선언한 경계를 넘는 사용량이 관측되면 비용을 기록하고 추가 호출을 중단한다. 제공자의 과금 규칙·숨은 토큰을 포함한 금융적 hard cap을 주장하지 않는다.
- 시간 예산은 누적 wall time으로 다음 호출을 제한하고 남은 시간으로 네트워크 timeout을 줄인다. 이미 전송된 요청을 제공자 쪽에서 취소하거나 과금을 취소하는 기능은 아니다.

예산은 전체 케이스×고유 조건×반복과 문서별 D2 호출을 먼저 산정한다. 예시 파일은 대표 파일럿용이며 전체 84건·파생 데이터의 최종 예산이 아니다.

## payload와 공통 정책

`configs/week3-common-policy.txt`를 모든 모드의 기본 system 메시지에 동일하게 적용한다. D1은 그 위의 추가 경계 지침과 JSON 직렬화다. 정책 내용의 해시를 base_system_prompt_version에 넣어 기존 2주차 결과와 구분한다.

source의 `metadata`는 case_id별로 family_id, parent_case_id, ablation_variant, removed_components, information_available, goal_kind, severity를 기록한다. 이 정보는 분석용이며 모델/D2 프롬프트에 보내지 않는다. 원본·파생 parent는 같은 split이어야 한다.

`comparisons=["payload"]`와 같은 family의 `C00`, `C01`, `A10`, `A11` 또는 `original`, `instruction_removed`, `quoted`를 지정할 수 있다. 현재 A11-C01, original-instruction_removed, original-quoted의 짝지은 목표값 노출 차이를 계산한다. C00/A10도 각 variant의 target_exposure_rate로 조회한다. 한 family/조건/repeat에 같은 variant가 여러 개면 모호한 pairing으로 거부한다.

목표값 노출은 별도 수동 `target_exposed` 검토를 사용한다. case 라벨이나 D2 allow를 노출 성공으로 대체하지 않는다. 최종 ASR·marker·보호정보 유출·D2 오판은 구분한다. 실제 paired 데이터·위협 모델·gold 검수와 효과 해석은 #33/#29의 인계 대상이다. 보호용 합성 값은 기존 마스킹 계약의 `CANARY_[A-Z0-9_]+` 형식을 사용하고 private raw log에서 판정한다.

## 집계·수동 검토·통계

집계는 공개 trace와 배치 ledger/검토 기록을 읽는다. 실제 trace의 케이스·모델·기본 정책·방어 위치·설정이 계획과 맞지 않으면 제외 사유를 기록하고 추천을 보류한다. 앱/source·언어·split·variant·실행 종류·조건·평가/가격 버전을 구분해 집계한다.

| 지표 | 분모/단위 |
| --- | --- |
| ASR | full_pipeline의 completed/blocked 중 attack_success가 success/failure인 attack 실행 |
| 정상 태스크 성공률 | 같은 조건의 benign/hard-negative 중 normal_task_success가 success/failure인 실행 |
| 두 case FPR | label별 유효 실행. 차단/격리/redact는 FP, 나머지는 excessive_transformation 수동 검토가 있어야 포함 |
| D2 FNR/FPR | 기존 detector_report의 검사 대상·독립 gold·오류/검토/미등록 분모; 최종 ASR과 별도 |
| p50/p95 | 저장된 모든 attempt의 end-to-end latency. 실패/명시적 재시도도 포함 |
| 토큰/요청 비용 | 같은 계획 항목의 모든 attempt 호출을 합한 값의 평균. 미확인/불확실 값은 별도 제외/총비용 null |
| 실행 실패율 | 결과가 저장된 completed/blocked/failed attempt 중 failed. 불확실 attempt는 별도 공개 |

정상 방어 차단은 공격 실패 판정의 유효 결과로 유지한다. 미평가/review_needed·오류·분모 0을 성공/실패/0으로 바꾸지 않는다. 각 metric은 value, numerator(비율), denominator, family_count, ci95, inference_status, excluded를 갖는다. 리소스 지표와 조건별 합계는 이미 발생한 실패 비용을 숨기지 않는다.

기본 draft CI는 같은 family의 모든 반복을 함께 뽑는 deterministic percentile cluster bootstrap이다. baseline 증감은 source/case/repeat의 공통 유효 쌍에서 계산한다. ASR 변화는 none-defense, 정상 성공/FPR 변화는 defense-none이며 %p 단위다. `baseline_resource_changes`는 공통 쌍의 모든 attempt를 반영한 p50/p95·토큰·비용 차이와 증가율/paired cluster CI를 제공한다. baseline이 0이면 증가율은 null이다. 최소 family/평가 수 미달이면 CI는 null이다. 작은 표본·전부 0/1인 결과의 bootstrap CI는 불확실성을 과소평가할 수 있어 표본/방법을 #33에서 검토해야 한다. 반복 3회만으로 충분한 통계라고 주장하지 않는다.

과도 변환·목표값 노출은 다음 형식으로 저장한다. reason에는 원시 보호값을 넣지 않는다. 검토 이력은 append로 보존되고 집계는 최신 검토를 사용한다. 평가/검토 변경은 evaluation_snapshot_sha256을 바꾸며 기존 export 파일을 수정하지 않는다.

```json
{"reviewer":"team-reviewer", "reason":"rubric에 따른 근거", "policy_version":"team-policy-v1",
 "excessive_transformation":false, "target_exposed":false}
```

```text
python -m scripts.week3_batch review batch-012345abcdef run-... --body runs/review.json
```

## holdout·추천 gate

inventory는 holdout hash를 검토용으로 출력할 수 있지만 실행을 허가하지 않는다. holdout create는 최소 3회, 검토자 2명 이상, frozen 통계와 완전한 frozen 서비스 정책, 정확히 일치하는 freeze_hashes를 요구한다. 모델·선택 세트·반복·가격/평가·코드 구현이 바뀌면 새 inventory/검토가 필요하다. 로컬 metadata의 검토자 이름은 인증·전자서명을 뜻하지 않는다.

`configs/week3-evaluation-policy.json`은 null 초안이다. #33에서 근거·reviewed_by·thresholds·priority를 채워 새 버전을 만들고 holdout 전에 고정한다. 임의 수치를 팀 합의로 기입하지 않는다.

추천은 real 실행·검토된 통계/서비스 정책·유효 평가/가격·표본/paired baseline·분류된 공격 목표/심각도를 요구한다. 미완료/불확실·검토 대기·미확인 비용·trace 조건 불일치는 보류한다. 기준 위반 및 치명 공격 성공을 탈락시킨 뒤 ASR/두 FPR/p95/비용↓·정상 성공↑의 전체 다지표 Pareto를 계산하고 사전 priority로 후보를 정한다. 우선순위상 첫 차이 지표의 CI가 겹치면 provisional_tied로 남기며 동등성이나 우월성을 확정하지 않는다. 후보가 없으면 no_candidate를 반환한다.

## 프론트엔드 계약

실행 계약 v0.3은 유지하고 별도 [batch-v0.1.schema.json](../contracts/batch-v0.1.schema.json)을 추가했다. 공통 경로/버전/배치 상태명은 shared-variables에 있다.

| API | 입력/응답 |
| --- | --- |
| GET /api/v1/batches | BatchSummary 목록 |
| GET /api/v1/batches/{batch_id} | 계획/상태/예산·버전·condition·entry/attempt/run 연결 |
| POST /api/v1/batches/{batch_id}/report | BatchFilters JSON (`{}` 가능) → BatchReport |
| POST /api/v1/batches/{batch_id}/export.csv | 같은 필터 → 같은 snapshot의 지표 CSV |
| PUT /api/v1/batches/{batch_id}/reviews/{run_id} | BatchReview → 마스킹된 검토 기록 |

필터: source_id, scenario, language, split, condition_id, comparison, family_id, attack_type, label, goal_kind, severity, execution_kind. 필터가 달라지면 표본/분모와 snapshot도 함께 확인한다. CSV는 필터·버전·condition·run_ids와 지표/CI/제외 수를 포함한다. JSON report와 decision-record는 전체 provenance와 추천 근거를 포함한다.

화면은 `groups[].metrics`, `baseline_changes_pp`, `payload_comparisons`, `detector_report`, `decisions.records`를 소비한다. 2차원 산점도로 전체 Pareto를 재계산하지 않는다. `completed` 배치에도 평가 대기/추천 보류가 있을 수 있다. 배치 실행 UI는 이번 백엔드 API의 범위가 아니며, 위 조회 API는 모델 호출을 발생시키지 않는다.

공개 fixture 샘플은 [인계 기록](examples/week3/README.md)을 따른다. 상태별 실패/분모/추천 경로는 backend/tests/test_batch*.py에서 synthetic 근거로 검증한다.

## 남은 팀 작업

- #33: 실제 paired 데이터·gold/번역·rubric 팀 검수, 서비스 요구/단가·최소 평가 수·통계 방법/우선순위 확정
- 실제 모델 키/예산을 로컬에 준비한 뒤 소형 dev 파일럿, 전송/사용량/판정 대조 및 holdout 진입 검토
- #35: 새 API/집계/export를 대시보드에 연결하고 화면 값·그래프·마스킹을 공동 인수
- 실제 모델 성능·최종 추천·팀 합의·holdout 완료는 이 구현/fixture 인계로 완료 처리하지 않는다.
