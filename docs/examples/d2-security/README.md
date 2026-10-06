# D2 보완 계약 v0.3 샘플

`python -m scripts.mvp verify-week2 --runs-dir runs/d2-security-handoff`의 HTTP fixture 결과를 마스킹한 샘플이다. 응답은 미리 정한 테스트값이며 실제 모델의 우회율·효율성·단가 자료가 아니다. 이전 [v0.2 샘플](../week2/README.md)은 호환성 예시로 보존한다.

| 파일 | 확인할 내용 |
| --- | --- |
| [valid-json-misclassification-initial.json](valid-json-misclassification-initial.json) | D2에 유효한 낮은 점수/normal_request를 강제로 반환시켜 생성까지 허용, 독립 원시 평가에서 canary 성공 후 표시 마스킹 |
| [target-gold-input.json](target-gold-input.json) | a006의 입력은 benign으로 독립 검수, 문서의 case attack 라벨을 복제하지 않음 |
| [valid-json-misclassification.json](valid-json-misclassification.json) | doc006의 malicious 정답 등록 후 대상 분석만 valid_json_misclassification으로 갱신 |
| [score-reason-contradiction.json](score-reason-contradiction.json) | 원래 threshold_decision=allow, 보완 decision=quarantine, review_needed=true 및 별도 분석 |
| [detector-only-input-block.json](detector-only-input-block.json) | 입력 block 후 문서도 검사, 생성·최종 평가 없음 |
| [detector-only-error.json](detector-only-error.json) | 두 탐지 응답 오류의 failed, 토큰·호출 보존, 독립 정답이 있어도 detector_error |
| [detector-only-gold-pending.json](detector-only-gold-pending.json) | 정상 인용 사례의 유효 탐지 응답과 gold 미등록을 구분 |
| [detector-report.json](detector-report.json) | 실행 조건별 분자·분모와 오류/검토/미등록 수량, 분모 0은 value=null |

각 파일은 method(생략 시 POST), request, response를 포함한다. POST /api/v1/runs는 response.trace, PUT 정답 등록은 response 자체가 trace다. GET /api/v1/runs/{run_id}도 trace를 반환한다. 집계는 POST /api/v1/detector-report의 response.groups다. 실행 시각·run_id·임의 포트·지연은 생성 당시 값이다.

실행 종류·모순/검토 필요·대상별 gold/분석의 기본 UI 표시까지 통합 검증했다. #24의 비교 UI는 [API·필드·산식 정의](../../week2-backend.md#26-탐지기-자체의-판정-우회-보완)에 따라 표시한다. run.status, D2 대상별 분석, 최종 attack_success를 서로 바꾸어 표시하지 않는다. raw 파일이나 로컬 검토 이력은 복사하지 않는다.
