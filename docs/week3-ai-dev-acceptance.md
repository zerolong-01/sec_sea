# 3주차 AI 교차 검토·dev 기술 인수

사용자는 실제 사람 검토·공동 인수 기록이 별도로 없다고 답하고 후속 작업을 위임했다. 이에 두 개의 새로운 AI 검토와 제3 AI 조정, 데이터(A)·백엔드(B)·공개 UI/인계(C)의 기술 검증을 수행했다. **이번 dev 작업의 검토 절차는 완료했으며, 사람이 수행한 독립 검토나 실제 A/B/C 팀 서명으로 기록하지 않는다.** 위임 범위·한계는 [별도 정책](../configs/week3-ai-dev-review-policy.v0.1.json)에 고정했다.

## 실제 검토와 결과

세 dev 배치의 최종 출력 648건과 실제 D2 탐지 대상 621건, 총 1,269개 검토 task를 사용했다. 원래 evidence SHA-256이 완전히 같은 항목만 중복 제거하여 최종 출력 241종·탐지 대상 42종, 고유 자료 283종을 만들었다. 반복 출력의 중복 제거는 통계적 독립 표본 수를 늘리지 않는다.

두 primary reviewer는 새로운 별도 context에서 기존 자동 평가·과거 AI 판정·실험 조건·상대방 판정을 보지 않고 283종을 각각 실독했다. 보호값은 일관된 alias로 가렸고, 원문 SHA와 1,269개 소속 연결은 private packet으로 검증했다. 자료 순서는 서로 다르게 섞었다. 합의는 218종, 불일치는 65종이었다. 불일치 65종은 별도 제3 AI가 두 원표와 원증거를 읽고 개별 사유로 조정했다. 조정은 원문 SHA와 두 응답의 canonical SHA에 연결했다.

| 검증 | 결과 |
| --- | --- |
| primary 응답 | 각각 283/283, 누락·중복 0 |
| 합의 / 조정 / 미조정 충돌 | 218 / 65 / 0 |
| 실제 task 연결 | 출력 648 + 탐지 대상 621 = 1,269 |
| 정상 작업 4차원 판정 | 고유 출력 241종 모두 success/failure 결정; 합계 success165/failure76 |
| 목표 관측 미확정 | 고유 출력 23종의 blind goal 판단에 `review_needed` 유지 |
| fresh target gold | 42종→실제 검사621건; 현재 저장 AI gold와621/621 일치 |
| 읽기 전후 입력 무결성 | 1,845파일 불변 |
| 추가 제공자 모델 호출 / 원본 판정 적용 | 0 / 없음 |

23종은 “미조정 충돌”이나 “공격 23건”이라는 뜻이 아니다. 각 항목은 조정 완료 또는 합의 상태이며 목표 자체의 증거가 부족한 판단을 남겼다. 정상·hard-negative의 목표 관측은 private 원래 label로 공격 ASR 대상에서 제외해 `not_applicable`로 매핑한다. 실제 공격 분모·제외 사유는 조건별 지표 파일에서 확인한다.

원래 자동 ASR·정상 평가, 저장 gold, frozen 입력·정책·가격·manifest·호출 ledger는 변경하지 않았다. 새 의미 판정은 `week3-two-ai-review-v0.1` overlay다. 이전 single-AI v0.4 보고서와 수치가 달라도 원래 기록을 소급 수정하지 않는다. 대시보드는 원래 저장 평가를 표시하며, 이 새 overlay를 자동 적용한 화면으로 설명하지 않는다.

## 공개 증거와 재현

[안전 요약과 해시](examples/week3-completion/ai-dev-review.v0.1.json)는 다음 파일을 연결한다.

- [고유 자료별 두 판정·조정·근거 283행](examples/week3-completion/ai-dev-review.units.v0.1.jsonl)
- [원래 task와 판정 연결 1,269행](examples/week3-completion/ai-dev-review.members.v0.1.jsonl)
- [조건별 출력 지표 144개·target gold 분포 24개](examples/week3-completion/ai-dev-review.metrics.v0.1.jsonl)
- [AI 역할 A/B/C 기술 검증 기록](examples/week3-completion/ai-dev-technical-acceptance.v0.1.json)

공개 기록에는 보호값 매핑표·원문 evidence·원시 출력·인증정보를 넣지 않았다. 근거 문장은 등록값·변환을 마스킹하고, 공개할 실제 파일을 literal/URL/문맥 포함 Base64 복원 검사로 다시 확인했다. 원문 hash는 내용 무결성 확인이며 작성자 서명 인증이 아니다.

private packet과 저장 실행 자료가 있는 환경에서 다음 명령으로 재검증한다. 가상환경을 활성화한 Git Bash·PowerShell에서 동일한 한 줄 명령이다. 출력 경로는 아직 없는 새 디렉터리여야 한다.

```sh
python -m scripts.week3_ai_review --review-dir runs/week3-completion/ai-dev-review-v0.1 --responses runs/week3-completion/ai-dev-review-v0.1/reviewer-1/responses.jsonl runs/week3-completion/ai-dev-review-v0.1/reviewer-2/responses.jsonl --adjudications runs/week3-completion/ai-dev-review-v0.1/adjudicator-3/responses.jsonl --output runs/week3-completion/ai-dev-review-replay-v0.1
```

도구는 현재 frozen source·실제 detector 입력·raw/public 로그·task 소속·두 응답·제3 응답 해시를 검증하고 JSON/CSV를 생성한다. 누락·미조정 충돌은 pending으로 보고하며 정상/공격 업무/원ASR/새AI 목표/두FPR의 분모를 분리한다. 출판 중 source가 바뀌면 성공 보고서를 남기지 않는다. 원본 annotation·평가를 쓰거나 모델을 호출하는 기능은 없다.

## 기술 인수와 수정

AI 역할 A는 구조·split·해시·dev 정적 기록을 확인했고 문서 범위 오류 한 건을 찾아 수정 확인했다. 원래 gold48행 중 제외18행은 RAG holdout12와 당시 정적 범위 밖 email dev6이었다. 이를 holdout18로 잘못 설명한 두 문서를 고쳤으며 데이터 원본은 보존했다.

AI 역할 B는 실제283/1,269 연결, 원본 불변과 서로 다른 평가 분모, 제3 응답의 양쪽 vote binding을 검증했다. AI 역할 C는 공개 trace13개·현재 API projection·catalog 해시와 정상/공격·AI overlay 표시를 확인했다. UI 집중 회귀10개가 통과했다.

독립 코드 검토에서 문맥과 함께 인코딩한 Base64 보호값이 공개 근거에서 복원될 수 있는 결함을 찾았다. 공유 마스킹 helper를 고쳐 contiguous 표준/URL-safe/무패딩 container를 검사하며, 원문·평가 후 공개 projection만 마스킹한다. privacy 회귀7개와 검토 CLI 회귀8개가 통과했고, 기존13개 공개 trace는 현재 projection과 계속 일치했다. 검증 중 source 변경으로 실패해도 완성 보고서가 남던 결함은 임시 디렉터리에서 검산 후 게시하도록 고쳤다.

최신 통합 CI·병합 상태는 [PR #39 Checks](https://github.com/zerolong-01/sec_sea/pull/39/checks)의 실제 head를 따른다. 이전 `63ef871`의191/113개 CI 기록은 당시 증거이며 이번 후속 코드를 검증한 증거로 바꾸지 않는다.

## 적용 한계

두 검토와 제3 조정은 동일 모델 계열을 사용했고 rubric·마스킹 준비 과정을 공유한다. 별도 context의 AI 검토는 사람·다른 모델 계열·통계적 독립 검증을 보장하지 않는다. A/B/C는 AI가 확인한 기술 역할이며 실제 담당자의 공동 시연·서명이 아니다. 원래 이슈의 사람 검토 요건은 미충족 사실을 보존한다.

이 dev 인수는 불충분한 family를 늘리거나 미확정을 성공/실패로 강제하지 않는다. 이 overlay의 통계 신뢰구간은 null, 최종 구성 추천은 deferred다. holdout 9건은 보존했고 최종 평가·운영 배포를 승인하지 않았다. [134개 원문 요구사항 대조표](week3-completion-status.md)의 원래 요건과 이번 위임 dev 경로를 구별해 읽는다.
