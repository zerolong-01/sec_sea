# 5주차 추가 모델 216건 새 실험과 원본 검산 — 2026-11-10

기존 216건의 원본을 확보하지 못해, 사용자가 새 실험으로 데이터를 생성하도록 요청했다. 두 모델·두 앱·6개 방어 조건·3회 반복의 dev 실험을 Windows에서 새로 실행하고, 저장된 원본과 별도 수신 패키지를 검산했다.

이번 실행 ID는 **`experiment-bd514d347cf4`**다. 이전 실행 `experiment-4e1e9895fd7f`의 원본을 복구한 것으로 표시하지 않는다. 기존 648건·다른 720건 보고값과도 별도로 관리한다.

## 실제 실행 결과

| 모델 | batch | 실행 | 응답 생성 | 차단 | API 호출 | 관측 토큰 기준 추정 비용 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `gpt-4.1-mini-2025-04-14` | `batch-b520d3098afb` | 108 | 90 | 18 | 198 | $0.041662 |
| `gpt-4.1-2025-04-14` | `batch-5b122a2e384a` | 108 | 90 | 18 | 198 | $0.1483772 |
| 합계 | | **216** | **180** | **36** | **396** | **$0.1900392** |

- RAG `a006/b006/h007`과 이메일 `email-attack-001/email-benign-001/email-hard-negative-001`, dev만 사용했다.
- 조건은 `none`, `D1`, `D2-both`, `D1-D2`, `D2-input`, `D2-retrieval`이며 각 3회다.
- 생성·공통 D2 탐지 호출을 모두 계측했다. HTTP 오류·미대조 호출·추가 실행 시도는 0이었다. 두 모델 간 송신 조건 198개를 대조했고 짝이 없는 호출은 0이었다.
- 실행 코드 기준은 `eb585502ae36aeea0843c8e3ce839bd1e09b62c7`이며 모델당 $0.48, 합계 $0.96의 동결 예산을 사용했다. 실행 도구의 총 상한은 $1였다.
- 단가는 실행일 공식 OpenAI Docs의 [mini 모델 단가](https://developers.openai.com/api/docs/models/gpt-4.1-mini), [full 모델 단가](https://developers.openai.com/api/docs/models/gpt-4.1)로 확인해 [가격 파일](../configs/pricing-openai-2026-11-10.json)에 동결했다. 비용은 실제 관측 토큰에 일반 비캐시 단가를 적용한 추정이며 청구서 금액은 아니다.

전체 수치·버전·식별자·해시와 검증 결과는 [기계 판독용 기록](examples/week5/real-model-reexecution-2026-11-10.json)에 보존한다.

## 원본과 전달 파일

아래 경로는 저장소 루트 기준이며 `runs/`는 Git에서 제외한다. 이 작업 PC에는 ZIP과 수신 검산 결과까지 생성되어 있다. 다른 담당자에게는 ZIP과 아래의 해시를 전달한다.

| 자료 | 경로 |
| --- | --- |
| 동결한 실제 실행 명세 | `runs/week5-model-experiment-20261110/spec.real.json` |
| 새 실험의 원본 runs | `runs/week5-model-experiment-20261110/main/runs` |
| 호출·사용량·ledger 대조 | `runs/week5-model-experiment-20261110/main/verification-report.json` |
| 전달 폴더 | `runs/week5-model216-handoff-20261110` |
| **전달용 ZIP** | **`runs/week5-model216-handoff-20261110.zip`** |
| 수신본 API/UI/CSV 검산 | `runs/week5-model216-received-check-20261110/handoff-verification.json` |

원본 저장소 458파일의 전후 hash가 같았다. 이관 패키지는 실행 잠금 파일 3개를 제외한 필수 증거 455파일과 별도 handoff manifest다. **216개 raw·216개 trace**, 두 batch의 manifest·호출 ledger·입력·설정 snapshot을 포함한다. ZIP은 1,493,337바이트이며 `.env`와 현재 설정된 API 키 값이 포함되지 않았음을 검사했다. 원시 합성 보호값·응답·로컬 경로가 있으므로 제한 이관용으로 보관한다.

- handoff manifest SHA-256: `13f4c010d57bad4feaa8a838ae533ce3f4132372a505aac303db61f2cda560c7`
- ZIP SHA-256: `852285e56494f08f9b4ce20742ae413e9363f90216a607b89ecf61a3bd97bd0d`
- 보고서 SHA-256: `207a066438f471b1eaad9f5051ac83b3a2ac79b5e9ee1c69719385a18b30fa44`

## 받는 PC에서 확인

ZIP을 새 폴더에 풀고, 바로 아래에 `handoff-manifest.json`이 있는 폴더를 `--package`로 지정한다. API 키 없이 검산할 수 있다. `--output`은 패키지 바깥의 새 폴더를 사용한다.

```powershell
$env:MVP_LOAD_DOTENV = "0"
$env:MODEL_PROVIDER = "demo"
python -m scripts.week5_model_handoff verify `
  --package runs/week5-model216-handoff-20261110 `
  --expected-manifest-sha256 13f4c010d57bad4feaa8a838ae533ce3f4132372a505aac303db61f2cda560c7 `
  --output runs/week5-model216-new-pc-check
```

현재 PC의 별도 수신 폴더에서 모든 raw 호출·사용량·ledger, trace API, 모델 비교 화면의 전체/D1 필터, JSON/CSV 값·해시·소속, 상세 trace를 대조했다. 원본·수신본 불변과 검산 시 모델 호출 0을 확인했다.

직접 화면을 확인할 때는 다음과 같이 수신 패키지의 `runs/`를 사용한다. 모델 비교에서 새 실험 ID를 선택한다.

```powershell
python -m scripts.mvp serve --runs-dir runs/week5-model216-handoff-20261110/runs `
  --service-logs-dir runs/week5-model216-view-logs --api-port 8003 --ui-port 8504
```

## 실험을 다시 실행할 때

깨끗한 checkout에서 [공개 실행 명세](../configs/model-experiment.week5-2026-11-10.json)와 가격 파일을 사용할 수 있다. 실제 실행에는 `MODEL_API_KEY`, `D2_API_KEY`가 필요하며 `--execute`에서 유료 호출이 발생한다. 기존 결과가 있는 PC에서는 새 출력 경로를 정해 원래 결과를 보존한다.

```powershell
python -m scripts.week2_data prepare-email --output runs/week5-model-experiment-20261110/prepared/email
python -m scripts.verify_real_model_experiment `
  --spec configs/model-experiment.week5-2026-11-10.json `
  --output runs/week5-model-experiment-20261110/main --execute --max-total-usd 1
```

공개 명세는 경로를 상대 경로로 바꾸었으며, 실제 동결 명세와 실험 설계·케이스 선택 hash가 동일함을 확인했다. 생성 응답과 실행 ID는 새로운 실험마다 달라질 수 있다.

이번 완료 범위는 **새 실제 실험 데이터 생성과 저장·재생·이관 자동 검산**이다. 원래 규칙 평가와 의미 판정 pending 정책을 보존했다. 사람의 독립 라벨링, 실제 judge 품질 통과, 다른 담당자의 직접 공동 인수, 최종 방어 추천과 holdout은 완료 처리하지 않는다.
