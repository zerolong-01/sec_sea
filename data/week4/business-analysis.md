# 4주차 사업성 분석 보고서

## 1. 프로젝트 개요

보안바다의 LLM Defense Trade-off Lab은 RAG 챗봇과 이메일 요약기를 대상으로 프롬프트 인젝션 공격 및 방어 성능을 비교하는 실험 플랫폼이다.

공격 성공률뿐 아니라 정상 업무 성공률, 오탐률, 응답 지연, 비용을 함께 분석하여 적절한 방어 구성을 선택할 수 있도록 지원한다.

해결하려는 문제는 다음과 같다.

- 어떤 방어 구성이 공격 차단과 정상 업무 유지에 효과적인가?
- 사용자 입력과 검색 문서 중 어디에 방어를 적용해야 하는가?
- 방어 적용으로 인한 오탐·지연·비용은 얼마나 발생하는가?
- 어떤 근거로 특정 방어 구성을 추천하거나 보류해야 하는가?

## 2. 유사 서비스 및 도구 비교

### 2.1 비교 범위

- 확인 방식: 제공사의 공식 기술 문서·공식 저장소·가격 및 제공 조건 확인
- 확인 범위: 주요 기능, 무료·유료 제공 방식, 공개 과금 기준
- 미확인 범위: 기업별 계약 단가, 실제 청구액, 동일 조건의 성능 및 총비용 비교

다음 표는 공개 공식 자료를 바탕으로 정리한 기능·제공 조건 비교이다. 경쟁 도구를 직접 실행하여 성능을 비교한 결과는 아니다.

### 2.2 도구 6개 비교

| 도구 | 공식 자료에서 확인한 주요 기능 | 과금·제공 방식 | 미확인 사항 | 출처 |
|---|---|---|---|---|
| Promptfoo | LLM 평가, 레드팀 테스트, 취약점 검사, 결과 보고, CI/CD 연계 | Community 무료, 월 10,000회 레드팀 probe. Enterprise·On-Premise 맞춤 견적 | 기업 계약 금액, 실제 운영 총비용 | [1], [2] |
| Microsoft Prompt Shields | 사용자 입력과 외부 문서의 프롬프트 인젝션 탐지 | Azure AI Content Safety의 서비스별 사용량 기반 과금 | 지역별 실제 단가, 운영 총비용 | [3], [4] |
| Microsoft Foundry AI Red Teaming Agent / PyRIT | 자동 공격 시험·평가·보고, 생성형 AI 위험 식별 | PyRIT는 오픈소스. Foundry 서비스·모델 호출 비용은 별도 | 실제 실행 및 서비스 이용 총비용 | [5], [6] |
| Check Point AI Guardrails / Lakera | 프롬프트 공격·데이터 유출 등 탐지, 정책 관리 및 위협 모니터링 | Community 월 10,000회 screening 요청. Enterprise 별도 문의 | 기업 계약 가격, 자체 호스팅 총비용 | [7], [8] |
| Cisco AI Defense | AI 자산 가시성, 보안 위험 검증, AI 애플리케이션 보호 | AI Application 수량 등을 기준으로 한 구독 계약 | 실제 계약 단가와 도입 총비용 | [9], [10] |
| NVIDIA NeMo Guardrails | 입력·대화·검색·실행·출력 단계의 프로그래밍 가능한 방어 | 오픈소스. 연결 모델·인프라 비용 별도 | 실제 운영비, 관리 인력 및 유지보수 비용 | [11] |

### 2.3 비교 결과 및 확인·미확인 구분

**공식 자료로 확인된 사항**

1. Promptfoo는 무료 Community와 유료 Enterprise·On-Premise 플랜을 구분한다.
2. Microsoft Prompt Shields는 입력 및 외부 문서의 공격 탐지를 지원하며, Azure AI Content Safety는 사용량 기반 요금 체계를 제공한다.
3. Microsoft PyRIT는 오픈소스 프레임워크로, Foundry AI Red Teaming Agent와 동일한 제품은 아니다.
4. Check Point AI Guardrails는 Community 이용 한도와 기업용 제공 조건을 안내한다.
5. Cisco AI Defense는 AI Application 수량 등을 구독 기준으로 사용한다.
6. NVIDIA NeMo Guardrails는 입력·대화·검색·실행·출력 단계의 방어 구성을 지원하는 오픈소스 도구다.

**미확인 사항**

- 각 서비스의 실제 기업 계약 금액과 할인 조건
- 같은 데이터와 실행 횟수를 기준으로 한 제품별 총비용
- 본 프로젝트와 경쟁 도구의 동일 조건 성능 차이
- 국내 기업 고객의 구매 의향과 지불 의사
- 실제 도입 후 평가 시간·운영 비용 절감 효과

기존 도구들도 공격 탐지, 보안 평가, 방어 정책 적용 및 결과 보고 기능을 제공한다.

따라서 본 프로젝트는 완전히 새로운 방어 기술을 개발했다고 주장하기보다, 동일한 업무와 실험 조건에서 방어 구성별 보안성과 정상 업무 영향을 비교하고 판단 근거를 제공하는 데 초점을 맞춘다.

무료 플랜과 오픈소스 제공은 모델 API·서버·운영 비용까지 모두 무료라는 의미가 아니다. 또한 서비스마다 과금 단위가 달라 공개 가격만으로 총비용 순위를 산출하지 않는다.

## 3. 프로젝트의 차별화 방향

| 비교 요소 | 본 프로젝트의 접근 |
|---|---|
| 방어 구성 비교 | none, D1, D2, D1+D2 비교 |
| 정상 업무 평가 | 공격 차단뿐 아니라 정상·hard-negative 요청의 업무 성공과 오탐 확인 |
| 적용 위치 분석 | 사용자 입력과 검색 문서의 검사 위치 비교 |
| 성능·비용 분석 | 보안성, 정상 업무, 지연, 비용을 함께 평가 |
| 평가 근거 추적 | 데이터·실행·판정 버전과 집계 결과 연결 |
| 추천 및 보류 | 성능 기준 미충족 또는 근거 부족 시 추천 보류 및 이유 기록 |

이러한 접근은 방어 구성 선택에 필요한 근거를 제공할 수 있다는 점에서 활용 가능성이 있다.

다만 기존 제품에 없는 독점적 기능이나 경쟁 제품 대비 성능 우위가 입증된 것은 아니다.

## 4. 실험 결과 및 기술 검증

기존 합성 dev 실험에서는 방어 구성에 따라 공격 성공률과 정상 업무 수행 결과가 달라지는 것을 확인했다.

일부 조건에서는 공격 성공률 감소와 함께 정상 업무 수행 저하가 관찰되었다. 따라서 공격 성공률만으로 최적 방어를 선정하지 않고 정상 업무 성공률, 오탐, 지연 및 비용을 함께 고려해야 한다.

4주차 실제 두 모델 실행 검증에서는 다음 결과가 기록되었다.

| 항목 | 결과 |
|---|---:|
| 사용 모델 | GPT-4.1 mini, GPT-4.1 |
| 계획 실행 및 기록 | 216건 |
| 생성 완료 | 180건 |
| 방어 차단 | 36건 |
| 본 실험 API 호출 | 396건 |
| 추정 API 비용 | 약 USD 0.189924 |

- 근거: `docs/examples/model-experiment-live/verification-report.json`
- 검증 기록 버전: `paid-model-experiment-evidence-v0.1`
- 관련 백엔드 작업: PR #49

해당 검증에서는 두 모델별로 108건의 실행이 기록되었으며, 각 모델에서 완료 90건과 방어 차단 18건을 확인했다.

추정 비용은 관측 토큰과 고정된 단가를 기준으로 계산한 금액이다. 실제 청구 금액이나 기업 운영 비용을 뜻하지 않는다.

또한 이 결과는 모델 호출·실행·사용량 관련 기술 검증 근거이며, 두 모델 사이의 보안 성능 순위 또는 최종 방어 추천을 확정한 결과가 아니다.

자세한 결과 및 미완료 검산 항목은 [result-check.md](result-check.md)와 [final-report.md](final-report.md)를 따른다.

## 5. 활용 방안 및 수익 모델

| 활용 분야 | 활용 방법 | 예상 수익 모델 |
|---|---|---|
| 교육·연구 | 공격·방어 실습 및 결과 비교 | 교육용 라이선스, 연구 지원 |
| 기업 보안 평가 | 기업 RAG 서비스의 방어 구성 비교 | 평가 프로젝트별 비용 |
| 반복 검증 | 모델·문서·방어 정책 변경 시 재평가 | 정기 구독 |
| 맞춤형 평가 | 고객 업무 데이터와 평가 기준을 반영한 실험 | 구축 및 컨설팅 비용 |

초기에는 교육·연구 및 소규모 서비스 개발팀의 평가 지원을 중심으로 활용 가능성을 검토하고, 이후 반복 검증 서비스로 확장하는 방안을 가정한다.

그러나 고객 인터뷰, 유료 계약 및 실제 매출 검증은 수행되지 않았으므로 위 수익 모델은 사업성 가설에 해당한다.

경제성을 판단하려면 API 호출 비용뿐 아니라 데이터 준비, 판정 검토, 인프라, 유지보수 및 오탐으로 인한 재처리 비용도 함께 고려해야 한다.

## 6. PoC 및 후속 검증 계획

기업용 서비스 확장 가능성을 확인하기 위해 다음 단계를 제안한다.

1. **고객 문제 확인:** AI 개발자 및 보안 담당자를 대상으로 기존 방어 평가 방식과 불편 사항 조사
2. **PoC 범위 설정:** 합성 데이터 또는 사용 승인을 받은 비민감 업무 데이터로 소규모 RAG 평가
3. **성과 측정:** 공격 성공률, 정상 업무 성공률, 오탐, 지연, 비용 및 평가 소요 시간 비교
4. **사용성 확인:** 결과 해석의 편의성과 실제 업무에 필요한 기능 조사
5. **사업성 판단:** 반복 사용 의향, 지불 의사 및 운영 비용 검토

현재 고객 대상 PoC와 구매 의향 검증은 수행되지 않았으며 위 내용은 후속 계획이다.

## 7. 한계 및 결론

현재까지 확보한 성과는 제한된 합성 dev 환경에서의 방어 구성 비교와 실험·평가 근거를 추적하는 기술적 절차이다.

다음 사항은 아직 입증되지 않았다.

- 기존 상용 보안 도구 대비 성능 우위
- 실제 기업 환경에서의 운영 안전성
- 고객의 비용 및 평가 시간 절감
- 고객 구매 의향과 지속적인 수익성
- Holdout 데이터에 대한 일반화 성능

최종 방어 추천은 `deferred`로 유지한다. 관련 판단과 제한 사항은 [final-report.md](final-report.md)에 연결한다.

본 프로젝트는 기존 상용 보안 제품을 대체한다고 주장하기보다, RAG 및 이메일 요약 업무에서 방어 적용에 따른 보안성과 정상 기능 손실을 함께 비교하는 실험·평가 도구로 활용 가능성을 검토한다.

사업화 여부는 향후 동일 조건의 도구 비교, 사용자 검증 및 실제 운영 비용 분석을 통해 판단해야 한다.

## 8. 참고 자료

공식 자료 확인일: **2026-10-29**

아래 자료는 유사 서비스의 공개 기능과 제공·과금 조건을 확인하기 위한 근거다. 프로젝트 초기 데이터·gold·rubric 작성에 실제 사용한 자료라고 소급하여 주장하지 않는다.

| 번호 | 공식 자료 | 확인 내용 |
|---|---|---|
| [1] | [Promptfoo 공식 문서](https://www.promptfoo.dev/docs/intro/) | 평가·레드팀 및 결과 보고 기능 |
| [2] | [Promptfoo Pricing](https://www.promptfoo.dev/pricing/) | 무료 Community, probe 한도, 기업용 맞춤 가격 |
| [3] | [Microsoft Prompt Shields](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection) | 입력·문서 공격 탐지 |
| [4] | [Azure AI Content Safety Pricing](https://azure.microsoft.com/en-us/pricing/details/content-safety/) | 사용량 기반 요금 및 서비스별 과금 |
| [5] | [Microsoft Foundry AI Red Teaming Agent](https://learn.microsoft.com/en-us/azure/foundry/concepts/ai-red-teaming-agent) | AI 자동 공격 시험·평가 |
| [6] | [Microsoft PyRIT 공식 저장소](https://github.com/microsoft/PyRIT) | 오픈소스 위험 식별 프레임워크 |
| [7] | [Check Point AI Guardrails 소개](https://docs.lakera.ai/guard) | 공격 탐지와 정책 기반 보호 |
| [8] | [Check Point AI Guardrails Dashboard](https://docs.lakera.ai/docs/platform) | Community 사용량 제한과 Enterprise 제공 |
| [9] | [Cisco AI Defense Data Sheet](https://www.cisco.com/c/en/us/products/collateral/security/ai-defense/ai-defense-ds.pdf) | AI 보안 기능 및 제공 범위 |
| [10] | [Cisco AI Defense Offer Description](https://www.cisco.com/c/dam/en_us/about/doing_business/legal/OfferDescriptions/AI-Defense-OD.pdf) | 구독·사용량 기준 |
| [11] | [NVIDIA NeMo Guardrails 공식 저장소](https://github.com/NVIDIA-NeMo/Guardrails) | 오픈소스 및 방어 단계 |


## 9. 프로젝트 내부 연결 자료

- [최종 보고서](final-report.md): 전체 실험 결과와 결론
- [결과 검산](result-check.md): 평가 수치와 미완료 검증
- [방어 비교](defense-comparison.md): 후보별 비교 및 추천·보류 근거
- [최종 근거 Index](final-evidence-index.md): 산출물과 원본 근거 연결
