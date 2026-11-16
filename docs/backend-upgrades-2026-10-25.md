# 백엔드·실험·재현 업그레이드

2026-10-25 기준으로 기존 1–4주차 데이터·실행·평가·배치·재현 경로와 GitHub 이슈를 점검했다.
다음 세 항목을 구현했다. 프론트엔드 파일, 의존성 lock, 공개 데이터와 기존 연구 evidence는 수정하지 않았다.

| 이슈 | 기존 문제 | 변경 결과 |
| --- | --- | --- |
| [#50](https://github.com/zerolong-01/sec_sea/issues/50) | 서비스별 스레드 잠금만 있어 독립 API 작업자가 같은 평가·gold를 덮어쓸 수 있음 | 실행별 OS 잠금으로 읽기부터 trace 저장까지 보호하고 충돌은 HTTP 409로 반환 |
| [#51](https://github.com/zerolong-01/sec_sea/issues/51) | HTTP 리다이렉트 자동 추적, 크기 제한 없는 응답 읽기, 잘못된 직접 설정 허용 | 리다이렉트 차단, 4 MiB 응답 상한, endpoint·timeout·숫자 제한·오류 정책 조기 검증 |
| [#52](https://github.com/zerolong-01/sec_sea/issues/52) | 파일 해시를 계산할 때 전체 파일을 메모리에 적재 | 1 MiB 입력 버퍼를 사용하는 SHA-256으로 배치·inventory·패키지 검증 경로 연결 |

## 운영 동작

평가와 detector gold 갱신은 같은 실행의 `review.lock`을 공유한다. 별도 history 파일도 각각
잠금 안에서 읽고 추가하므로 저장소를 직접 사용하는 작성자 사이에서도 이력 유실을 막는다.
같은 서비스의 스레드는 기존처럼 순서대로 처리하고 독립 서비스/프로세스의 경합은
`409 {"detail":{"code":"CONCURRENT_WRITE"}}`로 반환한다. 배치 검토의 작성자 충돌도 같은 코드다.
작성 중에도 기존 trace 조회는 가능하다. 잠금은 파일 존재 여부가 아니라 OS가 관리하며
프로세스 종료나 예외 때 해제된다. 각 JSON 파일은 원자적으로 교체하지만 여러 파일의
저장을 하나의 데이터베이스 트랜잭션으로 묶지는 않는다.
기존 target gold 등록 도구는 해당 갱신 대상의 두 잠금 파일만 변경 허용 목록에 포함한다.
원시 근거·다른 실행·관련 없는 잠금 파일은 계속 원래 해시를 검사한다.

모델 제공자가 반환한 301/302/303/307/308 응답을 다른 주소로 전달하지 않는다.
`MODEL_REDIRECT_BLOCKED` 오류 trace에 원래 HTTP 상태를 남긴다. 응답 본문이 4 MiB를
넘으면 `MODEL_RESPONSE_TOO_LARGE`로 실패한다. 원래 요청을 재전송하지 않고 observer 정산은
한 번 수행한다. 사용량을 알 수 없는 실패는 기존 예산 예약과 미확인 비용 처리를 따른다.
잘못된 UTF-8, 과도하게 중첩된 JSON, 잘못된 응답 구조와 사용량도 제어된 오류로 기록한다.

HTTP endpoint의 인증정보·query·fragment·공백·잘못된 포트와 양수가 아닌/유한하지 않은
timeout을 거부한다. 직접 만든 `Settings`에서도 bool/소수가 토큰·호출 개수로 사용되지 않으며
잘못된 제공자와 detector 오류 정책은 실행 전에 거부한다.

파일 해시는 기존 SHA-256 문자열과 동일하다. 64 MiB 바이너리에서 기준 해시와 일치했고
`tracemalloc`로 관찰한 해시 계산 중 Python 할당 최고값은 1,054,105 bytes였다.
이는 해시 함수의 측정값이며 보고서 파싱을 포함한 전체 프로세스 메모리를 의미하지 않는다.

## 검증

검증은 Python 3.11.17에서 로컬 fixture와 저장 결과만 사용한다. 다음 회귀 검증을 포함한다.

| 최종 검증 | 결과 |
| --- | --- |
| 백엔드 회귀 테스트 | 145개 통과 |
| 프로젝트 회귀 테스트 | 239개 통과 |
| 1–3주차 데이터 검증 | 모두 통과 |
| 4주차 통합 검증 | 두 앱 × 6조건 × 3회 = 108회 실행, 로컬 HTTP 호출 207회 |
| 배치 재개 | 중복 모델 호출 0회 |
| API·CSV·패키지 | 원평가·연구 overlay 일치, 반복 export 동일, 원본 자료 유지 |
| 재현 과정 모델 호출 | 0회 |
| 변경 범위 확인 | frontend·data·contracts·configs·의존성 lock 변경 없음 |

검증 결과는 `runs/upgrade-20261025/verification-report.json`과
`runs/upgrade-20261025/week4/verification-report.json`에 보관한다.
macOS에서 검증했으며 Ubuntu/Windows 원격 CI는 실행하지 않았다.
구현과 원격 반영 상태는 관련 이슈 #50–#52에서 확인한다.

- 서로 다른 앱 인스턴스의 평가/gold 충돌, HTTP 409, 변경 없는 거부, 잠금 해제 후 재시도
- 평가와 target gold의 교차 갱신 및 기존 같은 서비스 동시 검토의 이력 보존
- 다른 프로세스의 실행 잠금 충돌 및 예외 후 재획득
- 실제 로컬 HTTP 서버의 5종 리다이렉트 미전달, 정확한 응답 크기 경계, 오류 시 정산 1회
- 비정상 endpoint/timeout/직접 설정, 응답 JSON·UTF-8·사용량 검증
- 빈 파일·바이너리·여러 청크 파일의 해시 일치 및 전체 파일 읽기 방지

실행 명령은 저장소 루트 기준이다.

```sh
(cd backend && ../.venv/bin/python -m unittest discover -s tests -q)
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m scripts.mvp check
.venv/bin/python -m scripts.week2_data check
.venv/bin/python -m scripts.week3_data check
.venv/bin/python -m scripts.verify_week4 --output runs/upgrade-20261025/week4
.venv/bin/python -m scripts.week4_package verify runs/upgrade-20261025/overlay
```

기존 배치의 실행 재개는 동결된 구현 해시를 검사하므로 백엔드 변경 후 새 배치를 생성한다.
기존 저장 결과의 조회·재현은 계속 지원한다. 실제 모델 품질 재평가, 사람의 독립 연구 검토,
holdout과 최종 추천에 대한 기존 이슈의 상태는 별도 근거가 필요한 사항으로 유지한다.
