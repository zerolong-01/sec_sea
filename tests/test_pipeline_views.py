"""보고서/API/CSV/상세 trace의 실제 연결과 snapshot 경계를 검증한다."""
from __future__ import annotations

import copy
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.app.batch import digest
from backend.app.config import Settings
from backend.app.experiment_models import ExperimentSpec
from backend.app.experiment_reports import experiment_report
from backend.app.experiments import ExperimentRunner
from backend.app.research_comparison import original_attack_comparison
from scripts.data_contract import ROOT
from scripts.week4_package import tree_hashes

sys.path.insert(0, str(ROOT / "frontend"))
import comparison_core as cc
import experiment_core as ec


def changed_csv(content, mutate):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    columns, rows = reader.fieldnames, list(reader)
    mutate(rows)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, columns)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


class PipelineViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.runs = Path(cls.temporary.name) / "runs"
        cls.settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=cls.runs,
            model_provider="demo", model_id="demo", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None)
        spec = ExperimentSpec.model_validate({
            "models": [{"model_key": key, "provider": "demo", "model_id": "demo-" + key} for key in ("first", "second")],
            "evaluation_rules_file": "configs/evaluation-starter.json",
            "batch": {"sources": [{"source_id": "rag", "data_dir": "data", "split": "dev", "case_ids": ["a006", "b006", "h007"]}],
                      "conditions": [{"condition_id": m, "defense_mode": m, "comparisons": ["technique"]} for m in ("none", "D1")],
                      "repeats": 1, "statistics": {"bootstrap_samples": 100},
                      "budget": {"max_calls": 100, "max_reserved_tokens": 1000000, "max_seconds": 60,
                                 "unknown_price_policy": "calls_tokens"}}})
        runner = ExperimentRunner(ROOT, cls.runs)
        state = runner.create(spec, settings=cls.settings)
        cls.experiment_id = state.experiment_id
        cls.summary = runner.execute(state.experiment_id)
        assert cls.summary.status == "completed"
        with patch.object(Settings, "from_environment", return_value=cls.settings):
            from backend.app.main import create_app
        cls.client = TestClient(create_app(cls.settings)).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temporary.cleanup()

    def setUp(self):
        self.before = tree_hashes(self.runs)
        self.calls = []

    def tearDown(self):
        self.assertEqual(tree_hashes(self.runs), self.before)

    def request(self, method, url, json=None, **kwargs):
        path = urlsplit(url).path
        self.assertFalse(method == "POST" and path == "/api/v1/runs", "Viewing caused execution")
        self.calls.append((method, path, json))
        return self.client.request(method, path, json=json)

    def test_both_csv_contracts_reject_changed_values_missing_duplicate_rows_and_stale_filters(self):
        for report, csv_path, get_csv in (
            (original_attack_comparison().model_dump(mode="json"), cc.PATHS["ORIGINAL_ATTACKS_CSV"], lambda r: cc.get_csv(r)),
            (experiment_report(ROOT, self.runs, self.experiment_id).model_dump(mode="json"),
             f"{ec.BASE}/{self.experiment_id}/export.csv", lambda r: ec.get_csv(self.experiment_id, {}, r)),
        ):
            response = self.client.request("GET" if "original-attacks" in csv_path else "POST", csv_path, json={})
            with patch("requests.request", return_value=response):
                self.assertIsNone(get_csv(report)[1])
            mutations = [lambda rows: rows.pop(), lambda rows: rows.append(copy.deepcopy(rows[-1])),
                         lambda rows: rows[-1].update(value="0.987654321"),
                         lambda rows: rows[-1].update(report_sha256="0" * 64)]
            if "original-attacks" not in csv_path:
                mutations.append(lambda rows: rows[-1].update(filters='{"condition_id":"D1"}'))
            for mutate in mutations:
                with self.subTest(path=csv_path), patch("requests.request", return_value=SimpleNamespace(
                        status_code=200, headers=response.headers, content=changed_csv(response.content, mutate))):
                    self.assertIsNotNone(get_csv(report)[1])

    def test_report_identity_and_requested_filter_are_checked_before_display(self):
        report = experiment_report(ROOT, self.runs, self.experiment_id).model_dump(mode="json")
        for update in ({"experiment_id": "experiment-000000000000"}, {"report_version": "unknown"},
                       {"filters": {"condition_id": "D1"}}):
            changed = {**copy.deepcopy(report), **update}
            changed["report_sha256"] = digest({k: v for k, v in changed.items() if k != "report_sha256"})
            with patch("requests.request", return_value=SimpleNamespace(status_code=200, json=lambda: changed)):
                self.assertIsNone(ec.get_report(self.experiment_id)[0])
        with patch("requests.request") as request:
            self.assertIsNone(ec.get_report("../outside")[0])
            request.assert_not_called()

    def test_fixed_report_page_download_matches_backend_and_uses_no_execution(self):
        from backend.app.providers import OpenAICompatibleProvider
        with patch("requests.request", side_effect=self.request), \
                patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("Paid call")):
            app = AppTest.from_file(str(ROOT / "frontend/pages/3_보고서_원본공격_비교.py"), default_timeout=30).run()
            app.button(key="comparison_csv_prepare").click().run()
        self.assertFalse(app.exception, app.exception)
        self.assertFalse(app.error, app.error)
        table = next(e.value for e in app.dataframe if "공격 상황 업무 성공" in e.value.columns)
        self.assertEqual(table.iloc[0]["공격 목표 달성"], "25.0% (3/12)")
        self.assertEqual(len(table), 6)
        self.assertIn("CSV의 보고서 해시", app.success[-1].value)
        self.assertTrue(all(method == "GET" for method, _, _ in self.calls))

    def test_model_page_filters_drop_download_and_trace_then_revalidate_same_snapshot(self):
        with patch("requests.request", side_effect=self.request), \
                patch("requests.get", side_effect=lambda url, **kw: self.request("GET", url, **kw)), \
                patch("requests.post", side_effect=AssertionError("Execution request")):
            app = AppTest.from_file(str(ROOT / "frontend/pages/4_모델_비교.py"), default_timeout=30).run()
            app.button(key="experiment_csv_prepare").click().run()
            app.button(key="experiment_load_trace").click().run()
            self.assertFalse(app.exception, app.exception)
            self.assertFalse(app.error, app.error)
            loaded_run = app.selectbox(key="experiment_run").value
            self.assertIn(loaded_run, [e.value for e in app.text])
            app.selectbox(key=f"experiment_{self.experiment_id}_condition_id").select("D1")
            next(b for b in app.button if b.label == "필터 적용").click().run()
            self.assertFalse(app.exception, app.exception)
            self.assertNotIn(loaded_run, [e.value for e in app.text])
            with self.assertRaises(KeyError):
                app.session_state["experiment_csv"]
            app.button(key="experiment_csv_prepare").click().run()
            self.assertFalse(app.error, app.error)
            self.assertIn("모델 소속", app.success[-1].value)
            filtered = ec.get_report(self.experiment_id, {"condition_id": "D1"})[0]
            self.assertEqual(app.session_state["experiment_csv"][0][1], filtered["report_sha256"])

    def test_empty_model_selection_keeps_metadata_export_and_unknown_cost_is_not_zero(self):
        with patch("requests.request", side_effect=self.request):
            empty, error = ec.get_report(self.experiment_id, {"condition_id": ""})
            self.assertIsNone(error)
            self.assertEqual(empty["rows"], [])
            content, error = ec.get_csv(self.experiment_id, {"condition_id": ""}, empty)
            self.assertIsNone(error)
            self.assertEqual(len(list(csv.DictReader(io.StringIO(content.decode())))), 1)
            report, _ = ec.get_report(self.experiment_id)
            unknown = copy.deepcopy(report)
            unknown["rows"][0]["metrics"]["cost_per_request_usd"]["value"] = None
            self.assertIn("기록 없음", ec.rows(unknown)[0]["요청당 비용 (USD)"])
            self.assertNotEqual(ec.rows(report)[0]["요청당 비용 (USD)"], ec.rows(unknown)[0]["요청당 비용 (USD)"])


if __name__ == "__main__":
    unittest.main()
