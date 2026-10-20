# 실제 OpenAI API dev 검증 — 2026-10-20

로컬 `.env`의 키로 생성·D2 모두 `gpt-4.1-mini-2025-04-14`와
`https://api.openai.com/v1/chat/completions`를 사용했다. 실행 데이터는
`synthetic_v0.2` RAG와 `synthetic_email_v0.1` 이메일이며 dev만 선택했다.
각 실행의 HTTP 200 응답, 관측 토큰, 가격 snapshot에 따른 추정 비용을
private raw·공개 trace·호출 예약 ledger 사이에서 대조했다.

| 기록 | 검증 범위 |
| --- | --- |
| [pilot-verification.json](pilot-verification.json) | 두 앱 × 대표 3건 × 6개 고유 구성 × 3회, 108건 |
| [detector-verification.json](detector-verification.json) | 탐지 전용 18건, 입력·문서 36개 대상, 생성 호출 0회 |
| [ui-verification.json](ui-verification.json) | 실제 저장 결과의 대표 3건·4개 모드·D2 세 위치 화면 표시와 마스킹, 추가 모델 호출 0회 |

파일럿은 완료 90건·방어 차단 18건·실행 오류 0건이며 198회 호출했다.
탐지 진단은 18건·36회 호출을 완료했다. 두 검증의 추정 비용은 합계
$0.0465908이고, 별도 정상 연결 smoke 1회($0.000136)를 포함하면
$0.0467268이다. 완료된 배치를 재개해도 추가 모델 호출은 0회였다.

6개 구성은 none, D1, D2(input+retrieval), D1+D2(input+retrieval),
D2(input), D2(retrieval)이다. D2 양쪽 구성은 기법/위치 비교에서 공유한다.
대표 12건과 세 위치 검증이 108건 안에 포함되며 중복 호출하지 않았다.
집계·목록·개별 trace·CSV API는 저장 파일과 대조했고, 조회 중 모델 호출을
차단한 상태에서도 동작했다. UI 검증은 저장된 실제 결과를 Streamlit에
재생한 것으로 실행 버튼을 눌러 추가 유료 호출을 만들지는 않았다.

공식 [모델 가격 안내](https://developers.openai.com/api/docs/models/gpt-4.1-mini)를
확인해 입력 $0.40/백만 토큰, 출력 $1.60/백만 토큰을
[버전 가격표](../../../configs/pricing-openai-2026-10-20.json)에 저장했다.
기록된 금액은 표준 단가 추정치이며 캐시 입력 할인이나 청구 정산 차이는 반영하지 않는다.

## 실행·재개

저장소 루트의 가상환경에서 실행한다. 첫 명령은 최대 $1, 두 번째 명령은
최대 $0.25의 개별 실행 예산을 사용한다. 같은 output으로 다시 실행하면
checkpoint를 재사용하고 완료된 항목을 다시 호출하지 않는다. 실패/불확실
호출은 자동 재시도하지 않는다. 새 output을 지정하면 새 유료 실험이다.

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_real_api --output runs/real-api-2026-10-20/pilot
.\.venv\Scripts\python.exe -m scripts.verify_real_detector --output runs/real-api-2026-10-20/detector
.\.venv\Scripts\python.exe -m scripts.verify_real_ui --runs-dir runs/real-api-2026-10-20/pilot/runs --batch-id batch-3fb7c66981bd
```

`--max-items 2`로 소형 확인 후 같은 output으로 재개할 수 있다.
원시 실행 자료와 전체 공개 trace·보고서·CSV는 Git에서 제외된
`runs/real-api-2026-10-20/`에 보관한다. 이 디렉터리에는 데이터와 설정의
고정 snapshot, run_id, checkpoint, 금액 예약과 실제 사용량의 대조 기록이 있다.
공개 기록에는 키나 원시 보호값을 포함하지 않는다. 유료 연결 전 샌드박스의
소켓 제한으로 실패했던 1건과 정상 연결 smoke 1건은 `smoke/`에 별도 보관한다.

## 검증 결과의 범위

이 기록은 실제 연결·실행·계측·저장·조회·화면 인수 근거다. 공격 성공/실패나
정상 의미 평가가 모두 확정됐다는 뜻은 아니다. 자동 평가의 `review_needed`를
성공으로 변경하지 않았다. 탐지 정답 36개는 단일 검수 초안이므로 팀 검수
대기로 두고, gold를 임의 등록하거나 오탐/미탐 분모에 포함하지 않았다.

남은 팀 작업은 대표 무방어 출력의 3인 판정 합의, gold·번역의 팀 검수,
통계·서비스 기준 확정과 holdout 동결·실행이다. 최종 방어 추천은 deferred다.

새 실행기 회귀 테스트 8건과 기존 환경·provider·batch 테스트를 통과했다.
로컬 HTTP fixture에서는 파일럿 108건의 중단·재개·완료 후 재조회 시 중복 호출
0건을 확인했고, 오류·불확실 호출의 자동 유료 재시도 방지도 검사했다.
