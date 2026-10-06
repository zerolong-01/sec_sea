from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.config import Settings
from scripts import mvp


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env_file = self.root / ".env"

    def write_env(self, text):
        # Windows editors may produce a UTF-8 BOM.
        self.env_file.write_text(text, encoding="utf-8-sig")

    def test_backend_loads_root_file_from_another_working_directory_and_resolves_paths(self):
        self.write_env("MODEL_PROVIDER=openai_compatible\nMODEL_ID=fixture-model\n"
            "MODEL_BASE_URL=http://127.0.0.1:9000/v1\nMODEL_API_KEY=synthetic-${UNCHANGED}\n"
            "D2_THRESHOLD=0.7\nDATA_DIR=custom-data\nRUNS_DIR=custom-runs\n"
            "PRICING_FILE=configs/prices.json\nEVALUATION_RULES_FILE=configs/rules.json\n")
        other = self.root / "other"
        other.mkdir()
        (other / ".env").write_text("MODEL_ID=wrong-directory", encoding="utf-8")
        original_cwd = Path.cwd()
        try:
            os.chdir(other)
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.from_environment(self.root)
        finally:
            os.chdir(original_cwd)
        self.assertEqual(settings.model_id, "fixture-model")
        self.assertEqual(settings.model_api_key, "synthetic-${UNCHANGED}")
        self.assertEqual(settings.d2_threshold, .7)
        self.assertEqual(settings.data_dir, self.root / "custom-data")
        self.assertEqual(settings.runs_dir, self.root / "custom-runs")
        self.assertEqual(settings.pricing_path, self.root / "configs/prices.json")
        self.assertEqual(settings.evaluation_rules_path, self.root / "configs/rules.json")

    def test_existing_environment_overrides_file_even_when_value_is_empty(self):
        self.write_env("MODEL_PROVIDER=openai_compatible\nMODEL_ID=file-model\n"
                       "MODEL_API_KEY=file-synthetic-key\nD2_THRESHOLD=0.7\n")
        with patch.dict(os.environ, {"MODEL_PROVIDER": "fixture_http", "MODEL_ID": "process-model",
                                    "MODEL_API_KEY": "", "D2_THRESHOLD": "0.2"}, clear=True):
            settings = Settings.from_environment(self.root)
        self.assertEqual(settings.model_provider, "fixture_http")
        self.assertEqual(settings.model_id, "process-model")
        self.assertEqual(settings.model_api_key, "")
        self.assertEqual(settings.d2_threshold, .2)

    def test_missing_file_keeps_demo_defaults_and_disabled_loading_ignores_local_file(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_environment(self.root)
        self.assertEqual(settings.model_provider, "demo")
        self.assertIsNone(settings.model_api_key)
        self.write_env("MODEL_PROVIDER=openai_compatible\nMODEL_API_KEY=synthetic-key\n")
        with patch.dict(os.environ, {"MVP_LOAD_DOTENV": "0"}, clear=True):
            settings = Settings.from_environment(self.root)
        self.assertEqual(settings.model_provider, "demo")
        self.assertIsNone(settings.model_api_key)

    def test_launcher_loads_file_before_resolving_bundle_defaults_and_cli_takes_priority(self):
        self.write_env("DATA_DIR=file-data\nMVP_MANIFEST=file-manifest.json\nMODEL_API_KEY=synthetic-key\n")
        bundle = SimpleNamespace(cases={}, documents={}, manifest=SimpleNamespace(dataset_version="fixture-v1"))
        for arguments, expected_data, expected_manifest in (
            (["check"], self.root / "file-data", self.root / "file-manifest.json"),
            (["check", "--data-dir", str(self.root / "cli-data"), "--manifest", str(self.root / "cli-manifest.json")],
             self.root / "cli-data", self.root / "cli-manifest.json"),
        ):
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), patch.object(mvp, "ROOT", self.root), \
                    patch.object(mvp, "VENV_PYTHON", self.root / "missing-python"), \
                    patch("scripts.data_contract.load_bundle", return_value=bundle) as load, redirect_stdout(output):
                self.assertEqual(mvp.main(arguments), 0)
                load.assert_called_once_with(expected_data, expected_manifest)
            self.assertNotIn("synthetic-key", output.getvalue())

    def test_demo_child_does_not_reload_real_settings_after_launcher_removes_them(self):
        self.write_env("MODEL_PROVIDER=openai_compatible\nMODEL_BASE_URL=https://api.openai.com/v1\n"
                       "MODEL_API_KEY=synthetic-local-key\nEVALUATION_RULES_FILE=configs/rules.json\n")
        bundle = SimpleNamespace(data_dir=self.root / "data", manifest_path=self.root / "manifest.json")

        class FakeProcess:
            def __init__(self, *args):
                pass
            def wait_ready(self, url):
                pass
            def close(self):
                pass

        process_env = {"MODEL_PROVIDER": "openai_compatible", "MODEL_BASE_URL": "https://api.openai.com/v1",
                       "MODEL_API_KEY": "synthetic-process-key", "EVALUATION_RULES_FILE": "configs/rules.json"}
        with patch.dict(os.environ, process_env, clear=True), patch("scripts.mvp.ManagedProcess", FakeProcess):
            with mvp.services(bundle, self.root / "runs", 0, 0, demo=True) as (_, _, child_env, _):
                self.assertEqual(child_env["MVP_LOAD_DOTENV"], "0")
                with patch.dict(os.environ, child_env, clear=True):
                    settings = Settings.from_environment(self.root)
                self.assertEqual(settings.model_provider, "demo")
                self.assertIsNone(settings.model_base_url)
                self.assertIsNone(settings.model_api_key)
                self.assertIsNone(settings.evaluation_rules_path)


if __name__ == "__main__":
    unittest.main()
