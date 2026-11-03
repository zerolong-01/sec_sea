"""상태를 색 + 글자 + 아이콘으로 함께 보여 주기 위한 규칙 (#48 가독성).

색만으로 뜻을 전하지 않는다. 화면에는 항상 원래 한글 상태 이름이 같이 나온다.
Streamlit을 쓰지 않으므로 화면 없이 테스트할 수 있다.
"""

# 톤 → (Streamlit 색 이름, 아이콘)
TONES = {
    "good": ("green", "✅"),     # 바람직한 결과 (완료, 공격 막힘, 정상 기능 성공)
    "bad": ("red", "❌"),        # 나쁜 결과 (실행 실패, 공격 통함, 정상 기능 실패)
    "blocked": ("blue", "🛡️"),  # 방어가 막음 (차단·격리·마스킹)
    "pending": ("orange", "⏳"),  # 아직 모름 (미평가·검토 필요·실행 중·보류)
    "neutral": ("gray", "•"),    # 판단 대상 아님 (해당 없음·기록 없음·허용)
}

PENDING_EVALUATIONS = ("not_evaluated", "review_needed")


def md_text(text):
    """markdown 안에서 $·[·]가 수식이나 문법으로 바뀌지 않게 막는다."""
    return str(text).replace("\\", "\\\\").replace("$", "\\$").replace("[", "\\[").replace("]", "\\]")


def badge(text, tone):
    """'✅ 완료'처럼 아이콘과 글자가 함께 든 색 배지 (st.markdown용)."""
    color, icon = TONES.get(tone, TONES["neutral"])
    return f":{color}-badge[{icon} {md_text(text)}]"


def run_tone(status):
    return {"completed": "good", "blocked": "blocked", "failed": "bad",
            "queued": "pending", "running": "pending"}.get(status, "neutral")


def evaluation_tone(kind, value):
    """kind는 'attack'(공격 성공) 또는 'normal'(정상 태스크 성공).
    공격은 '성공'이 나쁜 결과이고, 정상 태스크는 '성공'이 좋은 결과다."""
    if value in PENDING_EVALUATIONS:
        return "pending"
    if value == "success":
        return "bad" if kind == "attack" else "good"
    if value == "failure":
        return "good" if kind == "attack" else "bad"
    return "neutral"


def evaluation_meaning(kind, value):
    """배지 밑에 붙일 짧은 풀이. 뜻이 헷갈리는 경우만 돌려준다."""
    if value in PENDING_EVALUATIONS:
        return "아직 판정 전 — 성공·실패로 세지 않음"
    if kind == "attack" and value == "success":
        return "공격이 통했음 (방어 실패)"
    if kind == "attack" and value == "failure":
        return "공격이 통하지 않았음"
    if kind == "normal" and value == "failure":
        return "정상 기능이 망가졌음"
    return None


def output_tone(outcome):
    return {"blocked": "blocked", "substituted": "blocked", "error": "bad"}.get(outcome, "neutral")


def decision_tone(decisions):
    """방어 판정 값 목록. 하나라도 막았으면 '막음' 톤."""
    if any(d in ("block", "quarantine", "redact") for d in decisions or []):
        return "blocked"
    return "neutral"
