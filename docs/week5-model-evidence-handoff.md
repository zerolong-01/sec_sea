# 5주차 Windows 인수와 추가 모델 216건 원본 이관 (#59)

## 현재 해결한 범위

- 한국어 Windows의 `tests/test_task_evaluation_client.py` 인코딩 오류는 [PR #64](https://github.com/zerolong-01/sec_sea/pull/64), merge `5fbc9a4`에 반영됐다. 최신 dev에서 `python -X utf8=0 -m unittest tests.test_task_evaluation_client -v` 4건이 통과했다.
- 이전 macOS 작업 환경의 [216건 검산 기록](week5-backend-acceptance.md)은 있지만, 현재 Windows 작업 폴더·다른 worktree·확인한 다운로드 파일과 GitHub 릴리스/Actions에는 그 원본이 없다. `git pull`은 Git에서 제외한 `runs/`를 가져오지 않는다.
- 이후 사용자 요청에 따라 **새 실제 실험 216건을 실행하고 raw·trace·manifest와 전달 ZIP을 생성했다.** 현재 사용할 새 실험 `experiment-bd514d347cf4`의 결과·해시·수신 명령은 [새 실험 및 원본 검산 기록](week5-model-reexecution-2026-11-10.md)을 따른다. 아래의 과거 실험 ID·원본 PC 내보내기 예시는 이전 원본을 이관할 때 사용한다.
- 원본 PC에서 필요한 증거만 내보내고, 수신 PC에서 manifest·모든 파일 hash·API/UI/CSV/trace를 검증하는 `scripts.week5_model_handoff`를 추가했다.
- 초기 [이관 검증 JSON](examples/week5/model-handoff-fixture.v0.1.json)은 **12건의 로컬 fixture**다. 이후 새 실제 216건도 별도 수신 패키지에서 검산했고 모델 호출 0을 확인했다. 과거 원본 복구와 다른 담당자의 실제 직접 인수는 pending이다.

## 필요한 원본

| 항목 | 대상 |
| --- | --- |
| 실험 | `experiment-4e1e9895fd7f` |
| 기존 PC의 경로 | `runs/real-model-experiment-20261025/main/runs` |
| mini | `gpt-4.1-mini-2025-04-14` / `batch-cf9d6a578a46` / 108건 |
| full | `gpt-4.1-2025-04-14` / `batch-f77b580973b9` / 108건 |
| 합계 | 2모델 × RAG/이메일 각 3케이스 × 6조건 × 3회 = 216건 |
| 공개 대조 기록 | [기존 실험 식별자·모델·source inventory](examples/model-experiment-live/verification-report.json) |

필수 파일은 다음과 같다. manifest만 전달하면 원시 응답·usage·ledger를 검산할 수 없다.

- `model-experiments/<experiment_id>/manifest.json`
- 두 `batches/<batch_id>/manifest.json`: 동결 명세·계획·실행 시도·호출 ledger
- 같은 batch 폴더의 `inputs/**`, 설정 `*.snapshot`, 존재하는 `reviews.json`
- 216개 실행의 **원래 `.trace.json`과 `.raw.json` 쌍**

도구는 해당 실험에 속한 파일만 복사한다. `.env`, 다른 실험, 서버 로그, 실행 잠금 파일은 포함하지 않는다. 이전 기록의 458파일은 잠금 파일 등을 포함한 원본 저장소 전체 수다. 이관 파일 수는 새 manifest의 목록을 기준으로 한다. 원래 JSON을 수정하거나 경로를 치환하지 않으며, 수신 PC에서는 동결 snapshot을 사용한다.

## 원본 PC에서 내보내기

내보내는 PC와 받는 PC 모두 이 도구가 포함된 같은 dev 버전을 사용한다. 원본이 있는 이전 PC의 저장소 루트에서 실행한다. macOS 예시:

```bash
MVP_LOAD_DOTENV=0 MODEL_PROVIDER=demo .venv/bin/python -m scripts.week5_model_handoff export \
  --runs-dir runs/real-model-experiment-20261025/main/runs \
  --output runs/week5-model216-handoff
```

실제 경로가 다르면 `--runs-dir`만 바꾼다. 성공 시 `ready_for_receiver_verification`, `planned_runs=216`, `execution_scope=real`, `manifest_sha256`이 출력된다. 원본이 없거나 raw가 누락됐으면 실패하며 결과를 만들어낸 것으로 표시하지 않는다.

`runs/week5-model216-handoff/` **폴더 전체**와 출력된 `manifest_sha256`을 수신자에게 제한 이관한다. 압축할 경우 이 폴더 전체를 압축한다. SHA-256 값은 원본 PC에서 출력된 값을 별도로 전달해 수신본의 manifest를 고정한다. 폴더 안의 manifest에서 값을 다시 읽기만 하는 것은 송신자 확인을 대신하지 않는다.

이 패키지는 원시 입력·응답과 로컬 경로를 포함하는 제한 이관용 증거다. `.env`나 API 키는 필요하지 않으며, 원시 패키지는 Git·공개 PR 첨부물에 올리지 않는다.

## Windows에서 받기와 검산

수신 폴더를 `runs/week5-model216-received/`에 놓는다. 그 폴더 바로 아래에 `handoff-manifest.json`과 `runs/`가 있어야 한다. 압축을 풀면서 폴더가 한 겹 더 생겼으면 `--package`를 그 내부 폴더로 지정한다.

```powershell
$env:MVP_LOAD_DOTENV = "0"
$env:MODEL_PROVIDER = "demo"
$env:PYTHONIOENCODING = "utf-8"
$handoffSha = "원본 PC가 출력한 64자리 manifest_sha256으로 교체"
python -X utf8=0 -m scripts.week5_model_handoff verify `
  --package runs/week5-model216-received `
  --expected-manifest-sha256 $handoffSha `
  --output runs/week5-model216-received-check
```

검사는 다음을 확인한다.

1. 송신자 manifest와 모든 필수 파일의 SHA-256, 누락·추가 파일·경로 이탈·symlink 거부.
2. 완료된 216실행과 모델·batch 식별자, 공개된 기존 source inventory 일치.
3. 원시 model call/usage/비용과 ledger 대조, 모든 저장 trace API, 모델 비교 화면 전체/D1 필터와 JSON/CSV/상세 trace 일치.
4. 수신 패키지의 전후 hash 동일, 새 모델 호출 0. 판정·원래 응답은 변경하지 않음.

성공 결과는 출력 폴더의 `handoff-verification.json`, `verification-report.json`, `source-file-hashes.json`, `model-ui-verification.json`, `inspection/`, `exports/`에 남는다. `--output`은 패키지 바깥의 새 폴더여야 한다.

원래 raw 출력이 필요한 작업에는 이 패키지의 `runs/`를 사용한다. 화면을 직접 인수할 때는 서버 로그도 패키지 밖에 둔다.

```powershell
python -m scripts.mvp serve --runs-dir runs/week5-model216-received/runs `
  --service-logs-dir runs/week5-model216-view-logs --api-port 8003 --ui-port 8504
```

모델 비교에서 해당 실험을 선택해 필터·표·CSV·상세 trace를 대조하고 [C 인수 기록](../frontend/verification/week5-integration-acceptance.md)에 실제 수행자·환경·시각·커밋을 적는다. 자동화 통과만으로 사람 공동 인수, 실제 judge 품질, 독립 라벨링 또는 holdout을 완료 처리하지 않는다. `--allow-fixture`는 이관 자동화 테스트에만 사용한다.
