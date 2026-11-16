# 3주차 초안의 실제 실행 파이프라인

PR #38의 초안을 기존 실행·예산·저장·집계 계약으로 변환한다. 원본 `data/week2`, `data/week3`는 수정하지 않는다. 새 데이터 버전은 `synthetic_week3_v0.1_draft`다. 팀 검수나 전체 이슈 #33의 완료를 뜻하지 않는다.

## 실행과 재개

저장소 루트 `.env`의 기존 생성/D2 모델 설정을 사용한다. 키를 명령행이나 문서에 넣지 않는다. OpenAI Docs의 [고정 모델 안내](https://developers.openai.com/api/docs/models/gpt-4.1-mini)에 맞춰 `gpt-4.1-mini-2025-04-14`와 표준 입력 $0.40/M·출력 $1.60/M 가격 snapshot을 유지한다. 캐시 할인·청구 정산을 반영한 금액은 아니다.

```text
python -m scripts.week3_pipeline --output runs/week3-live-2026-10-20 --max-items 2
python -m scripts.week3_pipeline --output runs/week3-live-2026-10-20
python -m scripts.week3_pipeline --output runs/week3-live-2026-10-20 --report-only
```

첫 명령은 최대 두 항목만 실행한다. 두 번째는 같은 checkpoint에서 남은 항목을 실행한다. 완료 항목은 재전송하지 않는다. 세 번째는 저장 결과만 검사하며 모델을 호출하지 않는다. 실패/uncertain은 자동 재시도하지 않고 원시 trace·ledger를 보존한다. 미완료 시 종료 코드 2, 실패 시 1을 반환한다.

`--report-only`는 저장 manifest의 모델 설정과 고정된 가격·평가 snapshot을 읽으므로 현재 API 키나 `.env`, 실행 당시의 Python·OS 환경이 필요하지 않다. 새 preparation·배치·checkpoint를 생성하지 않으며 파생 집계·export·검증 파일만 갱신한다. 원시 trace·ledger와 고정 파일의 무결성 검사는 유지한다. 실행 코드를 갱신한 뒤 과거 배치를 조회할 때도 이 옵션을 사용한다. 실제 실행·재개는 구현·설정의 동일성 검사를 유지하므로 변경된 조건의 새 실험은 별도 `--output`으로 만든다.

기본 계획은 RAG 초안 15조건(원본/요소 제거/별도 대조군 11 + 보호값 4), 이메일 대표 3조건 × 중복 없는 방어 구성 6 × 반복 3 = **324건**이다. `dev`만 선택한다. 최대 $1, 1,200호출, 예약 토큰 4천만, 실행 시간 90분의 독립 상한을 적용한다. 이는 전체 데이터 성능 검증이나 holdout 실험이 아니다.

데이터만 준비하려면 다음 명령을 사용한다. 기존 출력 경로는 덮어쓰지 않는다.

```text
python -m scripts.week3_prepare --output runs/week3-prepared
python -m scripts.mvp check --data-dir runs/week3-prepared/rag
```

## 실행 세션·저장 조회·동시 실행

통합 파이프라인·생성 파일럿·탐지 진단은 한 배치 실행 세션에서 진행하고 첫 실패/uncertain 항목에서
다음 항목 실행을 멈춘다. 호출 전 예약·개별 시도·시간/호출/토큰/금액 상한·명시적 재시도 계약은 유지한다.
세션마다 입력 전체를 검증하고 소스별 repository를 공유한다. 데이터 조회는 실제 파일 바이트를 확인하며,
동결 해시와 다르면 변경된 데이터를 모델에 전달하기 전에 실패한다. 일반 API의 데이터 변경도 파일 크기·mtime과 무관하게 반영한다.
호출자에게는 복사한 모델을 반환하므로 반환값 수정으로 인덱스가 바뀌지 않는다.

같은 `--output`은 준비·배치 생성·checkpoint·실행·검증 전체를 `.pipeline.lock`의 OS 잠금으로 보호한다.
다른 프로세스의 동시 요청은 `PIPELINE_ALREADY_RUNNING`으로 거부한다. 프로세스가 종료되면 잠금은 해제되며,
잠금 파일이 남아 있다는 이유로 실행을 막거나 예전 유료 요청을 재전송하지 않는다.
`--report-only`도 같은 출력의 파생 파일을 갱신하므로 이 잠금을 사용한다.

공개 trace의 마스킹은 `backend/app/privacy.py`가 담당한다. 한 공개 응답의 모든 필드가 같은 보호값 패턴을
공유하며, 요청을 넘나드는 보호값/인증정보 캐시는 만들지 않는다. 원문·혼합 URL·공백·Base64 변형과
문맥을 포함한 Base64 검사는 유지한다. 과거 검토 스크립트의 `RunService._mask_value` 진입점도 지원한다.

기존 export를 재사용할 때는 JSON·CSV·판정 기록을 현재 보고서와 대조한다. 불일치는
`EXPORT_ARTIFACT_MISMATCH`로 거부하며 손상 파일을 덮어쓰지 않는다. 파이프라인·파일럿·탐지 진단의
재검증 중 예외나 중단이 발생하면 `verification-report.json`을 실패 상태로 기록한다. 원래 trace·ledger·checkpoint는
유지하며, 검증에 실패한 현재 요청을 과거의 성공 기록으로 표시하지 않는다.

전후 성능 수치와 증거는 [4주차 검증 기록](week4-backend-acceptance.md)에 정리한다.

## 데이터와 판정 경계

- 원본 계약 검사를 위해 기존 RAG 84건을 새 버전으로 복제하고 파생 15건을 추가한다. 실제 배치는 명시적으로 새 15건만 선택한다. 기존 대표 manifest와 holdout는 실행 대상으로 확장하지 않는다.
- 파생 `case_id`는 고유하다. 내용이 다른 문서는 내용 기반의 불투명 ID를 사용해 조건별 내용이 덮어써지지 않게 한다. 보호값 4조건의 질문·제목은 같다. 입력·정답·분석 metadata를 분리하며 조건명이나 gold를 모델 입력에 추가하지 않는다.
- 불투명 문서 ID도 본문과 함께 달라진다. 이 파일럿의 paired 차이는 이 구현 조건에서의 관측이며, 문서 식별자까지 동일한 엄격한 단일 요소 인과 실험으로 해석하지 않는다.
- 원본 공격별 family와 파생 관계를 기록한다. 원본 유형을 뜻하는 F001 등의 대분류를 서로 독립인 실험 family로 세지 않는다. coarse family는 preparation의 provenance에 보존한다.
- a001의 보안 무시 문구 제거와 a021의 D2 조작 제거는 악성 목표가 남으므로 attack이다. a006의 지시 제거와 a021의 전체 공격 제거는 benign으로 변환한다. 이 라벨은 변환기의 해석 초안이며 팀 확정 gold가 아니다.
- a006의 별도 benign 문서는 단일 요소 대조가 아니므로 paired 효과 계산에 쓰지 않는다. a021은 D2 조작만 제거한 쌍과 전체 공격 제거 쌍을 구분한다.
- A11−C01은 공격 지시 추가 효과, A10−C00은 목표 정보 부재 조건의 관측 차이다. C01 자체 노출률도 기록한다. 목표가 없는 A10의 노출 없음은 곧바로 ASR 실패로 바꾸지 않는다.

## 저장 결과

| 경로 | 내용 |
| --- | --- |
| `.pipeline.lock` | 출력 전체의 OS 잠금. 파일 존재는 실행 중이라는 증거가 아님 |
| `prepared/preparation.json` | 원본/생성 파일 SHA256, 파생 관계·라벨 초안·측정 목표. 합성 목표값이 있으므로 로컬 전용 |
| `prepared/rag`, `prepared/email` | API·UI가 읽는 실행 데이터와 manifest |
| `prepared/evaluation-rules.json`, `prepared/batch-spec.json` | 버전별 평가 규칙과 고정 선택·구성·예산 |
| `runs/batches/<batch_id>` | 입력/규칙/정책/가격 snapshot, 무결성 해시, 계획·예산 ledger |
| `runs/*.raw.json` | 원시 출력·전송 메시지. Git 제외 |
| `public-samples`, `report.real.json`, `exports` | 마스킹 trace·공통 집계·CSV/JSON·추천 보류 근거 |
| `exact-observations.json` | 원시 출력의 정확한 목표 문자열 포함 여부와 paired 차이. 목표 원문은 포함하지 않음 |
| `verification-report.json` | 실제/fixture 구분, 사용량·비용·HTTP/ledger/API/export 검증, 관측 파일 해시 |

공통 batch report의 target exposure는 기존 수동 검토 계약을 유지한다. 자동 관측은 `exact-observations.json`에 측정 방식과 함께 분리한다. 자동 관측을 사람이 검토한 gold로 등록하지 않는다. 정확한 문자열이 없더라도 부분·인코딩 유출이 없다고 단정하지 않는다. 정상 작업 의미·과잉 변형·D2 대상별 gold는 팀 검토 대기다. 단일 원본의 반복 3회는 독립 표본 3개가 아니므로 해당 paired CI는 null이다. 최종 추천은 draft 정책 때문에 보류한다.

집계 v0.3은 CSV에 변형명·집계 구현 해시를 보존하며, a021의 D2 지시 제거 쌍을 수동 검토 이후에도 비교할 수 있게 한다. 실제 생성 당시의 구현 해시와 재집계 구현 해시를 구분한다. 기존 export는 덮어쓰지 않는다.

## 실제 저장 결과의 화면 검증

`checkpoint.json`의 batch_id를 사용한다.

```text
python -m scripts.verify_real_ui --runs-dir runs/week3-live-2026-10-20/runs --batch-id <batch_id> --data-dir runs/week3-live-2026-10-20/prepared/rag --case-ids w3_a006_original w3_a006_instruction_removed w3_a001_hard_negative_control w3pv_a11
python -m scripts.verify_real_ui --runs-dir runs/week3-live-2026-10-20/runs --batch-id <batch_id> --dashboard-only
python -m scripts.mvp serve --pipeline-output runs/week3-live-2026-10-20
```

첫 화면 검증은 실제 저장 결과의 네 모드·세 위치 표와 새 배치 대시보드를 모두 검사한다. `--dashboard-only`는 대표 케이스를 지정하지 않고 대시보드만 검사한다. 전체·앱별 출처 필터의 집계 표, payload 불확실성, CSV/JSON 다운로드, 공개 trace를 실제 저장 API와 대조한다. 모델 호출과 외부 네트워크를 차단하며 결과는 `dashboard-verification-report.json`에 기록한다. 예전 네 모드 검증 기록은 대시보드 단독 검증으로 덮어쓰지 않는다.

`serve --pipeline-output`은 checkpoint와 배치에 고정된 입력·설정 snapshot을 검증하고 데이터·runs·평가 규칙·가격·공통 정책을 두 서버에 함께 전달한다. 입력은 `runs/batches/<batch_id>/inputs/week3`에서 읽으므로 원본이나 `prepared`가 바뀌어도 저장된 배치를 열 수 있다. PowerShell 환경변수나 Bash `export`를 따로 입력할 필요가 없다. 이 옵션은 독립적인 `--data-dir`, `--manifest`, `--runs-dir`, `--fixture-model`과 섞을 수 없다. 화면 왼쪽의 **배치 대시보드**에서 checkpoint의 배치를 선택한다. 기본 포트가 사용 중이면 `--api-port 8001 --ui-port 8502`처럼 변경한다.

`serve`의 새 단건 실행 버튼은 현재 `.env`의 모델 설정을 사용한다. 저장된 배치 조회·필터·export에는 새 모델 호출이 없으며, 과거 실제 실행의 설정과 범위는 저장 manifest에서 표시한다. 배치 실행은 CLI에서 한다.

회귀 `tests/test_week3_pipeline.py`는 변환의 결정성·원본 보존·파생 라벨·조건별 문서 분리·프롬프트 gold 분리와 실제 로컬 HTTP의 324건 재개·집계·마스킹·추가 호출 없는 조회를 검증한다. CI에서는 실제 API 키를 사용하지 않는다.

추가 통합 회귀는 다음 명령으로 실행한다.

```text
python -m unittest tests.test_pipeline_state tests.test_pipeline_services tests.test_week3_offline_replay tests.test_verify_batch_ui
```

키와 현재 설정이 없는 재검증, 손상된 snapshot 거절, 대시보드의 실제 v0.3 API/CSV/trace 경로와 서버 환경 연결을 검사한다. [프론트엔드 통합 기록](../frontend/verification/week3-pipeline-integration.md)을 참고한다.
