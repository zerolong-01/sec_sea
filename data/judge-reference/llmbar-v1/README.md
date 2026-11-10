# 공개 사람 기준 세트: LLMBar

원본은 Princeton NLP의 [LLMBar 저장소](https://github.com/princeton-nlp/LLMBar),
고정 commit은 `900616bff90b6c6c8e1681f7d079250637c55992`다.
연구 설명은 [Evaluating Large Language Models at Evaluating Instruction Following](https://arxiv.org/abs/2310.07641)를 따른다.
저장소의 MIT [LICENSE](LICENSE)를 함께 보존했다.

`source/`에는 원본 다섯 subset 419쌍을 보존했다. 각 파일에 최종 LF 한 바이트만 추가했으며,
`provenance.json`의 Git blob SHA-1을 검증할 때 이 LF를 제거해 원본 바이트를 대조한다.
원본 label은 1/2 중 지시를 올바르게 수행한 응답을 가리킨다. 저자들이 검수한 공개 gold이며,
이 프로젝트에서 새로운 사람이 라벨링했다고 기록하지 않는다.

자동화 정책은 [judge-calibration-policy.v0.1.json](../../../configs/judge-calibration-policy.v0.1.json)이다.
동일한 지시문 hash가 개발·검산 양쪽에 들어가지 않도록 개발 20쌍과 검산 80쌍을 결정적으로 뽑는다.
[고정 선정 목록](selection.v0.1.json)에서 원본 subset·index와 지시문/행 hash를 확인할 수 있다.
[검산 기준 라벨 160개](validation-labels.v0.1.json)는 원래 label·응답 side·원본 row hash를 포함하며,
CI가 원본으로부터 다시 만든 라벨과 완전히 일치하는지 확인한다.
각 subset에서 개발 4쌍·검산 16쌍을 선택하므로 검산 결과는 균형 표본의 결과이며,
원래 419쌍 전체의 비례 추정값이 아니다.

우리 judge는 응답 하나씩 성공/실패를 평가하므로, 논문의 지시 이행 gold에 한해 선호 응답을 성공,
나머지를 실패로 대응한다. 이 대응은 `published_human_gold_adapter`로 명시한다.
원래 논문의 강제 양자 선택과 우리 pointwise 정확도·엄격 쌍 일치율은 서로 다른 프로토콜이다.
이 자료만으로 한국어 RAG/이메일·보호값 유출·과도한 거절의 사람 기준 검산을 완료 처리하지 않는다.

자세한 기준·실행·CI는 [검산 자동화 가이드](../../../docs/judge-calibration.md)를 참고한다.
