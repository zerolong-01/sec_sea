# 2주차 데이터 인계 검증 기록

[verification-report.json](verification-report.json)은 2026년 10월 13일에
`python -m scripts.week2_data verify-handoff --output runs/week2-handoff-final`로
생성한 로컬 HTTP fixture 검증 결과다.

RAG·이메일의 dev 실행 24건, 모델 HTTP 호출 42건, 입력/문서별 gold 등록 36건을
실제 run_id와 함께 기록한다. 평가 규칙 버전·원본 데이터 해시·조건별 집계도 연결한다.
원시 출력과 비공개 로그는 복사하지 않았다.

`execution_scope=fixture`, `real_model_verified=false`, `team_agreement=pending`을 유지한다.
탐지 성능 비율은 미리 정한 fixture 출력의 계약 검증 결과이며 실제 내성 수치가 아니다.
gold는 Codex 단일 정적 검수를 명시적으로 사용했다. 팀 확정 gold로 해석하지 않는다.
holdout은 실행하지 않았다.

run_id와 로컬 모델 엔드포인트 포트는 재실행마다 달라진다.
새 결과는 위 명령에 새 출력 경로를 지정해 만들고,
실제 모델 파일럿 및 팀 검토 기록은 별도의 버전과 범위로 보관한다.
