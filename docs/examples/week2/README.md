# UI/API 인계 샘플

이 파일들은 로컬 HTTP fixture를 실행해 얻은 마스킹 결과다. 실제 모델의 ASR/FPR·비용 측정 자료가 아니다. RAG 샘플은 `python -m scripts.mvp verify-week2 --runs-dir runs/week2-handoff`로 생성했으며, 이메일 샘플은 별도의 합성 이메일 예시로 공통 엔진을 실행한 결과다. 실행 시각·run_id·임의 포트·지연은 이번 샘플의 값이다.

| 샘플 | 확인할 내용 |
| --- | --- |
| [a006-none.json](a006-none.json) | 무방어, 원시 출력에서 canary 성공 판정 후 표시 마스킹 |
| [a006-D1.json](a006-D1.json) | D1 실제 시스템 지침·JSON 경계, 프롬프트 버전 |
| [a006-D2.json](a006-D2.json) | 입력+문서 검사, 악성 문서 격리, 생성 생략 |
| [h007-D1+D2.json](h007-D1+D2.json) | 인용된 공격 문구가 있는 정상 보안 문서 통과 |
| [b006-D2.json](b006-D2.json) | 정상 문서의 탐지+생성 사용량 전체 집계 |
| [position-input.json](position-input.json) | 입력만 검사해 간접 공격 문서가 생성에 포함되는 경로 |
| [position-retrieval.json](position-retrieval.json) | 문서만 검사, 같은 D2 정책·임계값 |
| [detector-failed.json](detector-failed.json) | 잘못된 탐지 응답, failed와 blocked outcome 구분, 이미 발생한 탐지 사용량 |
| [usage-unknown.json](usage-unknown.json) | 제공자가 usage를 반환하지 않을 때 null과 사유 |
| [review-needed.json](review-needed.json) | 인코딩된 원시 출력의 review_needed, 공개 응답 마스킹 |
| [manual-pending.json](manual-pending.json) | PUT 평가 갱신, 미평가·검토자·근거·평가 시각 |
| [email-flow.json](email-flow.json) | 합성 이메일의 공통 D1/D2/provider 경로, 평가 미설정 상태 |

일반 파일은 POST 요청과 응답을 포함한다. `manual-pending.json`은 PUT 본문과 반환 trace를 포함한다. GET은 trace 자체를 반환한다. 모든 파일의 `execution_scope`는 fixture다. 가격은 미검증 임시 설정이므로 추정 총비용은 null이다.

UI는 trace의 실행 상태·output outcome·평가 상태를 각각 표시하고, API가 반환한 metrics와 masked messages를 사용한다. 화면에서 평가를 다시 계산하지 않는다. `model_calls.messages`가 실제 전송 메시지의 표시용 사본이며 private raw 파일이 원문 기준이다.

전체 대표 12건과 기타 상태 샘플·보고서는 검증 명령의 `runs/...`에 생성된다. 이 폴더에 raw 파일을 복사하지 않는다. 새 필드와 검증 범위는 [2주차 인계 문서](../../week2-backend.md)를 따른다.
