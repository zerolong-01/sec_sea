"""프론트엔드 비교 판정과 화면 검증 스크립트의 실패 처리 회귀 테스트 (#24, PR #30 리뷰)"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "frontend"))

import ui_core  # noqa: E402
import verify_ui  # noqa: E402

SAMPLES = ROOT / "docs" / "examples" / "week2"


def sample(name):
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))["response"]["trace"]


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class CompareVerdictTests(unittest.TestCase):
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
