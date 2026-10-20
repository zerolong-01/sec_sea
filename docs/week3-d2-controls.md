# D2 조작 6종과 교육용 인용 대조군 v0.4

`scripts.week3_d2_controls`는 #26의 D2 조작 유형 6종과 대응 hard-negative 6종을 준비한다.
이 도구는 **데이터·검사 대상별 AI gold·배치 계획만 생성**하며 모델 실행이나 batch 생성은 하지 않는다.
기존 dev 원본 `a021`~`a024`만 설계 출처로 사용한다. holdout의 공격 문구를 설계에 사용하지 않는다.

| 기술 | 출처 parent | 상속 family |
| --- | --- | --- |
| 점수·JSON 응답 강요 | a021 | F006 |
| 관리자 권한 사칭 | a022 | F005 |
| 가짜 검사 완료 결과 | a023 | F002 |
| 가짜 역할·문서 경계 | a024 | F002 |
| Base64 절차 복원·실행 | a021의 새 변형 | F006 |
| 영어·스페인어·한국어 지시 | a021의 새 변형 | F006 |

기술은 6종이지만 원본 family는 **3개**다. 새로운 변형·대조군·반복으로 독립 family 수를 늘리지 않는다.
새 준비물은 각 기술의 attack·quoted 양쪽 메타데이터에 동일한 `comparison_pair_id`를 기록한다.
이 ID는 비교 짝을 식별하는 키일 뿐 독립 family가 아니다. 6개 명시적 짝을 3개 parent family 안에서
계산하며 bootstrap도 parent family 단위로 유지한다. pair sidecar에도 같은 ID를 기록하고 모델 입력에는 넣지 않는다.
a021/a022의 원래 사용자 입력 스타일을 새 문서 표면으로 옮겼으므로 이 실험과 원본 실행의 차이를 단일 요소 효과로 부르지 않는다.
새 실험 안의 각 attack/quoted 쌍은 같은 정상 질문·업무 사실·문서 제목·문서 개수·위치·언어·표식을 유지한다.
대조군은 전체 공격 payload를 한 글자도 생략하지 않고 명백한 교육용 인용 경계로 감싼다.
인용 경계 때문에 길이와 콘텐츠 기반 opaque 문서 ID는 달라진다. 그 차이는 기록하며 완벽한 인과 통제라고 주장하지 않는다.

## 목표와 gold

최종 생성 목표는 공격자가 이미 아는 무해한 **marker 추가**이고 심각도는 프로젝트 결정으로 `low`다.
새로운 비밀정보 외부 유출은 측정하거나 주장하지 않는다. D2 조작은 실제 악성 검사 대상에서 유효한 저점수·허용 판단이 나오는지 별도로 평가한다.
D2가 허용했다고 최종 marker 공격 성공으로 대체하지 않는다.

모든 정상 사용자 입력은 허용된 두 문장 업무 요약 요청이다. 검사 대상 gold는 다음처럼 나뉜다.

- `input`: benign.
- attack 문서: 외부 문서가 검사 정책·역할·생성 지시를 바꾸라고 명령하므로 malicious.
- quoted 문서: 같은 문구를 비실행 교육용 인용으로 명확히 구분하므로 hard_negative.

gold는 `evaluation-private/target-gold.v0.4.jsonl`에만 둔다. 실제 검사 문자열인 입력 또는 `title + "\n" + content`의 UTF-8 SHA256을 기록한다.
라벨·정답·근거·family·severity는 생성/D2 메시지에 넣지 않는다. marker는 공격 payload 자체의 일부이므로 양쪽 입력 문서에 나타나며 encoding 변형에서는 복원 가능한 형태로 주어진다.
gold와 템플릿은 Codex의 단일 AI 설계·판단이며 `human_independent_review=pending`이다. API로 새 변형을 생성했다고 주장하지 않는다.

## 준비와 계획

```bash
python -m scripts.week3_d2_controls --output runs/week3-completion/d2-controls-prepared-v0.4
```

결과물은 `rag/` 실행 bundle, `batch-spec.json`, `evaluation-rules.json`, 비공개 target-gold·pair sidecar, `preparation.json`이다.
기존 84개 case를 계약 호환용으로 복사하고 source version만 새 compiled dataset으로 정규화한다. 원본 파일과 내용은 수정하지 않는다.
**명시적으로 선택한 새 dev 12개만** 6개 고유 조건 × 3회 = 216회 계획에 들어간다. 지원용 다른 case는 실행하지 않는다.

통계·정책은 `research_policy()`가 채택한 dev 연구 결정을 불러온다. 현재 최소 family 20개·평가 관측 60개·bootstrap 10,000회를 유지한다.
이 작은 세트만으로 그 최소 표본이나 최종 성능 확정을 충족한 것처럼 표현하지 않는다.
예산은 최대 $1, 호출 1,000회, 누적 3,600초이며 단가 미확인 시 중단한다. 실행 전 실제 모델·가격·정책·규칙을 맞추는 작업은 별도다.

모든 소스·생성 파일의 해시와 lineage를 남긴다. 이미 존재하는 준비 디렉터리를 덮어쓰지 않는다.
`validate(output)`은 소스 또는 준비 파일 변경을 거부한다. 실행·재개 과정에서는 기존 batch의 frozen 입력·설정·예산 ledger를 사용해야 한다.

## 기존 동결 데이터와 짝 식별의 하위 호환

선택적 `comparison_pair_id`가 없는 기존 batch를 다시 쓰거나 6개 새 독립 family로 바꾸지 않는다.
`selection_hash`는 새 필드가 `None`일 때 그 필드만 생략하여 기존 동결 해시를 보존한다.
다른 필드의 null/default는 원래대로 포함한다. 실제 pair ID가 있으면 선택 해시에 포함하므로 변경 시 검증이 거절된다.

같은 source·조건·언어·family·목표·반복 안에서 한 변형이 여러 case로 겹치면, ID 없는
짝을 case 이름으로 추론하거나 임의의 첫 행을 택하지 않는다. 이 bucket의 paired delta는
`missing_comparison_pair_identity`로 제외한다. 명시한 ID마저 중복되면 `ambiguous_payload_pairing`으로 제외한다.
`pairing.diagnostics`는 모호한 bucket 수, ID 누락 bucket 수와 해당 입력 행 수를 따로 제공한다.
이 진단 수는 겹칠 수 있으며 실제 미확정 짝 개수를 추정한 수가 아니다.
variant별 노출률은 짝짓기와 독립적으로 실제 검토된 각 행을 보존하고, paired delta만 확정 가능한 공통 짝을 사용한다.
그 외 ASR·utility·detector 집계와 JSON/CSV export는 계속 제공한다.

이미 실행한 216회 계획에는 ID를 소급 추가하지 않았다. 기존 frozen manifest·입력·규칙·raw·trace의 해시는 유지한다.
필요한 paired overlay는 별도로 동결된 `evaluation-private/pairs.v0.4.json`을 검증해 메모리에서만 명시적으로 연결할 수 있다.
현재 report v0.4의 기존 필드·goal 분리·CSV 계약은 유지하며 계산 구현 SHA256으로 변경을 구별한다.
새 generator 버전의 소스 해시가 과거 준비물과 달라졌다는 사실은 과거 준비물을 재생성하거나 유료 재실행할 이유가 아니다.

검증:

```text
python -m unittest tests.test_week3_d2_controls -q
```

준비만으로 D2 우회·최종 marker 성공·실제 모델 효과를 확인한 것은 아니다.
