"""프론트엔드 비교 판정과 화면 검증 스크립트의 실패 처리 회귀 테스트 (#24, PR #30 리뷰)"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "frontend"))

import ui_core  # noqa: E402
import verify_ui  # noqa: E402

SAMPLES = ROOT / "docs" / "examples" / "week2"


def sample(name):
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))["response"]["trace"]


def mode_sample(mode):
    trace = sample("h007-D1+D2" if mode == "D1+D2" else "a006-" + mode)
    trace["request"]["case_id"] = "a006"
    return trace


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class CompareVerdictTests(unittest.TestCase):
    def results(self):
        return [{"title": mode, "trace": mode_sample(mode), "error": None}
                for mode in ("none", "D1", "D2", "D1+D2")]

    def test_failed_running_and_trace_errors_are_unavailable(self):
        for status in ("failed", "running", "queued"):
            results = self.results()
            results[0]["trace"]["status"] = status
            self.assertEqual(ui_core.compare_verdict(results)[0], ui_core.COMPARE_UNAVAILABLE)
        results = self.results()
        results[0]["trace"]["error"] = {"code": "FAIL", "message": "failed"}
        self.assertEqual(ui_core.compare_verdict(results)[0], ui_core.COMPARE_UNAVAILABLE)

    def test_missing_conditions_do_not_count_as_equal(self):
        results = self.results()
        for item in results:
            item["trace"]["manifest"].pop("model_id")
        verdict, message, rows = ui_core.compare_verdict(results)
        self.assertEqual(verdict, ui_core.COMPARE_UNAVAILABLE)
        self.assertIn("생성 모델", message)
        self.assertEqual(next(row for row in rows if row["조건"] == "생성 모델")["같음"], "확인 불가")

    def test_modes_require_both_positions_and_all_modes(self):
        results = self.results()
        self.assertEqual(ui_core.compare_verdict(results, "modes")[0], ui_core.COMPARE_SAME)
        results[2]["trace"]["manifest"]["defense_position"] = "input"
        self.assertEqual(ui_core.compare_verdict(results, "modes")[0], ui_core.COMPARE_DIFFERENT)
        self.assertEqual(ui_core.compare_verdict(results[:2], "modes")[0], ui_core.COMPARE_UNAVAILABLE)

    def test_positions_require_d2_only_and_three_distinct_positions(self):
        results = [{"title": p, "trace": copy.deepcopy(sample("a006-D2")), "error": None}
                   for p in ("input", "retrieval", "input_retrieval")]
        for item in results:
            item["trace"]["manifest"]["defense_position"] = item["title"]
            item["trace"]["request"]["defense_position"] = item["title"]
        self.assertEqual(ui_core.compare_verdict(results, "positions")[0], ui_core.COMPARE_SAME)
        results[0]["trace"]["request"]["defense_mode"] = "D1+D2"
        self.assertEqual(ui_core.compare_verdict(results, "positions")[0], ui_core.COMPARE_UNAVAILABLE)

    def test_execution_kind_and_d1_version_are_comparison_conditions(self):
        for path, value in (("execution_kind", "detector_only"), ("defense_config_versions", {"D1": "different"})):
            results = self.results()
            results[1]["trace"]["manifest"][path] = value
            self.assertEqual(ui_core.compare_verdict(results)[0], ui_core.COMPARE_DIFFERENT)

    def test_requested_position_must_match_saved_position(self):
        results = self.results()
        results[2]["trace"]["request"]["defense_position"] = "input"
        verdict, message, _ = ui_core.compare_verdict(results, "modes")
        self.assertEqual(verdict, ui_core.COMPARE_DIFFERENT)
        self.assertIn("요청과 저장된", message)

    def test_all_connections_failed_is_unavailable(self):
        error = {"status": None, "code": None, "message": "연결 실패", "run_id": None}
        results = [{"title": mode, "trace": None, "error": error} for mode in ("none", "D1", "D2", "D1+D2")]
        verdict, message, rows = ui_core.compare_verdict(results)
        self.assertEqual(verdict, ui_core.COMPARE_UNAVAILABLE)
        self.assertIn("none", message)
        self.assertTrue(all(row["같음"] == "확인 불가" for row in rows))

    def test_partial_results_are_unavailable(self):
        results = [
            {"title": "무방어", "trace": sample("a006-none"), "error": None},
            {"title": "D1", "trace": None, "error": {"code": "CONNECTION"}},
        ]
        self.assertEqual(ui_core.compare_verdict(results)[0], ui_core.COMPARE_UNAVAILABLE)

    def test_single_result_is_unavailable(self):
        results = [{"title": "무방어", "trace": sample("a006-none"), "error": None}]
        self.assertEqual(ui_core.compare_verdict(results)[0], ui_core.COMPARE_UNAVAILABLE)

    def test_same_conditions(self):
        results = [{"title": name, "trace": sample(name), "error": None}
                   for name in ("a006-none", "a006-D1", "a006-D2")]
        self.assertEqual(ui_core.compare_verdict(results)[0], ui_core.COMPARE_SAME)

    def test_different_case_is_reported(self):
        results = [{"title": name, "trace": sample(name), "error": None}
                   for name in ("a006-none", "h007-D1+D2")]
        verdict, message, _ = ui_core.compare_verdict(results)
        self.assertEqual(verdict, ui_core.COMPARE_DIFFERENT)
        self.assertIn("케이스", message)


class SavedRunTests(unittest.TestCase):
    def test_lookup_uses_get_without_post(self):
        trace = sample("a006-none")
        with patch.object(ui_core.requests, "get", return_value=FakeResponse(200, trace)) as get, \
                patch.object(ui_core.requests, "post") as post:
            self.assertEqual(ui_core.load_run(trace["run_id"]), (trace, None))
            self.assertTrue(get.call_args.args[0].endswith(trace["run_id"]))
            post.assert_not_called()

    def test_invalid_ids_do_not_issue_requests(self):
        with patch.object(ui_core.requests, "get") as get:
            for run_id in ("", "../../raw.json", "run-a?raw=true"):
                self.assertEqual(ui_core.load_run(run_id)[1]["code"], "INVALID_RUN_ID")
            get.assert_not_called()

    def test_bad_json_and_non_object_payloads_are_errors(self):
        for body in ([], None, "gateway error", {"trace": None}):
            with patch.object(ui_core.requests, "post", return_value=FakeResponse(201, body)):
                trace, error = ui_core.run_case("a006", "rag_chat", "v1", "v1", "none")
                self.assertIsNone(trace)
                self.assertEqual(error["code"], "INVALID_RESPONSE")
        response = FakeResponse(502, None)
        with patch.object(response, "json", side_effect=ValueError), \
                patch.object(ui_core.requests, "get", return_value=response):
            self.assertEqual(ui_core.load_run("run-abc")[1]["code"], "INVALID_RESPONSE")

    def test_lookup_connection_not_found_and_mismatched_id(self):
        with patch.object(ui_core.requests, "get", side_effect=requests.ConnectionError):
            self.assertEqual(ui_core.load_run("run-abc")[1]["code"], "CONNECTION_ERROR")
        with patch.object(ui_core.requests, "get", return_value=FakeResponse(404, {"detail": {"code": "ARTIFACT_NOT_FOUND"}})):
            error = ui_core.load_run("run-abc")[1]
            self.assertEqual(error["run_id"], "run-abc")
            self.assertEqual(error["code"], "ARTIFACT_NOT_FOUND")
        with patch.object(ui_core.requests, "get", return_value=FakeResponse(200, sample("a006-none"))):
            self.assertEqual(ui_core.load_run("run-abc")[1]["code"], "INVALID_RESPONSE")


class ScreenTests(unittest.TestCase):
    def app(self):
        app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=15).run()
        self.assertFalse(app.exception)
        return app

    def test_lookup_and_refresh_show_updated_evaluation_without_post(self):
        trace = sample("a006-none")
        with patch.object(ui_core.requests, "get", return_value=FakeResponse(200, trace)) as get, \
                patch.object(ui_core.requests, "post") as post:
            app = self.app()
            app.text_input(key="stored_run_id").set_value(trace["run_id"])
            app.button(key="load_run").click().run()
            self.assertFalse(app.exception)
            updated = copy.deepcopy(trace)
            updated["evaluation"]["normal_task_success"] = "review_needed"
            get.return_value = FakeResponse(200, updated)
            app.button(key="refresh_run").click().run()
            self.assertEqual(app.session_state["result"]["trace"], updated)
            self.assertIn("검토 필요", [e.value for e in app.text])
            post.assert_not_called()
            get.return_value = FakeResponse(404, {"detail": {"code": "ARTIFACT_NOT_FOUND"}})
            app.text_input(key="stored_run_id").set_value("run-missing")
            app.button(key="load_run").click().run()
            self.assertTrue(app.error)
            self.assertEqual(app.session_state["result"]["trace"], updated)

    def test_partial_trace_and_unknown_usage_do_not_invent_zero_counts(self):
        app = self.app()
        trace = {"run_id": "run-partial", "request": {"case_id": "a006"},
                 "model_calls": [{"messages": [{}]}], "metrics": {"stages": [{}]},
                 "retrieval": [{"document_id": "doc006"}], "detector_evaluation": [{}]}
        app.session_state["result"] = {"trace": trace, "error": None}
        app.run()
        self.assertFalse(app.exception)
        shown = "\n".join(str(e.value) for e in [*app.text, *app.caption])
        self.assertIn("생성 호출 기록 없음 · 탐지 호출 기록 없음", shown)
        self.assertIn("실행 종류: 기록 없음", shown)
        self.assertIn("미확인", shown)
        self.assertIn("기록 없음", app.dataframe[0].value["프롬프트 포함"].tolist())

    def test_status_samples_render_masked_and_keep_evaluation_separate(self):
        app = self.app()
        for name in ("a006-D2", "detector-failed", "usage-unknown", "review-needed"):
            trace = sample(name)
            app.session_state["result"] = {"trace": trace, "error": None}
            app.run()
            self.assertFalse(app.exception, name)
            self.assertIn(ui_core.label_of("run_statuses", trace["status"]), [e.value for e in app.text])
            shown = "\n".join(str(e.value) for e in [*app.text, *app.code, *app.caption])
            self.assertNotIn("CANARY_EDU_SECRET_2026", shown)
            if trace.get("error"):
                self.assertTrue(any(trace["error"]["code"] in e.value for e in app.error))

    def test_mode_compare_fixed_position_refresh_and_failed_trace(self):
        def execute(case_id, scenario, dataset, corpus, mode, position):
            self.assertEqual(position, ui_core.BOTH)
            return mode_sample(mode), None

        with patch.object(ui_core, "run_case", side_effect=execute) as run:
            app = self.app()
            app.button(key="run_compare").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(run.call_count, 4)
        traces = {item["trace"]["run_id"]: item["trace"] for item in app.session_state["compare"]["results"]}
        with patch.object(ui_core.requests, "get", side_effect=lambda url, **kw: FakeResponse(200, traces[url.rsplit("/", 1)[1]])) as get, \
                patch.object(ui_core.requests, "post") as post:
            app.button(key="refresh_compare").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(get.call_count, 4)
            post.assert_not_called()
        app.session_state["compare"]["results"][0]["trace"]["evaluation"]["normal_task_success"] = "not_evaluated"
        app.run()
        self.assertTrue(any("미평가" in e.value for e in app.warning))
        app.session_state["compare"]["results"][0]["trace"]["error"] = {"code": "SAVED_FAILURE", "message": "failed"}
        app.run()
        self.assertTrue(any(ui_core.COMPARE_UNAVAILABLE in e.value for e in app.error))
        self.assertTrue(any("SAVED_FAILURE" in e.value for e in app.error))


class CheckRunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.runs = Path(temp.name)

    def check(self, trace, mode, position="input_retrieval"):
        (self.runs / f"{trace['run_id']}.trace.json").write_text(json.dumps(trace), encoding="utf-8")
        with patch.object(verify_ui.requests, "get", return_value=FakeResponse(200, trace)):
            problems, _ = verify_ui.check_run(trace, None, mode, position, self.runs)
        return problems

    def test_detector_failure_is_a_problem(self):
        trace = sample("detector-failed")
        self.assertEqual(trace["status"], "failed")
        problems = self.check(trace, "D2", trace["manifest"]["defense_position"])
        self.assertTrue(any("failed" in item for item in problems), problems)

    def test_defense_block_is_not_a_problem(self):
        trace = sample("a006-D2")
        self.assertEqual(trace["status"], "blocked")
        self.assertEqual(self.check(trace, "D2"), [])

    def test_completed_run_passes(self):
        self.assertEqual(self.check(sample("a006-none"), "none"), [])

    def test_trace_error_on_finished_run_is_a_problem(self):
        trace = copy.deepcopy(sample("a006-none"))
        trace["error"] = {"code": "UNEXPECTED", "message": "test"}
        self.assertTrue(any("trace 오류" in item for item in self.check(trace, "none")))

    def test_missing_trace_is_a_problem(self):
        problems, row = verify_ui.check_run(None, {"code": None}, "D1", "input_retrieval", self.runs)
        self.assertTrue(problems)
        self.assertEqual(row["방어 모드"], "D1")

    def test_get_disconnect_and_corrupt_saved_trace_are_reported(self):
        trace = sample("a006-none")
        (self.runs / f"{trace['run_id']}.trace.json").write_text("broken", encoding="utf-8")
        with patch.object(verify_ui.requests, "get", side_effect=requests.ConnectionError):
            problems, _ = verify_ui.check_run(trace, None, "none", ui_core.BOTH, self.runs)
        self.assertTrue(any("GET 조회 실패" in item for item in problems))
        self.assertTrue(any("파일을 읽을 수 없음" in item for item in problems))

    def test_non_summary_trace_differences_are_detected(self):
        trace = sample("a006-none")
        saved = copy.deepcopy(trace)
        saved["prompt_assembly"][0]["display_text"] = "different prompt"
        (self.runs / f"{trace['run_id']}.trace.json").write_text(json.dumps(saved), encoding="utf-8")
        with patch.object(verify_ui.requests, "get", return_value=FakeResponse(200, saved)):
            problems, _ = verify_ui.check_run(trace, None, "none", ui_core.BOTH, self.runs)
        self.assertTrue(any("GET 값이 다름" in item for item in problems))
        self.assertTrue(any("저장 파일 값이 다름" in item for item in problems))


class VerifyMainTests(unittest.TestCase):
    """서버가 failed trace를 돌려주거나 연결이 모두 실패하면 종료 코드가 1이어야 한다."""

    def run_main(self, fake_run_case):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        runs = Path(temp.name) / "runs"
        runs.mkdir()
        out = Path(temp.name) / "report.md"
        store = {}

        def fake_get(url, timeout=0):
            if url.endswith("/health"):
                return FakeResponse(200, {"schema_version": "0.3", "model_provider": "test"})
            return FakeResponse(200, store[url.rsplit("/", 1)[1]])

        def recording_run_case(*args):
            trace, error = fake_run_case(*args)
            if trace:
                store[trace["run_id"]] = trace
                (runs / f"{trace['run_id']}.trace.json").write_text(json.dumps(trace), encoding="utf-8")
            return trace, error

        argv = ["verify_ui.py", "--runs-dir", str(runs), "--out", str(out)]
        with patch.object(verify_ui, "run_case", recording_run_case), \
                patch.object(verify_ui.requests, "get", fake_get), patch.object(sys, "argv", argv):
            code = verify_ui.main()
        return code, out.read_text(encoding="utf-8")

    @staticmethod
    def trace_for(case_id, mode, position, base):
        trace = copy.deepcopy(sample(base))
        trace["run_id"] = f"run-{case_id}-{mode}-{position}".replace("+", "_")
        trace["request"]["case_id"] = case_id
        trace["request"]["defense_mode"] = mode
        trace["manifest"]["defense_position"] = position
        return trace

    def test_failed_detector_run_fails_verification(self):
        bases = {"none": "a006-none", "D1": "a006-D1", "D2": "detector-failed", "D1+D2": "h007-D1+D2"}

        def fake(case_id, scenario, dataset, corpus, mode, position):
            trace = self.trace_for(case_id, mode, position, bases[mode])
            if mode == "D1+D2":
                trace["manifest"]["d2_configuration"] = sample("detector-failed")["manifest"]["d2_configuration"]
            return trace, None

        code, report = self.run_main(fake)
        self.assertEqual(code, 1)
        self.assertIn("실행 오류(failed)", report)
        self.assertNotIn("전체 통과", report)

    def test_all_connections_failed_fails_verification(self):
        def fake(*args):
            return None, {"status": None, "code": None, "message": "연결 실패", "run_id": None}

        code, report = self.run_main(fake)
        self.assertEqual(code, 1)
        self.assertIn(ui_core.COMPARE_UNAVAILABLE, report)


if __name__ == "__main__":
    unittest.main()
