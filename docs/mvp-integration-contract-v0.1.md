# MVP 통합 계약 v0.1

이 문서는 실험·데이터, 백엔드·방어, 프론트엔드·시각화 담당자가 같은 개념을 다르게 정의해 통합 시점에 발생하는 문제를 막기 위한 공통 계약이다.

구조의 기준은 [mvp-integration-v0.1.schema.json](../contracts/mvp-integration-v0.1.schema.json)이며, 코드에서 반복해 쓰는 필드명·상태값·화면 표시명은 [shared-variables-v0.1.json](../contracts/shared-variables-v0.1.json)에서 가져온다.

## 언어와 키 이름 원칙

- 문서, 설명, 화면 표시명은 한국어로 작성한다.
- JSON 필드명과 코드 값은 영어 식별자를 유지한다. 예: case_id, defense_mode, run_trace.
- 영어 키를 한국어 키로 번역하거나 각 역할이 별도 변수명을 만들면 API·데이터·UI 통합이 깨질 수 있다.
- 화면에는 통합 변수 파일의 label_ko를, 코드와 저장 데이터에는 value를 사용한다.

## 계약 대상

| 아티팩트 | 생성 담당 | 사용 담당 | 목적 |
| --- | --- | --- | --- |
| case | 실험·데이터 | 백엔드, 프론트엔드 | 라벨과 성공 기준이 있는 평가 케이스 |
| source_document | 실험·데이터 | 백엔드 | 통제된 RAG 코퍼스의 버전 고정 문서 |
| run_request | 프론트엔드 또는 배치 실행기 | 백엔드 | 특정 케이스를 특정 방어 모드로 실행하는 요청 |
| run_trace | 백엔드 | 프론트엔드, 실험·데이터 | 한 번의 실행 전체를 기록한 관측 로그 |

모든 아티팩트는 "schema_version": "0.1"을 사용한다. 기존 필드의 이름·허용값·의미가 달라지면 새 버전을 만들며, 같은 키의 뜻을 조용히 바꾸지 않는다.

## 권장 파일 배치

~~~text
contracts/mvp-integration-v0.1.schema.json
contracts/shared-variables-v0.1.json
data/cases.v0.1.jsonl
data/corpus.v0.1.jsonl
runs/<run_id>.trace.json
~~~

JSONL 데이터 파일의 한 줄은 스키마 아티팩트 한 개다. 실행 trace는 실행 한 건당 완전한 JSON 문서 한 개다. 경로를 바꿀 수는 있지만, 변경한 경로는 README에 기록하고 통합 변수 파일의 canonical_paths도 함께 갱신한다.

## 통합 변수 파일 사용법

"shared-variables-v0.1.json"은 모든 역할이 공유하는 문자열 상수 사전이다. 스키마의 구조 자체를 대체하지 않으며, 코드에 문자열을 중복 작성하지 않도록 돕는다.

| 역할 | 반드시 사용할 변수 | 사용 방식 |
| --- | --- | --- |
| 실험·데이터 | artifact_types, scenarios, languages, splits, case_labels | JSONL 생성 시 value를 저장한다. 예: case_labels.ATTACK.value는 "attack" |
| 백엔드·방어 | keys, defense_modes, run_statuses, defense_decisions, evaluation_statuses, metric_keys | 요청 검증·trace 생성·API 응답에서 value를 사용한다. 1주차 무방어는 defense_modes.NONE.value와 빈 defense_events 배열을 사용한다. |
| 프론트엔드·시각화 | trace_stages, run_statuses, defense_modes, metric_keys의 label_ko | UI 텍스트와 trace 표시 순서를 통합 변수 파일에서 읽는다. 문자열을 화면 컴포넌트에 직접 하드코딩하지 않는다. |

새 방어 모드, 실행 상태, 평가 상태가 필요하면 세 역할이 합의한 뒤 스키마와 통합 변수 파일을 같은 변경에서 갱신한다.

## 공통 식별자와 공정 비교 단위

- case_id, document_id, run_id는 소문자 영문·숫자·밑줄·하이픈으로 된 안정적인 식별자다. run trace가 만들어진 뒤에는 이름을 바꾸지 않는다.
- source_version, dataset_version, corpus_version은 고정된 입력을 식별한다. 문서 본문이나 케이스 내용을 바꾸면 새 버전을 만든다.
- 방어 효과를 비교할 때 아래 묶음은 고정하고 defense_mode 및 그 방어 설정만 바꾼다.

~~~text
case_id + dataset_version + corpus_version + model_id
+ system_prompt_version + generation_parameters + retrieval_config_version
~~~

- holdout의 정답 라벨, 공격 목표, 기대 결과는 실행 뒤 평가에만 사용한다. 모델 프롬프트나 방어 판단 입력으로 전달하지 않는다.

## 역할별 세부 사용 규칙

### 실험·데이터

1. case와 source_document를 생성하고 스키마 검증 후 전달한다.
2. label은 attack, benign, hard_negative 중 하나다. hard_negative는 인젝션 관련 표현을 포함할 수 있지만 공격이 아니다.
3. 모든 case에 expected_normal_task와 success_criterion을 넣는다. attack에는 attack_type과 attack_goal도 채운다.
4. 1주차의 소형 코퍼스와 source_version을 고정한다. 기존 문서의 본문을 덮어쓰지 않는다.
5. 완료 trace는 evaluation 객체로 평가한다. 판단이 모호하면 review_needed를 사용한다.

### 백엔드·방어

1. run_request를 받고, 참조된 case와 corpus 원본을 변경하지 않는다.
2. 성공·차단·실패 실행 모두 run_trace를 만든다. 실패한 경우에는 도달한 단계와 error 객체를 남긴다.
3. retrieval에는 document_id, rank, included_in_prompt를 남기고, prompt_assembly에는 order와 source_ref를 남긴다.
4. 1주차에는 defense_mode를 none으로 기록하고 defense_events는 빈 배열로 둔다. D1/D2는 나중에 이벤트를 추가하되 trace 모양은 바꾸지 않는다.
5. manifest에 모델, 시스템 프롬프트, 생성 파라미터, 검색 설정, 방어 설정 버전을 기록한다.
6. display_text에는 발표·UI에 보여도 되는 값만 넣는다. 마스킹했으면 is_masked를 true로 남기며, 비공개 시스템 지시나 비밀값을 trace API로 내보내지 않는다.

### 프론트엔드·시각화

1. case_id, dataset_version, corpus_version, defense_mode가 명시된 run_request만 보낸다. run_id는 클라이언트에서 만들지 않는다.
2. run_trace를 input → retrieval → prompt_assembly → defense_events → output → evaluation → metrics 순서로 표시한다.
3. included_in_prompt, is_masked, status, manifest 식별자를 화면에서 확인할 수 있게 한다.
4. 공격 성공, FPR, 태스크 성공, 비용, 방어 결정을 화면에서 별도로 계산하지 않는다. 백엔드 trace와 evaluator version을 기준으로 표시한다.
5. blocked, failed, null metric, review_needed를 오류가 아닌 표시 가능한 상태로 구현한다.

## 지표 의미

| 지표 | 분자 | 분모 | 주의점 |
| --- | --- | --- | --- |
| ASR | evaluation.attack_success가 success인 공격 실행 | 평가된 전체 attack 실행 | attack 라벨만 사용 |
| FPR - 정상 | 차단·격리·과도 변환된 benign 실행 | 평가된 전체 benign 실행 | hard-negative와 분리 보고 |
| FPR - 하드 네거티브 | 차단·격리·과도 변환된 hard_negative 실행 | 평가된 전체 hard_negative 실행 | 과잉 방어의 핵심 신호 |
| 정상 태스크 성공률 | evaluation.normal_task_success가 success인 실행 | 평가된 benign·hard_negative 실행 | case의 rubric을 사용 |
| 지연·비용 | metrics의 기록값 | 보고서에서 명시한 completed/blocked 실행 | null은 제외 수와 함께 보고 |

## 1주차 통합 게이트

통합 MVP는 attack, benign, hard_negative 각 1개 이상을 같은 흐름으로 실행해 아래를 모두 충족할 때 완료다.

- 각 case, source_document, run_trace가 v0.1 스키마를 통과한다.
- 프론트엔드가 case ID, 문서 ID, 프롬프트 구성 순서, 출력 상태, metric을 백엔드 trace와 동일하게 표시한다.
- 데이터 담당자가 case의 success_criterion만으로 evaluation 결과를 판단할 수 있다.
- 같은 비교 단위로 재실행하면 새 run_id가 만들어지되 입력 버전과 manifest 기준은 유지된다.
- 애매한 결과는 review_needed로 남기며, 라벨이나 필드를 임의로 수정하지 않는다.

## 변경 절차

1. 필드, enum, 변수, 의미 변경안을 공통 스키마 이슈에 제안한다.
2. 세 역할 담당자가 영향 범위를 검토한다.
3. 기존 아티팩트를 무효화하거나 의미를 바꾸는 변경이면 schema_version을 올리고 migration note를 남긴다.
4. 스키마, 통합 변수 파일, 생산자, 소비자를 같은 변경 단위에서 함께 갱신한다.
