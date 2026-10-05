# 백엔드·방어 MVP (1주차)

이 디렉터리는 #8 이슈의 무방어 RAG 실행·trace·manifest MVP다. 데이터 원본을 바꾸지 않고, 통합 계약 v0.1에 맞는 실행 기록을 남긴다.

## 제공 기능

- JSONL의 case와 source_document를 읽는 고정 코퍼스 RAG
- 1주차 무방어 모드 "none" 실행
- 입력 → 검색 → 프롬프트 조립 → 방어 이벤트 → 출력의 구조화 trace
- 모델·프롬프트·검색 설정·토큰·지연·비용을 담은 manifest와 metrics
- run ID별 JSON trace 저장 및 조회
- 외부 모델 키 없이 재현 가능한 demo 제공자
- 설정 시 OpenAI 호환 "/chat/completions" 엔드포인트 사용

## 실행

backend 디렉터리에서 의존성을 설치한 뒤 서버를 실행한다.

~~~text
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
~~~

기본 데이터 경로는 프로젝트 루트의 "data"이고, trace는 "runs"에 저장된다. 실험·데이터 담당이 아래 파일을 제공하면 된다.

~~~text
data/cases.v0.1.jsonl
data/corpus.v0.1.jsonl
~~~

## 환경 변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `DATA_DIR` | 프로젝트 루트의 `data` | cases/corpus JSONL 경로 |
| `RUNS_DIR` | 프로젝트 루트의 `runs` | 마스킹 trace와 로컬 원시 로그 저장 경로 |
| `MODEL_PROVIDER` | `demo` | `demo` 또는 `openai_compatible` |
| `MODEL_ID` | `demo-rag-v0.1` | manifest에 기록할 모델 식별자 |
| `SYSTEM_PROMPT_VERSION` | `v0.1` | manifest에 기록할 시스템 프롬프트 버전 |
| `RETRIEVAL_CONFIG_VERSION` | `lexical-v0.1` | manifest에 기록할 검색 설정 버전 |
| `MODEL_BASE_URL` | 없음 | `openai_compatible` 사용 시 필수 |
| `MODEL_API_KEY` | 없음 | `openai_compatible` 사용 시 선택적 인증 키 |

## API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /health | 서버·스키마·모델 제공자 상태 |
| POST | /api/v1/runs | run_request를 받아 실행 후 trace 반환 |
| GET | /api/v1/runs/{run_id} | 저장된 trace 조회 |

POST 요청은 공통 계약의 run_request 모양을 사용한다. 1주차에는 defense_mode에 "none"만 허용한다. D1/D2 요청은 422와 "DEFENSE_MODE_NOT_IMPLEMENTED" 코드를 반환한다.

## trace와 원시 로그

`runs/<run_id>.trace.json`과 API 응답은 화면에 바로 표시해도 되는 마스킹 trace다. canary 값은 사용자 입력, 검색 문서, 프롬프트 구성, 모델 출력, 제공자 오류에서 `[MASKED_CANARY]`로 치환된다.

같은 run ID의 `runs/<run_id>.raw.json`에는 재현·수동 판정용 원시 입력, 최종 프롬프트 구성, 모델 출력 또는 제공자 오류가 저장된다. 이 파일은 API로 제공하지 않으며, 접근이 제한된 로컬 실행 환경에서만 사용한다. `runs/` 전체는 Git 추적 대상이 아니다.

## 데이터 인계 후 3종 통합 확인

실험·데이터 담당이 `data/cases.v0.1.jsonl`과 `data/corpus.v0.1.jsonl`을 제공하면 attack, benign, hard-negative 대표 case_id를 각각 한 번씩 아래 요청 형식으로 실행한다.

~~~text
POST /api/v1/runs
Content-Type: application/json

{
  "schema_version": "0.1",
  "artifact_type": "run_request",
  "case_id": "<대표 case_id>",
  "scenario": "rag_chat",
  "defense_mode": "none",
  "dataset_version": "<cases source_version>",
  "corpus_version": "<corpus source_version>",
  "requested_by": "week1-integration"
}
~~~

각 응답의 `run_id`로 `GET /api/v1/runs/{run_id}`를 호출해 input, retrieval, prompt_assembly, output, manifest, metrics가 모두 존재하는지 확인한다. 같은 요청을 다시 실행하면 run ID는 달라도 request와 manifest의 비교 조건은 같아야 한다.

세 대표 ID가 확정된 뒤에는 아래 검증 명령으로 세 케이스를 한 번에 재실행할 수 있다. 명령은 attack, benign, hard-negative가 각각 하나인지와 UI가 필요한 trace 필드를 검사한다.

~~~text
python -m scripts.verify_week1_integration \
  --case-id <attack_case_id> \
  --case-id <benign_case_id> \
  --case-id <hard_negative_case_id> \
  --corpus-version <corpus_source_version>
~~~

## 모델 제공자

기본값은 "MODEL_PROVIDER=demo"다. 이 제공자는 오프라인에서 결정론적으로 동작하므로 통합 테스트와 trace 확인에 사용한다.

OpenAI 호환 서버를 사용하려면 다음 환경 변수를 지정한다.

~~~text
MODEL_PROVIDER=openai_compatible
MODEL_BASE_URL=https://your-host/v1
MODEL_API_KEY=...
MODEL_ID=...
~~~

API 키는 저장된 trace에 기록하지 않는다.

## 검증

backend 디렉터리에서 실행한다.

~~~text
python -m unittest discover -s tests -v
~~~

테스트는 임시 JSONL 데이터로 무방어 실행, trace 저장·조회, D1 미구현 응답을 확인한다.

## 통합 계약

- 구조: "../contracts/mvp-integration-v0.1.schema.json"
- 공통 변수: "../contracts/shared-variables-v0.1.json"
- 역할별 가이드: "../docs/mvp-integration-contract-v0.1.md"

API·trace의 키와 enum은 위 계약을 기준으로 하며, 화면용 한글 표시명은 공통 변수 파일의 "label_ko"를 사용한다.
