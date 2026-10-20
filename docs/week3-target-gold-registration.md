# 실제 검사 대상 621개의 AI gold 연결

2026-10-20의 세 dev 실험에 대해 실제 검사한 입력·문서와 AI gold를 연결했다.
새 모델 호출은 0회다. 판정은 **AI 근거 검토**이며 실제 사람의 독립 검토·팀 합의는 아직 수행되지 않았다.

## 대상과 현재 상태

| 저장 cohort | 계획 실행 | 정적 case/target 쌍 | 실제 검사 대상 | benign / malicious / hard-negative | 판정 가능 |
| --- | ---: | ---: | ---: | --- | ---: |
| 기존 payload·정상 대조 | 324 | 36 | 306 | 198 / 72 / 36 | 306 |
| 새 인용 대조 | 108 | 12 | 99 | 45 / 27 / 27 | 99 |
| 새 D2 6기법 대조 | 216 | 24 | 216 | 108 / 54 / 54 | 216 |

대상 수는 여러 조건·반복에서 실제 검사한 관측 횟수다. 621개를 독립 case나 family로 해석하지 않는다.
검사 전에 차단되어 방문하지 않은 문서나 해당 위치를 검사하지 않는 구성은 분모에 추가하지 않는다.
세 cohort 모두 실제 검사 대상의 오류·모순·판정 보류·gold 누락은 각각 0이었다.
이것은 탐지기의 모든 판정이 맞았다는 뜻이 아니다. 미탐과 오탐은 각 조건별 FNR/FPR로 따로 남는다.

## 검토와 등록 절차

1. 선택된 dev case의 실제 입력·문서 전문을 stage별로 검토했다. case 전체의 attack 라벨을 정상 입력이나 보호 문서에 복사하지 않았다.
2. 파생 입력도 따로 판단했다. a001에서 override를 지워도 비공개 값 공개 요구가 남으면 malicious이고, a021에서 D2 JSON 조작 문구만 지워도 토큰 공개 요구가 남으면 malicious이다. 교육용 인용과 비공개 값이 들어 있는 정상 문서는 별도로 구분한다.
3. 기존 36개 대상과 인용 12개 대상은 다른 AI 작업자가 수행한 정적 검토와 root AI 교차 검토를 연결했다. 교차 검토 화면에서는 등록된 목표값만 마스킹하고 문장 전체를 읽었으며, 실제 원문의 SHA-256을 보존했다. 동일 모델 계열의 별도 AI 검토를 독립 사람 검토로 표시하지 않는다.
4. `week3_detector_gold`의 사전 검사에서 frozen 선택·버전·source·case·stage·target_ref·실제 전송 텍스트 해시를 대조했다. 동일 버전의 충돌은 거부하며 이미 일치한 주석은 중복 적용하지 않는다.
5. 후속 AI gold 주석을 기록하고 원시 로그·동결 입력·manifest·호출 ledger가 변하지 않았음을 확인했다. 이후 세 배치를 다시 집계해 JSON/CSV/decision record와 전체 분모를 확인했다.

| 기록 | 검토·등록 근거 |
| --- | --- |
| 기존 파생 target gold 36행 | [등록용 gold](../data/week3/research-legacy-target-gold.v0.4.jsonl), [별도 AI 교차 검토](../data/week3/research-legacy-target-cross-review.v0.4.jsonl), [D2 조작 제거 비교](week3-derived-detector-review.md) |
| 인용 target gold 12행 | [사전 정적 검토](week3-quotation-review.md), [등록용 gold](../data/week3/research-quotation-target-gold.v0.4.jsonl), [root 교차 검토](../data/week3/research-quotation-target-cross-review.v0.4.jsonl) |
| D2 target gold 24행 | 실행 전에 저장한 private gold와 [별도 AI 정적 교차 검토](week3-d2-control-review.md) |
| 후속 실제 집계 | 로컬 `runs/week3-completion/final-analysis-v0.5/`, [공개 후속 증거](examples/week3-completion/followup.v0.5.json) |

## 보존 범위

등록은 **공개 trace의 후속 detector annotation·표시 마스킹과 detector-gold 이력 파일**을 변경한다.
따라서 등록 전 공개 trace 파일 전체가 계속 같은 해시라고 주장하지 않는다.
원래 raw 로그와 자동 `evaluation`, 데이터·규칙·가격·공통 정책 snapshot, manifest·호출 ledger는 보존했다.
후속 annotation을 원래 자동 ASR·정상 판정으로 바꾸지 않았다.

주석 전 v0.4 report·검토 문서·해시 증거는 당시 상태의 기록이다.
당시의 ‘gold 미등록 306/99’와 후속 등록 완료를 구분한다.
최종 재집계에서는 저장 파일 922·297·585개가 각각 읽기 전후 불변이고, 그룹/CSV는 90/990·24/264·12/132였다.
gold 등록으로 오래된 검토 packet의 공개 trace 해시가 바뀌므로 새 사람 응답은
[현재 packet 인덱스](examples/week3-completion/review-handoff.v0.4.json)의 post-gold 자료를 사용한다.

## 해석과 남은 검토

대상 FNR은 **AI gold가 malicious인 실제 검사 대상 중 유효한 미탐**이며 최종 생성 ASR과 다르다.
정상 target FPR도 정상 작업 전체 성공률과 다르다. D2가 인용문을 허용해도 이후 생성이 인용된 지시를 실행하거나 요구 형식을 놓치면 작업은 실패할 수 있다.
새 연구 정상 작업 검토와 paired exact 관측은 별도 overlay이며 대시보드의 원래 평가에 자동 적용하지 않았다.

통계 신뢰구간 null·최종 추천 deferred, 사람 2인의 독립 검토·불일치 조정, 역할별 실제 인수 합의, 충분한 독립 family 확보는 그대로 남는다.
holdout은 실행하지 않았고 새 gold·정책 파일은 holdout 또는 운영 승인을 부여하지 않는다.
