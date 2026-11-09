# 5주차 백엔드·화면 연결 검증

2026-11-09 macOS arm64, Python 3.11.18의 로컬 검증 기록이다.
기준 dev `9cc0e3c`에서 `feat/week5-backend-auto-evaluation` 브랜치를 생성했다.
구현·공통 API 계약·재현 명령은 [백엔드 가이드](week5-backend.md),
현재 판정·화면 연결의 기계 판독용 요약은 [v0.2 검증 JSON](examples/week5/connected-verification.v0.2.json)을 따른다.
초기 백엔드 검증은 [v0.1 기록](examples/week5/backend-verification.v0.1.json)에 보존한다.
중간 커밋은 초기 구현 `0b3be76`, 판정·원본 검증 보완 `843baf1`이다.

## 완료한 B 담당 범위

- 정상 태스크 규칙 평가와 별도 LLM judge를 연결하는 명시적 실행 API.
- 정상/하드 네거티브의 `attack_success=not_applicable`과 공격 상황의 업무 수행/ASR 구분.
- 원래 규칙 평가·trace/raw 보존, source-bound 별도 평가 이력과 수동 수정 이력.
- rubric·모델·프롬프트·정책 버전/hash, 실제 응답 인용 근거, 출처와 불확실/오류 상태.
- 호출 전 영속 예약, 중복 ID·중단 복구의 자동 재호출 방지, 호출/토큰/timeout 상한.
- 부가 호출·usage·지연·추정 비용 분리, 미상 비용/usage 보존.
- 마스킹된 JSON/CSV와 같은 보고서 hash, C 담당자를 위한 독립 스키마와 경로 계약.
- 저장된 자동 판정을 사람/fixture dev 라벨과 대조하는 읽기 전용 CLI.
- 로컬에서 확보한 추가 실제 모델 216건의 새 모델 비교 UI/API/CSV/trace 검산 도구와 결과.
- 유효한 JSON과 의미 평가의 분리, 문서 인용 대조, h007 두 세부 rubric의 개별 답변 근거 검증.
- 원본 변경 시 재평가·수동 수정의 호출/쓰기 사전 차단, 인코딩된 문장 안의 보호값 검사.
- 한눈에 보기·기존 비교표·상세 trace의 정상 업무 판정 연결과 출처/버전 표시.
- 응답 유실 후 같은 ID의 재전송, 수동 수정/새 조회 후 CSV 무효화, 케이스 변경 시 이전 결과 숨김.

## 검증 결과

| 항목 | 결과 |
| --- | --- |
| 백엔드 전체 회귀 | 181개 통과. 자동 평가 테스트 18개 포함 |
| 전체 파이프라인/UI 회귀 | 301개 통과 |
| 최종 화면 변경의 추가 회귀 | 관련 화면·클라이언트 테스트 48개 통과 |
| 기존 CI 데이터·HTTP/UI·배치·리포트 경로 | 12개 명령 모두 종료 코드 0 |
| 새 `verify_week5` | 통과. h007 네 모드와 오답/거절/불확실/형식 오류 4개 fixture |
| 새 `verify_week5_ui` | 실제 Streamlit 버튼 → API → 저장 판정/근거 → CSV → 재전송/수동 수정 → 기존 비교표 통과 |
| 실제 MVP 런처 | backend HTTP/Streamlit 프로세스와 fixture judge 연결·호출 없는 GET·서버 정리 확인 |
| 모델 호출/오류 처리 | 정상/실패/보류·잘못된 JSON·provider 오류·timeout·중단 예약·상한 검증 |
| 이력/개인정보 | 원본 hash, 중복 POST, 수동 수정 revision/재전송, canary·키 마스킹 검증 |
| 추가 실제 모델 원본 | 2모델·216실행, 원본 458파일 전후 hash 동일 |
| 추가 모델 호출 대조 | 모델당 198호출 ledger/raw/usage 대조, 미대조·오류 0 |
| 추가 모델 새 화면 | 전체/D1 필터 UI 표·JSON/CSV hash·상세 trace 마스킹 일치 |
| 조회 모델 호출 | 새 평가 재조회/CSV와 추가 실제 모델 재생 모두 0 |
| 변경 형식 검사 | `git diff --check` 통과 |

기존 CI 12개 명령은 데이터 `mvp/week2/week3 check`, 보고서 비교표 검산,
`mvp verify`, `mvp verify-week2`, 이메일 데이터 준비와 비교 UI, week2 인계,
week3 배치, week4 불변 재생, 다중 모델 비교 검증이다.
`.github/workflows/mvp-integration.yml`에 새 week5 fixture 검증을 추가했다.
원격 Ubuntu/Windows의 이 작업 브랜치 CI는 아직 실행하지 않았다.

새 fixture 8개는 고정 응답 기대값과 검증기의 동작을 대조한다. 정상 네 모드는 성공,
오답·과도한 거절은 실패, 불확실은 검토 필요, 잘못된 JSON은 미평가로 보존했다.
fixture benchmark에서 미평가 1개를 포함한 7/8 일치는 실제 judge 정확도가 아니다.
추정 비용은 검증 단가가 없어 null이며, 로컬 추가 지연은 해당 artifact의 관측값이다.
실제 유료 judge 모델의 품질·추가 비용·지연을 측정한 결과로 해석하지 않는다.

추가 결함 세 가지는 수정 전 실패를 확인했다: 문서가 있는데 grounding을 적용 제외해도 성공,
원본 변경 뒤 새 판정이 호출/저장된 후에야 거부, 유효한 JSON만으로 의미 판정을 건너뜀.
보완 후 이 테스트들과 세부 criterion 누락, 날조 문서 인용, 잘못된 JSON/NaN/중복 키,
문서 snapshot 변조, 관측 usage/미상 비용 테스트가 통과했다.

로컬 산출물:

- `runs/week5-handoff-20261109/verification-report.json`: h007 네 모드 API/CSV/hash 및 원본 보존.
- 같은 디렉터리의 `*.report.json`, `*.csv`, `fixture-labels.jsonl`, `fixture-benchmark*.json`.
- 같은 디렉터리의 `integration-checks.json`: 기존 CI 경로 12개 명령의 성공 기록.
- `runs/week5-saved-models-final-20261109/verification-report.json`: 실제 저장 216건 재검산.
- 같은 디렉터리의 `source-file-hashes.json`: 모든 원본 458파일의 SHA256.
- 같은 디렉터리의 `model-ui-verification.json`, `inspection/`, `exports/`: UI/API/CSV/trace 근거.
- `runs/week5-judge-v2-final-20261109/`: 강화한 v0.2 평가의 네 모드·오류/보류 fixture.
- `runs/week5-ui-final-20261109/`: 최종 한눈에 보기·기존 비교표·상세 trace·수동 수정·CSV 검증.
  같은 디렉터리의 `integration-checks.json`은 최종 화면 코드로 수행한 기존 CI 12단계 기록이다.
- `runs/week5-ui-release-20261109/`: fixture 런처 보완 이후 같은 UI 흐름의 재확인.
- `runs/week5-launcher-final-20261109/verification-report.json`: 실제 두 서버·HTTP 연결 검증.

원본 실제 모델 저장소는 `runs/real-model-experiment-20261025/main/runs`,
실험 ID는 `experiment-4e1e9895fd7f`다. 기존 모델을 재실행하지 않았다.
이 기록은 로컬 원본 검산이며 다른 기기로의 제한 이관을 수행한 기록은 아니다.

## 남은 실제 모델·사람 검산

1. **A:** 후보 rubric과 확신도 기준 검산, 실제 사람이 독립 라벨링한 dev 표본 제공,
   오답·거절·정상 인용·불확실 사례의 일치율/오판/검토 회송률 평가.
2. **C:** 연결한 네 모드·상세 trace·수정/CSV 흐름의 실제 사용 인수. 기능 연결과 자동 검증은 완료했다.
3. **A/B/C:** 문서만 사용한 다른 깨끗한 환경의 실제 사람 공동 인수와 후보 head 원격 CI 확인.
4. 실제 judge dev 검증이 필요하면 모델·평가 버전·표본·호출/비용 예산을 고정하고 실행한다.

후보 정책은 `dev_candidate`, `human_validated=false`다. 실제 사람의 검토, 미확정 23종 해소,
최종 방어 추천, holdout 진입/실행, 고객 PoC는 이번 자동 검증으로 완료 처리하지 않았다.
이슈 #59의 팀 완료 체크나 기존 사람 인수 이슈를 변경하지 않았다.
