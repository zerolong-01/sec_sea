"""Consumer rejects wrong-source reports, stale exports and altered CSV values."""
import copy
import csv
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import requests

from backend.app.task_evaluation import task_evaluation_csv
from backend.app.task_evaluation_models import TaskEvaluationRecord, TaskEvaluationReport

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "frontend"))
import task_evaluation_core as core
import ui_core


class TaskEvaluationClientTests(unittest.TestCase):
    def setUp(self):
        sample = json.loads((ROOT / "docs/examples/week2/h007-D1+D2.json").read_text())
        self.trace = sample["response"]["trace"]
        request = self.trace["request"]
        record = TaskEvaluationRecord(evaluation_id="judge-fixture", revision=1, source="llm_judge",
            state="completed", normal_task_success="failure", attack_success="not_applicable",
            reason="Fixture failure evidence.", created_at="2026-11-09T00:00:00Z", requested_by="fixture",
            source_sha256="a"*64, execution_scope="fixture", model_id="fixture-judge")
        report = TaskEvaluationReport(run_id=self.trace["run_id"], case_id=request["case_id"],
            dataset_version=request["dataset_version"], corpus_version=request["corpus_version"],
            trace_sha256=core.digest(self.trace), judge_configured=True, max_model_calls=4,
            original_evaluation=self.trace["evaluation"], current_trace_evaluation=self.trace["evaluation"],
            records=[record], latest=record, revision=1, reserved_model_calls=1)
        self.report = report.model_dump(mode="json")
        self.sign(self.report)

    def sign(self, report):
        report["report_sha256"] = core.digest({k:v for k,v in report.items() if k != "report_sha256"})

    def response(self, text=None, report=None, **headers):
        return httpx.Response(200, text=text if text is not None else json.dumps(report or self.report), headers={
            "X-Report-SHA256": self.report["report_sha256"], "X-Report-Version": self.report["report_version"],
            "X-Evaluation-Source": self.report["evaluation_source"], **headers})

    def test_report_identity_revision_and_state_are_bound_to_original_trace(self):
        self.assertIsNone(core.report_error(self.report, self.trace))
        for field, value in (("run_id", "run-other"), ("case_id", "b006"),
                             ("dataset_version", "other-version"), ("trace_sha256", "0"*64), ("revision", 999)):
            report = copy.deepcopy(self.report)
            report[field] = value
            self.sign(report)
            self.assertEqual(core.report_error(report, self.trace)["code"], "SNAPSHOT_MISMATCH")
        report = copy.deepcopy(self.report)
        report["records"][0]["human_review"] = True
        report["latest"] = report["records"][0]
        self.sign(report)
        self.assertIsNotNone(core.report_error(report, self.trace))

    def test_csv_checks_every_row_value_not_only_header_hash(self):
        content = task_evaluation_csv(TaskEvaluationReport.model_validate(self.report))
        with patch("requests.request", return_value=self.response(text=content)):
            data, error = core.csv_bytes(self.trace, self.report)
            self.assertIsNone(error)
            self.assertEqual(data.decode(), content)
        rows = list(csv.reader(io.StringIO(content)))
        for changed in (rows[:-1], [*rows, rows[-1]], [*rows[:2], [*rows[-1][:4], "999", *rows[-1][5:]]]):
            stream = io.StringIO(newline="")
            csv.writer(stream).writerows(changed)
            with patch("requests.request", return_value=self.response(text=stream.getvalue())):
                self.assertEqual(core.csv_bytes(self.trace, self.report)[1]["code"], "SNAPSHOT_MISMATCH")
        with patch("requests.request", return_value=self.response(text=content, **{"X-Report-SHA256":"0"*64})):
            self.assertIsNotNone(core.csv_bytes(self.trace, self.report)[1])

    def test_api_errors_are_visible_and_never_fall_back_to_success(self):
        with patch("requests.request", side_effect=requests.Timeout):
            self.assertEqual(core.request_report(self.trace)[1]["code"], "CONNECTION_ERROR")
        for response in (httpx.Response(200, text="not JSON"), httpx.Response(200, json={"run_id":"run-other"}),
                         httpx.Response(409, json={"detail":{"code":"TASK_JUDGE_CALL_LIMIT"}})):
            with patch("requests.request", return_value=response):
                report, error = core.request_report(self.trace)
                self.assertIsNone(report)
                self.assertIsNotNone(error)

    def test_display_projection_preserves_attack_and_generation_metrics(self):
        before = copy.deepcopy(self.trace)
        shown = core.effective_trace(self.trace, self.report)
        self.assertEqual(shown["evaluation"]["normal_task_success"], "failure")
        self.assertEqual(shown["evaluation"]["attack_success"], self.trace["evaluation"]["attack_success"])
        self.assertEqual(shown["metrics"], self.trace["metrics"])
        self.assertEqual(self.trace, before)
        original_key = core.state_key(self.trace)
        with patch.object(ui_core, "BACKEND_URL", "http://another-server"):
            self.assertNotEqual(core.state_key(self.trace), original_key)


if __name__ == "__main__":
    unittest.main()
