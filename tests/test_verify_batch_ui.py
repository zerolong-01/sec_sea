"""저장된 v0.3 배치를 실제 집계 API와 대시보드로 재생한다."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import BatchRunner
from backend.app.batch_models import BatchSpec
from backend.app.config import Settings
from scripts.data_contract import ROOT, DataContractError
from scripts.verify_real_ui import verify_dashboard
from scripts.week3_prepare import prepare

sys.path.insert(0, str(ROOT / "frontend"))


class SavedBatchDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        prepared = cls.folder / "prepared"
        prepare(prepared)
        data = json.loads((prepared / "batch-spec.json").read_text(encoding="utf-8"))
        data["repeats"] = 1
        data["min_call_interval_seconds"] = 0
        data["statistics"]["bootstrap_samples"] = 100
        data["conditions"] = [condition for condition in data["conditions"]
                              if condition["condition_id"] in ("none", "D1")]
        rag_ids = ["w3_a006_original", "w3_a006_instruction_removed", "w3pv_a11", "w3pv_c01"]
        data["sources"][0]["case_ids"] = rag_ids
        for source in data["sources"]:
            source["metadata"] = {case_id: meta for case_id, meta in source["metadata"].items()
                                  if case_id in source["case_ids"]}
        data["budget"] = {"max_calls": 100, "max_reserved_tokens": 1000000,
                          "max_seconds": 60, "unknown_price_policy": "calls_tokens"}
        cls.runs = cls.folder / "runs"
        settings = Settings(project_root=ROOT, data_dir=prepared / "rag", runs_dir=cls.runs,
            model_provider="demo", model_id="demo-rag-v0.1", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None,
            evaluation_rules_path=prepared / "evaluation-rules.json")
        cls.runner = BatchRunner(settings)
        state = cls.runner.create(BatchSpec.model_validate(data))
        cls.state = cls.runner.execute(state.batch_id)
        if cls.state.status != "completed":
            raise AssertionError(f"Offline batch failed: {cls.state.reason}")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_v03_dashboard_filters_csv_and_public_trace_match_saved_api_without_model_calls(self):
        before = copy.deepcopy(self.runner.store.get(self.state.batch_id).model_dump(mode="json"))
        report = verify_dashboard(self.runs, self.state.batch_id, allow_fixture=True)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["report_version"], "batch-cluster-summary-v0.3")
        self.assertEqual(report["execution_scope"], "demo")
        self.assertFalse(report["real_model_verified"])
        self.assertEqual((report["additional_model_calls"], report["network_calls"]), (0, 0))
        self.assertTrue(report["api_aggregate_ui_json_csv_consistent"])
        self.assertTrue(report["saved_batch_unchanged"])
        self.assertTrue(report["calculation_implementation_sha256"])
        self.assertEqual(len(report["contexts"]), 3)  # 전체 + RAG + 이메일
        self.assertTrue(all(context["trace_run_id"] for context in report["contexts"]))
        self.assertGreater(report["contexts"][0]["payload_comparison_count"], 0)
        after = self.runner.store.get(self.state.batch_id).model_dump(mode="json")
        self.assertEqual(before, after)

    def test_demo_batch_cannot_be_reported_as_real_model_verification(self):
        with self.assertRaisesRegex(DataContractError, "needs real traces"):
            verify_dashboard(self.runs, self.state.batch_id)

    def test_invalid_ui_json_download_fails_replay_verification(self):
        with patch("batch_core.report_json_bytes", return_value=b"{}"):
            with self.assertRaisesRegex(DataContractError, "JSON differs"):
                verify_dashboard(self.runs, self.state.batch_id, allow_fixture=True)

    def test_cold_import_replays_saved_batch_with_invalid_current_model_environment(self):
        # A subprocess ensures backend.app.main has not already cached its
        # module-level default app before the intentionally broken setting.
        code = ("import json,sys; from pathlib import Path; "
                "from scripts.verify_real_ui import verify_dashboard; "
                "print(json.dumps(verify_dashboard(Path(sys.argv[1]),sys.argv[2],allow_fixture=True)))")
        environment = dict(os.environ, MVP_LOAD_DOTENV="0", MODEL_TEMPERATURE="invalid-current-setting",
                           PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, "-c", code, str(self.runs), self.state.batch_id],
            cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr[-2000:])
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "passed")
        self.assertEqual((report["additional_model_calls"], report["network_calls"]), (0, 0))

    def test_planned_real_batch_ui_replay_is_not_completed_real_model_verification(self):
        settings = replace(self.runner.settings, model_provider="openai_compatible",
                           model_id="gpt-4.1-mini", model_base_url="https://api.openai.com/v1")
        with patch("urllib.request.urlopen", side_effect=AssertionError("No model request is allowed")):
            planned = BatchRunner(settings).create(self.state.spec)
            report = verify_dashboard(self.runs, planned.batch_id)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["execution_scope"], "real")
        self.assertEqual(report["batch_status"], "planned")
        self.assertEqual(report["status_counts"], {"pending": len(planned.plan)})
        self.assertEqual(report["attempt_count"], 0)
        self.assertFalse(report["real_model_verified"])
        self.assertTrue(all(context["trace_run_id"] is None for context in report["contexts"]))
        self.assertEqual((report["additional_model_calls"], report["network_calls"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
