# 백엔드·방어 MVP

4주차 #47의 설치·버전 inventory·평가 출처 API·모델 호출 없는 결과 패키지는
[4주차 백엔드 가이드](../docs/week4-backend.md), 검증 상태는 [기술 인수 기록](../docs/week4-backend-acceptance.md)을 참고한다.
연구 CSV v0.2는 target gold 건수와 빈 선택 metadata를 포함하며, 전달받은 결과 패키지는 저장소 루트에서
`python -m scripts.week4_package verify PATH`로 원본 store·API 키 없이 검사한다.
원평가 집계 v0.6은 빈 CSV에도 보고서 해시·필터를 남기며 기존 v0.5 패키지도 검증한다.
저장 파일의 ID 불일치·손상과 끊긴 모델 응답 처리도 [4주차 가이드](../docs/week4-backend.md)에 정리했다.
마스킹 패턴 재사용·바이트 기준 데이터 인덱스·배치 실행 세션과 파이프라인 출력 잠금은
[통합 파이프라인 가이드](../docs/week3-live-pipeline.md#실행-세션저장-조회동시-실행)를 따른다.
평가 동시 갱신, 모델 HTTP 통신 제한, 대용량 해시 계산의 추가 개선은
[백엔드 업그레이드 기록](../docs/backend-upgrades-2026-10-25.md)에 정리했다.
여러 대상 모델을 같은 데이터·방어 조건으로 실행하는 [모델 일괄 실험](../docs/multi-model-experiments.md)은
별도 명세, 중단 후 재개, 공통 D2 탐지기, 모델별 보안성·정상 기능·비용 비교와 JSON/CSV export를 제공한다.

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

평가와 detector gold 갱신은 실행 ID별 OS 파일 잠금으로 보호한다. 다른 서비스/프로세스가
같은 실행을 갱신 중이면 `409`와 `detail.code=CONCURRENT_WRITE`를 반환한다. 갱신이 끝난 뒤
요청을 다시 보낼 수 있다. 잠금 파일은 남아 있어도 프로세스 종료 시 OS 잠금이 해제된다.

모델 생성·탐지 HTTP 요청은 리다이렉트를 따르지 않으며 `MODEL_REDIRECT_BLOCKED`로 기록한다.
응답 본문은 최대 4 MiB이고 초과 시 `MODEL_RESPONSE_TOO_LARGE`로 기록한다. 두 오류 모두
추가 모델 호출 없이 실패한 호출을 보존하며 사용량을 모르면 비용은 미확인 상태를 유지한다.

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

## 3주차 배치·집계 인계

[3주차 백엔드 안내](../docs/week3-backend.md)에 고정 스냅샷, 6개 고유 조건의 반복 배치,
호출/토큰/금액 예약·중단/재개, 집계·수동 검토·CSV/JSON·추천 gate와 조회 API를 정리했다.
실행 계약 v0.3을 유지하며 별도 `contracts/batch-v0.1.schema.json`을 사용한다.

```text
python -m scripts.verify_week3 --output runs/week3-handoff
```

두 앱의 108건·3회 반복을 로컬 HTTP fixture로 검증한다. 실제 모델 성능·팀 정책 확정·holdout 및 프론트엔드 대시보드 인수는 후속 작업이다.
