# 이메일 인터페이스 예시

실제 이메일 대신 합성 본문으로 공통 실행 경로를 확인한다. 저장소 루트에서 실제 모델 환경 변수를 설정한 다음 백엔드만 실행한다. 이 작은 예시 세트는 RAG 대표 3종 manifest를 갖추지 않았으므로 `scripts.mvp serve`의 기본 bundle 검사 대상이 아니다.

```powershell
$env:DATA_DIR = "backend/examples/email"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

`POST /api/v1/runs` 요청 예시:

```json
{
  "schema_version": "0.2",
  "artifact_type": "run_request",
  "case_id": "email-benign-001",
  "scenario": "email_summary",
  "defense_mode": "D1+D2",
  "defense_position": "input_retrieval",
  "dataset_version": "email_interface_v0.1",
  "corpus_version": "email_interface_v0.1",
  "requested_by": "email-handoff"
}
```

외부 모델이 없어도 backend/tests/test_week2.py가 임시 이메일 데이터와 로컬 HTTP fixture를 만들어 공통 D1/D2·생성 경로를 검증한다. 실제 이메일 세트와 최종 품질 rubric은 #21에서 인계받아 3주차 배치에 연결한다.
