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

| 도구 | 주요 기능 | 제공 방식 |
|---|---|---|
| Promptfoo | LLM 보안 평가, 공격 테스트, 결과 보고 | 오픈소스 및 기업용 서비스 |
| Microsoft Prompt Shields | 사용자 입력·외부 문서의 인젝션 탐지 | Azure 기반 서비스 |
| Microsoft AI Red Teaming / PyRIT | AI 공격 자동화 및 취약점 평가 | PyRIT 오픈소스, 실행 비용 별도 |
| Check Point AI Guardrails / Lakera | 프롬프트 공격 및 민감정보 탐지 | 기업용 보안 서비스 |
| Cisco AI Defense | AI 시스템 보안 평가 및 운영 보호 | 기업용 서비스 |
| NVIDIA NeMo Guardrails | 입력·검색·출력 단계의 방어 규칙 구성 | 오픈소스, 모델·인프라 비용 별도 |

기존 도구들도 공격 탐지, 보안 평가, 방어 정책 적용 등의 기능을 제공한다.

따라서 본 프로젝트는 완전히 새로운 방어 기술의 개발보다 동일한 실험 조건에서 방어 구성별 보안성과 정상 업무 영향을 비교하고 결과의 근거를 제공하는 기능에 초점을 맞춘다.

위 비교는 공개된 제품 기능을 바탕으로 한 기능 수준의 정리이며, 해당 도구들과 직접 성능 실험을 수행한 결과는 아니다. 공식 기능 및 가격 정보의 최신 재확인은 필요하다.

## 3. 프로젝트의 차별화 방향

| 비교 요소 | 본 프로젝트의 접근 |
|---|---|
| 방어 구성 비교 | none, D1, D2, D1+D2 비교 |
| 정상 업무 평가 | 공격 차단뿐 아니라 정상·Hard-negative 요청의 업무 성공과 오탐 확인 |
| 적용 위치 분석 | 입력 검사와 검색 문서 검사의 결과 비교 |
| 성능·비용 분석 | 보안성, 정상 업무, 지연, 비용을 함께 평가 |
| 평가 근거 추적 | 데이터·실행·판정 버전과 집계 결과 연결 |
| 추천 및 보류 | 성능 기준을 충족하지 못하면 추천을 보류하고 이유 기록 |

이러한 기능은 방어 구성 선택에 필요한 근거를 제공할 수 있다는 점에서 활용 가능성이 있다.

다만 기존 제품 대비 독점적인 기능이나 성능 우위가 입증된 것은 아니다.

## 4. 실험 결과 및 기술 검증

기존 합성 dev 실험에서 방어 구성에 따라 공격 성공률과 정상 업무 수행 결과가 달라지는 것을 확인했다.

특히 일부 방어는 공격 성공률을 낮췄지만 정상 업무 수행도 저하시켰다. 따라서 공격 성공률만으로 최적 방어를 선정하지 않는 평가 방식이 필요하다.

4주차 실제 두 모델 실행 검증에서는 다음 결과가 기록됐다.

| 항목 | 결과 |
|---|---:|
| 사용 모델 | GPT-4.1 mini, GPT-4.1 |
| 본 실험 실행 | 216건 |
| API 호출 | 396건 |
| 추정 API 비용 | 약 USD 0.189924 |
| API·JSON·CSV 및 사용량 검증 | PR #49 완료 기록 확인 |

이 비용은 해당 실험의 관측 토큰과 적용 단가를 이용한 추정치다. 실제 기업 운영 비용이나 서비스 도입에 따른 비용 절감 효과를 의미하지 않는다.
### 4.2 공식 기능·과금 근거 재확인

- 공식 자료 확인일: **2026-10-29**
- 확인 방식: 제공사의 공식 기술 문서·공식 저장소·가격 안내·제공 조건 문서 확인
- 확인 범위: 공개 기능, 제공 방식, 무료·유료 조건 및 공개 과금 기준
- 제외 범위: 비공개 계약 가격, 실제 고객 청구액, 경쟁 제품 직접 실행 및 동일 조건 성능 비교

| 비교 대상 | 공식 기능 확인 | 공식 과금·제공 조건 확인 | 미확인 항목 | 공식 출처 |
|---|---|---|---|---|
| Promptfoo | LLM 평가, 레드팀, 취약점 검사, 결과 보고, CI/CD 연계 | Community 무료, 월 10,000회 레드팀 probe 제공. Enterprise·On-Premise는 맞춤 견적 | 기업별 계약 금액, 실제 운영 총비용 | [1]~[3] |
| Microsoft Prompt Shields | 사용자 입력 공격과 외부 문서 공격 탐지 | Azure AI Content Safety는 모델·처리량에 따라 과금하며 텍스트 레코드 기반 요금 체계가 있음 | 적용 지역별 최종 단가, 실제 요청당 비용 | [4], [5] |
| Microsoft Foundry AI Red Teaming Agent / PyRIT | 자동 공격 시험·평가·보고. PyRIT는 오픈소스 위험 식별 프레임워크 | PyRIT 프레임워크 자체는 오픈소스. Foundry 서비스 및 모델 호출 비용은 별도로 고려 | 실제 Foundry 실행 총비용, 조직별 적용 요금 | [6], [7] |
| Check Point AI Guardrails / Lakera | 프롬프트 공격, 데이터 유출, 콘텐츠 위반, 악성 링크 탐지 및 정책 기반 대응 | Community는 월 10,000회 screening 요청 한도가 안내됨. Enterprise는 별도 영업 문의 | Enterprise 계약 단가, Self-hosted 총운영 비용 | [8], [12] |
| Cisco AI Defense | AI 자산 가시성, 공급망 위험 검사, AI 모델·앱 검증, 실행 중 보호 | 공식 Offer Description에 AI Application 수량 기반 구독 방식이 명시됨 | 애플리케이션당 실제 계약 단가, 총도입 비용 | [9], [10] |
| NVIDIA NeMo Guardrails | Input·Dialog·Retrieval·Execution·Output 단계의 프로그래밍 가능한 방어 | 오픈소스 라이브러리로 제공 | 연결 모델 호출비, 인프라 비용, 운영 인건비 | [11] |

#### 확인된 사실과 미검증 사항 구분

**공식 자료로 확인한 사항**

1. Promptfoo는 무료 Community와 유료 Enterprise·On-Premise를 구분한다.
2. Prompt Shields는 사용자 입력과 문서 공격을 탐지하며, Azure Content Safety의 사용량 기반 요금 체계와 연결된다.
3. PyRIT는 Microsoft가 공개한 오픈소스 프레임워크이고, Foundry AI Red Teaming Agent와 구분된다.
4. Check Point AI Guardrails는 무료 Community 이용 한도와 기업용 제공 방식을 안내한다.
5. Cisco AI Defense는 구독 계약에서 AI Application 수량을 과금 기준으로 사용한다.
6. NVIDIA NeMo Guardrails는 다섯 방어 단계를 지원하는 오픈소스 도구다.

**아직 확인하지 못한 사항**

- 각 기업의 실제 계약 금액과 할인 조건
- 같은 실험 1회를 실행했을 때의 제품별 총비용
- 본 프로젝트와 경쟁 제품의 동일 데이터·모델·조건 성능 차이
- 국내 기업 고객의 구매 의향과 지불 의사
- 도입 이후 관리 비용 및 실제 비용 절감 효과

공식 기능이나 가격 정책이 확인됐다는 사실은 해당 제품의 실제 보안 성능, 총소유비용 또는 본 프로젝트 대비 우수성을 검증했다는 뜻이 아니다.

특히 무료 플랜과 오픈소스는 모델 API·서버·운영 비용까지 모두 무료라는 의미가 아니다. 비공개 계약 가격은 임의로 추정하지 않는다.

#### 과금 방식 비교 시 유의사항

도구마다 과금 단위가 다르므로 단순 가격 순위를 작성하지 않는다.

- Promptfoo: Red Teaming probe 수와 기업별 계약 조건
- Azure AI Content Safety: 서비스별 텍스트 처리량과 적용 요금
- PyRIT: 실행에 연결되는 모델·서비스·인프라 사용량
- Check Point AI Guardrails: Screening 요청량과 기업 계약 조건
- Cisco AI Defense: 구독 대상 AI Application 수량
- NeMo Guardrails: 모델·인프라·운영 리소스

향후 비용 비교를 수행하려면 동일한 공격·정상 데이터, 모델, 실행 횟수, 검사 위치와 비용 포함 범위를 고정해야 한다.

이번 문서는 공개 기능·요금 구조 비교이며, 제품별 최저 가격 또는 총비용 우열 비교는 수행하지 않았다.

#### 추가 공식 근거

기존 참고자료 [1]~[11]을 유지하고 다음 자료를 추가한다.

[12] Check Point AI Security, AI Guardrails Dashboard  
https://docs.lakera.ai/docs/platform

- 확인 위치: Community와 Enterprise 제공 조건, 월별 screening 요청 한도
- 활용: Check Point 무료 이용 한도 및 기업용 제공 방식 확인
- 확인일: 2026-10-29

공식 자료는 향후 갱신될 수 있으므로, 사업화 또는 실제 도입 검토 시 적용 날짜와 계약 조건을 재확인해야 한다.
### 4.2 공식 기능·과금 근거 재확인

- 공식 자료 확인일: **2026-10-29**
- 확인 방식: 제공사의 공식 기술 문서·공식 저장소·가격 안내·제공 조건 문서 확인
- 확인 범위: 공개 기능, 제공 방식, 무료·유료 조건 및 공개 과금 기준
- 제외 범위: 비공개 계약 가격, 실제 고객 청구액, 경쟁 제품 직접 실행 및 동일 조건 성능 비교

| 비교 대상 | 공식 기능 확인 | 공식 과금·제공 조건 확인 | 미확인 항목 | 공식 출처 |
|---|---|---|---|---|
| Promptfoo | LLM 평가, 레드팀, 취약점 검사, 결과 보고, CI/CD 연계 | Community 무료, 월 10,000회 레드팀 probe 제공. Enterprise·On-Premise는 맞춤 견적 | 기업별 계약 금액, 실제 운영 총비용 | [1]~[3] |
| Microsoft Prompt Shields | 사용자 입력 공격과 외부 문서 공격 탐지 | Azure AI Content Safety는 모델·처리량에 따라 과금하며 텍스트 레코드 기반 요금 체계가 있음 | 적용 지역별 최종 단가, 실제 요청당 비용 | [4], [5] |
| Microsoft Foundry AI Red Teaming Agent / PyRIT | 자동 공격 시험·평가·보고. PyRIT는 오픈소스 위험 식별 프레임워크 | PyRIT 프레임워크 자체는 오픈소스. Foundry 서비스 및 모델 호출 비용은 별도로 고려 | 실제 Foundry 실행 총비용, 조직별 적용 요금 | [6], [7] |
| Check Point AI Guardrails / Lakera | 프롬프트 공격, 데이터 유출, 콘텐츠 위반, 악성 링크 탐지 및 정책 기반 대응 | Community는 월 10,000회 screening 요청 한도가 안내됨. Enterprise는 별도 영업 문의 | Enterprise 계약 단가, Self-hosted 총운영 비용 | [8], [12] |
| Cisco AI Defense | AI 자산 가시성, 공급망 위험 검사, AI 모델·앱 검증, 실행 중 보호 | 공식 Offer Description에 AI Application 수량 기반 구독 방식이 명시됨 | 애플리케이션당 실제 계약 단가, 총도입 비용 | [9], [10] |
| NVIDIA NeMo Guardrails | Input·Dialog·Retrieval·Execution·Output 단계의 프로그래밍 가능한 방어 | 오픈소스 라이브러리로 제공 | 연결 모델 호출비, 인프라 비용, 운영 인건비 | [11] |

#### 확인된 사실과 미검증 사항 구분

**공식 자료로 확인한 사항**

1. Promptfoo는 무료 Community와 유료 Enterprise·On-Premise를 구분한다.
2. Prompt Shields는 사용자 입력과 문서 공격을 탐지하며, Azure Content Safety의 사용량 기반 요금 체계와 연결된다.
3. PyRIT는 Microsoft가 공개한 오픈소스 프레임워크이고, Foundry AI Red Teaming Agent와 구분된다.
4. Check Point AI Guardrails는 무료 Community 이용 한도와 기업용 제공 방식을 안내한다.
5. Cisco AI Defense는 구독 계약에서 AI Application 수량을 과금 기준으로 사용한다.
6. NVIDIA NeMo Guardrails는 다섯 방어 단계를 지원하는 오픈소스 도구다.

**아직 확인하지 못한 사항**

- 각 기업의 실제 계약 금액과 할인 조건
- 같은 실험 1회를 실행했을 때의 제품별 총비용
- 본 프로젝트와 경쟁 제품의 동일 데이터·모델·조건 성능 차이
- 국내 기업 고객의 구매 의향과 지불 의사
- 도입 이후 관리 비용 및 실제 비용 절감 효과

공식 기능이나 가격 정책이 확인됐다는 사실은 해당 제품의 실제 보안 성능, 총소유비용 또는 본 프로젝트 대비 우수성을 검증했다는 뜻이 아니다.

특히 무료 플랜과 오픈소스는 모델 API·서버·운영 비용까지 모두 무료라는 의미가 아니다. 비공개 계약 가격은 임의로 추정하지 않는다.

#### 과금 방식 비교 시 유의사항

도구마다 과금 단위가 다르므로 단순 가격 순위를 작성하지 않는다.

- Promptfoo: Red Teaming probe 수와 기업별 계약 조건
- Azure AI Content Safety: 서비스별 텍스트 처리량과 적용 요금
- PyRIT: 실행에 연결되는 모델·서비스·인프라 사용량
- Check Point AI Guardrails: Screening 요청량과 기업 계약 조건
- Cisco AI Defense: 구독 대상 AI Application 수량
- NeMo Guardrails: 모델·인프라·운영 리소스

향후 비용 비교를 수행하려면 동일한 공격·정상 데이터, 모델, 실행 횟수, 검사 위치와 비용 포함 범위를 고정해야 한다.

이번 문서는 공개 기능·요금 구조 비교이며, 제품별 최저 가격 또는 총비용 우열 비교는 수행하지 않았다.

#### 추가 공식 근거

기존 참고자료 [1]~[11]을 유지하고 다음 자료를 추가한다.

[12] Check Point AI Security, AI Guardrails Dashboard  
https://docs.lakera.ai/docs/platform

- 확인 위치: Community와 Enterprise 제공 조건, 월별 screening 요청 한도
- 활용: Check Point 무료 이용 한도 및 기업용 제공 방식 확인

공식 자료는 향후 갱신될 수 있으므로, 사업화 또는 실제 도입 검토 시 적용 날짜와 계약 조건을 재확인해야 한다.
## 5. 활용 방안 및 수익 모델

| 활용 분야 | 활용 방법 | 예상 수익 모델 |
|---|---|---|
| 교육·연구 | 공격·방어 실습 및 성능 비교 | 교육용 라이선스, 연구 지원 |
| 기업 보안 평가 | 기업 RAG 서비스의 방어 구성 비교 | 평가 프로젝트별 비용 |
| 반복 검증 | 모델·문서·방어 정책 변경 시 재평가 | 정기 구독 |
| 맞춤형 평가 | 고객 데이터·업무 기준을 반영한 실험 | 구축 및 컨설팅 비용 |

초기에는 교육·연구 및 소규모 기업 평가를 중심으로 활용 가능성을 검토하고, 이후 반복 검증 서비스로 확장하는 방안을 가정한다.

그러나 현재는 고객 인터뷰, 유료 계약 및 실제 매출 검증이 없으므로 수익 모델은 사업성 가설에 해당한다.

## 6. PoC 및 후속 검증 계획

기업용 서비스로의 확장 가능성을 확인하기 위해 다음 단계를 제안한다.

1. **고객 문제 확인:** AI 개발자 및 보안 담당자를 대상으로 현재 방어 평가 방식과 불편 사항 조사
2. **PoC 범위 설정:** 합성 데이터 또는 승인된 비민감 업무 데이터를 이용한 소규모 RAG 평가
3. **성과 측정:** 공격 성공률, 정상 업무 성공률, 오탐, 지연, 비용 및 평가 소요 시간 비교
4. **사업성 판단:** 실제 사용자 피드백, 반복 사용 의향 및 지불 의사 확인

현재 PoC와 고객 검증은 수행되지 않았으며, 위 내용은 후속 실행 계획이다.

## 7. 한계 및 결론

현재까지 확인된 성과는 방어 구성별 실험 결과와 평가·추적 절차이며, 다음 항목은 입증되지 않았다.

- 기존 상용 보안 도구 대비 성능 우위
- 실제 기업 환경에서의 운영 안전성
- 실고객 비용 및 평가 시간 절감
- 고객 구매 의향과 지속적인 수익성


## 참고 자료

- [Promptfoo 공식 문서](https://www.promptfoo.dev/docs/red-team/quickstart/)
- [Microsoft Prompt Shields](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/content-filter-prompt-shields)
- [Microsoft PyRIT](https://github.com/Azure/PyRIT)
- [Check Point 공식 사이트](https://www.checkpoint.com/)
- [Cisco AI Defense 공식 사이트](https://www.cisco.com/)
- [NVIDIA NeMo Guardrails](https://docs.nvidia.com/nemo/guardrails/latest/home)
- [보안바다 PR #49](https://github.com/zerolong-01/sec_sea/pull/49)

