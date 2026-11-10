# 공개 사람 기준 세트와 judge 검산 자동화

이 프로젝트의 실제 정상 업무 judge를 공개된 사람 기준 응답에 실행하고, 일치율·오판·보류·비용을
자동 계산한다. 출처가 없는 새 답변을 사람이 확정한 것처럼 기록하지 않는다.

## 연구 근거와 채택 기준

| 연구 | 확인한 근거 | 이 프로젝트에서 사용하는 부분 |
| --- | --- | --- |
| [LLMBar, ICLR 2024](https://arxiv.org/abs/2310.07641) | 연구진이 검수한 지시 이행 응답 419쌍. 별도 전문가 두 명의 80개 표본 일치율을 94%로 보고 | 공개 gold와 명시적인 지시 이행 기준을 재사용 |
| [MT-Bench, NeurIPS 2023](https://arxiv.org/abs/2306.05685) | 해당 연구 조건에서 judge와 사람 선호의 80% 초과 일치 보고 | 사람과의 대조 및 모델·프롬프트 고정 필요성의 근거. 우리 정확도로 환산하지 않음 |
| [G-Eval, EMNLP 2023](https://aclanthology.org/2023.emnlp-main.153/) | 명시적인 평가 항목과 사람 평가의 상관관계를 검산 | 항목별 rubric과 근거를 사용. 상관계수를 성공/실패 정확도로 변환하지 않음 |

위 연구는 모든 서비스에 공통으로 적용되는 인증 통과선을 정하지 않았다.
따라서 [채택 정책](../configs/judge-calibration-policy.v0.1.json)은 **94%를 참조한 프로젝트 목표**임을
명시한다. 논문의 94%는 사람끼리의 pairwise 일치율이며, 아래 자동 검산은 pointwise 대응이므로
수치가 같아도 같은 실험이나 사람 수준 인증을 뜻하지 않는다.

현재 외부 기준 gate는 검산 80쌍 이상, 전체 응답 정확도 94% 이상, 잘못된 성공률 5% 이하,
모든 응답 평가 완료다. 80쌍은 연구의 표본 크기를 참고한 프로젝트 선택이며 통계적 충분성 보장이 아니다.
잘못된 성공률 5%는 이 프로젝트의 위험 허용 후보값이다. 각 숫자의 출처/해석은 정책의 `gate_basis`에 고정했다.

## 기준 세트와 라벨 계보

[원본 자료](../data/judge-reference/llmbar-v1/README.md)는 commit·파일별 원본 Git blob SHA와 MIT
라이선스를 보존한다. 원본 수정, label 변경, 중복 ID와 동결 라벨 변경은 실행 전에 거부한다.

전체 419쌍에서 같은 지시문이 양쪽에 들어가지 않도록 개발용 20쌍, 검산용 80쌍을 선정한다.
검산은 Natural, Neighbor, GPTInst, GPTOut, Manual을 각각 16쌍씩 사용한다.
선정 seed와 순서를 모델 실행 전에 동결하며, 점수가 좋은 사례를 나중에 골라내지 않는다.
이 분할은 외부 기준 세트의 분할이다. 기존 프로젝트의 동결 holdout 9건을 실행하거나 승인하지 않는다.

원본 label의 지시 이행 선호를 응답별 성공/실패로 대응해 160개의 기준 값을 만든다.
원본 label·side·row hash·commit을 `human-reference-labels.json`에 보존한다.
평가 프롬프트에는 원래 지시문과 후보 답변만 전달하며, gold·예상 성공/실패·원본 label을 전달하지 않는다.
기존 생성 trace를 위조하거나 공개 응답을 이 프로젝트 모델이 생성한 것으로 저장하지 않는다.

이 라벨은 `published_human_gold_adapter`다. 기존 실제 수행자의 수동 라벨 `human`, AI 합의,
fixture와 섞지 않는다. 사람 기준의 범위는 **영어 지시 이행**이며 한국어 보안 업무의 독립 사람
검산이 완료됐다고 표시하지 않는다. 같은 지시문 hash를 단위로 CI를 계산하지만, 서로 다른 문장들의
의미적 독립성까지 검증된 것은 아니다.
한국어 프로젝트 실행의 독립 평가 절차·판정 예시·빈 작업지는 [사람 검산 지침](judge-human-review-protocol.md)에 정리했다.

## 로컬 실행

새 출력 디렉터리를 지정한다. 기존 `.env`는 수정하지 않는다.

```bash
python -m scripts.judge_calibration prepare --output runs/judge-calibration
```

prepare는 키 없이 원본·정책을 검사하고 80쌍/160응답 계획과 기준 라벨을 저장한다.

독립 `JUDGE_BASE_URL`, `JUDGE_MODEL_ID`, `JUDGE_API_KEY`, `PRICING_FILE` 설정을 사용한 실제 실행:

```bash
python -m scripts.judge_calibration run --execute --output runs/judge-calibration
```

현재 로컬 생성 모델 설정을 이 검산의 judge로 명시적으로 사용하려면 다음 플래그를 붙인다.
자동 fallback은 없다. `--execute`가 없으면 계획만 작성한다.

```bash
python -m scripts.judge_calibration run --execute --use-generation-config --output runs/judge-calibration
```

실행은 서비스와 같은 `SYSTEM`, `JudgeVerdict`, `judge_outcome`, rubric·판정 정책을 사용한다.
기본 `JUDGE_RESPONSE_FORMAT=json_schema`는 네 평가 항목과 해당 rubric 키를 실제 출력 제약으로
전달한다. 호환 제공자가 이를 지원하지 않으면 `prompt_only`를 명시할 수 있으나, 로컬 스키마 검사는
동일하게 유지한다. 형식이 틀리면 미평가이며 성공으로 보정하지 않는다.
출력 제약은 [OpenAI Structured Outputs 공식 문서](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)의
모든 필드 `required` 및 객체별 `additionalProperties: false` 요구에 맞춘다.

기본 한도는 호출 200회, 예약 토큰 8백만, 시간 1,800초, 고정 가격표 기준 추정 1 USD다.
`--max-usd 0.9`처럼 금액 한도를 낮출 수 있고, 재개할 때 같은 값을 사용해야 한다.
모델·프롬프트·가격표·코드·정책이 달라지면 같은 실행에 이어 붙일 수 없다.
단가는 관측 토큰에 고정 가격표를 적용한 추정이며 실제 청구서의 상한 보장이 아니다.

호출 전 예약을 저장하고 완료한 unit을 건너뛰므로 중단/재개 시 중복 호출하지 않는다.
중단 시점의 호출 결과가 불분명하면 자동 재호출하지 않는다. 연속 세 번의 잘못된 judge JSON도
추가 지출을 중단한다. `--max-items N`은 계획 순서에서 아직 평가하지 않은 N응답만 실행한다.
결과를 보고 프롬프트를 고칠 때는 개발 세트를 사용하고, 같은 검산 세트에 대한 반복 최적화를
독립적인 새 검증으로 주장하지 않는다.

## 조회·통과 판정·CI

다음 명령은 저장된 ledger를 읽으며 현재 API 키나 외부 모델 호출이 필요 없다.

```bash
python -m scripts.judge_calibration report --output runs/judge-calibration
python -m scripts.judge_calibration check --output runs/judge-calibration
```

`report.json`과 `report.csv`는 같은 `report_sha256`을 사용한다.
전체 정확도의 분모에는 검토 필요·미평가도 포함한다. 확정 결과만의 일치율은 별도로 표시해
보류를 늘려 정확도가 좋아 보이는 것을 막는다. 잘못된 성공률은 사람 기준 실패 응답 중 judge가
성공으로 처리한 비율이다. subset별 결과, 혼동행렬, 지시문 그룹 bootstrap 95% 구간,
두 응답을 모두 맞힌 엄격 쌍 일치율, 호출·토큰·추정 비용·시간을 저장한다.

`check`는 채택한 외부 기준 gate에 미달하면 종료 코드 2로 CI를 실패시킨다.
외부 gate를 통과하더라도 `project_domain_human_validation=pending`은 유지한다.

기존 MVP CI에는 `python -m scripts.verify_judge_calibration --output runs/judge-calibration-fixture-ci`를
추가했다. 모든 답변을 성공 처리하는 로컬 fixture를 공개 gold에 대조해 정확도 50%, 잘못된 성공률
100%로 탈락하는지 검사한다. 이 CI 성공은 실제 judge 정확도 통과가 아니라 자동화의 정상 동작이다.

[수동 실제 검산 workflow](../.github/workflows/judge-calibration.yml)는 `workflow_dispatch`로만
실행한다. 저장소의 `JUDGE_API_KEY` secret을 설정한 후 실행하면 고정 모델·예산으로 평가하고,
gate 실패 시에도 보고서와 source-bound ledger를 artifact로 남긴다. PR마다 유료 호출하지 않는다.

현재 실제 실행 결과와 검증 근거는 [실행 기록](judge-calibration-acceptance.md)에 정리한다.
