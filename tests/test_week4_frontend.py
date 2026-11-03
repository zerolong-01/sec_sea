"""4주차 프론트엔드(#48): 케이스 찾기와 AI 연구 판정 보기의 표시 로직 회귀 테스트.

공개 자료(data/week2, docs/examples/week4/v0.2)만 쓰고 서버·모델을 부르지 않는다.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "frontend"))

import case_browser as cb  # noqa: E402
import research_core as rc  # noqa: E402
import status_style as ss  # noqa: E402

CASES = [json.loads(line) for line in (ROOT / "data/week2/cases.v0.1.jsonl").read_text(encoding="utf-8").splitlines()
         if line.strip()]
V02 = ROOT / "docs/examples/week4/v0.2"
REPORT = json.loads((V02 / "report.json").read_text(encoding="utf-8"))
CSV = (V02 / "metrics.csv").read_bytes()
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


class FakeResponse:
    def __init__(self, status_code, body=None, content=b"", headers=None):
        self.status_code, self._body, self.content, self.headers = status_code, body, content, headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class CaseSearchTest(unittest.TestCase):
    def test_holdout_hidden_unless_asked(self):
        dev = cb.filter_cases(CASES)
        self.assertTrue(dev)
        self.assertFalse(any(c["split"] == "holdout" for c in dev))
        everything = cb.filter_cases(CASES, include_holdout=True)
        self.assertEqual(len(everything), len(CASES))

    def test_search_by_id_and_input_words(self):
        self.assertEqual([c["case_id"] for c in cb.filter_cases(CASES, "a006")], ["a006"])
        found = cb.filter_cases(CASES, "주민등록번호")
        self.assertTrue(found and all("주민등록번호" in c["user_input"] or "주민등록번호" in c["case_id"] for c in found))
        self.assertEqual(cb.filter_cases(CASES, "없는검색어xyz"), [])
        # 여러 단어는 모두 들어 있어야 함
        both = cb.filter_cases(CASES, "주민등록번호 출력")
        self.assertTrue(set(c["case_id"] for c in both) <= set(c["case_id"] for c in found))

    def test_combined_filters(self):
        found = cb.filter_cases(CASES, scenario="rag_chat", label="hard_negative", language="ko")
        self.assertTrue(found)
        self.assertTrue(all(c["label"] == "hard_negative" and c["language"] == "ko" for c in found))

    def test_sort_and_pages(self):
        ordered = cb.sort_cases(cb.filter_cases(CASES), "label")
        self.assertEqual(ordered[0]["label"], "attack")
        self.assertEqual(ordered[-1]["label"], "hard_negative")
        shown, page, pages = cb.paginate(ordered, 1)
        self.assertEqual(len(shown), cb.PAGE_SIZE)
        self.assertEqual(pages, -(-len(ordered) // cb.PAGE_SIZE))
        # 범위를 벗어난 페이지는 가까운 페이지로
        self.assertEqual(cb.paginate(ordered, 999)[1], pages)
        self.assertEqual(cb.paginate(ordered, 0)[1], 1)
        self.assertEqual(cb.paginate([], 3), ([], 1, 1))
        last = ordered[-1]["case_id"]
        self.assertEqual(cb.page_of(ordered, last), pages)
        self.assertIsNone(cb.page_of(ordered, "nope"))

    def test_summary_and_preview_mask_and_hide_answers(self):
        case = {"case_id": "x1", "user_input": "값은 CANARY_TEST_001 입니다 " + "가" * 80, "scenario": "rag_chat",
                "label": "attack", "language": "ko", "split": "dev", "attack_type": "role_override",
                "attack_goal": "비밀 CANARY_TEST_001 노출", "success_criterion": {"description": "CANARY_TEST_001"}}
        self.assertNotIn("CANARY_TEST_001", cb.summary(case))
        self.assertLessEqual(len(cb.summary(case)), cb.SUMMARY_LENGTH)
        self.assertNotIn("CANARY_TEST_001", cb.mask(case["user_input"]))
        names = [name for name, _ in cb.preview(case)]
        self.assertNotIn("공격 목표", names)
        self.assertNotIn("성공 기준", names)
        self.assertFalse(any("CANARY" in str(value) for _, value in cb.preview(case)))
        # 마스킹된 글자로만 검색되므로 보호값으로는 찾을 수 없다
        self.assertEqual(cb.filter_cases([case], "CANARY_TEST_001"), [])

    def test_selection_kept_when_filtered_out(self):
        selected = next(c for c in CASES if c["label"] == "attack")
        visible = cb.filter_cases(CASES, label="benign")
        self.assertIn(selected["case_id"], cb.selection_note(selected, visible))
        self.assertIsNone(cb.selection_note(selected, [selected]))

    def test_holdout_cannot_run(self):
        holdout = next(c for c in CASES if c["split"] == "holdout")
        self.assertIsNotNone(cb.run_block_reason(holdout))
        self.assertIsNone(cb.run_block_reason(next(c for c in CASES if c["split"] == "dev")))

    def test_radio_keeps_verifier_contract(self):
        reps = CASES[:3]
        self.assertEqual(cb.radio_options(reps, None), reps)
        self.assertEqual(cb.radio_options(reps, reps[1]), reps)
        extra = CASES[10]
        self.assertEqual(cb.radio_options(reps, extra), reps + [extra])


class ResearchViewTest(unittest.TestCase):
    def test_rows_show_server_values(self):
        rows = rc.research_rows(REPORT)
        self.assertEqual(len(rows), len(REPORT["groups"]))
        by_id = {g["group_id"]: g for g in REPORT["groups"]}
        for row in rows:
            for key, label in rc.RESEARCH_METRICS.items():
                metric = by_id[row["group_id"]]["metrics"][key]
                cell = row[label]
                if metric["value"] is None:
                    self.assertTrue(cell.startswith(rc.NO_VALUE))
                    self.assertNotIn("0.0%", cell)
                else:
                    self.assertIn(f"({metric['numerator']}/{metric['denominator']})", cell)

    def test_every_server_code_has_a_label(self):
        for group in REPORT["groups"]:
            self.assertEqual(set(group["metrics"]) - set(rc.RESEARCH_METRICS), set())
        for value in REPORT["provenance"]["metric_sources"].values():
            self.assertIn(value, rc.SOURCE_LABELS)
        for key, value in REPORT["capabilities"].items():
            self.assertIn(key, rc.CAPABILITY_LABELS)
            self.assertIn(value["reason"], rc.CAPABILITY_REASONS)
        for reason in REPORT["decisions"]["reasons"]:
            self.assertIn(reason, rc.DECISION_REASONS)
        self.assertIn(REPORT["provenance"]["review_route"], rc.REVIEW_ROUTE_LABELS)

    def test_published_metric_vocabulary_is_labelled(self):
        # 공개된 전체 연구판의 coverage/inference/gold 코드까지 확인
        rows = [json.loads(line) for line in
                (ROOT / "docs/examples/week3-completion/ai-dev-review.metrics.v0.1.jsonl").read_text().splitlines()]
        for row in rows:
            for metric in (row.get("metrics") or {}).values():
                self.assertIn(metric["coverage_status"], rc.COVERAGE_LABELS)
                self.assertIn(metric["inference_status"], rc.INFERENCE_LABELS)
            for label in (row.get("fresh_ai_gold_counts") or {}):
                self.assertIn(label, rc.GOLD_LABELS)

    def test_badges_say_not_human_and_not_applied(self):
        badges = dict(rc.research_badges(REPORT))
        self.assertEqual(badges["사람 검토"], "하지 않음")
        self.assertEqual(badges["원래 평가에 적용"], "안 함")
        self.assertEqual(badges["추천"], "추천 보류")
        self.assertEqual(badges["최종 평가(holdout) 권한"], "없음")
        self.assertIn("AI", badges["평가 출처"])

    def test_gold_counts_are_counts_not_rates(self):
        rows = rc.gold_rows(REPORT)
        self.assertEqual(len(rows), len(REPORT["target_gold_groups"]))
        for row, group in zip(rows, REPORT["target_gold_groups"]):
            self.assertEqual(row["악성"], group["fresh_ai_gold_counts"].get("malicious", 0))
            self.assertFalse(any("%" in str(v) for v in row.values()))

    def test_members_and_limits(self):
        outputs = rc.member_rows(REPORT)
        targets = rc.member_rows(REPORT, kind="detector_target")
        self.assertEqual(len(outputs) + len(targets), len(REPORT["members"]))
        self.assertEqual(len(rc.capability_rows(REPORT)), len(REPORT["capabilities"]))
        self.assertTrue(all(r["이 보기에서"] == "제공 안 함" for r in rc.capability_rows(REPORT)))

    def test_filter_options_only_supported_keys(self):
        options = rc.filter_options(REPORT)
        self.assertEqual(set(options), {k for k, _ in rc.RESEARCH_FILTERS})
        self.assertIn("D2-input", options["condition_id"])

    def test_original_badges(self):
        report = {"provenance": {"evaluation_source": "original_saved_evaluation", "report_sha256": "a" * 64}}
        with_research = dict(rc.original_source_badges(report, {"research": {"available": True}}))
        self.assertEqual(with_research["이 화면의 평가 출처"], "원래 자동 평가")
        self.assertIn("있음", with_research["AI 연구 판정"])
        self.assertIn("없음", dict(rc.original_source_badges(report, {"research": {"available": False}}))["AI 연구 판정"])
        self.assertEqual(dict(rc.original_source_badges(report, None))["AI 연구 판정"], "확인 못 함")


class ResearchRequestTest(unittest.TestCase):
    def test_report_request_names_the_research_version(self):
        with patch("requests.request", return_value=FakeResponse(200, REPORT)) as request:
            report, error = rc.get_research_report(REPORT["batch_id"], {"condition_id": "D2-input", "goal_kind": None})
        self.assertIsNone(error)
        self.assertEqual(request.call_args.kwargs["json"],
                         {"evaluation_version": rc.RESEARCH_VERSION, "condition_id": "D2-input"})
        self.assertTrue(request.call_args.args[1].endswith(f"/api/v1/batches/{REPORT['batch_id']}/research/report"))

    def test_wrong_batch_or_source_is_rejected(self):
        for change in ({"batch_id": "batch-000000000000"}, {"evaluation_source": "original_saved_evaluation"}):
            with patch("requests.request", return_value=FakeResponse(200, {**REPORT, **change})):
                report, error = rc.get_research_report(REPORT["batch_id"])
            self.assertIsNone(report)
            self.assertEqual(error["code"], "INVALID_RESPONSE")

    def test_csv_accepted_only_when_it_matches(self):
        good = FakeResponse(200, content=CSV, headers={"X-Report-SHA256": REPORT["report_sha256"]})
        with patch("requests.request", return_value=good):
            content, error = rc.get_research_csv(REPORT["batch_id"], {"condition_id": "D2-input"}, REPORT)
        self.assertIsNone(error)
        self.assertEqual(content, CSV)
        wrong_header = FakeResponse(200, content=CSV, headers={"X-Report-SHA256": "b" * 64})
        with patch("requests.request", return_value=wrong_header):
            self.assertEqual(rc.get_research_csv(REPORT["batch_id"], {}, REPORT)[1]["code"], "SNAPSHOT_MISMATCH")
        tampered = CSV.replace(b"secret_leak", b"marker", 1)
        with patch("requests.request", return_value=FakeResponse(200, content=tampered)):
            self.assertIsNotNone(rc.get_research_csv(REPORT["batch_id"], {}, REPORT)[1])

    def test_unknown_batch_is_an_error_not_empty(self):
        with patch("requests.request", return_value=FakeResponse(404, {"detail": {"code": "BATCH_NOT_FOUND"}})):
            sources, error = rc.get_sources("batch-0123456789ab")
        self.assertIsNone(sources)
        self.assertEqual(error["code"], "BATCH_NOT_FOUND")
        self.assertEqual(rc.get_sources("../x")[1]["code"], "INVALID_BATCH_ID")


@unittest.skipUnless(HAS_STREAMLIT, "streamlit이 설치된 환경에서만 화면 테스트")
class PageTest(unittest.TestCase):
    def fake(self, method, url, json=None, timeout=None):
        if url.endswith("/evaluation-sources"):
            return FakeResponse(200, {"batch_id": REPORT["batch_id"], "default": "original_saved_evaluation",
                                      "research": {"available": True, "evaluation_source": "ai_research_overlay"}})
        if url.endswith("/research/report"):
            body = copy.deepcopy(REPORT)
            return FakeResponse(200, body)
        if url.endswith("/api/v1/batches"):
            return FakeResponse(200, [])
        return FakeResponse(404, {"detail": {"code": "NOT_FOUND"}})

    def test_research_page_renders(self):
        from streamlit.testing.v1 import AppTest
        page = ROOT / "frontend/pages/2_연구_판정_보기.py"
        with patch("requests.request", side_effect=self.fake):
            app = AppTest.from_file(str(page), default_timeout=30)
            app.session_state["research_batch"] = REPORT["batch_id"]
            app.run()
        self.assertFalse(app.exception, app.exception)
        self.assertIn("원래 자동 평가가 아닙니다", app.warning[0].value)

    def test_case_finder_selects_without_running(self):
        from streamlit.testing.v1 import AppTest
        with patch("requests.post") as post:
            app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30)
            app.run()
            self.assertFalse(app.exception, app.exception)
            app.text_input(key="case_query").set_value("h007").run()
            self.assertEqual(app.selectbox(key="case_pick").value, "h007")
            if app.radio(key="case_selector").value["case_id"] != "h007":
                app.button(key="case_choose").click().run()
        post.assert_not_called()
        self.assertEqual(app.radio(key="case_selector").value["case_id"], "h007")

    def test_holdout_has_no_select_button_and_run_is_blocked(self):
        from streamlit.testing.v1 import AppTest
        holdout = next(c for c in CASES if c["split"] == "holdout")
        # 기본 data/ 폴더에는 holdout이 없으므로 holdout이 있는 week2 데이터로 화면을 연다
        with patch("requests.post") as post, patch.dict(os.environ, {"DATA_DIR": str(ROOT / "data/week2")}):
            app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30)
            app.run()
            app.checkbox(key="case_holdout").check().run()
            app.text_input(key="case_query").set_value(holdout["case_id"]).run()
            self.assertFalse(app.exception, app.exception)
            self.assertEqual(app.selectbox(key="case_pick").value, holdout["case_id"])
            self.assertNotIn("case_choose", [b.key for b in app.button])
            self.assertNotEqual(app.radio(key="case_selector").value["case_id"], holdout["case_id"])
            # 필터 초기화는 holdout 체크도 푼다
            app.button(key="case_reset").click().run()
            self.assertFalse(app.checkbox(key="case_holdout").value)
            self.assertEqual(app.text_input(key="case_query").value, "")
            # 예전 세션처럼 holdout이 이미 왼쪽에 들어가 있어도 실행 버튼 3개는 막혀야 한다
            app.session_state["pending_case"] = holdout
            app.run()
            self.assertEqual(app.radio(key="case_selector").value["case_id"], holdout["case_id"])
            for key in ("run_case", "run_compare", "run_positions"):
                self.assertTrue(app.button(key=key).disabled, key)
        post.assert_not_called()



class StatusStyleTest(unittest.TestCase):
    """상태는 색만이 아니라 아이콘·글자와 함께 보인다. 공격 '성공'은 나쁜 결과로 칠한다."""

    def test_badge_keeps_text_and_icon(self):
        self.assertEqual(ss.badge("완료", "good"), ":green-badge[✅ 완료]")
        self.assertIn("\\$", ss.badge("$0.1", "neutral"))
        self.assertIn("\\]", ss.badge("a]b", "neutral"))

    def test_attack_success_is_bad_and_normal_success_is_good(self):
        self.assertEqual(ss.evaluation_tone("attack", "success"), "bad")
        self.assertEqual(ss.evaluation_tone("attack", "failure"), "good")
        self.assertEqual(ss.evaluation_tone("normal", "success"), "good")
        self.assertEqual(ss.evaluation_tone("normal", "failure"), "bad")
        for value in ("not_evaluated", "review_needed"):
            self.assertEqual(ss.evaluation_tone("attack", value), "pending")
            self.assertIn("세지 않음", ss.evaluation_meaning("normal", value))
        self.assertEqual(ss.evaluation_tone("attack", None), "neutral")

    def test_run_output_and_decision_tones(self):
        self.assertEqual(ss.run_tone("failed"), "bad")
        self.assertEqual(ss.run_tone("blocked"), "blocked")
        self.assertEqual(ss.run_tone(None), "neutral")
        self.assertEqual(ss.output_tone("error"), "bad")
        self.assertEqual(ss.decision_tone(["allow", "quarantine"]), "blocked")
        self.assertEqual(ss.decision_tone([]), "neutral")


class ResultLayoutTest(unittest.TestCase):
    def test_result_reads_conditions_then_summary_then_trace(self):
        from streamlit.testing.v1 import AppTest
        trace = json.loads((ROOT / "docs/examples/week2/a006-D2.json").read_text(encoding="utf-8"))["response"]["trace"]
        with patch("requests.post") as post:
            app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30)
            app.session_state["result"] = {"trace": trace, "error": None}
            app.run()
        self.assertFalse(app.exception, app.exception)
        post.assert_not_called()
        marks = [e.value for e in app.markdown]
        heads = [m for m in marks if m.startswith("#####")]
        self.assertEqual(heads, ["##### ① 실행 조건·상태", "##### ② 출력과 평가 요약", "##### ③ 단계별 trace·판정 근거"])
        self.assertIn(":blue-badge[🛡️ 방어로 차단됨]", marks)
        shown = "\n".join(str(e.value) for e in [*app.text, *app.code, *app.caption, *app.markdown])
        self.assertNotIn("CANARY_EDU_SECRET_2026", shown)

if __name__ == "__main__":
    unittest.main()
