"""저장 pipeline의 데이터·규칙·가격을 서버 실행 환경에 연결하는 검사."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import BatchRunner
from backend.app.batch_models import BatchSpec
from backend.app.config import Settings
from scripts import mvp
from scripts.data_contract import ROOT
from scripts.week3_prepare import VERSION, prepare


class PipelineServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name).resolve() / "pipeline"
        self.prepared = self.output / "prepared"
        prepare(self.prepared)
        settings = Settings(project_root=ROOT, data_dir=self.prepared / "rag", runs_dir=self.output / "runs",
                            model_provider="demo", model_id="demo-rag-v0.1", model_base_url=None,
                            model_api_key=None, system_prompt_version="v0.1", retrieval_config_version="lexical-v0.1",
                            pricing_path=ROOT / "configs/pricing-openai-2026-10-20.json",
                            evaluation_rules_path=self.prepared / "evaluation-rules.json",
                            common_policy_path=ROOT / "configs/week3-common-policy.txt")
        self.runner = BatchRunner(settings)
        self.state = self.runner.create(BatchSpec.model_validate_json(
            (self.prepared / "batch-spec.json").read_text(encoding="utf-8")))
        (self.output / "pipeline.json").write_text(json.dumps({"version": VERSION}), encoding="utf-8")
        (self.output / "checkpoint.json").write_text(json.dumps({
            "version": VERSION, "batch_id": self.state.batch_id}), encoding="utf-8")

    def test_paths_come_from_validated_pipeline_and_immutable_snapshots(self):
        env, batch_id = mvp.pipeline_environment(self.output)
        self.assertEqual(batch_id, self.state.batch_id)
        self.assertEqual(Path(env["DATA_DIR"]), self.prepared / "rag")
        self.assertEqual(Path(env["RUNS_DIR"]), self.output / "runs")
        folder = self.runner.store.folder(batch_id)
        for key, filename in (("PRICING_FILE", "pricing"), ("EVALUATION_RULES_FILE", "evaluation_rules"),
                              ("COMMON_POLICY_FILE", "common_policy")):
            self.assertEqual(Path(env[key]), folder / f"{filename}.snapshot")
        self.assertEqual(self.runner.store.get(batch_id).plan, self.state.plan)

    def test_launcher_replaces_stale_shell_paths_and_passes_profile_to_both_services(self):
        captured = []

        class FakeProcess:
            def __init__(self, name, command, log_dir, env):
                captured.append((name, dict(env)))
            def wait_ready(self, url):
                pass
            def check_running(self):
                raise KeyboardInterrupt
            def close(self):
                pass

        output = io.StringIO()
        stale = {"MVP_LOAD_DOTENV": "0", "DATA_DIR": "missing-data", "MVP_MANIFEST": "missing-manifest",
                 "RUNS_DIR": "missing-runs", "EVALUATION_RULES_FILE": "missing-rules",
                 "PRICING_FILE": "missing-prices", "COMMON_POLICY_FILE": "missing-policy",
                 "MODEL_API_KEY": "synthetic-key"}
        with patch.dict(os.environ, stale, clear=True), patch.object(mvp, "ManagedProcess", FakeProcess), \
                patch.object(mvp, "VENV_PYTHON", self.output / "missing-python"), redirect_stdout(output):
            result = mvp.main(["serve", "--pipeline-output", str(self.output), "--api-port", "0", "--ui-port", "0"])
        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in captured], ["backend", "frontend"])
        for _, env in captured:
            self.assertEqual(env["DATA_DIR"], str(self.prepared / "rag"))
            self.assertEqual(env["MVP_LOAD_DOTENV"], "0")
            with patch.dict(os.environ, env, clear=True):
                settings = Settings.from_environment(ROOT)
            self.assertEqual(settings.runs_dir, self.output / "runs")
            self.assertEqual(settings.evaluation_rules_path, self.runner.store.folder(self.state.batch_id) / "evaluation_rules.snapshot")
            self.assertEqual(settings.model_api_key, "synthetic-key")
        self.assertNotIn("synthetic-key", output.getvalue())

    def test_changed_snapshot_is_rejected_before_service_start(self):
        (self.runner.store.folder(self.state.batch_id) / "pricing.snapshot").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            mvp.pipeline_environment(self.output)

    def test_missing_checkpoint_is_not_created(self):
        checkpoint = self.output / "checkpoint.json"
        checkpoint.unlink()
        with self.assertRaises(FileNotFoundError):
            mvp.pipeline_environment(self.output)
        self.assertFalse(checkpoint.exists())

    def test_explicit_pipeline_cannot_be_mixed_with_independent_runs(self):
        with patch.dict(os.environ, {"MVP_LOAD_DOTENV": "0"}, clear=True), \
                patch.object(mvp, "VENV_PYTHON", self.output / "missing-python"), \
                patch.object(mvp, "ManagedProcess") as start, redirect_stderr(io.StringIO()):
            result = mvp.main(["serve", "--pipeline-output", str(self.output), "--runs-dir", "other"])
        self.assertEqual(result, 1)
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
