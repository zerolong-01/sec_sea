"""첫 페이지의 케이스 찾기(검색·필터·정렬·페이지)와 미리보기 (#48).

Streamlit을 쓰지 않으므로 화면 없이 테스트할 수 있다.
여기 있는 함수는 모두 읽기 전용이라 모델이나 서버를 부르지 않는다.
"""
import re

from ui_core import NO_VALUE, label_of

PAGE_SIZE = 10
SUMMARY_LENGTH = 48
CANARY_PATTERN = re.compile(r"CANARY_[A-Z0-9_]+")  # backend/app/privacy.py와 같은 공개 마스킹 규칙
HOLDOUT = "holdout"

SORT_OPTIONS = {
    "case_id": "케이스 ID 순",
    "label": "라벨 순",
    "scenario": "앱 순",
}
LABEL_ORDER = {"attack": 0, "benign": 1, "hard_negative": 2}

ATTACK_TYPE_LABELS = {
    "direct_instruction": "직접 지시",
    "indirect_document": "문서 속 간접 지시",
    "role_override": "역할 바꾸기",
    "encoding_obfuscation": "인코딩·난독화",
    "data_exfiltration": "데이터 유출",
    "other": "기타",
}


def mask(text):
    """미리보기·목록에 보이는 글자에서 합성 보호값(CANARY_...)을 가린다."""
    return CANARY_PATTERN.sub("[MASKED_CANARY]", str(text or ""))


def summary(case, length=SUMMARY_LENGTH):
    """목록에 보일 짧은 입력 요약 (마스킹 후 자름)."""
    text = " ".join(mask(case.get("user_input")).split())
    return text if len(text) <= length else text[:length - 1] + "…"


def matches(case, query):
    """검색어가 케이스 ID나 입력 내용(마스킹된 글자 기준)에 있으면 True. 대소문자 무시."""
    words = [w for w in str(query or "").lower().split() if w]
    if not words:
        return True
    haystack = " ".join([case.get("case_id", ""), mask(case.get("user_input")),
                         ATTACK_TYPE_LABELS.get(case.get("attack_type"), "")]).lower()
    return all(word in haystack for word in words)


def filter_cases(cases, query="", scenario=None, label=None, language=None, include_holdout=False):
    """조건에 맞는 케이스만 남긴다. None은 '전체'. holdout은 따로 켜야 보인다."""
    result = []
    for case in cases:
        if case.get("split") == HOLDOUT and not include_holdout:
            continue
        if scenario and case.get("scenario") != scenario:
            continue
        if label and case.get("label") != label:
            continue
        if language and case.get("language") != language:
            continue
        if not matches(case, query):
            continue
        result.append(case)
    return result


def sort_cases(cases, key="case_id"):
    if key == "label":
        return sorted(cases, key=lambda c: (LABEL_ORDER.get(c.get("label"), 9), c.get("case_id", "")))
    if key == "scenario":
        return sorted(cases, key=lambda c: (c.get("scenario", ""), c.get("case_id", "")))
    return sorted(cases, key=lambda c: c.get("case_id", ""))


def page_count(total, size=PAGE_SIZE):
    return max(1, -(-total // size))


def paginate(items, page, size=PAGE_SIZE):
    """(이 페이지 항목, 실제 페이지 번호 1부터, 전체 페이지 수). 범위를 벗어나면 가까운 페이지로."""
    pages = page_count(len(items), size)
    page = min(max(1, int(page or 1)), pages)
    start = (page - 1) * size
    return items[start:start + size], page, pages


def page_of(items, case_id, size=PAGE_SIZE):
    """목록에서 case_id가 있는 페이지 번호. 없으면 None."""
    for index, case in enumerate(items):
        if case.get("case_id") == case_id:
            return index // size + 1
    return None


def option_values(cases, key):
    return sorted({c.get(key) for c in cases if c.get(key)})


def row(case, selected_id=None):
    """목록 표 한 줄."""
    return {
        "선택": "▶" if case.get("case_id") == selected_id else "",
        "케이스 ID": case.get("case_id"),
        "입력 요약": summary(case),
        "앱": label_of("scenarios", case.get("scenario")),
        "라벨": label_of("case_labels", case.get("label")),
        "언어": label_of("languages", case.get("language")),
        "구분": label_of("splits", case.get("split")),
    }


def preview(case):
    """선택한 케이스 미리보기. 판정 정답·목표값이 들어 있을 수 있는 칸(성공 기준, 공격 목표)은 넣지 않는다."""
    return [
        ("케이스 ID", case.get("case_id") or NO_VALUE),
        ("앱", label_of("scenarios", case.get("scenario"))),
        ("라벨", label_of("case_labels", case.get("label"))),
        ("언어", label_of("languages", case.get("language"))),
        ("데이터 구분", label_of("splits", case.get("split"))),
        ("공격 유형", ATTACK_TYPE_LABELS.get(case.get("attack_type"), case.get("attack_type") or "해당 없음")),
        ("참조 문서", ", ".join(case.get("source_document_ids") or []) or NO_VALUE),
        ("데이터 버전", case.get("source_version") or NO_VALUE),
    ]


def case_text(case):
    return " · ".join([case["case_id"], label_of("case_labels", case.get("label")),
                       label_of("scenarios", case.get("scenario")), label_of("languages", case.get("language"))])


def selection_note(selected, visible):
    """선택한 케이스가 지금 필터 결과에 없을 때 알려 줄 문구. 있으면 None."""
    if selected is None:
        return None
    if any(c.get("case_id") == selected.get("case_id") for c in visible):
        return None
    return (f"선택한 케이스 {selected.get('case_id')}는 지금 검색·필터 결과에 없습니다. "
            "선택은 그대로 유지되며, 실행하면 이 케이스로 실행됩니다.")


def run_block_reason(case):
    """실행 버튼을 막아야 하면 이유를, 아니면 None.
    holdout은 #43·#45 결정에 따라 최종 평가 전까지 실행하지 않고 보존한다."""
    if case and case.get("split") == HOLDOUT:
        return "최종 평가용(holdout) 케이스는 팀 결정(#43·#45)에 따라 실행하지 않고 보존합니다."
    return None


def radio_options(representatives, selected):
    """사이드바 'case_selector' 라디오의 선택지. 대표 케이스 + (대표가 아닌 선택 케이스).
    기존 검증 스크립트가 이 라디오에 케이스 dict를 넣어 선택하므로 형식을 유지한다."""
    options = list(representatives)
    if selected and all(o.get("case_id") != selected.get("case_id") for o in options):
        options.append(selected)
    return options
