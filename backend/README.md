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

## API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /health | 서버·스키마·모델 제공자 상태 |
| POST | /api/v1/runs | run_request를 받아 실행 후 trace 반환 |
| GET | /api/v1/runs/{run_id} | 저장된 trace 조회 |

POST 요청은 공통 계약의 run_request 모양을 사용한다. 1주차에는 defense_mode에 "none"만 허용한다. D1/D2 요청은 422와 "DEFENSE_MODE_NOT_IMPLEMENTED" 코드를 반환한다.

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
