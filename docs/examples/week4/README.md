# 4주차 공개 계약 예시

`research-report.example.json`과 `research-metrics.example.csv`는 공개된 기존 AI 연구 판정에서
quotation batch의 none·secret_leak·original cohort를 선택한 실제 읽기 전용 결과다.
새 모델 실행이나 사람 검토 기록이 아니다. `decision-record.example.json`도 같은 report hash를 참조한다.

전체 cohort는 다음 명령으로 별도 경로에 재생성한다:

```bash
python -m scripts.week4_package replay batch-8fb19849d67c --source overlay --output runs/week4-public-replay-v1
```

`verification-report.json`은 macOS의 로컬 새 환경·HTTP fixture 기술 검증 요약이다.
실제 모델 성능/Ubuntu·Windows CI/다른 사람 인수 증거와 구분한다.
자세한 [필드/분모/미지원 계약](../../week4-backend.md), [인수 기록](../../week4-backend-acceptance.md)을 따른다.

`real-attempt-status.v0.1.json`은 별도 실제 API 시도의 인증 실패 기록이다. 1실패·107대기와
비용 미확인(null), 원본 불변·모델 호출0 조회/export 검증을 구분한다. API 키·원시 응답은 포함하지 않는다.
