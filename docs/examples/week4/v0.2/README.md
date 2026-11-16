# 연구 export v0.2 예시

quotation batch `batch-8fb19849d67c`의 `condition_id=D2-input` 선택이다.
기존 공개 AI 판정만 읽었으며 새 모델 호출이나 사람 검토는 없다.

- `report.json`: 출력 지표·탐지 대상 gold·분모·제외·unsupported/null 및 근거 membership.
- `metrics.csv`: metadata 1행, 출력 지표 행, target gold 건수 행. 같은 report hash·필터·평가판을 참조한다.
- `decision-record.json`: 같은 보고서의 추천 보류·사람 검토 대기·holdout 미승인.

CSV의 target gold 건수는 탐지기 결정이나 FNR/FPR이 아니다. 비율 칸을 비워 둔다.
평가판 `week3-two-ai-review-v0.1`과 원래 지표는 유지하고 export 형식만 v0.2로 변경했다.
이 예시 파일은 공개 문서의 LF 줄바꿈을 사용한다. 전송 패키지는 manifest가 고정한 원래 바이트로 검증한다.

완전한 재현 패키지는 새 경로로 생성한 뒤 검사한다:

```bash
python -m scripts.week4_package replay batch-8fb19849d67c --source overlay --filters docs/examples/week4/v0.2/filters.json --output runs/week4-overlay-v2
python -m scripts.week4_package verify runs/week4-overlay-v2
```

검사는 원본 store·키·Git·네트워크 없이 가능하다. 원본 자체를 다시 검증한 것은 아니며,
기대 report/source inventory hash를 별도로 받았다면 `--expected-report-sha256`와
`--expected-source-inventory-sha256`도 지정한다. 자세한 [계약·명령](../../../week4-backend.md)을 따른다.
