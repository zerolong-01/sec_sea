# 5주차 PR 검토와 재실행 검증 — 2026-11-10

사용자 요청에 따라 원격 `dev`를 다시 가져오고, PR #63의 화면 변경과 PR #64의 Windows 인코딩 수정을 합친 코드에서 검증 근거를 새로 생성했다. 기존 실험 원본이 없는 720건의 실제 모델 성능 수치는 미검증 보고값으로 유지한다.

## 실행 조건과 근거

- 기준 dev: `fc447d7d9b94e3eb7edfc1248cea4b426bb14f67`.
- 검증 후보: `f3f5abb1148438e3881e5f40188e4910102ddd73`.
- Windows, Python 3.11.9. `MVP_LOAD_DOTENV=0`, `MODEL_PROVIDER=demo`, `PYTHONIOENCODING=utf-8`, `python -X utf8=0`으로 실행했다. 한국어 Windows 기본 인코딩에서도 파일 입출력이 동작하는지 확인했다.
- [실행별 커밋·명령·환경·종료 코드·로그 SHA-256](../docs/examples/week5/pr-review-2026-11-10/suites.json), [정상 업무 API 검증](../docs/examples/week5/pr-review-2026-11-10/api.json), [화면 검증](../docs/examples/week5/pr-review-2026-11-10/ui.json), [공개 사람 정답 기반 보정 자동화 검증](../docs/examples/week5/pr-review-2026-11-10/calibration.json).
- 초기 통합 검증 커밋 `027231e`와 후보 `f3f5abb`의 차이는 테스트 파일 네 개의 인코딩 지정뿐이다. 통합 검증에 사용한 실행 코드·화면·설정·데이터의 Git tree를 대조해 동일함을 확인한다. 각 실행의 실제 커밋을 JSON에 보존한다.

## 새로 확인한 결과

| 대상 | 확인 결과 |
| --- | --- |
| 데이터 계약 | 기본 36개 케이스·15개 문서 검사 통과 |
| HTTP와 기본 화면 | 실제 로컬 서버 시작·HTTP 요청·화면 검증·종료 통과 |
| 정상 업무 API | h007 네 모드의 별도 판정·이력·API/CSV 일치, 원래 파일 불변 확인 |
| 한눈에 보기와 첫 페이지 | 네 모드 판정 표시·조회·수동 수정·CSV·상세 trace 연결 통과 |
| 재전송과 CSV | 응답 유실 뒤 같은 요청 ID 재사용, 수동 수정 후 이전 CSV 무효화 확인 |
| 판정 자동화 | 공개 사람 정답 80쌍에 대한 fixture 판정 160건, 잘못된 판정기 거부·재개 중복 호출 0 확인 |
| 전체 파이프라인 회귀 | 310건 실행. Git 소유권 검사로 막힌 12건은 프로세스 한정 신뢰 설정 후 같은 테스트를 재실행해 통과 |
| 백엔드 회귀 | 183건 중 182건 통과·1건 skip |
| 추가 인코딩 회귀 | 변경한 세 테스트 모듈 43건 통과. 전체 310건과 겹치므로 독립 표본으로 합산하지 않음 |

`verify_week5`의 fixture judge 호출은 8회, `verify_week5_ui`는 5회다. 보정 자동화 검증의 160개 fixture 예측과 서로 다른 검사 흐름이므로 같은 성능 표본으로 합산하지 않는다. 저장 조회의 모델 호출과 유료 외부 모델 호출은 0이다.

Windows 전체 검증에서 확인한 UTF-8 인코딩 누락을 PR #64에서 보완했다. 샌드박스 안의 첫 서버 종료 검사는 `taskkill` 권한 제한으로 실패했으며, 자식 서버를 종료할 수 있는 실행 환경에서 다시 검증했다. 이때 worktree 소유 계정 차이로 Git 조회가 막힌 12건은 해당 프로세스에서 작업 경로만 신뢰하도록 설정한 뒤 통과했다. 전역 Git 신뢰 설정은 변경하지 않았다. 전체 실행의 오류와 재실행 결과를 JSON에 구분해 보존했고, 임시 서버를 정리했다.

## 재실행

의존성 설치 후 저장소 루트에서 실행한다. `--output`은 매번 새 디렉터리를 사용한다.

```powershell
$env:MVP_LOAD_DOTENV = "0"
$env:MODEL_PROVIDER = "demo"
$env:PYTHONIOENCODING = "utf-8"
python -X utf8=0 -m scripts.mvp check
python -X utf8=0 -m unittest discover -s tests -q
Push-Location backend
python -X utf8=0 -m unittest discover -s tests -q
Pop-Location
python -X utf8=0 -m scripts.mvp verify
python -X utf8=0 -m scripts.verify_week5 --output runs/week5-review-api
python -X utf8=0 -m scripts.verify_week5_ui --output runs/week5-review-ui
python -X utf8=0 -m scripts.verify_judge_calibration --output runs/week5-review-calibration
```

이 기록은 구현의 회귀·통합 검증이다. 실제 GPT-4.1 mini의 ASR·FPR·정상 업무 성공률, 실제 judge의 정확도, 사람의 독립 인수 또는 holdout 결과를 새로 입증하지 않는다. 기존 720건 보고값의 원본을 복원하거나 그 수치를 테스트 결과로 대체하지 않았다.
