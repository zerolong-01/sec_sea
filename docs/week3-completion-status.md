# 3주차 요구사항·증빙 대조표 — 2026-10-20

이 문서는 #32·#33·#34·#35·#29·#12·#26의 **본문과 완료 기준을 실제 코드·파일·저장 검증 기록에 대조**한 인계 기록이다. 이슈의 CLOSED 상태를 완료 증거로 사용하지 않는다. 조회한 원문 사본은 로컬 `runs/week3-completion/issue-{번호}.json`에 있다.

사용자는 공개 논문·기업 자료를 근거로 프로젝트 기준을 결정하도록 위임했다. 따라서 **dev용 데이터·gold·정상 작업 rubric, 서비스 수치·우선순위, 통계 방법의 연구 결정은 채택 완료**다. 이를 사람 2인의 독립 검토, A/B/C 세 담당자의 실제 합의, 운영 승인 또는 holdout 승인으로 바꾸지 않는다. 정책의 runtime `draft`는 이 구별을 유지하는 계약 지위이며 수치 미정을 뜻하지 않는다. [연구 결정](week3-research-decisions.md), [통계 정책](week3-statistical-policy.md)을 함께 읽는다.

## 상태와 검증 범위

| 상태 | 의미 |
| --- | --- |
| `implemented_verified` | 구현과 기존 실제 저장 증빙 또는 해당 기능의 회귀 검사가 확인됨. 아래 최종 head 전체 회귀·CI 통과 선언과는 별개다. |
| `evidence_pending` | 인터페이스·초안은 있으나 해당 실제 실행, 판정 반영, 하위 분석 또는 최신 통합 검산 증거가 부족함. |
| `human_review_pending` | 원문이 요구하는 실제 독립 사람 검토·불일치 조정·역할별 합의가 없음. AI 검토 기록과 구별함. |
| `not_in_dev_scope` | 보존하기로 한 holdout, 운영 배포·최종 확증 결론, 미구현 도구·외부 전송·대규모 확장 등 이번 dev 완료 범위 밖임. |

**최신 변경 전체의 최종 회귀와 Ubuntu·Windows CI 결과는 아직 이 문서에 기록하지 않았다.** 기능별 과거 통과 기록을 최종 head의 통과로 소급하지 않는다. 최종 검증 담당자가 아래 기록란을 실행 후 채운다.

## 서로 합치지 않는 실물 증빙

| 식별 | 확인한 실물 | 말할 수 있는 범위 |
| --- | --- | --- |
| E1 데이터·구조 | `scripts/week2_data.py check`, `scripts/week3_data.py check`; `data/week2`, `data/week3` | RAG 84·52, 이메일 3·3, 제안 기법 28, 번역 3, gold 48의 구조·해시·split 검사. week3 구조 검사 37개. 구조 통과는 의미 검수·공격 효과가 아니다. |
| E2 기존 실제 파일럿 | [실제 API 인계](examples/real-api/README.md), [108건 검증](examples/real-api/pilot-verification.json) | 두 앱 대표 3종×6구성×3회. 완료 90·차단 18, 추정 $0.0415772. 당시 정책·판정을 보존한다. |
| E3 실제 payload 파일럿 | [324건 검증](examples/week3-live/verification-report.json), [입력 대조](examples/week3-live/input-verification-report.json), [관측 요약](examples/week3-live/observation-summary.json) | `batch-bd093a919251`: 완료 251·차단 73, HTTP 557회, 추정 $0.1022296. 새 RAG 15조건+이메일 3조건×6×3. RAG exact 관측 270·paired 비교 36. 정확 문자열 관측을 사람 gold·최종 ASR로 승격하지 않는다. |
| E4 별도 탐색 감사 | 로컬 `runs/attack-audit-2026-10-20/independent-verification.json`, [이슈 #41](https://github.com/zerolong-01/sec_sea/issues/41) | 별도 157입력×6구성=942계획 조합, 완료 742·차단 200. 943개 run_id에는 추가 attempt가 포함된다. 한 호출의 사용량·비용 미확정이 남아 확인 비용 소계 $0.3585468과 실제 총액을 구별한다. 324건의 3회 반복 효과 실험과 합산하지 않는다. |
| E5 D2 진단 | [18건 탐지 검증](examples/real-api/detector-verification.json) | 탐지 전용 18건·36대상, 생성 0회, 반복 1회. 당시 gold 36개는 팀 검토 대기로 미등록. 생성 공격 효과나 6종 D2 공격의 3회 평가를 대신하지 않는다. |
| E6 새 인용 대조 | [준비기](../scripts/week3_quote_controls.py), [회귀](../tests/test_week3_quote_controls.py) | 원본 3 family의 새 original/quoted 쌍, 신규 dev 6건·계획 108건. 기존 324건을 바꾸지 않는다. 실제 108건 실행은 미완료다. 직접 공격은 입력 surface와 원래 문서를 유지하며 새 업무 질문 추가를 기록한다. 간접 공격은 문서 ID·길이 차이도 공개한다. |
| E7 채택 정책 | [서비스 근거](../configs/week3-service-decision.v0.2.json), [실행 정책](../configs/week3-evaluation-policy.json), [통계 wrapper](../configs/week3-statistical-policy.json), [rubric](../data/week3/research-evaluation-spec.v0.4.json), [loader](../scripts/week3_policy.py) | `adopted_for_dev`. 서비스 8개 수치·우선순위, 반복 3·bootstrap 10,000·최소 family 20/판정 60을 결정. 사람 reviewer는 만들지 않고 holdout 권한은 false. 새 준비에 적용하고 과거 snapshot은 보존한다. |
| E8 gold·분류·번역 AI 검토 | [설명](week3-gold-review.md), [58행 기록](../data/week3/research-gold-review.v0.2.jsonl) | dev 실제 target 30행·서로 다른 텍스트 25개, dev catalog 25행, 번역 3행을 AI가 검토. 번역은 영어 입력과 한국어 문서의 혼합 언어 변형이다. 원본 gold 48행을 수정하지 않으며 holdout 18 target·3 attack은 의미 검토에서 제외. 인간 독립 검토와 통계 family 독립성을 확정한 기록이 아니다. |
| E9 정상 출력 AI 검토 | [방법·결과](week3-output-review.md), [324행 기록](../data/week3/research-output-review.v0.4.jsonl) | `ai_evidence_review`. case·원시 출력 해시로 묶은 생성 본문 114개를 읽고 run별 기록으로 펼침. 정상 작업 success 223·failure 100·review_needed 1. 원시 출력 해시·차원별 근거가 있으나 기존 평가 snapshot에 자동 반영된 것으로 해석하지 않는다. benign/hard-negative 정상 작업 180건과 attack하 정상 작업 144건의 분모를 분리한다. |
| E10 독립 검토 인계 | [준비·합의 계획기](../scripts/week3_review_handoff.py), [11개 회귀](../tests/test_week3_review_handoff.py); 로컬 `runs/week3-completion/independent-review-v0.1/manifest.json` | 실제 324 final-output+306 D2-target=630개의 private task. task hash·blinding·동일 신원 정규화·충돌·시각·근거·마스킹 검증. `applied=false`, `human_review=pending`. 빈 응답 template와 A/B/C template는 실제 검토나 서명이 아니다. |
| E11 최신 대시보드 재생 | 로컬 `runs/week3-completion/dashboard-api-replay-v0.4.json`; [화면 보완 기록](../frontend/verification/week3-dashboard-completion.md) | 실제 324건의 저장 API→집계→화면 JSON/CSV/공개 trace 대조. 추가 모델·외부 네트워크 0, 원본 배치 불변. 기록 당시 v0.4 전체 90그룹·payload 78·family 비교 114. 이후 구현은 최종 head로 다시 확인한다. |
| E12 기능 계약·표시 회귀 | [백엔드 집계](../backend/app/batch_analysis.py), [집계 회귀](../backend/tests/test_batch_analysis.py), [UI 회귀](../tests/test_batch_dashboard_completion.py), [API/UI 회귀](../tests/test_verify_batch_ui.py) | 목표별 ASR 분리, 명시적 정상 benchmark·선정 cohort, 표본·정책·가격·family 노출률, 그래프→trace, 비용 미확인 점, 불일치·빈·부분·실패·동률·후보 없음. 합성 검증 수치를 실제 효과로 표시하지 않는다. |
| E13 새 D2 6종 대조 | [설계·준비 기록](week3-d2-controls.md), [준비기](../scripts/week3_d2_controls.py); 로컬 `runs/week3-completion/d2-controls-prepared-v0.4/preparation.json` | 새 dev attack 6·교육용 hard-negative 6, 6구성×3회=216계획. 기존 dev 4 parent의 3개 family를 상속하므로 6개 독립 family로 세지 않음. 단일 AI target gold와 hash·lineage 기록은 있고 실제 216회 모델 효과·독립 사람 검토는 미완료. |

E6의 옛 `runs/week3-completion/quoted-controls-v0.2-draft`는 보존한다. 연구 정책을 연결한 별도 준비가 `runs/week3-completion/quote-experiment-v0.2/prepared`에 생성됐다. 새 spec에서 반복 3·bootstrap 10,000·최소 family 20/판정 60과 선택 dev 6건을 확인했다. 작성 시 `execution_status=not_executed`, 계획 108건이다. 옛 source hash가 새 정책과 다르다는 이유로 덮어쓰지 않는다.

확인한 고정 자료의 SHA-256은 다음과 같다. 작업 중 생성·검토 파일의 후속 버전은 새 해시로 기록한다.

| 자료 | SHA-256 |
| --- | --- |
| E3 `verification-report.json` | `1a79e2d6d12738690922bbad149a2ea4e01577c7da99f3100096281095392cff` |
| E4 `independent-verification.json` | `c56cd4d2cb80509b4cbbef76f9c982e6ccd16aa19454753e95bde54f0de59cd7` |
| E8 gold 검토 JSONL, 번역 3행 추가 후 | `731e18e015440886522161b6effeb78f948d54618258a6160fd0b5406d16044b` |
| E9 정상 출력 검토 JSONL | `7ad9bec3983b0a5705c53369781727cb24d9a945423fb28c00a8752ecdbe5c4b` |
| E10 manifest | `8d7b3048eb5ed78a4b37d4624e9a9aa12cef3e4c39e551560b3c5470fed6da7f` |
| E11 대시보드 재생 JSON | `f783be00d8afb72c28b397f67e03a56f0ad67cbbd28f58091fd4bf1ada278fd2` |

## 이슈별 전체 체크리스트 대조

번호는 각 본문의 checkbox를 위에서 아래로 센 순서다. `01–03`은 세 항목 모두를 뜻한다. #32 16개, #33 27개, #34 30개, #35 33개, #29 10개, #12 9개, #26 9개, **총 134개 checkbox**를 아래에서 빠짐없이 연결한다. checkbox가 아닌 필수 설계·완료 문장은 다음 절에서 별도 대조한다.

### #32 상위 계획

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 32-01 | 최신 dev 전체 회귀·인계 | `evidence_pending` | E1/E12 기능 증거는 있음. 최종 head 전체 회귀·두 OS CI는 아래 최종 기록 대상. |
| 32-02 | 모델·버전·단가·전체 예산 | `implemented_verified` | E2/E3의 고정 모델·가격 snapshot·ledger, E7의 위임 연구 결정. 실제 사람 합의였다고 표기하지 않음. |
| 32-03 | 대표 3종 연결과 세 담당자 합의 | `human_review_pending` | 연결 E2/E3/E11, 실제 세 담당자 판정 합의 없음. |
| 32-04 | #29/#26 실험 설계 연결 | `implemented_verified` | 원본/제거·요인 실험·인용 준비 E3/E6, detector-only·별도 gold E5/E8. 모든 효과 실험 완료는 아님. |
| 32-05 | holdout 전 최종 고정 | `not_in_dev_scope` | dev 기준 E7 결정 완료. holdout 보존과 사람/외부 동결 gate 유지. |
| 32-06 | 두 앱 계획/실행/평가/제외 추적 | `implemented_verified` | E2/E3 manifest·run/attempt·평가 snapshot·ledger. |
| 32-07 | 실제 기법·위치·payload 반복 | `evidence_pending` | E3 원본/제거/요인 3회 완료. 새 인용 E6 108건은 미실행. |
| 32-08 | 지표·평가 수·CI | `evidence_pending` | 산식·null·제외·CI 구현 E12. 실제 의미 판정과 충분한 family가 없는 지표는 미완료/CI null. |
| 32-09 | D2 FNR/FPR·미탐·모순·오류 | `evidence_pending` | E5/E8/E10. 324건 실제 D2 306대상의 등록·검토 상태와 최종 생성 결과를 분리해야 함. |
| 32-10 | payload 추가 효과·불확실성 | `evidence_pending` | E3 exact 관측·36쌍은 존재. 의미 판정·기본 노출/정상 손실 및 새 인용 결과는 분리 보완. |
| 32-11 | 필터→Pareto→우선순위·보류 | `implemented_verified` | E7/E12, 부족한 표본·가격·평가·정책에서 강제 추천하지 않음. |
| 32-12 | 저장→집계/export/UI 재현 | `implemented_verified` | E11. 최신 변경의 최종 재생은 별도 기록. |
| 32-13 | 대표 사례·팀 판정·4주차 인계 | `human_review_pending` | 실제 사례·AI 기록과 이 인계표는 있음. 사람 판정 합의·최종 발표 패키지를 만들지 않음. |
| 32-14 | #33 실험·데이터 인수 | `human_review_pending` | 아래 #33의 AI/dev 결정과 실제 사람 검수 미완료를 구별. |
| 32-15–16 | #34/#35 구현·통합 인수 | `evidence_pending` | 기능 E11/E12. 최신 전체 검증과 아래 실제 누락을 닫은 뒤 인수. |

### #33 데이터·평가

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 33-01 | 원본 RAG/이메일/영어/gold 점검 | `implemented_verified` | E1, E8. 원본 수와 single-review 상태를 숨기지 않음. |
| 33-02 | 기법·family·실제 평가 범위 | `evidence_pending` | catalog dev 25행 AI 명칭 대조 E8. 통계 family 독립성·실제 심각도별 분석은 별도 확정 필요. |
| 33-03 | gold·번역·rubric 독립 재검수 | `human_review_pending` | E7/E8은 AI/dev 근거이며 번역 3행의 AI 정적 의미 대조도 기록됨. 사람 독립 검수·불일치 조정은 없음. |
| 33-04 | parent/variant split·누수·미지원 범위 | `implemented_verified` | E1/E6. 영어 holdout·실제 다중 턴·외부 도구 실행은 미평가. |
| 33-05 | holdout 전 전체 평가 snapshot | `not_in_dev_scope` | dev 입력/규칙/선택·E7 해시 고정 지원. 성공 subset만 남긴 전체 ASR을 만들지 않으며 holdout은 보존. |
| 33-06 | marker/비밀/작업/D2 성공 분리 | `implemented_verified` | E7/E8/E12와 기존 exact 관측의 제한. |
| 33-07 | 직접·간접·D2 원본/제거/인용 준비 | `implemented_verified` | E3/E6. 새 직접 쌍의 업무 질문 추가·간접 doc ID/길이 차이를 기록하고 엄격한 단일 요인 인과를 주장하지 않음. |
| 33-08 | C00/C01/A10/A11·공통 정책 | `implemented_verified` | E3 실제 실행·입력 대조. 공격 payload에 미지의 보호값을 추가하지 않음. |
| 33-09 | parent/variant/정보 조건·hash·입력 분리 | `implemented_verified` | E3/E6 frozen metadata, wire 검사·prompt metadata 분리 회귀. |
| 33-10 | 노출 차이·기본 누출·정상 손실·D2 gold | `evidence_pending` | exact 관측과 원시 근거는 있음. 의미 검토·실제 대상 gold와 새로운 인용 효과를 완료로 대체하지 않음. |
| 33-11 | 대표·애매 사례의 2인/3역할 검토 | `human_review_pending` | E9/E10 AI·private 검토 도구는 완료. 두 사람/세 역할 합의는 pending. |
| 33-12 | raw·부분/인코딩·미확보 판정 | `evidence_pending` | E7 기준 채택, E3/E4 raw 근거와 E9 AI 검토. 애매한 판단은 유지하며 등록·검산 결과와 연결 필요. |
| 33-13–14 | 서비스 수치·우선순위·통계 결정 | `implemented_verified` | E7의 사용자 위임 연구 결정. 운영 기준의 외부 인증·충분 표본 보장으로 표현하지 않음. |
| 33-15–17 | 판정 이력·분모/CI 명세·D2 분리 | `implemented_verified` | 평가/gold/BatchReview API, E7/E10/E12. 실제 gold 미등록은 null/제외로 공개. |
| 33-18 | 하위 결과·실패·과잉 차단 분석 | `evidence_pending` | 필터·목표별 그룹 E12. 실제 심각도 metadata, 충분한 표본·의미 판정이 부족한 하위 결과는 보류. |
| 33-19 | 정책 기반 후보·불명확성 보류 | `implemented_verified` | E7/E12. 개별 CI 중첩을 동등성 입증으로 쓰지 않음. |
| 33-20 | 실제/fixture/추정비용·4주차 입력 | `evidence_pending` | E2–E11 구분과 이 표. 최신 통합 검증·새 인용 효과·미해결 판정은 후속 자료. |
| 33-21 | 팀 검수·split/hash 기록 | `human_review_pending` | 구조/hash와 AI 검토 완료. 실제 팀 검수는 별도. |
| 33-22 | 목표별 성공 기준·paired 준비 | `implemented_verified` | E3/E6/E7. 준비와 실증을 구별. |
| 33-23 | holdout 전 최종 정책 고정 | `not_in_dev_scope` | dev 결정은 완료; holdout/frozen 승인 아님. |
| 33-24 | run별 수동 판정·제외 추적 | `human_review_pending` | E9/E10와 기존 API 지원. 실제 사람 판정 파일 없음. |
| 33-25 | 분자/분모/차이/CI 원시 검산 | `evidence_pending` | 기존 golden 회귀와 E3/E11은 있음. 새 연구 판정과 최신 집계의 검산을 추가 기록해야 함. |
| 33-26–27 | D2/최종·marker/비밀 분리와 보류 인계 | `implemented_verified` | E7/E8/E12, 이 대조표와 저장 decision record. |

### #34 배치·백엔드

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 34-01–04 | 식별/버전·family·6구성·앱/split 선택 | `implemented_verified` | BatchSpec/BatchStore·계약·E2/E3. D2 양쪽 공유 실행을 중복 생성하지 않음. |
| 34-05–10 | 반복·seed·예산·재개·오류·부분 완료 | `implemented_verified` | BatchCallBudget·attempt ledger·취소/uncertain/명시 재시도 회귀, E2/E3/E4. 미확정 비용을 0으로 만들지 않음. |
| 34-11 | 공통 정책과 D1 추가 방어 분리 | `implemented_verified` | 동일 common policy snapshot·wire 검사 E3. |
| 34-12 | 원본/제거/인용·4조건 실제 실행 | `evidence_pending` | E3 원본/제거/4조건 완료. E6 인용 108건 미실행. |
| 34-13 | gold 입력 분리·비공개/공개 마스킹 | `evidence_pending` | 입력 분리·canary 검증은 완료. 등록된 non-canary 보호값의 과거 공개 trace 문맥 노출을 읽기 시 frozen 규칙으로 마스킹하는 수정 진행 중. 최종 회귀·실제 재생 확인 필요. |
| 34-14–19 | D2 정책·평가 이력·지표/표본·API/export | `implemented_verified` | E5/E10/E12. detector-only·오류·미등록·실행 범위와 목표를 분리. |
| 34-20 | 최신 저장 재생·원시 교차 검산 | `evidence_pending` | E3/E11 기준은 존재. 최종 변경 head와 연구 판정의 재집계 증빙 필요. |
| 34-21–23 | threshold→Pareto→priority·decision·사용법 | `implemented_verified` | E7/E12, [실행 안내](week3-live-pipeline.md). 실제 권고 확정 아님. |
| 34-24–26 | 두 앱 반복·예산/재개·실제 wire | `implemented_verified` | E2/E3 및 입력 검증 report. |
| 34-27 | 새 A 명세와 구현·export 일치 | `evidence_pending` | E7 loader·정책 회귀와 E12. 최신 전체 검증·재생 결과로 마무리. |
| 34-28–30 | 재생성·정직한 결측·C 연결 | `implemented_verified` | 저장 조회 0호출·E11. 최신 최종 검증란은 별도. |

### #35 화면·통합

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 35-01–05 | 목록/상태·필터·비교 흐름·불일치·범위 | `implemented_verified` | E11/E12, cohort 버전·실행 종류·빈/한/부분/오류 상태 구별. |
| 35-06–10 | 지표·표본/CI·D2 별도·미확인·하위 결과 | `implemented_verified` | 서버 sample counts·버전 inventory·가격 근거·목표별 그룹을 소비. 실제 미평가 지표는 그대로 비워 둠. |
| 35-11–14 | 방어 색상·비용 점·CI·Pareto/정책 사유 | `implemented_verified` | E12. 정상 benchmark 참조를 명시하고 미확인 비용도 빈 점으로 남김. |
| 35-15 | family별 payload 노출률/차이·목표 분리 | `evidence_pending` | 표·family 비교·CI 표시 구현 E12. 실제 인용 실행과 수동/AI 판정 반영 범위는 E6/E9와 구별. |
| 35-16–18 | 사례→trace·문서 포함·같은 snapshot export | `implemented_verified` | E11/E12. 선택 변경 시 이전 trace 제거, CSV 준비 시 snapshot 정합성 회귀 포함. |
| 35-19 | 보호값·인증정보·raw 다운로드 마스킹 | `evidence_pending` | 기존 canary/키 검증과 임의 등록 target reason 마스킹 회귀는 있음. 과거 non-canary 보호값의 전체 공개 trace 검증 범위를 보완해야 함. |
| 35-20 | 저장 재생·사용 안내·시연 | `implemented_verified` | `serve --pipeline-output` 안내와 기존 시연 문서. 과거 demo 배치 ID·분모·수치를 현재 실험으로 대체하지 않음. |
| 35-21 | 같은 필터의 A/B/export/UI 대조 | `evidence_pending` | E11 API/저장/화면 대조 완료. 최신 연구 판정·최종 head 검산 기록은 추가. |
| 35-22–24 | 두 앱 대표·특수 상태·0호출 재현 | `implemented_verified` | E2/E3/E11와 명시적 합성 상태 회귀 E12. |
| 35-25 | A/B 공동 시연·불일치/마스킹 기록 | `human_review_pending` | 자동·AI 인계 기록을 실제 A/B 공동 인수 서명으로 쓰지 않음. |
| 35-26–31 | 필터·지표/추천·payload·그래프/trace·export | `implemented_verified` | E11/E12. 검토 대기와 표본 부족은 완료 판정으로 바꾸지 않음. |
| 35-32 | 특수 상태와 다운로드 마스킹 증빙 | `evidence_pending` | 상태 회귀는 있음. 위 non-canary 보호값 범위와 최신 head 확인을 포함해 닫아야 함. |
| 35-33 | 4주차 화면·대표 결과·사용법 인계 | `implemented_verified` | E2/E3/E11와 이 표. 최종 발표물·연구 결론의 완성까지 주장하지 않음. |

### #29 공격 성공 기준·payload ablation

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 29-01–02 | 성공 종류·권한/지식·공통 정책 | `implemented_verified` | E3/E7/E8. a006 표식과 미지 정보 유출을 분리. |
| 29-03–05 | 새 버전 4조건·제거/인용·대표 family·metadata | `implemented_verified` | E3/E6. strict single-factor 한계와 새 direct 업무 질문을 기록. |
| 29-06 | 독립 gold/rubric·shortcut 점검 | `human_review_pending` | AI target/taxonomy 검토 E8과 입력 metadata 분리 검사. 사람 검수와 의미 동등성 확정은 pending. |
| 29-07 | 실제 paired 파일럿·원시 근거·팀 판정 | `human_review_pending` | E3 실제 파일럿·E9 AI 검토, 팀 판정 없음. |
| 29-08 | holdout 전 최종 고정 | `not_in_dev_scope` | dev 기준 E7 채택; holdout 승인·소비 없음. |
| 29-09–10 | 단위별 효과·원본/제거/인용 결과·불확실성 | `evidence_pending` | E3 exact·기존 paired 비교와 E6 신규 준비를 섞지 않음. 새 인용 실행과 의미 판정·정상 손실 분석 필요. |

### #12 판정·선정

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 12-01–02 | 산식·상태·기준/반복/통계/우선순위 | `implemented_verified` | E7/E12. dev 결정 완료이고 pre-holdout 사람 동결·운영 허용 기준이라는 뜻은 아님. |
| 12-03–07 | paired 실행·지표/CI·탈락·Pareto 재현 | `implemented_verified` | E2/E3/E12. 표본 부족의 null CI와 deferred도 유효한 산출물이다. |
| 12-08 | 앱/언어/유형/심각도 실패 구간 검토 | `evidence_pending` | 필터·근거 연결 지원. 원래 324건 severity는 unspecified이며 영어/대규모 하위 분석도 제한됨. |
| 12-09 | 최종 추천 구성 확정 | `not_in_dev_scope` | dev decision record와 보류 이유는 재생성 가능. 최종 안전성·holdout 기반 운영 선택은 미확정. |

### #26 D2 우회 검증

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 26-01 | 공격 대상·실제 검사문·정답 근거 분리 | `implemented_verified` | raw 검사 payload·target별 gold 계약·E8/E10. |
| 26-02 | 서로 다른 D2 조작 공격 최소 6건 | `implemented_verified` | 기존 catalog dev 4개에 기반해 인코딩·다국어 새 변형을 포함한 dev 6종과 쌍 대조 6건을 준비 E13. holdout a025/a026은 사용하지 않음. 실제 반복 효과 검증은 아래와 별도. |
| 26-03 | 대응 정상 보안 대조군 최소 6건 | `implemented_verified` | dev b021–b024·h021–h024가 있음. 원본/변형/반복 수를 별도 셈. |
| 26-04 | input/document 각각 별도 검수 | `human_review_pending` | dev 실제 target 30개 AI 검토 E8, a006 입력 benign/문서 malicious 구별. E13 새 입력 benign·attack 문서 malicious·quoted 문서 hard-negative의 AI gold도 준비됨. 실제 사람 독립 검수는 없음. |
| 26-05 | 동일 조건의 모드/위치·버전 비교 | `implemented_verified` | E2/E3 고정 구성·위치·모델/threshold/정책 저장. 6개 D2 공격 전체의 반복 효과 검증을 뜻하지 않음. |
| 26-06 | dev 조정·정책 고정·split·정답 분리 | `evidence_pending` | split·입력 경계·기존 D2 설정 기록은 있음. dev 6종의 임계값/정책 효과 평가와 holdout 전 최종 동결은 구별 필요. |
| 26-07 | 대상 FNR/FPR·오류·생성/정상 지표 | `evidence_pending` | 집계 구현 E12. 실제 등록되지 않은 target은 비율 분모에서 제외·미등록 수 공개. E5 한 번의 진단을 최종 FNR로 쓰지 않음. |
| 26-08 | 원시 독립 평가·수동 검토·run 연결 | `human_review_pending` | E8–E10, 실제 사람 판정과 조정 기록 없음. |
| 26-09 | 검사·재시도 전체 계측·표시 | `implemented_verified` | E2–E5 ledger·call/usage/error·UI. 검토 task 수와 실제 사람 작업 시간을 혼동하지 않음. |

## checkbox 밖의 필수 설계·완료 문장

| 원문 범위 | 대조 결과 |
| --- | --- |
| #32 비교 조건 1–8 | 6개 고유 실행·paired mode/position·고정 버전·seed 한계·case 반복 의존성·방어 차단 포함·오류/검토 제외를 구현. payload 실증과 독립 검토의 남은 범위는 32-07–10 참조. |
| #29 2.1의 5개 성공 유형 | marker·보호값·작업/형식·D2를 분리. 실제 도구 실행·외부 수신이 없는 URL/HTML/가짜 trace는 외부 전송 성공으로 판정하지 않음. |
| #29 2.2–2.3 | marker/secret 지식 조건·C01 기본 노출·공통 정책을 명시. 부분/복원 인코딩은 개별 목표에 따른 근거가 필요하며 exact-match 부재를 안전 증명으로 쓰지 않음. 새 무작위 보호값을 실행 블록마다 재생성하는 실험은 현재의 고정 합성값 파일럿과 별도다. |
| #29 3.1–3.3 | C00/C01/A10/A11·override 제거·D2 조작만 제거하는 악성 목표 유지 쌍 구현. quoted 신규 준비. 역할 사칭 제거·출력 형식 강요 제거의 모든 추가 축을 이미 실험한 것으로 쓰지 않음. 정상본 b006/기존 hard-negative는 엄격한 공격 제거 쌍이 아님. |
| #29 4의 5단계 | 구조·실제 노출·고정 파일럿·추가 효과·상태 분리로 추적. 후보 유효성, 특정 모델에서의 관측, 효과 불명확, 실행/노출 오류를 구별. 성공만 선별한 E4 사례를 전체 성능으로 쓰지 않음. |
| #26 완료 기준 6문장 | E13에서 최소 6 dev 공격·쌍 정상 6개·대상별 AI gold·3회 계획을 준비했지만 실제 결과·반복 효과는 아직 없음. 유효 JSON 의미 오판과 형식 오류는 별도 계약·회귀/관측으로 구별하며 최종 생성 성공과 분리. 추가 대책의 효과·잔여 위험과 효율성 결론은 해당 실제 증거 범위로 제한. |
| #26 댓글의 보호·대안·계측 | 텍스트 전용 D2·지침/검사 분리·schema/점수 검증·기본 fail_closed·threshold/모순 정책 지원. 전용 classifier·독립 모델·결정론 방어·D3 도입은 이번 dev 필수 범위 밖이며 효과를 주장하지 않음. 실제 수동 검토 시간은 미계측, task 수만 준비됨. |
| #12 필수 하위 분석 | 앱/언어/공격/목표/심각도/구성별 선택을 지원하되 미지원 영어 holdout·실제 다중 턴·도구 실행의 성능은 미평가. 개별 CI를 다중 비교의 유의성 보정이나 통계적 동등성 입증으로 쓰지 않음. |
| #34/#35 인계·범위 | API/저장/export/화면의 단일 집계 출처를 유지. 합성 상태 검증을 실제 모델 효과로, 과거 CI를 최신 CI로 대체하지 않음. 상용 운영 화면·외부 공개·최종 발표물 완성은 별도 범위. |

## 현재 실제로 남는 항목

1. **최신 head 전체 검증·재생성.** 기능별 기존 로그는 있으나 최종 commit과 일치하는 root/backend 회귀·두 OS CI·실제 저장 배치 재생 결과를 기록해야 한다. 이 항목은 담당자가 진행 중이며 성공을 미리 적지 않는다.
2. **등록된 비-canary 보호값의 표시 범위.** 수정 전 원래 324건의 frozen 규칙을 기준으로 검사하면 non-canary `protected_values`가 설정된 공개 trace 72개 중 54개의 전체 JSON에 등록된 합성 목표값이 남아 있었다. 표시 출력에서 발견된 것은 0개이고 주로 prompt/context의 값이다. 원문은 이 문서에 싣지 않는다. 기존 `public_canary_leak=false`는 이 검사와 동치가 아니다. 현재는 batch membership·frozen 규칙 해시를 확인해 fresh GET과 전체 공개 trace에 마스킹을 적용하고 raw·비공개 평가 이력은 보존하는 수정이 진행 중이다. 최종 회귀와 실제 저장 자료 재생을 확인해야 34-13/35-19/35-32를 닫을 수 있다.
3. **실제 판정과 새 분석 연결.** 원래 E3 snapshot의 공격 success 21/failure 69/review_needed 54/not_applicable 180, 정상 review_needed 230/failure 94, BatchReview 0, D2 target 306개 미등록 상태를 보존한다. E9의 새 AI 정상 판정은 별도 provenance로 검산·연결해야 하며 pending 1건을 실패나 성공으로 강제 변환하지 않는다.
4. **새 인용 108건과 #26의 새 216건 반복 효과.** E6/E13의 별도 준비·계획과 실제 모델 실행을 구별한다. holdout a025/a026을 사용하지 않고 dev 6종 설계는 보완했다. 새 실행을 진행하면 고정한 행렬·예산·정책·실제 입력·판정과 비용을 별도 기록한다.
5. **하위 분류·독립 검토.** 원래 324건은 severity가 전부 unspecified이고 이메일 공격의 goal도 unspecified다. 새 [위험·목표 등록](../configs/week3-case-risk.v0.2.json)과 compiler 연결이 진행 중이며 old manifest는 덮어쓰지 않는다. 새 metadata/분석 버전의 실제 증거로 범위를 확정해야 한다. 번역 3개 AI 재검토는 E8에 추가됐으며, 사람 번역 검토·family 독립성·독립 사람 판정과 3역할 합의는 각각 남겨 둔다.

holdout의 최종 평가·운영 배포/최종 안전 구성 확정은 `not_in_dev_scope`다. 위 dev용 기준 결정이 끝났다는 사실과 최종 연구 인수가 아직 아니라는 사실은 동시에 성립한다.

## 과거 대기 문서와 이번 기록의 관계

[이전 백엔드 인수표](week3-backend-acceptance.md)는 PR #36 인계 당시의 기록이다. 다음 과거 문구를 현재 전체 상태로 읽지 않는다.

| 과거 기록 | 이번에 확인한 현재 해석 |
| --- | --- |
| 집계 보완 버전 v0.2·실제 payload 효과 미완료 | E3의 실제 324건·v0.3·exact paired 관측과 E11의 v0.4 재생이 추가됨. 최신 목표/정상 benchmark·선정 cohort는 E12의 별도 구현·검증 범위. |
| C 전체 대시보드 연결 대기 | E11/E12와 [화면 완료 기록](../frontend/verification/week3-dashboard-completion.md)이 추가됨. 실제 A/B/C 공동 인수 서명은 여전히 없음. |
| 서비스 threshold·최소 표본·우선순위 미정 | E7에서 사용자 위임 연구 결정으로 수치·방법을 채택함. 외부·사람 검토 대기를 수치 미정으로 되돌려 표현하지 않음. |
| paired 데이터 초안·빈 A 산출물 | E3 실행, E6 새 인용 준비, E8 AI gold·분류, E9 정상 출력 AI 검토와 E10 독립 검토 packet이 생김. 사람 검수 완료와 새 인용 실제 실행을 뜻하지 않음. |
| root/backend/Ubuntu·Windows CI·PR #36 대기 표 | 과거 표를 새 head 통과 증거로 사용하지 않음. 최종 결과는 아래에 새 commit·로그·CI URL로 기록해야 함. |
| 경로에 남은 `v0.1? ... ??` 표기 | 실제 현재 export는 `exports/<report_version>/<전체 report hash>/`의 JSON/CSV/decision record와 대조. 과거 export를 삭제·덮어쓰지 않음. |
| `data/week3/*review*.md`·ablation 보고서의 실제 실행 미완료 | 그 작성 시점의 정적 초안 기록을 보존. 이번 E3/E7–E10이 추가된 범위만 갱신된 근거로 참조. |
| 과거 시연의 108건·12그룹·비어 있는 산점도 | 해당 배치의 실제 기록. 현재 324건·목표별 그룹·새 AI 판정·새 policy와 혼동하지 않으며 `serve --pipeline-output`으로 해당 배치를 명시. |

## 최종 검증 담당자 기록란

아래 항목은 **현재 미기록·최종 확인 예정**이다. 파일 존재나 과거 통과 로그만으로 자동 완료 처리하지 않는다.

| 검증 | 최종 commit/결과 | 증빙 |
| --- | --- | --- |
| root 전체 회귀 | 미기록 | 최종 head의 명령·개수·결과·로그 해시 기록 예정 |
| backend 전체 회귀 | 미기록 | 최종 head의 명령·개수·결과·로그 해시 기록 예정 |
| 실제 324 저장 재집계/API/export/UI 재생 | 미기록 | report version·집계 구현 SHA·평가 snapshot·추가 모델/네트워크 0·원본 불변 기록 예정 |
| 새 연구 정책·인용 준비·AI 검토 자료의 정합성 | 미기록 | 새 output/해시·검사 명령·검토 방법·미해결 수 기록 예정 |
| Ubuntu CI / Windows CI | 미기록 | 해당 최종 head의 run URL·결과 기록 예정 |
| PR·검토·merge | 미기록 | 최종 head·base dev·실제 검토 결과·merge commit 기록 예정 |
