# 3주차 백엔드 공개 fixture 인계

구현 코드 커밋 `e23a6cf`에서 생성한 로컬 HTTP fixture 기록이다. 실제 LLM 성능·팀 판정 합의·holdout 검증 결과가 아니다.

| 파일 | 용도 |
| --- | --- |
| verification-report.json | 두 앱 108건·207회 HTTP 호출·재개/재생성 검증 요약 |
| batch-summary.fixture.json | 목록/상세 화면용 계획·상태·예산·entry/attempt/run 매핑 |
| report.fixture.json | 지표·분모/제외·CI·baseline 변화·D2 집계·추천 보류 API 샘플 |

세 파일은 공개 반환 artifact만 복사했다. 원시 입력·모델 메시지·보호값·인증키·private batch manifest는 포함하지 않는다. 파일 안의 run/batch ID와 로컬 fixture 주소는 해당 검증의 식별값이며 외부 서버에서 조회할 수 있는 주소가 아니다.

```text
python -m scripts.verify_week3 --output runs/week3-handoff
```

다시 실행하면 새 ID·포트·지연시간으로 기록한다. 동일 저장 로그를 다시 집계하면 같은 evaluation_snapshot_sha256·지표·export가 생성되는 것을 검증한다. 샘플의 통계 정책은 draft이고 비용은 미확인이다. 분모 0/단일 family의 CI는 null이며 추천은 `deferred`다.

예산 종료·HTTP 실패·명시적 재시도·호출 결과 불확실·동시 writer·검토 변경·조건 불일치와 추천/탈락/Pareto/불확실 후보 경로는 `backend/tests/test_batch.py`, `test_batch_analysis.py`의 synthetic 회귀 검증을 따른다. synthetic 정책·검토자를 실제 팀의 확정 기준으로 사용하지 않는다.

새 API·필드·표시 규칙은 [백엔드 안내](../../week3-backend.md)와 [배치 스키마](../../../contracts/batch-v0.1.schema.json)를 따른다. 프론트엔드 연결·화면 인수는 #35에서 수행한다.
