# 4주차 최종 결과 및 근거 자료 Index

## 1. 목적

4주차 실험·데이터 산출물과 검증 근거의 위치를 연결하여 결과 추적 및 팀 인계에 활용한다.

실험 결과, 평가 기준, 검산 수치 및 한계에 대한 상세 설명은 각 문서를 따른다.

## 2. 최종 산출물 목록

아래 파일은 모두 `data/week4/`를 기준으로 한다.

| 파일 | 내용 |
|---|---|
| [final-report.md](final-report.md) | 최종 실험 결과 및 결론 |
| [data-review-v0.4.md](data-review-v0.4.md) | 데이터 구성과 평가 근거 |
| [data-review-detail.md](data-review-detail.md) | 미확정 판정 검토 |
| [result-check.md](result-check.md) | 지표 검산 및 B/C 대조 |
| [defense-comparison.md](defense-comparison.md) | 방어 성능 비교 및 추천·보류 |
| [failure-analysis.md](failure-analysis.md) | 대표 실패 사례 및 원인 |
| [evaluation-guide.md](evaluation-guide.md) | 평가 기준과 지표 정의 |
| [business-analysis.md](business-analysis.md) | 유사 도구 조사 및 사업성 분석 |

## 3. 주요 원본 및 검증 근거

| 자료 | 위치 |
|---|---|
| AI 검토 결과 | `docs/examples/week3-completion/ai-dev-review.v0.1.json` |
| 평가 단위 | `docs/examples/week3-completion/ai-dev-review.units.v0.1.jsonl` |
| 개별 평가 | `docs/examples/week3-completion/ai-dev-review.members.v0.1.jsonl` |
| 지표 집계 | `docs/examples/week3-completion/ai-dev-review.metrics.v0.1.jsonl` |
| 평가·검토 정책 | `configs/week3-ai-dev-review-policy.v0.1.json` |
| 배치·원본 위치 및 해시 | `configs/week4-release-index.v0.1.json` |
| B 공개 JSON/CSV 결과 | `docs/examples/week4/v0.2/` |
| C 화면 재생 검증 | `docs/examples/week3-live/ui-verification-report.json` |
| 4주차 두 모델 실행 검증 | `docs/examples/model-experiment-live/verification-report.json` |
| 추가 실제 재현 검증 | `docs/examples/week4/real-reproduction.v0.3.json` |

세부 batch/run/task, 평가 버전, 분모 및 검산 결과는 [result-check.md](result-check.md)와 [final-report.md](final-report.md)를 참고한다.

## 4. 최종 인계 상태

| 항목 | 상태 | 상세 근거 |
|---|---|---|
| 최종 보고서 및 분석 자료 | 작성 | [final-report.md](final-report.md) |
| 평가 수치 및 후보 판정 | 일부 검증·최종 추천 보류 | [result-check.md](result-check.md) |
| B/C 최종 결과 직접 대조 | 미완료 | [result-check.md](result-check.md) |
| 사업성 자료 | 작성·고객 검증 미완료 | [business-analysis.md](business-analysis.md) |
| Holdout 9건 | 미실행·미승인 | [final-report.md](final-report.md) |

B/C 공동 대조 및 Holdout 미진입 사유와 후속 계획은 상위 이슈 #45에 인계한다.

최종 방어 추천은 `deferred`로 유지한다.
