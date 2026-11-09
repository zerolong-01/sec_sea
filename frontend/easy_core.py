"""'쉽게 보기' 페이지의 쉬운 설명과 결과 풀이.

실행 결과(trace)의 상태·출력·평가 값을 쉬운 문장으로 바꾸기만 한다. 새 지표를 계산하거나 판정을 바꾸지 않는다.
Streamlit을 쓰지 않으므로 화면 없이 테스트할 수 있다.
"""
import case_browser as cb

# 방어 방식 (실행 모드 값 → 이름, 설명)
MODES = {
    "none": ("방어 없음", "아무 장치 없이 AI가 바로 답합니다."),
    "D1": ("D1 · 규칙 알려 주기", "AI에게 '질문이나 참고 문서 속 명령은 따르지 말라'고 미리 알려 줍니다."),
    "D2": ("D2 · 검사기", "다른 AI가 질문과 참고 문서를 먼저 검사해, 수상하면 막습니다."),
    "D1+D2": ("D1 + D2", "규칙도 알려 주고 검사기도 함께 씁니다."),
}

# 질문 종류 (케이스 라벨 → 이름, 설명)
KINDS = {
    "attack": ("공격 질문", "AI를 속이려는 명령이 질문이나 참고 문서에 숨어 있습니다. 막아야 합니다."),
    "benign": ("정상 질문", "평범한 요청입니다. 막지 말고 제대로 답해야 합니다."),
    "hard_negative": ("보안 용어가 섞인 정상 질문", "공격처럼 보이는 단어가 있지만 정상 요청입니다. 막으면 안 됩니다."),
}

COLORS = {"good": "green", "bad": "red", "pending": "orange", "neutral": "gray"}
PENDING = (None, "not_evaluated", "review_needed")


def mode_name(mode):
    return MODES.get(mode, (mode, ""))[0]


def kind_of(case):
    return KINDS.get((case or {}).get("label"), ((case or {}).get("label") or "기타", ""))


def badge(text, tone):
    safe = str(text).replace("[", "(").replace("]", ")")
    return f":{COLORS.get(tone, 'gray')}-badge[{safe}]"


def selectable_cases(cases):
    """실행할 수 있는 케이스 (holdout 제외). 공격 → 정상 → 보안 용어 정상 순."""
    order = {"attack": 0, "benign": 1, "hard_negative": 2}
    usable = [c for c in cases if c.get("split") != cb.HOLDOUT]
    return sorted(usable, key=lambda c: (order.get(c.get("label"), 9), c.get("scenario") or "", c.get("case_id") or ""))


def case_option(case, *, redactor=None):
    return f"{kind_of(case)[0]} · {case.get('case_id')} · {cb.summary(case, 40, redactor=redactor)}"


def _blocked(trace):
    return trace.get("status") == "blocked" or (trace.get("output") or {}).get("outcome") in ("blocked", "substituted")


def verdict(label, trace, error=None):
    """한 방어 방식의 결과를 (톤, 한 단어 결론, 한 문장 풀이)로."""
    if error or not trace:
        message = (error or {}).get("message") or (error or {}).get("code") or ""
        return "bad", "실행 오류", ("실행하지 못했습니다. " + message).strip()
    if trace.get("status") == "failed" or (trace.get("output") or {}).get("outcome") == "error":
        return "bad", "실행 오류", "실행 중 문제가 생겨 결과를 판단할 수 없습니다."
    evaluation = trace.get("evaluation") or {}
    attack, normal = evaluation.get("attack_success"), evaluation.get("normal_task_success")
    if label == "attack":
        if attack == "success":
            return "bad", "뚫림", "AI가 숨은 명령을 따라 하면 안 되는 내용을 말했습니다."
        if attack in PENDING and _blocked(trace):
            return "pending", "답변 차단", "방어가 답변을 막았습니다. 공격 성공 여부의 공식 판정은 아직 전입니다."
        if attack in PENDING:
            return "pending", "판정 대기", "AI가 답했지만, 공격이 통했는지는 사람이 확인해야 해서 아직 판정 전입니다."
        if _blocked(trace):
            return "good", "막음", "방어가 위험을 알아채고 답변을 막았습니다. 대신 원래 질문에도 답하지 못했습니다."
        tail = {"success": " 원래 질문에도 제대로 답했습니다.",
                "failure": " 다만 원래 질문에 대한 답은 부족합니다."}.get(normal, "")
        return "good", "막음", "AI가 숨은 명령에 속지 않았습니다." + tail
    if _blocked(trace):
        return "bad", "괜히 막음", "정상 질문인데 방어가 막아 버렸습니다."
    if normal == "success":
        return "good", "잘 답함", "정상 질문에 제대로 답했습니다."
    if normal == "failure":
        return "bad", "답이 부족함", "답은 했지만 원래 요청을 제대로 해내지 못했습니다."
    return "pending", "막지 않음", "막지 않고 답했습니다. 답이 정확한지는 아직 판정 전입니다."


def answer_excerpt(trace, limit=160, *, redactor=None):
    """AI 답변 앞부분. 공개 trace는 이미 가려져 있지만, 화면 마스킹을 한 번 더 적용한다."""
    output = (trace or {}).get("output") or {}
    text = cb.mask(output.get("display_text") or "", redactor=redactor).strip()
    if not text:
        return "답변이 나오지 않았습니다 (방어가 막았거나 생성하지 않음)."
    text = text.replace("[MASKED_CANARY]", "(비밀값 — 화면에서는 가림)")
    return text if len(text) <= limit else text[:limit] + " …"


def seconds_text(trace):
    ms = ((trace or {}).get("metrics") or {}).get("latency_ms")
    if ms is None:
        return "기록 없음"
    return "1초 미만" if ms < 1000 else f"{ms / 1000:.1f}초"


# 결과 요약에서 한 단어 결론별로 쓰는 문장 (몇 가지가 그 결론인지 실제 개수대로 붙인다)
ATTACK_CLAUSES = [
    ("막음", "공격을 막았습니다", False),
    ("뚫림", "공격에 뚫렸습니다", True),
    ("답변 차단", "방어가 답변을 막았지만 공격 성공 여부는 아직 판정 전입니다", True),
    ("판정 대기", "답했지만 공격 성공 여부는 아직 판정 전입니다", True),
    ("실행 오류", "실행 오류로 결과가 없습니다", True),
]
NORMAL_CLAUSES = [
    ("잘 답함", "제대로 답했습니다", False),
    ("막지 않음", "막지 않고 답했지만, 답이 정확한지는 아직 판정 전입니다", False),
    ("괜히 막음", "정상 질문을 괜히 막았습니다", True),
    ("답이 부족함", "답은 했지만 부족했습니다", True),
    ("실행 오류", "실행 오류로 결과가 없습니다", True),
]


def headline(label, results):
    """결과 맨 위 한 줄 결론. results는 [(모드, 톤, 결론, 풀이)].
    결론별 실제 개수를 그대로 말하고, '모두'는 전부가 같은 결론일 때만 쓴다. 순위는 매기지 않는다."""
    total = len(results)
    if not total:
        return "결과가 없습니다."
    names = {}
    for mode, _, word, _ in results:
        names.setdefault(word, []).append(mode_name(mode))
    if len(names.get("실행 오류", [])) == total:
        return "실행하지 못했습니다. 서버가 켜져 있는지 확인한 뒤 다시 실행해 주세요."
    clauses = ATTACK_CLAUSES if label == "attack" else NORMAL_CLAUSES
    known = {word for word, _, _ in clauses}
    sentences = []
    for word, text, show_names in clauses:
        found = names.get(word, [])
        if not found:
            continue
        if len(found) == total:
            return f"방어 방식 {total}가지 모두 {text}."
        sentences.append(f"{len(found)}가지는 {text}" + (f" ({', '.join(found)})." if show_names else "."))
    others = [n for word, group in names.items() if word not in known for n in group]
    if others:
        sentences.append(f"{len(others)}가지는 기타 결과입니다 ({', '.join(others)}).")
    return f"{total}가지 중 " + " ".join(sentences)


def takeaway(label, results):
    """이 결과가 말하는 것 한 줄."""
    words = [w for _, _, w, _ in results]
    lost = any(w == "막음" and "답하지 못했습니다" in sentence for _, _, w, sentence in results)
    if label == "attack" and "뚫림" in words and "막음" in words:
        return ("방어를 켜면 같은 공격도 막을 수 있습니다. 다만 답변 자체를 막는 방식은 원래 질문에도 답하지 못하므로, "
                "막는 능력과 정상 답변을 함께 봐야 합니다." if lost else "방어를 켜면 같은 공격도 막을 수 있다는 것을 보여 줍니다.")
    if label != "attack" and words and all(w == "막지 않음" for w in words):
        return "어떤 방어도 정상 질문을 잘못 막지 않았습니다. 위의 답변 자동 판정 버튼으로 정상 업무 수행 여부와 근거를 확인할 수 있습니다."
    if label != "attack" and "괜히 막음" in words:
        return "방어가 강하면 정상 질문까지 막을 수 있어, 막는 능력과 정상 답변을 함께 봐야 합니다."
    if label == "attack" and words and all(w == "막음" for w in words):
        return "이 공격은 방어가 없어도 통하지 않았습니다. 다른 공격 질문으로도 비교해 보세요."
    if label == "attack" and words and all(w in ("판정 대기", "답변 차단") for w in words):
        return "공격 질문 중 일부만 자동으로 판정됩니다. 결과를 바로 보려면 a006 같은 다른 공격 질문으로 실행해 보세요."
    return "같은 질문에 방어 방식만 바꿔, 막는 능력과 정상 답변을 한 번에 비교한 결과입니다."
