"""배치 대시보드 선택 상태와 내보내기 스냅샷의 회귀 테스트.

공개 fixture와 읽기 전용 HTTP 모형만 사용한다. 모델 API는 호출하지 않는다.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.batch_analysis import REPORT_VERSION, report_csv
from backend.app.batch_models import BatchReport

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "frontend"))
SAMPLES = ROOT / "docs" / "examples" / "week3"
PAGE = ROOT / "frontend" / "pages" / "1_배치_대시보드.py"
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None
SUMMARY = json.loads((SAMPLES / "batch-summary.fixture.json").read_text(encoding="utf-8"))
REPORT = json.loads((SAMPLES / "report.fixture.json").read_text(encoding="utf-8"))
BATCH_ID = SUMMARY["batch_id"]
OTHER_BATCH_ID = "batch-aaaaaaaaaaaa"


class Response:
    status_code = 200

    def __init__(self, body=None, content=b""):
        self.body = body
        self.content = content

    def json(self):
        return copy.deepcopy(self.body)


class SavedBatchServer:
    """저장된 결과의 조회·집계·CSV만 제공하며 실행 요청은 거부한다."""

    def __init__(self):
        other_summary = json.loads(json.dumps(SUMMARY).replace(BATCH_ID[6:], OTHER_BATCH_ID[6:]))
        other_summary["created_at"] = "2000-01-01T00:00:00+00:00"
        other_report = json.loads(json.dumps(REPORT).replace(BATCH_ID[6:], OTHER_BATCH_ID[6:]))
        self.summaries = {BATCH_ID: copy.deepcopy(SUMMARY), OTHER_BATCH_ID: other_summary}
        self.reports = {BATCH_ID: copy.deepcopy(REPORT), OTHER_BATCH_ID: other_report}
        # 과거 공개 fixture는 보존하고 모형 API만 현재 CSV 계약으로 만든다.
        # 이 해시는 테스트용 metadata이며 실제 계산·실험 증거가 아니다.
        for report in self.reports.values():
            report["report_version"] = REPORT_VERSION
            report["provenance"]["calculation_implementation_sha256"] = "a" * 64
        self.csv_snapshot = None
        self.calls = []

    def __call__(self, method, url, json=None, timeout=None):
        self.calls.append((method, url, copy.deepcopy(json)))
        if method == "GET" and url.endswith("/api/v1/batches"):
            return Response(list(self.summaries.values()))
        for batch_id in self.summaries:
            if method == "GET" and url.endswith(f"/api/v1/batches/{batch_id}"):
                return Response(self.summaries[batch_id])
            if method == "POST" and url.endswith(f"/api/v1/batches/{batch_id}/report"):
                report = copy.deepcopy(self.reports[batch_id])
                report["filters"] = json or {}
                return Response(report)
            if method == "POST" and url.endswith(f"/api/v1/batches/{batch_id}/export.csv"):
                report = copy.deepcopy(self.reports[batch_id])
                report["filters"] = json or {}
                if self.csv_snapshot is not None:
                    report["evaluation_snapshot_sha256"] = self.csv_snapshot
                content = report_csv(BatchReport.model_validate(report)).encode("utf-8")
                return Response(content=content)
        raise AssertionError(f"허용되지 않은 요청: {method} {url}")


@unittest.skipUnless(HAS_STREAMLIT, "streamlit이 설치된 환경에서만 화면 테스트를 실행")
class BatchDashboardStateTest(unittest.TestCase):
    def setUp(self):
        self.server = SavedBatchServer()
        request_patch = patch("requests.request", side_effect=self.server)
        self.request = request_patch.start()
        self.addCleanup(request_patch.stop)
        self.loaded_runs = []
        trace_patch = patch("ui_core.load_run", side_effect=self.load_trace)
        trace_patch.start()
        self.addCleanup(trace_patch.stop)

    def load_trace(self, run_id):
        self.loaded_runs.append(run_id)
        return {
            "run_id": run_id,
            "status": "completed",
            "request": {"case_id": "synthetic-loaded-case"},
            "evaluation": {"attack_success": "success"},
            "output": {"display_text": f"TRACE_OUTPUT_{run_id}"},
        }, None

    def page(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(PAGE), default_timeout=30).run()
        self.assertFalse(app.exception, app.exception)
        return app

    def load_selected_trace(self, app):
        selected = app.selectbox(key="trace_run").value
        app.button(key="load_trace").click().run()
        self.assertFalse(app.exception, app.exception)
        self.assertIn(f"TRACE_OUTPUT_{selected}", [code.value for code in app.code])
        return selected

    def assert_trace_hidden_without_another_lookup(self, app, previous_run):
        self.assertFalse(app.exception, app.exception)
        self.assertNotIn(f"TRACE_OUTPUT_{previous_run}", [code.value for code in app.code])
        self.assertEqual(self.loaded_runs, [previous_run])

    @staticmethod
    def csv_downloads(app):
        return [element for element in app.get("download_button")
                if element.proto.label == "지표 CSV 내려받기"]

    def test_run_change_hides_previously_loaded_trace(self):
        app = self.page()
        previous = self.load_selected_trace(app)
        other = next(run_id for run_id in app.selectbox(key="trace_run").options if run_id != previous)
        app.selectbox(key="trace_run").select(other).run()
        self.assert_trace_hidden_without_another_lookup(app, previous)

    def test_group_change_hides_trace_outside_selected_group(self):
        app = self.page()
        previous = self.load_selected_trace(app)
        other_group = next(group for group in REPORT["groups"] if previous not in group["run_ids"])
        app.selectbox(key="trace_group").select(other_group["group_id"]).run()
        self.assert_trace_hidden_without_another_lookup(app, previous)

    def test_applied_filter_change_hides_previously_loaded_trace(self):
        app = self.page()
        previous = self.load_selected_trace(app)
        # 이 fixture는 전부 한국어이므로 같은 그룹을 유지하는 필터 변경도 검증한다.
        app.selectbox(key=f"filter_{BATCH_ID}_language").select("ko")
        next(button for button in app.button if button.label == "필터 적용").click().run()
        self.assert_trace_hidden_without_another_lookup(app, previous)

    def test_batch_change_hides_previously_loaded_trace(self):
        app = self.page()
        previous = self.load_selected_trace(app)
        app.selectbox(key="batch_id").select(OTHER_BATCH_ID).run()
        self.assert_trace_hidden_without_another_lookup(app, previous)

    def test_csv_from_different_evaluation_snapshot_is_not_downloadable(self):
        app = self.page()
        self.server.csv_snapshot = "f" * 64
        app.button(key="prepare_csv").click().run()
        self.assertFalse(app.exception, app.exception)
        self.assertFalse(self.csv_downloads(app))
        self.assertIn("SNAPSHOT_MISMATCH", [error.value for error in app.error])

    def test_refresh_drops_old_csv_until_it_is_prepared_again(self):
        app = self.page()
        app.button(key="prepare_csv").click().run()
        self.assertFalse(app.exception, app.exception)
        self.assertEqual(len(self.csv_downloads(app)), 1)

        # 배치 ID와 필터가 같아도 명시적인 새로고침 뒤에는 CSV를 다시 준비한다.
        app.button(key="reload_batches").click().run()
        self.assertFalse(app.exception, app.exception)
        self.assertFalse(self.csv_downloads(app))
        csv_calls = [call for call in self.server.calls if call[1].endswith("/export.csv")]
        self.assertEqual(len(csv_calls), 1, "새로고침은 CSV나 모델을 자동 실행하지 않습니다.")

        app.button(key="prepare_csv").click().run()
        self.assertFalse(app.exception, app.exception)
        self.assertEqual(len(self.csv_downloads(app)), 1)


if __name__ == "__main__":
    unittest.main()
