# 3주차 대시보드 잔여 구현 검증 (#35)

2026-10-20, 저장 결과를 읽는 화면의 표시·연결 검증입니다. 새 유료 모델 호출과 holdout 실행은 없습니다.
기존 실제 실험 기록은 [week3-ui-verification.md](week3-ui-verification.md)에 그대로 보존합니다.

| 항목 | 보완·검증 |
| --- | --- |
| Trade-off 색상 | 방어 구성·D2 검사 위치로 구분. 서버 추천 상태는 도움말·표에 표시 |
| 비용 미확인 | 확인 비용은 크기 척도, 미확인은 별도 고정 크기 빈 점. 혼합·전부 미확인 모두 점이 남는지 확인 |
| 불확실성·표본 | 차트 도움말에 두 축의 95% CI·평가 수·family 수, KPI 아래 전체 지표와 고유 케이스·반복·검토 대기 내역 |
| 정상 기준 연결 | 서버 `tradeoff_points`의 동일 조건 정상 benchmark ID·공유 범위·run_id와 정상 지표를 사용. 원래 목표별 그룹의 분모는 변경하지 않음 |
| 그래프 → trace | 유효 group_id만 허용, 선택한 그룹의 대표 run_id를 GET으로 조회. 그룹·실행 변경 시 이전 trace 제거 회귀 유지 |
| 정책·가격 | 서버의 평가 정책 기준값·우선순위·검토 상태와 저장 가격표 출처·적용일 표시. 미정 값·검토자를 생성하지 않음 |
| payload | 서버의 집계·family별 공격/대조 노출률, 짝 차이·CI·제외 수를 그대로 표시 |
| 공격 목표 | marker 출력·보호값 유출의 서버 그룹을 별도 이름과 표 열로 표시 |
| 필터 | 저장된 모델·평가기·평가 정책·가격 버전 선택지를 서버 inventory에서 읽음 |
| 특수 상태 | 빈·한 결과·부분 완료·전부 실패·비용 미확인·탈락·잠정 동률·추천 후보 없음의 합성 화면 확인 |
| 과거 버전 | 과거 fixture는 수정하지 않음. 새 계약 필드가 없는 화면은 기록 없음으로 표시 |

`tests/test_batch_dashboard_completion.py`는 공개 fixture의 사본과 명시적인 합성 값으로 위 표시를 검증합니다.
합성 정책·추천 상태는 테스트 모형이며 팀의 실제 정책 합의나 평가 정답이 아닙니다.
`tests/test_verify_batch_ui.py`는 소형 오프라인 저장 배치로 실제 집계 API와 화면의 JSON/CSV/trace를 대조합니다.

```text
python -m unittest discover -s tests -p "test_batch_*.py" -v
python -m unittest discover -s tests -p test_verify_batch_ui.py -v
```

실제 저장 배치를 추가 모델 호출 없이 재생하려면 다음 명령을 사용합니다.

```text
python -m scripts.verify_real_ui --runs-dir runs/week3-live-2026-10-20/runs --batch-id <batch_id> --dashboard-only
```

평가자 gold, 정상 성공·과도 변환·보호값 노출 검토와 정책 동결은 담당자의 별도 확인이 필요합니다.
리포트와 화면은 그 상태를 보류·검토 대기로 유지합니다.
