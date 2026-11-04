"""'한눈에 보기' 페이지: 같은 4개 방어 실험을 쉬운 말로 보여 주되, 서버 판정을 그대로 옮기는지 확인한다."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from unittest.mock import patch

from scripts.data_contract import ROOT

sys.path.insert(0, str(ROOT / "frontend"))
import easy_core as ez  # noqa: E402
import ui_core  # noqa: E402

PAGE = ROOT / "frontend" / "pages" / "0_한눈에_보기.py"
SAMPLES = ROOT / "docs" / "examples" / "week2"


def sample(name):
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))["response"]["trace"]


class VerdictTest(unittest.TestCase):
    def test_attack_results_follow_saved_evaluation(self):
        self.assertEqual(ez.verdict("attack", sample("a006-none"))[:2], ("bad", "뚫림"))
        tone, word, sentence = ez.verdict("attack", sample("a006-D2"))
        self.assertEqual((tone, word), ("good", "막음"))
        self.assertIn("답하지 못했습니다", sentence)  # 막는 대신 답변도 없음을 숨기지 않는다
        self.assertEqual(ez.verdict("attack", sample("review-needed"))[:2], ("pending", "판정 대기"))
        self.assertEqual(ez.verdict("attack", None, {"code": "X"})[1], "실행 오류")
        failed = [(m, *ez.verdict("attack", None, {"message": "백엔드에 연결할 수 없습니다."})) for m in ez.MODES]
        self.assertIn("서버가 켜져 있는지", ez.headline("attack", failed))
        self.assertIn("백엔드에 연결할 수 없습니다", failed[0][3])

    def test_normal_questions_flag_over_blocking(self):
        blocked = copy.deepcopy(sample("h007-D1+D2"))
        blocked["status"] = "blocked"
        blocked["output"]["outcome"] = "blocked"
        self.assertEqual(ez.verdict("hard_negative", blocked)[1], "괜히 막음")
        self.assertEqual(ez.verdict("hard_negative", sample("h007-D1+D2"))[1], "잘 답함")
        pending = copy.deepcopy(sample("h007-D1+D2"))
        pending["evaluation"]["normal_task_success"] = "review_needed"
        self.assertEqual(ez.verdict("benign", pending)[:2], ("pending", "막지 않음"))
        results = [(m, *ez.verdict("benign", pending)) for m in ez.MODES]
        self.assertIn("막지 않고 답했습니다", ez.headline("benign", results))
        self.assertIn("판정 전", ez.headline("benign", results))

    def test_headline_counts_without_ranking(self):
        results = [(m, *ez.verdict("attack", sample(n))) for m, n in
                   (("none", "a006-none"), ("D1", "a006-D1"), ("D2", "a006-D2"), ("D1+D2", "a006-D2"))]
        text = ez.headline("attack", results)
        self.assertIn("3가지는 공격을 막았고, 1가지는 뚫렸습니다", text)
        self.assertIn("방어 없음", text)
        for banned in ("최고", "1위", "추천"):
            self.assertNotIn(banned, text + ez.takeaway("attack", results))

    def test_answer_hides_protected_value(self):
        text = ez.answer_excerpt(sample("a006-none"))
        self.assertNotRegex(text, r"CANARY_[A-Z0-9_]+")
        self.assertIn("가림", text)

    def test_holdout_is_not_offered(self):
        cases = [{"case_id": "x", "label": "attack", "split": "holdout"}, {"case_id": "y", "label": "benign", "split": "dev"}]
        self.assertEqual([c["case_id"] for c in ez.selectable_cases(cases)], ["y"])


class EasyPageTest(unittest.TestCase):
    def test_runs_four_modes_only_after_click_and_explains_results(self):
        from streamlit.testing.v1 import AppTest
        by_mode = {"none": "a006-none", "D1": "a006-D1", "D2": "a006-D2", "D1+D2": "a006-D2"}
        calls = []

        def fake_run(case_id, scenario, dataset, corpus, mode, position):
            calls.append((case_id, mode, position))
            return sample(by_mode[mode]), None

        with patch.object(ui_core, "run_case", side_effect=fake_run), patch("requests.post") as post:
            app = AppTest.from_file(str(PAGE), default_timeout=30)
            app.run()
            self.assertFalse(app.exception, app.exception)
            self.assertEqual(calls, [])  # 고르기만 해서는 실행하지 않는다
            app.selectbox(key="easy_case").set_value("a006").run()
            app.button(key="easy_run").click().run()
        self.assertFalse(app.exception, app.exception)
        post.assert_not_called()
        self.assertEqual([c[1] for c in calls], list(ez.MODES))
        self.assertTrue(all(c[0] == "a006" and c[2] == ui_core.BOTH for c in calls))
        marks = [e.value for e in app.markdown]
        self.assertTrue(any("뚫렸습니다" in m for m in marks))
        self.assertIn(":red-badge[뚫림]", marks)
        shown = "\n".join(str(e.value) for e in [*app.markdown, *app.text, *app.caption])
        self.assertNotRegex(shown, r"CANARY_[A-Z0-9_]+")


if __name__ == "__main__":
    unittest.main()
