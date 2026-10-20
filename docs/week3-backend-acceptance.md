# 3주차 B 백엔드 인수 기록

## 2026-10-20 추가 인계: 현재 확인한 상태

현재 완료 범위는 [전체 요구사항·증빙 대조표](week3-completion-status.md), [위임 연구 결정](week3-research-decisions.md),
[공개 안전 요약](examples/week3-completion/README.md), [실제 artifact hash·수치](examples/week3-completion/summary.v0.4.json)를 따른다.
**아래 PR36 당시 표는 역사 기록으로 보존한다.** 당시의 정책 미정·인용 미실행·C 연결/마스킹 대기·로컬 회귀 대기 문구를 현재 상태로 읽지 않는다.

| 이번에 추가 완료한 범위 | 실제 증거 |
| --- | --- |
| dev 데이터·gold·정상 rubric·서비스/통계 기준 결정 | 사용자 위임으로 공개 논문·기업 자료를 근거로 adopted_for_dev 채택. runtime draft와 빈 reviewer는 미수행 사람 검수/최종 승인을 숨기지 않는 지위이며 수치 미정이 아님. |
| 신규 실제 인용 대조108 | batch-8fb19849d67c: 생성85·차단23·오류0·184호출·추정$0.0373288. [별도 AI 의미 검토](week3-quotation-output-review.md), quoted utility54/54·attack 아래18/54. |
| 신규 실제 D2 6종216 | batch-fb671ff629f0: 생성180·차단36·오류0·396호출·추정$0.0754176. [의미 검토](week3-d2-output-review.md), HN utility60/108·attack 아래6/108. marker102와 비밀 공개를 분리. |
| 실제 D2 대상 gold·지표 | AI 작성/교차검토를 216 target에 annotation 적용·남음0·immutable true·모델0. 6그룹 각eligible36/오류0/대기0. input3그룹 각benign FPR0/36, retrieval3그룹 각FNR6/18·HN FPR0/18. 최종 생성 ASR과 별도. |
| legacy pairing·신규 paired 검산 | fbf9120: 명시적 comparison_pair_id와 inherited family cluster 분리·모호한 legacy 짝 사유 공개. 신규 quotation54/D2 108 matched pairs·각3family exact overlay. frozen metadata 재작성 없음. |
| 공개 privacy·실제 API/UI | 보호값 설정72 trace의 과거54노출→현재GET0노출. frozen 규칙 사용·독립 privacy 회귀. legacy API/schema/CSV/UI passed·원 pipeline845파일 불변·모델0. |
| 최신 report/export | v0.4 legacy90그룹/CSV990·quotation24/264·D2 12/132. 각각706/225/585파일 검증 전후 불변, 추가모델0·선정 deferred. |
| 로컬 최종 회귀 | root191 tests/325.060s·backend113/67.179s OK. UI paired focused1 별도pass. runs/week3-completion/{root,backend}-final-tests.log. |
| 앞으로 확인할 항목 | push 후 새 head의 Ubuntu/Windows CI가 PR Checks에 연결되면 확인. PR39 draft/base dev 유지·자동 merge 없음. 실제 사람2인/세 역할 합의·holdout·운영 최종 선택은 pending. |

기존324·별도942 탐색·신규108/216을 한 ASR로 합치지 않는다. 새로운 AI gold/출력 검토는 사람 검수나 source 서명 인증이 아니다.
각 신규 세트의3family는 채택 최소20에 미달하며 반복으로 독립 표본을 늘리지 않는다. CI null·최종 deferred를 유지한다.

## PR #36 당시 인수 기록 — 보존


대상은 [#34](https://github.com/zerolong-01/sec_sea/issues/34)의 배치 실행·예산·평가 저장·집계·export와 [PR #36](https://github.com/zerolong-01/sec_sea/pull/36)이다. 실행 방법과 API 계약은 [백엔드 안내](week3-backend.md)를 따른다. 작성일은 2026-10-20이다.

B의 완료 기준은 재현 가능한 실행·기록·분석 기능과 그 검증 근거를 제공하는 것이다. A의 최종 데이터·gold·서비스 기준 확정, C의 전체 대시보드 공동 인수, 최종 성능 실험은 각각 별도 인수 항목이다. `completed` 배치나 이 문서의 기능 완료를 연구 결과 확정으로 해석하지 않는다.

## 요구사항과 증빙

`구현·검증`은 기존 회귀 또는 저장된 fixture/실제 dev 결과에서 확인한 범위다. 이번 보완의 최종 회귀·CI 결과는 아래 최종 검증 표에 별도로 기록한다.

| B 요구사항 | 상태 | 구현·검증 근거 |
| --- | --- | --- |
| none/D1/D2 양쪽/D1+D2 양쪽/D2 입력/D2 문서의 6개 고유 조건, D2 양쪽 결과의 기법·위치 비교 공유 | 구현·검증 | [batch_models.py](../backend/app/batch_models.py)의 `default_conditions`; [test_batch.py](../backend/tests/test_batch.py)의 `test_six_unique_conditions_snapshot_and_resume_without_duplicate_calls`, `test_comparison_cannot_change_threshold_and_effective_duplicates_are_rejected` |
| RAG·이메일, source/case/language/split 선택, 반복·순서 seed, dev/holdout 분리 | 구현·검증 | [week3_batch.py](../scripts/week3_batch.py), [verify_week3.py](../scripts/verify_week3.py); `test_duplicate_conditions_split_mix_and_unfrozen_holdout_rejected`, `test_holdout_inventory_does_not_authorize_execution_and_selection_is_frozen` |
| case/corpus/manifest·선택·family/variant·정책·가격·평가 규칙·구현 hash의 불변 snapshot | 구현·검증 | [batch.py](../backend/app/batch.py)의 `inspect_inputs`, `create`, `verify_frozen_artifacts`; `test_tampered_snapshot_and_runtime_configuration_stop_before_any_call`, `test_plan_case_or_family_cannot_change_after_snapshot_freeze` |
| 생성 모델·기본 프롬프트·D1 버전·D2 모델/정책/임계값/위치/행동/형식과 실제 trace의 일치 검사 | 구현, 최종 회귀 대기 | [batch_analysis.py](../backend/app/batch_analysis.py); [test_batch_analysis.py](../backend/tests/test_batch_analysis.py)의 `test_manifest_configuration_drift_is_excluded`. 다른 실행 설정의 trace는 제외하고 추천을 보류한다. |
| 호출·예약 토큰·누적 시간·선택적 USD 예산, 생성/D2/실패/재시도의 공통 ledger | 구현·검증 | [batch_budget.py](../backend/app/batch_budget.py); `test_before_call_limit_cannot_be_bypassed_by_detector_fail_open`, `test_token_and_verified_dollar_reservations_stop_before_transport`, `test_expired_wall_budget_prevents_new_attempts`, `test_reservation_write_delay_cannot_send_a_call_after_deadline` |
| 검증 가격·관측 usage 기반 비용, 미확인 비용은 null, known 소계와 총액 구분 | 구현·검증 | [accounting.py](../backend/app/accounting.py); `test_unknown_prices_stop_before_transport_when_usd_cap_is_requested`, `test_http_failure_keeps_its_admitted_call_and_unknown_usage`; 실제 파일럿의 raw/trace/ledger 대조 |
| 호출 직전 durable 예약, 단일 writer, entry/attempt/run 연결, 완료 항목 재호출 방지 | 구현·검증 | `test_writer_lock_blocks_a_second_runner`, `test_durable_reservation_on_interrupt_is_not_silently_replayed`, `test_status_replace_survives_a_concurrent_windows_reader`; fixture·실제 완료 배치의 재개 호출 0회 |
| 호출 전 중단의 취소 attempt 이력 보존, 호출 후 불확실 결과의 자동 재시도 금지 | 구현, 최종 회귀 대기 | `test_interrupt_before_transport_keeps_cancelled_attempt_and_resumes_once`; `test_cancelled_attempt_is_audited_without_poisoning_metrics`. `cancelled_before_transport`는 이력/attempt 수에 남고, 전송하지 않은 시도를 모델 실패·지연·사용량 분모에 넣지 않는다. |
| 여러 D2 호출 중 중단 시 확정 비용·미확정 예약을 함께 보고 | 구현·개별 회귀 검증 | [test_verify_real_api.py](../tests/test_verify_real_api.py)의 `test_mid_detector_crash_reports_settled_and_reserved_calls_without_retry`; [test_verify_real_detector.py](../tests/test_verify_real_detector.py)의 `test_crash_without_saved_trace_keeps_paid_reservation_uncertain`. settled 첫 호출과 reserved 다음 호출을 보존하고 재개 시 모델을 호출하지 않는다. |
| 공통 애플리케이션 정책의 모든 모드 동일 적용, 분석 metadata·gold의 모델 입력 분리 | 구현·검증 | [week3-common-policy.txt](../configs/week3-common-policy.txt); `test_common_policy_identical_in_actual_none_and_d1_requests`; [verify_week3.py](../scripts/verify_week3.py)의 wire payload 검사, [week2_data.py](../scripts/week2_data.py)의 `{stage,text}` 탐지 입력 검사 |
| family/parent/variant 기반 payload pairing과 별도 target exposure 평가 | 구현·synthetic 검증 | `test_payload_pairing_uses_target_exposure_review_and_keeps_family_clusters`. C00/C01/A10/A11 및 original/instruction_removed/quoted 표현을 지원한다. A의 최종 paired 데이터로 수행한 실제 효과 검증은 미완료다. |
| 자동/수동 평가·독립 대상 gold의 분리와 변경 이력, 공개 마스킹 | 구현·검증 | [service.py](../backend/app/service.py), [test_week2_data.py](../tests/test_week2_data.py), [test_detector_security.py](../backend/tests/test_detector_security.py); `test_review_history_and_masking`, `test_evaluation_update_changes_snapshot_and_separates_versions` |
| ASR·정상 성공·benign/hard-negative FPR·대상 D2 FNR/FPR·지연·토큰·비용·실패율의 분모/제외 수 | 구현·synthetic 검증 | `test_golden_denominators_paired_changes_and_family_clusters`, `test_missing_review_unknown_cost_and_failed_run_are_not_success_or_zero`, `test_failed_retry_cost_and_latency_remain_in_resource_totals`. 미평가·검토 대기·오류를 0 또는 성공으로 바꾸지 않는다. |
| family 단위 cluster bootstrap CI와 paired baseline 변화, 부족한 표본의 CI null | 구현·synthetic 검증 | [batch_analysis.py](../backend/app/batch_analysis.py)의 `statistic`, `paired_delta`, `paired_resources`; `test_single_family_repeats_do_not_create_false_inference`. 통계 방법·최소 표본 수의 팀 확정은 A 인수 대상이다. |
| source/시나리오/언어/split/조건/비교/family/라벨/공격 목표/심각도/실행 종류 필터 | 구현·검증 | [batch_models.py](../backend/app/batch_models.py)의 `BatchFilters`; `test_reproducible_filter_api_and_csv_do_not_call_provider` |
| 목록·상세·검토·집계·CSV API, 같은 snapshot의 JSON/CSV/decision-record export, 조회 시 모델 호출 0회 | 구현·검증 | [main.py](../backend/app/main.py), [week3_batch.py](../scripts/week3_batch.py); [verify_week3.py](../scripts/verify_week3.py), [verify_real_api.py](../scripts/verify_real_api.py)의 API/저장/CSV 대조와 provider 호출 차단 |
| threshold 탈락 → 전체 지표 Pareto → 사전 priority, 치명 공격/불확실성/미완료 gate | 구현, 최종 회귀 대기 | `test_threshold_pareto_priority_critical_failure_and_no_candidate`, `test_incomplete_batch_defers_completed_groups`. 다른 그룹이나 필터 밖에 미완료·불확실 실행이 남아도 완료된 그룹의 최종 추천을 보류한다. |
| 실제 모델 dev 연결·사용량·가격·저장·조회, UI의 실제 저장 결과 재생 | 구현·실제 dev 검증 | 아래 실제 실행 증빙. gold/정상 의미 판정·팀 합의·최종 방어 추천과는 구분한다. |

이번 집계 보완의 `report_version`은 `batch-cluster-summary-v0.2`다. 기존 공개 fixture와 실제 파일럿 문서는 생성 당시의 v0.1 기록으로 보존한다. v0.2의 최종 회귀와 재생성 검증 결과는 아래 표에서 확인한다. 실행 계약 v0.3과 배치 계약 v0.1의 버전 번호와는 별개다.

## 실제 실행과 공개 인계물

| 증빙 | 확인한 범위 |
| --- | --- |
| [fixture 인계](examples/week3/README.md), [verification-report.json](examples/week3/verification-report.json), [batch-summary.fixture.json](examples/week3/batch-summary.fixture.json), [report.fixture.json](examples/week3/report.fixture.json) | RAG·이메일 각 대표 3건 × 6개 조건 × 3회 = 108건, HTTP fixture 207회. 7건 후 중단·재개, 완료 후 중복 호출 0회, API/CLI/export 일치. 고정 응답의 기능 검증이다. |
| [실제 dev 인계](examples/real-api/README.md), [pilot-verification.json](examples/real-api/pilot-verification.json) | `gpt-4.1-mini-2025-04-14`, RAG `synthetic_v0.2`와 이메일 `synthetic_email_v0.1`, dev 108건. 완료 90·정상 방어 차단 18·실행 오류 0, HTTP 200 호출 198회, 관측 입력 50,739/출력 13,301토큰, 표준 단가 추정 $0.0415772. 대표 네 모드 12건과 D2 세 위치 비교를 포함한다. |
| [detector-verification.json](examples/real-api/detector-verification.json) | dev 탐지 전용 18건·입력/문서 36대상, HTTP 200 호출 36회, 생성 0회, 추정 $0.0050136. 단일 검수 gold 36개를 팀 검수 대기로 제외했으며 임의 등록하지 않았다. |
| [ui-verification.json](examples/real-api/ui-verification.json) | [verify_real_ui.py](../scripts/verify_real_ui.py)로 RAG 대표 3건의 네 모드·세 위치 저장 결과를 Streamlit에 재생하고 표시값·마스킹을 대조했다. 추가 모델 호출 0회다. C 전체 배치 대시보드 공동 인수와는 별도다. |

실제 실행의 합계는 234회·추정 $0.0465908이다. 별도 정상 연결 smoke 1회까지 포함한 과금 추정은 [실제 dev 인계](examples/real-api/README.md)의 구분을 따른다. 금액은 [고정 가격표](../configs/pricing-openai-2026-10-20.json)의 표준 단가 추정이며 청구 정산 금액을 뜻하지 않는다.

실제 run_id·raw·전체 공개 trace·고정 snapshot·호출 ledger와 export는 Git에서 제외된 `runs/real-api-2026-10-20/pilot/` 및 `detector/`에 있다. 파일럿 export는 v0.1? `exports/<evaluation_snapshot_sha256>/`? v0.2? `exports/<report_version>/<?? report hash>/` ?? `report.json`, `metrics.csv`, `decision-record.json`을 포함한다. 공개 문서에는 키와 원시 보호값을 넣지 않는다. 저장된 배치 재조회·export 재생성은 유료 모델 호출을 요구하지 않는다.

## 최종 회귀·CI 기록

아래 최종 항목이 채워지기 전에는 이 문서를 근거로 PR 병합 또는 CI 통과를 완료 처리하지 않는다. 이 표는 인수 담당자가 최종 실행 결과로 갱신한다.

| 검증 | 최종 상태 | 증빙 |
| --- | --- | --- |
| 최신 변경 기준 root 회귀: `python -m unittest discover -s tests -v` | 대기 | 최종 commit·개수·결과 기록 필요 |
| 최신 변경 기준 backend 회귀: backend에서 `python -m unittest discover -s tests -v` | 대기 | manifest drift·취소 attempt·미완료 배치 gate를 포함한 결과 기록 필요 |
| 데이터 패키지·기존 HTTP/UI·D1/D2·gold 인계·3주차 fixture 인계 | 대기 | 최종 로컬 검증 경로와 결과 기록 필요 |
| v0.2 집계의 저장된 실제 결과 재생성·API/export 대조 | 대기 | 추가 모델 호출 0회 및 report_version 확인 필요 |
| Ubuntu·Windows CI | 대기 | [mvp-integration.yml](../.github/workflows/mvp-integration.yml)의 두 OS run URL·결과 기록 필요. CI는 실제 API 키를 사용하지 않는다. |
| PR #36 → dev | 대기 | 최종 PR head SHA, 검토/CI, merge commit 기록 필요 |

회귀 테스트의 fixture 주입은 명시적으로 `allow_fixture=True`를 요구한다. 실제 `.env`가 있는 로컬 환경에서도 비용이 드는 모델로 전환하지 않도록 새 실행기 테스트는 설정과 가격표를 직접 주입한다. 공유 변수 subprocess 검증은 모델·D2·가격/평가/공통 정책 설정을 제거하고 `demo`, `MVP_LOAD_DOTENV=0`으로 분리한다.

## A·C와 공동 인수에 남은 항목

| 담당/범위 | 남은 인수 |
| --- | --- |
| A 데이터·평가 / #33 | 최종 taxonomy와 paired C00/C01/A10/A11 데이터·metadata 계약, gold/번역/rubric 팀 검수, 대표 무방어 출력의 3인 판정 합의, 최소 평가 수·통계 방법·서비스 threshold/priority 확정. 현재 A의 draft overlay와 빈 산출물은 최종 데이터·정책 인수 근거로 사용하지 않는다. |
| B와 A의 최종 연결 | 확정 인계물로 새 inventory·snapshot을 만들고 스키마·버전·source/family/variant·평가/가격 조건을 대조한다. 현재 dev 파일럿을 A 최종 데이터 전체 또는 실제 payload 효과 실험으로 간주하지 않는다. |
| C 화면 / #35 | 새 배치 목록/상세·필터·검토·집계·CSV·decision-record를 전체 대시보드에 연결하고 API의 값·분모/제외·CI·마스킹·추천 보류 표시를 공동 인수한다. |
| 팀 최종 연구 인수 | 검토된 정책·통계와 정확한 freeze hash로 holdout 진입을 승인하고 최종 반복 실험·성능 해석·방어 선택을 수행한다. 현재 holdout 미실행, 추천 `deferred`, 팀 합의 대기를 유지한다. |

PR #36은 B의 구현과 검증 인계를 완료하는 단위다. A·C의 위 항목이나 최종 연구 결론을 함께 완료 처리하지 않는다.
