# 3주차 요구사항·증빙 대조표 — 2026-10-20

이 문서는 #32·#33·#34·#35·#29·#12·#26의 **본문과 완료 기준을 실제 코드·파일·저장 검증 기록에 대조**한 인계 기록이다. 이슈의 CLOSED 상태를 완료 증거로 사용하지 않는다. 조회한 원문 사본은 로컬 `runs/week3-completion/issue-{번호}.json`에 있다.

사용자는 공개 논문·기업 자료를 근거로 프로젝트 기준을 결정하도록 위임했다. 따라서 **dev용 데이터·gold·정상 작업 rubric, 서비스 수치·우선순위, 통계 방법의 연구 결정은 채택 완료**다. 이를 사람 2인의 독립 검토, A/B/C 세 담당자의 실제 합의, 운영 승인 또는 holdout 승인으로 바꾸지 않는다. 정책의 runtime `draft`는 이 구별을 유지하는 계약 지위이며 수치 미정을 뜻하지 않는다. [연구 결정](week3-research-decisions.md), [통계 정책](week3-statistical-policy.md)을 함께 읽는다.

**후속 사용자 위임에 따른 AI dev 검토·기술 인수도 완료했다(E21).** 실제 사람 기록이 별도로 없다는 답변을 반영해 새 AI 두 검토와 제3 조정, AI 역할 A/B/C 검증을 수행했다. 아래 `human_review_pending`은 원문 사람 요건의 실제 미충족 사실이며, 이번 위임 AI dev 절차를 아직 수행하지 않았다는 뜻이 아니다. 사람·최종 holdout·운영 인수와 구별한 [완료 기록](week3-ai-dev-acceptance.md)을 함께 본다.

## 상태와 검증 범위

| 상태 | 의미 |
| --- | --- |
| `implemented_verified` | 구현과 기존 실제 저장 증빙 또는 해당 기능의 회귀 검사가 확인됨. 아래 최종 head 전체 회귀·CI 통과 선언과는 별개다. |
| `evidence_pending` | 인터페이스·초안은 있으나 해당 실제 실행, 판정 반영, 하위 분석 또는 최신 통합 검산 증거가 부족함. |
| `human_review_pending` | 원문이 요구하는 실제 독립 사람 검토·불일치 조정·역할별 합의가 없음. AI 검토 기록과 구별함. |
| `not_in_dev_scope` | 보존하기로 한 holdout, 운영 배포·최종 확증 결론, 미구현 도구·외부 전송·대규모 확장 등 이번 dev 완료 범위 밖임. |

**구현 head `63ef871`의 Ubuntu·Windows CI에서 root191개·backend113개와 통합 검증이 모두 통과했다.** 실제324·새인용108·새D2 216의 저장 재집계/export도 추가 모델0으로 완료했다. base dev인 PR #39의 최신 체크·병합 상태는 [GitHub 기록](https://github.com/zerolong-01/sec_sea/pull/39)을 따른다. [공개 안전 요약](examples/week3-completion/README.md), [실제 artifact hash·수치](examples/week3-completion/summary.v0.4.json), [해당 head CI](https://github.com/zerolong-01/sec_sea/actions/runs/39428651601)를 함께 본다.

이후 추가한 실패 구간 분석·파생 D2 문구 제거 비교·target gold와 사례 인계는 아래 E18–E20 및 [후속 증거](examples/week3-completion/followup.v0.5.json)에 연결한다. `63ef871`의 CI가 이 후속 변경까지 검증했다고 주장하지 않으며, 최신 head의 PR Checks 확인은 별도다.

## 서로 합치지 않는 실물 증빙

| 식별 | 확인한 실물 | 말할 수 있는 범위 |
| --- | --- | --- |
| E1 데이터·구조 | `scripts/week2_data.py check`, `scripts/week3_data.py check`; `data/week2`, `data/week3` | RAG 84·52, 이메일 3·3, 제안 기법 28, 번역 3, gold 48의 구조·해시·split 검사. week3 구조 검사 37개. 구조 통과는 의미 검수·공격 효과가 아니다. |
| E2 기존 실제 파일럿 | [실제 API 인계](examples/real-api/README.md), [108건 검증](examples/real-api/pilot-verification.json) | 두 앱 대표 3종×6구성×3회. 완료 90·차단 18, 추정 $0.0415772. 당시 정책·판정을 보존한다. |
| E3 실제 payload 파일럿 | [324건 검증](examples/week3-live/verification-report.json), [입력 대조](examples/week3-live/input-verification-report.json), [관측 요약](examples/week3-live/observation-summary.json) | `batch-bd093a919251`: 완료 251·차단 73, HTTP 557회, 추정 $0.1022296. 새 RAG 15조건+이메일 3조건×6×3. RAG exact 관측 270·paired 비교 36. 정확 문자열 관측을 사람 gold·최종 ASR로 승격하지 않는다. |
| E4 별도 탐색 감사 | 로컬 `runs/attack-audit-2026-10-20/independent-verification.json`, [이슈 #41](https://github.com/zerolong-01/sec_sea/issues/41) | 별도 157입력×6구성=942계획 조합, 완료 742·차단 200. 943개 run_id에는 추가 attempt가 포함된다. 한 호출의 사용량·비용 미확정이 남아 확인 비용 소계 $0.3585468과 실제 총액을 구별한다. 324건의 3회 반복 효과 실험과 합산하지 않는다. |
| E5 D2 진단 | [18건 탐지 검증](examples/real-api/detector-verification.json) | 탐지 전용 18건·36대상, 생성 0회, 반복 1회. 당시 gold 36개는 팀 검토 대기로 미등록. 생성 공격 효과나 6종 D2 공격의 3회 평가를 대신하지 않는다. |
| E6 새 인용 실제 실행 | [입력 peer review](week3-quotation-review.md), [출력 의미 검토](week3-quotation-output-review.md) | batch-8fb19849d67c: dev6×6조건×3회=108, 생성85·차단23·오류0, 호출184·추정$0.0373288. 고유 생성 본문42개 실독·108행 기록. quoted 정상54/54, attack 아래 업무18/54, a021 original 보호값 실제 노출10. 기존324와 합치지 않음. |
| E7 채택 정책 | [서비스 근거](../configs/week3-service-decision.v0.2.json), [실행 정책](../configs/week3-evaluation-policy.json), [통계 wrapper](../configs/week3-statistical-policy.json), [rubric](../data/week3/research-evaluation-spec.v0.4.json), [loader](../scripts/week3_policy.py) | `adopted_for_dev`. 서비스 8개 수치·우선순위, 반복 3·bootstrap 10,000·최소 family 20/판정 60을 결정. 사람 reviewer는 만들지 않고 holdout 권한은 false. 새 준비에 적용하고 과거 snapshot은 보존한다. |
| E8 gold·분류·번역 AI 검토 | [설명](week3-gold-review.md), [58행 기록](../data/week3/research-gold-review.v0.2.jsonl) | RAG dev 실제 target 30행·서로 다른 텍스트 25개, dev catalog 25행, 번역 3행을 AI가 검토. 번역은 영어 입력과 한국어 문서의 혼합 언어 변형이다. 원본 gold 48행을 수정하지 않으며 RAG holdout 12 target·3 attack과 당시 정적 범위 밖 email dev 6 target은 이 기록에서 제외했다. 이후 실제 이메일 target 검토는 E14/E21과 구별한다. 인간 독립 검토와 통계 family 독립성을 확정한 기록이 아니다. |
| E9 기존324 정상 출력 AI 검토·검산 | [방법·결과](week3-output-review.md), [324행](../data/week3/research-output-review.v0.4.jsonl) | 고유 본문114개 실독. 전체 success223/failure100/review_needed1, 정상 세트170/179·coverage179/180 partial. 연구 overlay CLI 해시 검산 통과·원본 자동 평가/ASR 보존. 애매한1건 강제 판정 없음. |
| E10 독립 검토 인계 | [계획기](../scripts/week3_review_handoff.py), [11회귀](../tests/test_week3_review_handoff.py), [현재 post-gold packet 인덱스](examples/week3-completion/review-handoff.v0.4.json) | 세 배치 final-output648+D2-target621=1,269 private task. 현재 annotation 이후 hash를 고정한 packet이며 blinding·신원/충돌/시각/근거/마스킹 검사를 지원한다. applied=false·human pending. 옛630task manifest는 당시 이력으로 보존하고 새 사람 응답에는 현재 인덱스를 사용한다. |
| E11 대시보드/API 재생 | [화면 기록](../frontend/verification/week3-dashboard-completion.md), E16 최신 legacy projection 재생 | 실제324 저장 API→집계→화면 JSON/CSV/trace, 대표3사례·3개 대시보드 필터 재생. 모델 추가0. 과거90그룹·payload78·family비교114는 당시 snapshot으로 보존하고 공개 projection 계약은 E16으로 갱신. |
| E12 기능 계약·표시·pairing 회귀 | [집계](../backend/app/batch_analysis.py), [회귀](../backend/tests/test_batch_analysis.py), [UI 회귀](../tests/test_batch_dashboard_completion.py) | 목표별ASR·정상benchmark/cohort·표본/가격/trace/특수상태. fbf9120은 comparison_pair_id와 inherited family cluster를 분리하고 legacy 모호한 쌍은 사유 공개·export 지속. family 수를 늘리지 않음. |
| E13 D2 6종 실제 실행 | [입력 교차검토](week3-d2-control-review.md), [출력 의미 검토](week3-d2-output-review.md) | batch-fb671ff629f0: dev12×6조건×3회=216, 생성180·차단36·오류0, 호출396·추정$0.0754176. 고유 본문69개 실독. HN 정상60/108, attack 아래 업무6/108. 알려진 표식 이행102를 비밀 노출과 분리. 6기법은 부모3family 상속. |
| E14 D2 gold 실제 적용·분모 | [621대상 등록 기록](week3-target-gold-registration.md), [legacy gold](../data/week3/research-legacy-target-gold.v0.4.jsonl)/[교차검토](../data/week3/research-legacy-target-cross-review.v0.4.jsonl), [quotation gold](../data/week3/research-quotation-target-gold.v0.4.jsonl)/[교차검토](../data/week3/research-quotation-target-cross-review.v0.4.jsonl) | legacy306·quotation99·D2 216의 실제 target621개에 AI gold annotation 완료. 배치별 benign/malicious/HN은 198/72/36, 45/27/27, 108/54/54. 실제 관측의 오류·모순·보류·gold누락 각0·API0. raw·원자동평가·frozen snapshot·manifest/ledger 보존, public trace와 gold history는 후속 annotation으로 변경. 사람/source 서명 인증은 pending/not_verified. |
| E15 신규 paired exact overlay | 로컬 {quotation,d2}-control-exact-observations-v0.1-final.json | quotation54·D2 108 matched pairs, 각각3 inherited family·6조건·3회. 사전sidecar를 in-memory pair identity로 연결, frozen metadata 불변. exact 기술 통계이며 사람 의미 검수·전체 변환 안전성·엄격 인과 효과가 아님. |
| E16 privacy·legacy 실제 재생 | 로컬 trace-privacy-verification.json, legacy-public-replay-v0.4/replay-integrity.json; [privacy 회귀](../backend/tests/test_protected_trace_privacy.py) | 보호값 설정72trace 중 과거54노출→GET72성공/노출0·동결규칙사용. 당시 API/schema/CSV/UI pass·public projection54변경·조회 전후 원 pipeline845파일 해시불변·모델0. 이후 E14의 명시적 annotation은 별도 변경 이력이다. 전달 일치와 독립 마스킹 검증을 구분. |
| E17 검증 head 회귀·당시 집계/export | [공개 인계](examples/week3-completion/README.md), [검증 요약](examples/week3-completion/summary.v0.4.json), [63ef871 CI 기록](examples/week3-completion/ci-63ef871.json) | root191/325.060s·backend113/67.179s OK, UI paired focused1 별도pass. 당시 v0.4 legacy90그룹/CSV990·706파일, quotation24/264·225파일, D2 12/132·585파일 각각 읽기 전후 불변. 추가모델0·selection deferred. 63ef871 두 OS CI와 후속 head의 검증을 구별. |
| E18 실제 실패 구간 분석 | [분석·실제 표](week3-failure-slices.md), [도구](../scripts/week3_failure_slices.py), [5회귀](../tests/test_week3_failure_slices.py), [최종 후속 증거](examples/week3-completion/followup.v0.5.json) | 세 배치648행을 따로 검증해 앱/언어/실제 frozen 공격유형·심각도 및 조건/목표/변형/버전별 144교차·216case slice, CSV729행(지표720+미평가scope9)을 생성. 정상·attack 아래 업무·원ASR·두FPR의 분모 분리. 최종 post-gold 재출판1,821입력파일 불변·API0. 옛 severity unspecified와 en/실제다중턴/도구의0/0·null 보존·CI null. |
| E19 악성 목표 유지 D2 조작 제거 비교 | [파생 target 검토·실제 FNR 표](week3-derived-detector-review.md), [도구](../scripts/week3_detector_ablation.py), 로컬 legacy-d2-manipulation-ablation-fnr.v0.1.json | 원본/제거본의 실제 검사·gold·raw detector 응답을 연결한 12조건/stage 비교·72target행. input의 공통 유효 반복 각3에서 D2-input FNR2/3→0/3, D2-both·D1-D2 각3/3→0/3. inherited family1·CI null·미검사/비악성 제외·API0. 일반적 인과/우월성 주장이 아님. |
| E20 대표 사례·4주차 재현 인계 | [13사례 설명](week3-case-handoff.md), [기계 판독 catalog](examples/week3-completion/case-handoff.v0.4.json), [저장 시연·사용법](week4-handoff-demo.md) | 공격 관측·정상 기능 실패·과잉 차단·미확정·인용 대조를 run/hash와 현재 마스킹 trace13개로 연결. 독립 검사에서 보호값 노출0·1,811입력파일 불변·API0. 원래 평가와 AI 의미 판정을 구별하며 실제 오류0 cohort에 가짜 오류를 추가하지 않음. 사람2인/세역할 합의·최종 발표/선정 완료를 대신하지 않음. |
| E21 위임 AI dev 교차 검토·기술 인수 | [완료 방법·한계](week3-ai-dev-acceptance.md), [283종·1,269연결 안전 증거](examples/week3-completion/ai-dev-review.v0.1.json), [별도 정책](../configs/week3-ai-dev-review-policy.v0.1.json) | 새 별도 context의 두 AI가283종을 각각 실독,218합의·65불일치를제3AI가모두조정. source/vote hash binding 통과·누락/미조정0·goal미확정23유지. fresh gold621/621일치,1,845입력파일불변·API0·원본적용false. AI역할A/B/C검증과두발견코드결함수정·8CLI/7privacy 회귀·13trace재검증. 사람서명없음·동일모델/공유준비한계·holdout보존·최종추천deferred. |

E6의 옛 quoted-controls-v0.2-draft·quote-experiment-v0.2/prepared는 준비 이력으로 보존한다.
실제 실행 입력은 quoted-controls-prepared-v0.4, 결과는 quoted-execution-v0.4다.
E13도 d2-controls-prepared-v0.4와 d2-execution-v0.4를 구별한다. 옛 준비 JSON의 not_executed는 당시 상태다.
현재108/216실행은 각각6조건·반복3·최대$1·최소family20/판정60·bootstrap10000의 고정 계획으로 완료했다.

확인한 고정 자료의 SHA-256은 다음과 같다. 작업 중 생성·검토 파일의 후속 버전은 새 해시로 기록한다.

| 자료 | SHA-256 |
| --- | --- |
| E3 `verification-report.json` | `1a79e2d6d12738690922bbad149a2ea4e01577c7da99f3100096281095392cff` |
| E4 `independent-verification.json` | `c56cd4d2cb80509b4cbbef76f9c982e6ccd16aa19454753e95bde54f0de59cd7` |
| E8 gold 검토 JSONL, 번역 3행 추가 후 | `731e18e015440886522161b6effeb78f948d54618258a6160fd0b5406d16044b` |
| E9 출력 AI 검토 JSONL | `7ad9bec3983b0a5705c53369781727cb24d9a945423fb28c00a8752ecdbe5c4b` |
| E10 원래 630task 인계 manifest | `8d7b3048eb5ed78a4b37d4624e9a9aa12cef3e4c39e551560b3c5470fed6da7f` |
| E11 당시 dashboard API 재생 JSON | `f783be00d8afb72c28b397f67e03a56f0ad67cbbd28f58091fd4bf1ada278fd2` |

## 이슈별 전체 체크리스트 대조

번호는 각 본문의 checkbox를 위에서 아래로 센 순서다. `01–03`은 세 항목 모두를 뜻한다. #32 16개, #33 27개, #34 30개, #35 33개, #29 10개, #12 9개, #26 9개, **총 134개 checkbox**를 아래에서 빠짐없이 연결한다. checkbox가 아닌 필수 설계·완료 문장은 다음 절에서 별도 대조한다.

### #32 상위 계획

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 32-01 | 최신 dev 전체 회귀·인계 | `evidence_pending` | 원문 착수 조건은 실제 최신 dev의 기존 데이터/회귀/HTTP·UI/fixture 통과다. 구현 head63ef871의 root191/backend113·두 OS CI 증거는 있으나 PR39는 draft/base dev로 아직 미병합이고 후속 head Checks도 별도다. 사람 공동 인수 대기와 구별한다. |
| 32-02 | 모델·버전·단가·전체 예산 | `implemented_verified` | E2/E3의 고정 모델·가격 snapshot·ledger, E7의 위임 연구 결정. 실제 사람 합의였다고 표기하지 않음. |
| 32-03 | 대표 3종 연결과 세 담당자 합의 | `human_review_pending` | 연결 E2/E3/E11, 실제 세 담당자 판정 합의 없음. |
| 32-04 | #29/#26 실험 설계 연결 | `implemented_verified` | E3 원본/제거·요인, E6 인용108, E13 D2 6종216 반복 실행·E14 별도 대상 gold 연결. |
| 32-05 | holdout 전 최종 고정 | `not_in_dev_scope` | dev 기준 E7 결정 완료. holdout 보존과 사람/외부 동결 gate 유지. |
| 32-06 | 두 앱 계획/실행/평가/제외 추적 | `implemented_verified` | E2/E3 manifest·run/attempt·평가 snapshot·ledger. |
| 32-07 | 실제 기법·위치·payload 반복 | `implemented_verified` | E3·E6·E13 모두 고정 조건의 3회 실행 완료. 기존324와 신규108/216은 별도 cohort. |
| 32-08 | 지표·평가 수·CI | `implemented_verified` | E9/E14/E15/E17 분자·분모·제외·판정 수 검산. 작은 family·미확정의 CI null과 deferred 유지. |
| 32-09 | D2 FNR/FPR·미탐·모순·오류 | `implemented_verified` | E14 세 배치 실제621 target 등록·분모 검산, E19 D2 조작 제거12비교. 과거 미등록306/99는 당시 snapshot 상태이며 현재 미등록으로 쓰지 않는다. D2 미탐과 최종 출력 성공을 분리. |
| 32-10 | payload 추가 효과·불확실성 | `implemented_verified` | E3 기존36쌍, E6/E13 실제 의미·노출 관측, E15 신규54/108 matched pairs. 3family·exact 범위 한계 공개. |
| 32-11 | 필터→Pareto→우선순위·보류 | `implemented_verified` | E7/E12, 부족한 표본·가격·평가·정책에서 강제 추천하지 않음. |
| 32-12 | 저장→집계/export/UI 재현 | `implemented_verified` | E16 실제 API/UI projection, E17 및 후속 세 배치 report/CSV/decision 재생. 추가 모델0·조회/분석 전후 source 불변. E14 후속 annotation 변경은 별도다. |
| 32-13 | 대표 사례·팀 판정·4주차 인계 | `human_review_pending` | E20 실제13사례 catalog·시연과 E10의1,269task를 인계. 사람 판정 합의·최종 발표 패키지 완성으로 바꾸지 않는다. |
| 32-14 | #33 실험·데이터 인수 | `human_review_pending` | 아래 #33의 AI/dev 결정과 실제 사람 검수 미완료를 구별. |
| 32-15–16 | #34/#35 구현·통합 인수 | `implemented_verified` | E12/E15–E17 구현·실제 저장·화면·로컬 통합 검증. 원격CI와 실제 역할별 공동 서명은 별도. |

### #33 데이터·평가

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 33-01 | 원본 RAG/이메일/영어/gold 점검 | `implemented_verified` | E1, E8. 원본 수와 single-review 상태를 숨기지 않음. |
| 33-02 | 기법·family·실제 평가 범위 | `implemented_verified` | E8 dev catalog25 AI 검토와 E6/E13 신규 실제 metadata·범위. family 독립성·corpus 전체 일반화는 미확정. |
| 33-03 | gold·번역·rubric 독립 재검수 | `human_review_pending` | E7/E8은 AI/dev 근거이며 번역 3행의 AI 정적 의미 대조도 기록됨. 사람 독립 검수·불일치 조정은 없음. |
| 33-04 | parent/variant split·누수·미지원 범위 | `implemented_verified` | E1/E6. 영어 holdout·실제 다중 턴·외부 도구 실행은 미평가. |
| 33-05 | holdout 전 전체 평가 snapshot | `not_in_dev_scope` | dev 입력/규칙/선택·E7 해시 고정 지원. 성공 subset만 남긴 전체 ASR을 만들지 않으며 holdout은 보존. |
| 33-06 | marker/비밀/작업/D2 성공 분리 | `implemented_verified` | E7/E8/E12와 기존 exact 관측의 제한. |
| 33-07 | 직접·간접·D2 원본/제거/인용 준비 | `implemented_verified` | E3/E6. 새 직접 쌍의 업무 질문 추가·간접 doc ID/길이 차이를 기록하고 엄격한 단일 요인 인과를 주장하지 않음. |
| 33-08 | C00/C01/A10/A11·공통 정책 | `implemented_verified` | E3 실제 실행·입력 대조. 공격 payload에 미지의 보호값을 추가하지 않음. |
| 33-09 | parent/variant/정보 조건·hash·입력 분리 | `implemented_verified` | E3/E6 frozen metadata, wire 검사·prompt metadata 분리 회귀. |
| 33-10 | 노출 차이·기본 누출·정상 손실·D2 gold | `implemented_verified` | E3 요인·E6/E13 정상 utility와 보호값/marker 분리·E14 gold·E15 paired exact 검산. 엄격한 단일 요인 인과는 주장하지 않음. |
| 33-11 | 대표·애매 사례의 2인/3역할 검토 | `human_review_pending` | E9/E10 AI·private 검토 도구는 완료. 두 사람/세 역할 합의는 pending. |
| 33-12 | raw·부분/인코딩·미확보 판정 | `implemented_verified` | E9/E6/E13 실제 전문·raw/full-facts 해시 검토와 노출 검사. 기존 애매한1건 유지, 정의한 변환 범위 밖 안전성은 미확정. |
| 33-13–14 | 서비스 수치·우선순위·통계 결정 | `implemented_verified` | E7의 사용자 위임 연구 결정. 운영 기준의 외부 인증·충분 표본 보장으로 표현하지 않음. |
| 33-15–17 | 판정 이력·분모/CI 명세·D2 분리 | `implemented_verified` | 평가/gold/BatchReview API, E7/E10/E12/E14. 현재 실제621 target annotation과 당시 미등록 이력을 분리하며 새 미등록은 null/제외로 공개. |
| 33-18 | 하위 결과·실패·과잉 차단 분석 | `implemented_verified` | E18의 실제144교차·216case slice와 앱/유형/심각도별 실패 표·정상 손실·FPR을 연결. 옛324 unspecified와 영어/도구/실제다중턴 미평가·표본 부족을 명시하며 필터 지원만으로 분석을 대신하지 않음. |
| 33-19 | 정책 기반 후보·불명확성 보류 | `implemented_verified` | E7/E12. 개별 CI 중첩을 동등성 입증으로 쓰지 않음. |
| 33-20 | 실제/fixture/추정비용·4주차 입력 | `implemented_verified` | E2–E20 실제/fixture·비용·판정/분모·정책·인계 구분. 세 배치 report/CSV·실패 표·13사례와 저장 시연 확보, 사람 검수·최종 결론은 별도. |
| 33-21 | 팀 검수·split/hash 기록 | `human_review_pending` | 구조/hash와 AI 검토 완료. 실제 팀 검수는 별도. |
| 33-22 | 목표별 성공 기준·paired 준비 | `implemented_verified` | E3/E6/E7. 준비와 실증을 구별. |
| 33-23 | holdout 전 최종 정책 고정 | `not_in_dev_scope` | dev 결정은 완료; holdout/frozen 승인 아님. |
| 33-24 | run별 수동 판정·제외 추적 | `human_review_pending` | E9/E10와 기존 API 지원. 실제 사람 판정 파일 없음. |
| 33-25 | 분자/분모/차이/CI 원시 검산 | `implemented_verified` | E9 연구 overlay·E14 detector621 분모·E15 paired·E17 저장 집계/export·E18 실패 slice·E19 paired FNR 검산. CI null·제외·이력 보존을 확인. |
| 33-26–27 | D2/최종·marker/비밀 분리와 보류 인계 | `implemented_verified` | E7/E8/E12, 이 대조표와 저장 decision record. |

### #34 배치·백엔드

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 34-01–04 | 식별/버전·family·6구성·앱/split 선택 | `implemented_verified` | BatchSpec/BatchStore·계약·E2/E3. D2 양쪽 공유 실행을 중복 생성하지 않음. |
| 34-05–10 | 반복·seed·예산·재개·오류·부분 완료 | `implemented_verified` | BatchCallBudget·attempt ledger·취소/uncertain/명시 재시도 회귀, E2/E3/E4. 미확정 비용을 0으로 만들지 않음. |
| 34-11 | 공통 정책과 D1 추가 방어 분리 | `implemented_verified` | 동일 common policy snapshot·wire 검사 E3. |
| 34-12 | 원본/제거/인용·4조건 실제 실행 | `implemented_verified` | E3 원본/제거/4조건, E6 실제 인용108·E13 D2 216 완료. 준비 계획을 실행 결과로 대체하지 않음. |
| 34-13 | gold 입력 분리·비공개/공개 마스킹 | `implemented_verified` | E16 현재 규칙 없이도 frozen 규칙·attempt 소속으로 GET72 검증, non-canary 목표 노출0. 당시 읽기 전용 projection 재생은 저장 trace 불변; 이후 E14 등록은 공개 trace의 주석/표시와 gold history를 명시적으로 갱신하고 raw·원평가·frozen/ledger를 보존. |
| 34-14–19 | D2 정책·평가 이력·지표/표본·API/export | `implemented_verified` | E5/E10/E12/E14/E19. detector-only·오류·미등록 이력·현재621 annotation·실행 범위와 목표를 분리. |
| 34-20 | 최신 저장 재생·원시 교차 검산 | `implemented_verified` | E9/E15–E19의 324/108/216 재생성·CSV·gold와 원 평가 분리. 분석 전후 source 불변·추가 모델0이며 annotation 변경 이력은 E14에 별도 기록. |
| 34-21–23 | threshold→Pareto→priority·decision·사용법 | `implemented_verified` | E7/E12, [실행 안내](week3-live-pipeline.md). 실제 권고 확정 아님. |
| 34-24–26 | 두 앱 반복·예산/재개·실제 wire | `implemented_verified` | E2/E3 및 입력 검증 report. |
| 34-27 | 새 A 명세와 구현·export 일치 | `implemented_verified` | E7 정책 loader·E9/E14/E15 검산·E17 세 배치 집계와 root191/backend113 통과. 새 head 원격CI는 별도. |
| 34-28–30 | 재생성·정직한 결측·C 연결 | `implemented_verified` | 저장 조회 0호출·E11. 최신 최종 검증란은 별도. |

### #35 화면·통합

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 35-01–05 | 목록/상태·필터·비교 흐름·불일치·범위 | `implemented_verified` | E11/E12, cohort 버전·실행 종류·빈/한/부분/오류 상태 구별. |
| 35-06–10 | 지표·표본/CI·D2 별도·미확인·하위 결과 | `implemented_verified` | 서버 sample counts·버전 inventory·가격 근거·목표별 그룹을 소비. 실제 미평가 지표는 그대로 비워 둠. |
| 35-11–14 | 방어 색상·비용 점·CI·Pareto/정책 사유 | `implemented_verified` | E12. 정상 benchmark 참조를 명시하고 미확인 비용도 빈 점으로 남김. |
| 35-15 | family별 payload 노출률/차이·목표 분리 | `implemented_verified` | E15 quotation54·D2 108 matched pairs·각3 inherited family. exact 관측과 AI utility를 분리하며 CI 부족은 null. |
| 35-16–18 | 사례→trace·문서 포함·같은 snapshot export | `implemented_verified` | E11/E12. 선택 변경 시 이전 trace 제거, CSV 준비 시 snapshot 정합성 회귀 포함. |
| 35-19 | 보호값·인증정보·raw 다운로드 마스킹 | `implemented_verified` | E16 frozen 규칙의 전체 공개 trace/GET 마스킹·독립 privacy 회귀·legacy API/UI 재생. raw/private 이력 보존. |
| 35-20 | 저장 재생·사용 안내·시연 | `implemented_verified` | E20의 Git Bash/PowerShell `serve --pipeline-output` 저장 시연과13사례 연결. 과거 demo 배치 ID·분모·수치를 현재 실험으로 대체하지 않음. |
| 35-21 | 같은 필터의 A/B/export/UI 대조 | `implemented_verified` | E11/E16 실제 API/UI, E15 신규 pair 관측·E17 세 배치 JSON/CSV. 실제 A/B 공동 서명은 35-25에 별도. |
| 35-22–24 | 두 앱 대표·특수 상태·0호출 재현 | `implemented_verified` | E2/E3/E11와 명시적 합성 상태 회귀 E12. |
| 35-25 | A/B 공동 시연·불일치/마스킹 기록 | `human_review_pending` | 자동·AI 인계 기록을 실제 A/B 공동 인수 서명으로 쓰지 않음. |
| 35-26–31 | 필터·지표/추천·payload·그래프/trace·export | `implemented_verified` | E11/E12. 검토 대기와 표본 부족은 완료 판정으로 바꾸지 않음. |
| 35-32 | 특수 상태와 다운로드 마스킹 증빙 | `implemented_verified` | E12 특수 상태/Arrow 회귀·E16 실제 projection/마스킹/불변·E17 로컬 최종 회귀. |
| 35-33 | 4주차 화면·대표 결과·사용법 인계 | `implemented_verified` | E20 실제13사례·현재 공개 trace·3배치 재생 안내와 이 표. 최종 발표물·연구 결론의 완성까지 주장하지 않음. |

### #29 공격 성공 기준·payload ablation

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 29-01–02 | 성공 종류·권한/지식·공통 정책 | `implemented_verified` | E3/E7/E8. a006 표식과 미지 정보 유출을 분리. |
| 29-03–05 | 새 버전 4조건·제거/인용·대표 family·metadata | `implemented_verified` | E3/E6. strict single-factor 한계와 새 direct 업무 질문을 기록. |
| 29-06 | 독립 gold/rubric·shortcut 점검 | `human_review_pending` | AI target/taxonomy 검토 E8과 입력 metadata 분리 검사. 사람 검수와 의미 동등성 확정은 pending. |
| 29-07 | 실제 paired 파일럿·원시 근거·팀 판정 | `human_review_pending` | E3 실제 파일럿·E9 AI 검토, 팀 판정 없음. |
| 29-08 | holdout 전 최종 고정 | `not_in_dev_scope` | dev 기준 E7 채택; holdout 승인·소비 없음. |
| 29-09–10 | 단위별 효과·원본/제거/인용 결과·불확실성 | `implemented_verified` | E3 원본/제거·요인, E6/E13 신규 실행·의미 판정, E15 matched54/108·정상 손실, E19 악성 목표 유지 D2 조작 제거 FNR12비교. 통계/인과 한계와 최종 우열 보류 유지. |

### #12 판정·선정

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 12-01–02 | 산식·상태·기준/반복/통계/우선순위 | `implemented_verified` | E7/E12. dev 결정 완료이고 pre-holdout 사람 동결·운영 허용 기준이라는 뜻은 아님. |
| 12-03–07 | paired 실행·지표/CI·탈락·Pareto 재현 | `implemented_verified` | E2/E3/E12. 표본 부족의 null CI와 deferred도 유효한 산출물이다. |
| 12-08 | 앱/언어/유형/심각도 실패 구간 검토 | `implemented_verified` | 선택 dev 실측 범위는 E18의144교차·216case slice/CSV729행과 실제 실패 표로 검토 완료. 원래324 severity unspecified를 보존하며 en·실제다중턴·도구는0/0·null/미평가로 남긴다. 이 미관측 범위의 분석 완료를 뜻하지 않음. |
| 12-09 | 최종 추천 구성 확정 | `not_in_dev_scope` | dev decision record와 보류 이유는 재생성 가능. 최종 안전성·holdout 기반 운영 선택은 미확정. |

### #26 D2 우회 검증

| 항목 | 요구 내용 | 상태 | 근거·남은 범위 |
| --- | --- | --- | --- |
| 26-01 | 공격 대상·실제 검사문·정답 근거 분리 | `implemented_verified` | raw 검사 payload·target별 gold 계약·E8/E10. |
| 26-02 | 서로 다른 D2 조작 공격 최소 6건 | `implemented_verified` | 기존 catalog dev 4개에 기반해 인코딩·다국어 새 변형을 포함한 dev 6종과 쌍 대조 6건을 준비 E13. holdout a025/a026은 사용하지 않음. 실제 반복 효과 검증은 아래와 별도. |
| 26-03 | 대응 정상 보안 대조군 최소 6건 | `implemented_verified` | E13의 실제 교육 인용 hard-negative6case와 공격6case 대조를 확보. 기존 b021–b024·h021–h024 및 원본/변형/반복 수와 구별. |
| 26-04 | input/document 각각 별도 검수 | `human_review_pending` | dev 실제 target 30개 AI 검토 E8, a006 입력 benign/문서 malicious 구별. E13 새 입력 benign·attack 문서 malicious·quoted 문서 hard-negative의 AI gold도 준비됨. 실제 사람 독립 검수는 없음. |
| 26-05 | 동일 조건의 모드/위치·버전 비교 | `implemented_verified` | E13 신규6종·6조건·3회와 E14 실제 target216 고정 설정 비교. 목표 marker·D2 valid allow를 분리. |
| 26-06 | dev 조정·정책 고정·split·정답 분리 | `implemented_verified` | dev 정책·D2 threshold0.5/정책/형식/실패 처리·split을 동결한 E13/E14 실측. 최적 threshold 탐색이나 holdout 전 사람 동결을 완료했다는 뜻은 아님. |
| 26-07 | 대상 FNR/FPR·오류·생성/정상 지표 | `implemented_verified` | E14 등록621의 배치별 분모와 E19 실제 미탐 비교 확보. 신규 D2 216의6그룹 각eligible36/오류0/대기0, retrieval3그룹 각FNR6/18·HN FPR0/18, input3그룹 각benign FPR0/36. 생성/정상 지표는 E13/E18에 별도. |
| 26-08 | 원시 독립 평가·수동 검토·run 연결 | `human_review_pending` | E8–E10, 실제 사람 판정과 조정 기록 없음. |
| 26-09 | 검사·재시도 전체 계측·표시 | `implemented_verified` | E2–E5 ledger·call/usage/error·UI. 검토 task 수와 실제 사람 작업 시간을 혼동하지 않음. |

## checkbox 밖의 필수 설계·완료 문장

| 원문 범위 | 대조 결과 |
| --- | --- |
| #32 비교 조건 1–8 | 6개 고유 실행·paired mode/position·고정 버전·seed 한계·case 반복 의존성·방어 차단 포함·오류/검토 제외를 구현. payload 실증과 독립 검토의 남은 범위는 32-07–10 참조. |
| #29 2.1의 5개 성공 유형 | marker·보호값·작업/형식·D2를 분리. 실제 도구 실행·외부 수신이 없는 URL/HTML/가짜 trace는 외부 전송 성공으로 판정하지 않음. |
| #29 2.2–2.3 | marker/secret 지식 조건·C01 기본 노출·공통 정책을 명시. 부분/복원 인코딩은 개별 목표에 따른 근거가 필요하며 exact-match 부재를 안전 증명으로 쓰지 않음. 새 무작위 보호값을 실행 블록마다 재생성하는 실험은 현재의 고정 합성값 파일럿과 별도다. |
| #29 3.1–3.3 | C00/C01/A10/A11·override 제거·D2 조작만 제거하는 악성 목표 유지 쌍을 실제 실행하고 E19에 대상 FNR 비교를 연결. 신규 quoted108은 E6, 추가 D2 quoted는 E13. 역할 사칭 제거·출력 형식 강요 제거의 모든 추가 축을 이미 실험한 것으로 쓰지 않음. 정상본 b006/기존 hard-negative는 엄격한 공격 제거 쌍이 아님. |
| #29 4의 5단계 | 구조·실제 노출·고정 파일럿·추가 효과·상태 분리로 추적. 후보 유효성, 특정 모델에서의 관측, 효과 불명확, 실행/노출 오류를 구별. 성공만 선별한 E4 사례를 전체 성능으로 쓰지 않음. |
| #26 완료 기준 6문장 | E13/E14에서 dev6공격·쌍정상6·3회 실제 실행·AI gold216 적용과 결과 확보. 유효 JSON 의미 미탐·형식 오류·최종 marker 이행·정상 손실·비용을 분리. 사람 독립 검토·최적 대책/운영 효과의 확증은 별도 한계. |
| #26 댓글의 보호·대안·계측 | 텍스트 전용 D2·지침/검사 분리·schema/점수 검증·기본 fail_closed·threshold/모순 정책 지원. 전용 classifier·독립 모델·결정론 방어·D3 도입은 이번 dev 필수 범위 밖이며 효과를 주장하지 않음. 실제 수동 검토 시간은 미계측, task 수만 준비됨. |
| #12 필수 하위 분석 | E18에서 실제 앱/언어/frozen 공격유형·심각도 및 조건/목표/변형/버전별 실패·정상 손실·오탐을 계산하고 case/run/hash에 연결했다. 영어·실제 다중 턴·도구 실행은0/0·null/미평가로 남겼다. 개별 CI를 다중 비교의 유의성 보정이나 통계적 동등성 입증으로 쓰지 않음. |
| #34/#35 인계·범위 | API/저장/export/화면의 단일 집계 출처를 유지. 합성 상태 검증을 실제 모델 효과로, 과거 CI를 최신 CI로 대체하지 않음. 상용 운영 화면·외부 공개·최종 발표물 완성은 별도 범위. |

## 현재 완료한 범위와 남는 한계

1. **dev 기준·실제 실행·분석 인계 완료.** E7 정책, E6 실제108·E13 실제216, E9/E14/E15 의미/target/paired 검산, E16 privacy/API/UI, E17 회귀/export와 E18–E20 실패 구간·D2 조작 제거·사례/시연을 연결했다. head63ef871의 Ubuntu·Windows CI 통과는 확인했고, 후속 변경의 최신 head PR Checks는 별도로 확인한다.
2. **사용자 위임 AI dev 검토·기술 인수 완료(E21).** 두 primary AI의 실제283행씩 응답과 제3 조정65행·역할별기술검증을 소속1,269task 및 원증거hash에 연결했다. 실제 사람2인·A/B/C 담당자의 공동서명은 수행하지 않았으며 원문 사람요건은 pending 사실을 보존한다. 동일모델계열·공유준비과정과 미확정goal23종의 한계를 기록했다.
3. **과거와 새 판정 상태를 분리.** 원래324의 자동 공격 success21/failure69/review_needed54, 정상 review_needed230/failure94·BatchReview0을 보존했다. 새 AI 정상 overlay는 정상170/179·미확정1이다. 당시 미등록306/99였던 target은 후속 AI annotation을 추가해 현재 legacy306·quotation99·D2 216 모두621개가 등록됐다. public trace/gold history 변경과 raw·원자동평가·frozen/manifest/ledger 보존을 구별하며 목표가 다른 ASR을 합치지 않는다.
4. **통계·적용 범위 제한.** 새 quotation/D2는 각각3family로 최소20에 미달한다. 반복·6기법으로 독립 family를 늘리지 않고 CI null·final deferred를 유지한다. exact 부재는 모든 부분/인코딩/추론 유출 부재를 증명하지 않는다.
5. **하위 분석·holdout 한계.** 선택 dev의 실제 실패 구간 표는 확보했으며 옛324의 severity/일부email goal unspecified는 보존한다. 신규 실행에는 위험·목표가 반영됐지만 corpus 전체나 미관측 영어/도구/실제다중턴으로 성능을 확대하지 않는다. holdout 최종평가·사람 동결·운영 배포/최종 안전 구성 확정은 `not_in_dev_scope`다.

자료·gold·수치가 미정이라서 dev 작업이 멈춘 상태는 아니다. 채택한 기준으로 dev 구현·실측·검산을 마쳤으며 미수행 승인·표본 충분성·최종 일반화는 별도로 남긴다.

## 과거 대기 문서와 이번 기록의 관계

[이전 백엔드 인수표](week3-backend-acceptance.md)는 PR #36 인계 당시의 기록이다. 다음 과거 문구를 현재 전체 상태로 읽지 않는다.

| 과거 기록 | 이번에 확인한 현재 해석 |
| --- | --- |
| 집계 보완 버전 v0.2·실제 payload 효과 미완료 | E3의 실제 324건·v0.3·exact paired 관측과 E11의 v0.4 재생이 추가됨. 최신 목표/정상 benchmark·선정 cohort는 E12의 별도 구현·검증 범위. |
| C 전체 대시보드 연결 대기 | E11/E12와 [화면 완료 기록](../frontend/verification/week3-dashboard-completion.md)이 추가됨. 실제 A/B/C 공동 인수 서명은 여전히 없음. |
| 서비스 threshold·최소 표본·우선순위 미정 | E7에서 사용자 위임 연구 결정으로 수치·방법을 채택함. 외부·사람 검토 대기를 수치 미정으로 되돌려 표현하지 않음. |
| paired 데이터 초안·빈 A 산출물 | E3/E6/E13 실제 실행, E8 AI gold/번역, E9/E6/E13 출력 검토, E14 gold 적용·E15 paired 검산이 추가됨. 실제 사람 검수·합의는 미완료. |
| root/backend/Ubuntu·Windows CI·PR #36 대기 표 | head63ef871의 root191/backend113·Ubuntu/Windows CI와 E17 export가 추가됨. 이후 최신 head의 PR Checks와 실제dev 반영은 별도이며 과거 PR 표나 과거CI로 대신하지 않음. |
| 경로에 남은 `v0.1? ... ??` 표기 | 실제 현재 export는 `exports/<report_version>/<전체 report hash>/`의 JSON/CSV/decision record와 대조. 과거 export를 삭제·덮어쓰지 않음. |
| `data/week3/*review*.md`·ablation 보고서의 실제 실행 미완료 | 당시 정적 초안으로 보존. E3 및 E6/E13 실제108/216, E14/E15·출력 검토·E17이 현재 추가 증거다. |
| 과거 시연의 108건·12그룹·비어 있는 산점도 | 해당 배치의 실제 기록. 현재 324건·목표별 그룹·새 AI 판정·새 policy와 혼동하지 않으며 `serve --pipeline-output`으로 해당 배치를 명시. |

## 최종 검증 기록

다음 로컬/CI 수치는 검증된 head63ef871 및 당시 저장 snapshot이다. E18–E20 후속 도구·annotation·인계의 최신 전체 회귀/PR Checks는 해당 새 head 결과로 별도 확인한다.

| 검증 | 확인 결과 | 증빙 |
| --- | --- | --- |
| root 전체 회귀 | 191 tests / 325.060s / OK | runs/week3-completion/root-final-tests.log |
| backend 전체 회귀 | 113 tests / 67.179s / OK | runs/week3-completion/backend-final-tests.log |
| legacy API/schema/export/UI | passed·모델0·원 pipeline845파일 불변 | E16 legacy-public-replay-v0.4/replay-integrity.json; projection54변경과 독립 privacy 회귀 구분 |
| quotation/D2 의미 검토 | 108/216행 CLI 검증·집계 통과, 원래 평가 보존 | [quotation 출력](week3-quotation-output-review.md), [D2 출력](week3-d2-output-review.md), 각 연구 overlay |
| 당시324/108/216 집계/export | v0.4; 90/24/12그룹·CSV990/264/132·각706/225/585파일 읽기 전후 불변·모델0 | [공개 안전 요약](examples/week3-completion/README.md), [artifact hash/수치](examples/week3-completion/summary.v0.4.json), 로컬 final-reports-v0.4/ |
| 후속621 gold·paired 관측 | legacy306·quotation99·D2 216 applied·API0; matched54/108·각3family | E14/E15; public annotation/history 변경을 기록하고 raw·원평가·frozen/manifest/ledger 보존 |
| 621 gold 후 세 배치 재집계/export | 90/24/12그룹·CSV990/264/132·각922/297/585 runs파일 읽기 전후 불변·모델0 | [등록·보존 기록](week3-target-gold-registration.md), [후속 증거](examples/week3-completion/followup.v0.5.json); 과거 v0.4 산출물 덮어쓰기 없음 |
| 후속 실패 구간·D2 조작 제거 | 144교차·216case slice/CSV729행; FNR12비교·CI null·API0 | E18/E19, [후속 증거](examples/week3-completion/followup.v0.5.json); 기존 보고서는 당시 hash로 보존 |
| 대표 사례·AI dev 인수 | 실제13사례·원평가/AI판정 분리;283종/1,269task·두AI+제3조정완료 | E10/E20/E21; 실제 사람2인/세 역할 서명·holdout 승인을 만들지 않음 |
| UI paired 관측 focused | 별도1개 pass·실제 두 overlay 생성·모델0 | commit9763648·E15 final JSON; root191과 중복 합산하지 않음 |
| Ubuntu CI / Windows CI | head63ef871 두 OS passed; 후속 최신 head Checks는 별도 확인 대기 | [검증된 CI](https://github.com/zerolong-01/sec_sea/actions/runs/39428651601), [고정 기록](examples/week3-completion/ci-63ef871.json); 과거 통과를 새 head 통과로 쓰지 않음 |
| PR·검토·merge | PR39 base dev; AI dev 검토·기술 인수 E21 | [PR 실제 상태·Checks](https://github.com/zerolong-01/sec_sea/pull/39) 기준이며 과거 draft/CI 상태를 최신으로 쓰지 않음 |
