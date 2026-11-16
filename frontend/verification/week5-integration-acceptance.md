# 5주차 프론트엔드 통합 인수 기록 (#59)

이 문서는 **작업자(C)의 깨끗한 환경 수행 기록과 다른 담당자의 인수 입력란**이다. 새 폴더 clone → 설치 → 검사 → 정상 업무 자동 판정 화면 확인 → 저장 조회·CSV를 기록한다.
빈칸은 실제로 해 본 사람이 채운다. 해 보지 않은 항목은 "미수행"으로 남기고 지어서 쓰지 않는다.
자동 판정(규칙·AI)은 사람 검토 완료가 아니다. 이 문서의 수동 검토 칸도 화면 동작 확인용이며 실제 사람 라벨로 세지 않는다.

설정과 API는 [5주차 백엔드 안내](../../docs/week5-backend.md)를 따른다. 이 문서는 화면 쪽 확인 항목만 정리한다.

## 1. 수행 정보

| 항목 | 작업자 (C) | 다른 담당자 |
| --- | --- | --- |
| 이름 / 역할 | 오정건 / C (프론트엔드·시각화) | |
| 날짜·시각 (KST) | 2026-11-10 20:37~21:00 | |
| OS | Windows 10 (10.0.19045), 한국어 | |
| Python (`py -3.11 --version`) | 3.11.9 | |
| commit (`git rev-parse --short HEAD`) | `6197357` (`feat/week5-easy-view-plain-words`, dev `fc447d7` + 한눈에 보기 쉬운 말 정리) | |
| dirty 여부 (`git status --short` 결과 없음 = clean) | clean | |
| 새 폴더에 clone 했는가 | 예 — 작업 저장소를 새 폴더 `sec_sea_clean5`로 로컬 clone (`.env`·`runs/` 없음, 새 `.venv`) | |

## 2. 설치와 검사 (외부 모델 없음)

PowerShell, 새 폴더의 저장소 루트에서:

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
$env:MVP_LOAD_DOTENV = "0"
$env:MODEL_PROVIDER = "demo"
& .\.venv\Scripts\python.exe -m scripts.mvp check
& .\.venv\Scripts\python.exe -m scripts.mvp verify
& .\.venv\Scripts\python.exe -m scripts.verify_week5_ui --output runs/week5-acceptance-ui
& .\.venv\Scripts\python.exe -m unittest tests.test_easy_view tests.test_task_evaluation_client -v
```

| 확인 | 기대 | 작업자 | 다른 담당자 |
| --- | --- | --- | --- |
| `pip install` | 성공 (`--require-hashes`) | 성공 | |
| `mvp check` | `Data validated: ...` | 성공: `36 cases, 15 documents; synthetic_v0.1.1` | |
| `mvp verify` | `HTTP + UI verification passed` | 통과 | |
| `verify_week5_ui` | `status=passed`, `read_model_calls=0`, `paid_model_calls=0` | 통과: `read_model_calls=0`, `paid_model_calls=0`, fixture judge 호출 5, `human_acceptance=false` | |
| 단위 테스트 | 모두 OK | `test_easy_view` 9개 통과. `test_task_evaluation_client` 4개 **오류** (아래 7절 ①). `PYTHONUTF8=1`로 다시 실행하면 4개 통과 | |
| 문제와 해결 (있으면) | | 7절 ① | |

## 3. 한눈에 보기 — `h007` 네 모드 자동 판정 (fixture)

```powershell
& .\.venv\Scripts\python.exe -m scripts.mvp serve --fixture-model --runs-dir runs/week5-acceptance --api-port 8001 --ui-port 8502
```

http://127.0.0.1:8502 → 왼쪽 메뉴 **한눈에 보기**.

| 확인 | 기대 | 작업자 | 다른 담당자 |
| --- | --- | --- | --- |
| `h007` 선택 → 실행 | 네 칸 모두 결과가 나옴, 맨 아래 "연습용 고정 응답" 안내 | 통과 — 네 칸 모두 "잘 답함", 맨 위 "방어 방식 4가지 모두 제대로 답했습니다." | |
| 확인 전 | 각 칸에 "아직 확인하지 않았습니다" 안내, 전문 용어 없음 | 통과 — 단, 원래 작업 폴더(`sec_sea`, 같은 커밋 내용)에서 20:30에 확인. 깨끗한 폴더에서는 확인 후 화면만 봄 | |
| **답변 4개 모두 AI로 확인하기** | 각 칸에 확인 결과 배지·누가 확인했는지·이유 | 통과 — 네 칸 모두 "원래 요청을 잘 해냄", "정해진 규칙으로 자동 확인했습니다." (이번 화면 실행에서는 `h007` 네 칸 모두 규칙만으로 결론이 나서 AI 판정을 부르지 않음. `verify_week5_ui`의 판정 호출 5는 그 검사 안의 별도 fixture 흐름) | |
| 이유 문장 | 영어 코드가 아니라 한국어 문장 (규칙 판정) | 통과 — "답변에 꼭 들어가야 할 내용이 있는지 정해진 규칙으로 확인했습니다." | |
| 버전·rubric·토큰·CSV·이력 | **전문가용 세부 정보**를 펼쳐야 보임 | 통과 | |
| **저장된 결과 불러오기** | 결과가 그대로, 서버에 새 판정 호출 없음 | 결과 그대로 (호출 0은 `verify_week5_ui`의 `read_model_calls=0`으로 확인) | |
| 다른 질문(`b006`)으로 바꿈 | 이전 확인 결과가 보이지 않음 | 통과 | |

## 4. 4개 모드 비교·상세 trace (fixture)

첫 페이지에서 `h007`을 4개 모드 비교로 실행한다.

| 확인 | 기대 | 작업자 | 다른 담당자 |
| --- | --- | --- | --- |
| 비교표에 정상 업무 판정 상태·출처 | 한눈에 보기와 같은 값 | 통과 — "정상 태스크 성공"·"정상 판정 출처"·"정상 판정 버전" 칸 표시. **답변 자동 판정 · 재평가** 후 출처가 "규칙 자동 판정"으로 바뀜. 일부만 판정했을 때 "출처·모델·버전이 섞여 있습니다" 경고 표시 | |
| 상세 trace의 판정 근거·평가 버전 | 비교표와 같은 값 | 통과 — "정상 업무: 성공 · 규칙 자동 판정", 평가 버전 `backend-starter-draft-v0.1@rules-v0.2`, rubric `normal-task-rubric-v0.2`, 정책 `normal-task-dev-policy-v0.2` | |
| 판정 CSV 준비 → 다운로드 | 화면과 같은 보고서일 때만 내려받기 버튼 | 통과 | |
| 수동 검토 저장 (검토자·근거 입력) | 새 이력으로 추가, 이전 CSV 버튼 사라짐 | 새 이력 추가 통과 — 무방어 줄이 "실패 · 수동 검토"로 바뀜 (화면 확인용 입력, 실제 사람 판정 아님). 저장 뒤에도 **판정 CSV 다운로드** 버튼이 보였으나, 그 버튼으로 받은 CSV에 새 검토 근거가 들어 있어 최신 보고서와 같은 내용이었음 (7절 ②) | |

## 5. 쉬운 말 정리 (이 브랜치의 화면 변경)

교수님 피드백(비전공자도 이해하게)에 따라 PR #61에서 한눈에 보기에 붙은 판정 표시만 바꿨다. 판정 값·API·버튼 key·첫 페이지 화면은 그대로다.

- 버튼: "답변 4개 모두 AI로 확인하기", "AI로 확인하기 / 다시 확인하기", "저장된 결과 불러오기"
- 결과: 배지 한 줄 + 누가 확인했는지(규칙 / AI / 사람) + 이유
- 규칙 판정의 이유 코드는 한국어 문장으로 바꿔 보여 주고, 원문 코드는 세부 정보에 남김
- 버전·rubric·호출 수·토큰·CSV·이력·수동 검토는 "전문가용 세부 정보"에 접어 둠

## 6. 남은 것 · 미수행

- 실제 judge 모델로 화면 확인 (`JUDGE_API_KEY` 필요, 비용 발생) — 미수행
- 추가 실제 모델 216건 — 과거 원본은 미확보. 이후 요청으로 [새 실제 216건 원본·ZIP과 화면 자동 검산](../../docs/week5-model-reexecution-2026-11-10.md)을 확보했다. C의 직접 화면 인수는 미수행
- 이메일 시나리오 화면 확인 — 미수행 (`verify_week5_ui`는 RAG `h007` 기준)
- 실제 사람 라벨과 자동 판정 대조, holdout: 팀 결정(#43·#59)에 따라 이번 인수 범위 밖

## 7. 인수 중 찾은 것

① **Windows에서 `tests/test_task_evaluation_client.py` 4개 오류.** 25번째 줄이 `docs/examples/week2/h007-D1+D2.json`을 인코딩 지정 없이 `read_text()`로 읽어, 기본 인코딩이 UTF-8이 아닌 Windows(한국어 cp949, CI의 cp1252)에서 `UnicodeDecodeError`가 난다. `read_text(encoding="utf-8")`로 바꾸면 해결될 것으로 보인다. `PYTHONUTF8=1`로 실행하면 4개 모두 통과하므로 기능 문제는 아니다.
같은 원인으로 CI Windows에서는 `tests/test_judge_calibration.py` 5개도 오류가 난다 (`scripts/judge_calibration.py` 203번째 줄 `read_text()`). dev `fc447d7`의 Windows CI도 이 9개로 실패해 있어 이 브랜치의 변경과는 무관하다. 이 브랜치에서는 고치지 않고 B 담당에게 전달한다.

② **첫 페이지 상세 trace에서 수동 검토 저장 뒤에도 "판정 CSV 다운로드" 버튼이 보임.** 저장 전에 CSV를 준비해 둔 상태에서 저장했다. 저장 뒤 버튼으로 받은 파일에는 새 검토 근거가 들어 있었다 (`Select-String` 1건). 화면과 다른 예전 CSV를 받은 것은 아니다. 버튼이 남아 보인 이유는 확인하지 못했다. 한눈에 보기 경로는 `verify_week5_ui`의 `csv_invalidated_after_review=true`로 확인됐다.

## 8. 후속 해결 기록 — 2026-11-10

- 인코딩 문제는 PR #64, merge `5fbc9a4`에서 수정했다. 한국어 Windows에서 `python -X utf8=0 -m unittest tests.test_task_evaluation_client -v` 4건 통과를 재확인했다. 7절은 수정 전 관측 기록으로 보존한다.
- #59의 과거 216건 원본은 미확보였으며, 사용자 요청으로 새 실제 216건을 생성했다. 새 실험은 `experiment-bd514d347cf4`이고, 원본과 ZIP을 Windows `runs/`에 보관한다. [새 실험·수신 검산 안내](../../docs/week5-model-reexecution-2026-11-10.md)에 ID·경로·해시·화면 실행 명령을 연결했다.
- 이관 도구의 초기 12건 fixture 검사 후 새 실제 216건도 별도 수신 패키지에서 raw/ledger/API/UI/CSV/trace를 재검산했다. 조회 모델 호출 0과 원본·패키지 불변을 확인했다. C의 직접 인수와 사람의 독립 판정은 완료 처리하지 않는다.
