# 4주차 프론트엔드 통합 인수 기록 (#48)

이 문서는 **작업자(C)의 수행 기록과 다른 담당자의 인수 입력란**이다. 설치 → 기동 → 대표 케이스 확인 → 저장 조회 → 집계·내보내기를 기록한다. Codex가 수행한 후속 자동 검증은 8절에 따로 기록한다.
빈칸은 실제로 해 본 사람이 채운다. 해 보지 않은 항목은 "미수행"으로 남기고 지어서 쓰지 않는다.

설치·기동 명령은 [4주차 백엔드 안내](../../docs/week4-backend.md)를 따른다. 이 문서는 화면 쪽 확인 항목만 정리한다.

## 1. 수행 정보

| 항목 | 작업자 (C) | 다른 담당자 |
| --- | --- | --- |
| 이름 / 역할 | 오정건 / C (프론트엔드·시각화) | |
| 날짜·시각 (KST) | 2026-11-03 20:20~20:33 | |
| OS | Windows 10 (10.0.19045) | |
| Python (`py -3.11 --version`) | 3.11.9 (python.org 설치 파일, 기존 3.14·3.15와 함께 설치) | |
| commit (`git rev-parse --short HEAD`) | `d0b986f` (`feat/week4-frontend`) | |
| dirty 여부 (`git status --short` 결과 없음 = clean) | clean | |
| 새 폴더에 clone 했는가 | 예 — 작업 저장소를 새 폴더 `sec_sea_clean`으로 로컬 clone (`.env`·`runs/` 없음, 새 `.venv`) | |

## 2. 설치와 기동 (외부 모델 없음)

PowerShell, 저장소 루트에서:

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
$env:MVP_LOAD_DOTENV = "0"
$env:MODEL_PROVIDER = "demo"
& .\.venv\Scripts\python.exe -m scripts.mvp check
& .\.venv\Scripts\python.exe -m scripts.mvp serve --fixture-model --runs-dir runs/week4-demo --api-port 8001 --ui-port 8502
```

| 확인 | 작업자 | 다른 담당자 |
| --- | --- | --- |
| `pip install` 성공 | 성공 (`--require-hashes`) | |
| `mvp check` 성공 | 성공: `Data validated: 36 cases, 15 documents; synthetic_v0.1.1` | |
| http://127.0.0.1:8502 화면이 열림 | 열림 (기동 직후 잠깐 늦게 뜸) | |
| 문제와 해결 (있으면) | ① 3.11 없음 → python.org 3.11.9 설치 (새 설치 관리자의 `py install`은 옛 Python Launcher와 충돌해 사용 못 함) ② PowerShell에서 `git clone ~\sec_sea`의 `~`가 풀리지 않음 → `"$HOME\sec_sea"`로 해결 | |

## 3. 첫 페이지 케이스 찾기 → 실행 (fixture 모델)

| 확인 | 기대 | 작업자 | 다른 담당자 |
| --- | --- | --- | --- |
| 케이스 찾기 탭에 전체 건수와 페이지가 보임 | 한 페이지 10건, 긴 목록 없음 | 통과 | |
| 검색어 `a006` | 1건 | 통과 | |
| 검색어 `zzzz` | 0건 안내 + 필터 초기화 | 통과 (개발 환경, [사용성 기록](week4-ui-usability.md)) | |
| 앱·라벨·언어 필터를 같이 걸고 초기화 | 원래대로 돌아옴 | 통과 (개발 환경) | |
| 정렬·페이지 이동 후에도 왼쪽 "실행할 케이스"가 그대로 | 선택 유지 | 통과 (자동 테스트·개발 환경) | |
| 선택한 케이스가 필터에서 빠지면 노란 안내 | 안내 문구 | 통과 (자동 테스트) | |
| attack / benign / hard-negative 각 1건 선택 → 실행 | 결과 화면의 케이스 ID = 고른 ID | 통과 (RAG, 결과 ①②③ 순서) | |
| 검색·필터·페이지·미리보기만 할 때 서버 실행 요청 없음 | 서버 로그에 POST /api/v1/runs 없음 | 통과 (자동 테스트: `requests.post` 미호출) | |
| 미리보기에 보호값(`CANARY_...`)이 보이지 않음 (a006 등) | 원문 노출 없음 | 통과 — a006의 보호값은 입력이 아니라 문서·공격 목표에만 있고, 공격 목표 칸은 미리보기에서 숨김 | |
| holdout 포함을 켜고 holdout 케이스를 봄 | 선택 버튼 없음, 실행 버튼 3개 비활성 | 통과 (개발 환경 `data/week2`. 기본 `data/`에는 holdout 없음) | |
| 이메일: `--data-dir runs/week4-email-demo-data`로 켜서 대표 3종 실행 | 위와 같음 | 미수행 (이메일은 `verify_week4` fixture 108건에 포함되어 자동 확인) | |

## 4. 저장 결과 조회·집계·내보내기 (모델 호출 0)

| 확인 | 기대 | 작업자 | 다른 담당자 |
| --- | --- | --- | --- |
| `python -m scripts.verify_week4 --output runs/week4-acceptance-v1` | 통과 | 통과: `status=passed`, fixture 108건(RAG·이메일, 6조건×3회), 재개 중복 호출 0, API·CLI·export 일치, 공개 보호값 노출 없음, 재생 모델 호출 0, holdout 미실행 | |
| 배치 대시보드 위쪽 평가 출처 칸 | "원래 자동 평가", 사람 검토 "하지 않음", 리포트 해시 | 통과 (개발 환경, batch-4d5d49d420c6) | |
| 지표 요약·Trade-off·추천 근거·trace 탭 | 빨간 오류 없음 | 통과 (개발 환경) | |
| 내보내기: CSV 준비 | 화면과 같은 해시일 때만 내려받기 버튼 | 자동 테스트로 확인 | |
| 필터를 바꾼 뒤 이전 CSV·trace가 남지 않음 | 다시 준비하라는 안내 | 자동 테스트로 확인 | |

## 5. AI 연구 판정 보기 (공개 파일만, 모델 호출 0)

왼쪽 메뉴 **연구 판정 보기**. 원래 실행 기록이 없는 PC에서도 열린다.

| 확인 | 기대 | 작업자 | 다른 담당자 |
| --- | --- | --- | --- |
| 맨 위 경고 | "원래 자동 평가가 아닙니다" | 통과 | |
| batch-8fb19849d67c, 방어 조건 D2-input | 출력 그룹·정답 건수 표가 보임 | 통과 (실행 기록 없는 새 폴더에서도 열림) | |
| 출처 표시 | 사람 검토 하지 않음 · 원래 평가에 적용 안 함 · 추천 보류 | 통과 | |
| 연구 CSV 준비 | "화면 보고서와 같습니다" 후 내려받기 | 통과 | |
| 내려받은 CSV를 [v0.2 샘플](../../docs/examples/week4/v0.2/metrics.csv)과 비교 (같은 필터) | 같음 | 같음 (개발 환경, 아래 6절 C1·C2) | |
| 실행별 판정에서 trace 조회 | 원래 기록이 없으면 "이 PC에는 원래 실행 기록이 없어" 안내 | 통과 | |
| 원래 대시보드 KPI 숫자가 연구 판정 때문에 바뀌지 않음 | 그대로 | 통과 (구조상 별도 페이지·별도 API, 자동 테스트) | |

## 6. 수치 대조 (같은 batch·필터·평가 버전)

A의 [최종 보고서](../../data/week4/final-report.md)·[결과 검산](../../data/week4/result-check.md)와 B의 export에서 2~3개 핵심 값을 골라 같은 조건으로 화면 값과 맞춘다.

**작업자(C) 대조 — 2026-11-03, 기존 개발 환경(Windows), fixture 서버, 모델 호출 0.** 화면은 "연구 판정 보기", 평가판 `week3-two-ai-review-v0.1`, 보고서 `week4-public-overlay-v0.2`.
B 열은 공개 연구 자료(`docs/examples/week3-completion/ai-dev-review.metrics.v0.1.jsonl`, `docs/examples/week4/v0.2/`)의 값이다.

| # | 배치 · 필터 | 값 | 보고서 (A) | API/CSV (B) | 화면 (C) | 같음? |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | batch-8fb19849d67c · D2-input | 평가 스냅샷 SHA-256 앞 12자리 | `96e456c140ed` (6.5절) | `96e456c140ed` | `96e456c140ed…` | 같음 |
| A2 | 〃 | 출력 그룹 · 출력 실행 | 6개 · 18건 (6.5절) | `counts.output_groups=6`, `output_runs=18` | 6개 · 18건 | 같음 |
| A3 | 〃 | D2 검사 대상 정답 건수 | 정상 6 · 하드 네거티브 6 · 악성 6 (6.5절) | `fresh_ai_gold_counts` 6/6/6 | 6 · 6 · 6 | 같음 |
| A4 | 〃 | 정상 인용 업무 성공 (AI 연구 판정) | 9/9 (4.3절 D2-input) | 인용 그룹 합 9/9 | 인용 행 모두 100% | 같음 |
| B1 | batch-fb671ff629f0 · none | 원본 공격 성공 (AI 연구 판정) | 83.3% (15/18) (4.4절) | 15/18 | 83.3% (15/18) | 같음 |
| B2 | batch-fb671ff629f0 · D2-retrieval | 원본 공격 성공 (AI 연구 판정) | 33.3% (6/18) | 6/18 | 33.3% (6/18) | 같음 |
| B3 | 〃 | 정상 인용 업무 성공 (AI 연구 판정) | 61.1% (11/18) | 11/18 | 61.1% (11/18) | 같음 |
| B4 | batch-fb671ff629f0 · D1-D2 | 정상 인용 업무 성공 (AI 연구 판정) | 44.4% (8/18) | 8/18 | 44.4% (8/18) | 같음 |
| C1 | batch-8fb19849d67c · D2-input | 연구 CSV 행 수 | 40행 (6.5절) | 샘플 `metrics.csv` 머리글 + 40행 | 내려받은 CSV 41줄 (머리글 + 40) | 같음 |
| C2 | 〃 | 연구 CSV 내용 | — | `docs/examples/week4/v0.2/metrics.csv` | `Compare-Object` 차이 없음 | 같음 (파일 해시는 다름: 줄바꿈·BOM 차이로 보이며 내용은 같음) |

보고서 4.3·4.4절의 공격·업무 성공 수치는 원래 자동 평가가 아니라 **AI 연구 판정**(`fresh_ai_*`) 값과 일치한다. 원래 자동 평가 대시보드의 ASR과 섞어 읽지 않는다.
4.4절처럼 조건별 한 그룹이면 화면 값이 곧 보고서 값이고, 4.3절처럼 한 조건에 그룹이 여러 개면 화면은 그룹별로 보여 주므로 보고서 값은 그 행들의 분자·분모 합이다 (화면에서 합계를 새로 계산하지 않음).

미수행: 원래 자동 평가(648건)의 보고서·화면 대조 — private 원래 실행 기록이 있는 PC 필요. 추가 모델 배치(`batch-cf9d6a578a46`, `batch-f77b580973b9`) 화면 대조 — 저장 폴더 없음.

## 7. 남은 것 · 미수행

- 실제 모델 대표 실행 (설정·예산 확정 후. 하지 않았으면 "미수행")
- private 원래 실행 기록(648건)이 있는 PC에서의 원래 평가 화면 대조
- 사람 검토, holdout: 팀 결정(#43·#45)에 따라 이번 인수 범위 밖

## 8. #56 후속 보완 검증 — Codex 자동 검증 (2026-11-03 KST)

사람의 "다른 담당자" 칸을 대신 채운 기록이 아니다. A/B/C의 실제 공동 인수는 미완료로 유지하고, 확인 가능한 기술 검증을 분리했다. #48을 자동 종료하지 않는다.

### 마스킹·조회 회귀

- `tests/test_case_preview_privacy.py` 6개와 `tests/test_week4_frontend.py` 27개 통과.
- 원문·Base64·URL-safe/패딩 생략·문장 전체 Base64·URL 인코딩·공백 분리 보호값, 등록된 비밀번호와 실행 환경의 인증정보를 화면·요약·검색에서 검증했다.
- 지정한 코퍼스/평가 규칙을 읽을 수 없거나 형식이 잘못되면 원문 표시와 새 실행을 차단한다. 저장된 공개 trace 조회는 유지한다.
- 탐색·필터·미리보기에서 실행 POST 없음, 원문 케이스/선택 ID·실행 계약과 파일 바이트 보존을 확인했다.

### 새 가상환경 통합 검증

별도 worktree `fix/week4-preview-redaction`, Windows `10.0.26200`, Python 3.11.9.
새 `.venv`에 `pip install --require-hashes -r requirements.lock`로 설치했다.
최종 기술 검증 커밋은 `d36d7d6d09e789c2bdc16235a50e4213aff37fc9`, 실행 전후 작업 트리는 clean이다. 이후 변경은 이 인수 기록과 안전한 JSON 요약뿐이다.

```powershell
python -m scripts.mvp check
python -m scripts.verify_week4 --output runs/clean-week4-final-code
```

`mvp check`는 36 case·15 document, `verify_week4`는 passed.
RAG·이메일의 attack/benign/hard-negative, 6조건×3반복 108건 fixture에서 중단/재개 중복 호출 0·API/CLI/export 일치·공개 canary 노출 없음이 확인됐다.
fixture의 로컬 HTTP 호출 207회와 실제 모델 호출을 구분한다. 저장 결과 재생에서는 모델 호출 0·원본 불변·반복 export 일치·JSON/CSV/평가 출처와 보고서 hash 일치가 확인됐다.

공개 증거: [frontend-clean-acceptance.v0.1.json](../../docs/examples/week4/frontend-clean-acceptance.v0.1.json). 커밋·lock hash·코드/데이터 inventory hash·fixture/재생 결과를 연결하고 private 원문과 인증정보는 포함하지 않았다.

첫 시도는 샌드박스의 Windows 자식 프로세스 종료 권한, 다음 시도는 Git 소유권 검사로 중단됐다. 이 작업의 서버만 종료하고 정상 프로세스 권한 및 해당 작업 폴더에만 적용되는 `GIT_CONFIG_COUNT/KEY_0/VALUE_0` 설정으로 최종 검증을 수행했다. 전역 Git 설정은 바꾸지 않았다.

### 실제 저장 사례 10개 재생

[#41 대표 사례 연결 기록](week4-case-trace-links.md#56-후속-자동-재생-검증-2026-11-03-codex)의 10/10 사례가 실제 private 저장소의 GET API → 화면 출력·평가 사유·방어 판정/근거 코드로 연결됐다.
모델 호출 0·전체 원본 파일 불변·공개 마스킹 검사를 통과했다. [공개 검증 JSON](../../docs/examples/week4/frontend-selected-traces.v0.1.json)에 실행 번호와 공개 trace hash를 남겼다.

실제 모델 대표 재실행·사람의 공동 인수·holdout은 수행하지 않았다. 기존 자동 평가를 AI 연구 판정으로 덮어쓰지 않았다.
