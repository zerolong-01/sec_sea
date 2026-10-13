# 백엔드·방어 MVP

고정 코퍼스 RAG와 합성 이메일을 공통 실행 엔진으로 실행한다. 2주차 #22의 D1/D2, 적용 위치, 평가 저장, 계측을 지원한다. 실제 모델 설정은 로컬 `.env`/환경 변수에서 읽으며 HTTP fixture 검증과 실제 모델 성능 검증을 구분한다.

## 실행

저장소 루트에서 실행한다.

```text
python -m scripts.mvp setup
python -m scripts.mvp serve --fixture-model
python -m scripts.mvp verify-week2
```

API: http://127.0.0.1:8000/docs · UI: http://127.0.0.1:8501. `serve`는 저장소 루트 `.env`/프로세스 환경 변수를 읽으며 설정이 없으면 오프라인 demo를 사용한다. 외부 설정이 없는 D2는 실패 trace를 반환한다. `--fixture-model`은 로컬 실제 모델 설정 대신 고정 HTTP 응답으로 네 모드를 시연한다.

백엔드만 실행하려면 backend 디렉터리에서 의존성을 설치하고 서버를 시작한다.

```text
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

백엔드 단독 실행도 저장소 루트 `.env`를 읽는다. [설정 예시](../configs/week2.env.example)를 `.env`로 복사해 MODEL_API_KEY를 로컬에 입력한다. 기존 환경 변수가 파일보다 우선하며 상대 파일 경로는 저장소 루트 기준이다. `.env`와 실제 API 키는 커밋하지 않는다.

## 기능과 계약

- none / D1 / D2 / D1+D2와 D2 입력 / 검색 문서 / 양쪽 위치
- D1 명령·데이터 경계와 정확한 전송 메시지 기록
- LLM 기반 D2, 점수·임계값·근거·정책 버전, 문서 격리/차단과 오류 정책
- 실행 상태와 독립된 평가, 수동 판정 갱신 및 원시 근거 보관
- 생성·탐지 호출 전체 사용량/추정 비용, 미확인 값 null·사유, 단계별 지연
- 마스킹된 trace 저장·조회, 합성 이메일 요약 공통 경로

데이터는 [v0.1](../contracts/mvp-integration-v0.1.schema.json), 새 실행은 [v0.3](../contracts/execution-v0.3.schema.json), 상수는 [공통 변수](../contracts/shared-variables-v0.1.json)를 사용한다. v0.1/v0.2 실행 요청·저장 trace도 읽는다.

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /health | 실행 버전·제공자 |
| POST | /api/v1/runs | 실행 결과와 trace |
| GET | /api/v1/runs/{run_id} | 저장된 표시용 trace |
| PUT | /api/v1/runs/{run_id}/evaluation | 검토자·버전·근거가 있는 수동 평가 |
| PUT | /api/v1/runs/{run_id}/detector-gold | 실행 후 입력·문서별 독립 정답과 근거 등록 |
| POST | /api/v1/detector-report | 조건별 대상 FNR/FPR·분모·오류/검토/미등록 수량 |

`runs/{run_id}.trace.json`은 API/UI와 동일한 표시용 결과다. `.raw.json`, `.evaluation.json`, `.detector-gold.json`은 로컬 원시 근거·판정 이력이며 API로 제공하지 않는다. `runs/`는 Git에서 제외한다.

#26 보완으로 score/reason 모순 검토·차단/격리 정책, 선택적인 제공자 JSON schema 형식, 생성 없이 검사하는 detector_only 실행을 지원한다. gold는 실행 후 등록하며 D2에 전달하지 않는다. 일관된 의미적 오판은 남는 위험이며 실제 모델 성능은 별도 검증이 필요하다. API 본문·산식과 인계는 [2주차 문서](../docs/week2-backend.md#26-탐지기-자체의-판정-우회-보완), [마스킹 샘플](../docs/examples/d2-security/README.md)을 참고한다.

환경 변수, 모델 HTTP 인터페이스, 실행 예산, 가격/평가 예시, 호환성 변경 및 남은 인수 조건은 [2주차 실행·인계 문서](../docs/week2-backend.md)를 따른다. [이메일 예시](examples/email/)와 [UI 샘플](../docs/examples/week2/README.md)을 제공한다.

## 검증

backend 디렉터리:

```text
python -m unittest discover -s tests -v
```

저장소 루트:

```text
python -m unittest discover -s tests -v
python -m scripts.mvp verify
python -m scripts.mvp verify-week2
```

실제 모델 대표 12건과 dev 임계값/오탐/미탐, #21의 최종 평가 rubric은 설정·인계 후 재검증한다. 두 앱 전체 배치·반복·통계는 3주차 범위다.
