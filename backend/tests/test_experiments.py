from __future__ import annotations

import json
import csv
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dataclasses import replace
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.experiment_models import ExperimentSpec
from app.experiments import ExperimentRunner
from app.experiment_reports import experiment_csv, experiment_report, export_experiment_report
from app.batch_models import BatchFilters
from app.batch_budget import BatchCallBudget
from app.main import create_app
from app.repository import ArtifactValidationError
from app.providers import MODEL_HTTP
from app.storage import exclusive_file_lock
from backend.testing.fixture_model import FixtureModelServer


class ExperimentPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runs = Path(self.temporary.name) / "runs"
        self.runner = ExperimentRunner(ROOT, self.runs)
        self.settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=self.runs,
            model_provider="demo", model_id="demo", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None)

    def spec(self, **updates):
        payload = {"models": [{"model_key": key, "provider": "demo", "model_id": "demo-" + key}
                               for key in ("first", "second")],
            "batch": {"sources": [{"source_id": "rag", "data_dir": "data", "split": "dev",
                                   "case_ids": ["a006", "b006", "h007"]}],
                "conditions": [{"condition_id": mode, "defense_mode": mode, "comparisons": ["technique"]}
                               for mode in ("none", "D1")], "repeats": 1,
                "budget": {"max_calls": 100, "max_reserved_tokens": 10000000,
                           "max_seconds": 60, "unknown_price_policy": "calls_tokens"}}}
        payload.update(updates)
        return ExperimentSpec.model_validate(payload)

    def test_planning_freezes_equal_inputs_and_never_calls_models(self):
        with patch("app.providers.DemoRagProvider.generate_prepared", side_effect=AssertionError("No model calls")):
            state = self.runner.create(self.spec(), settings=self.settings)
        children = self.runner.validate_members(self.runner.store.get(state.experiment_id))
        self.assertEqual(len(children), 2)
        self.assertNotEqual(children[0].batch_id, children[1].batch_id)
        self.assertEqual(children[0].plan, children[1].plan)
        self.assertEqual(children[0].source_snapshots, children[1].source_snapshots)
        self.assertNotEqual(children[0].execution_settings["model_id"], children[1].execution_settings["model_id"])
        self.assertTrue(all(not child.calls for child in children))

    def test_invalid_profiles_and_missing_shared_detector_are_rejected(self):
        payload = self.spec().model_dump(mode="json")
        for change in ("duplicate_key", "duplicate_model", "mixed_scope", "missing_detector", "inline_key"):
            data = json.loads(json.dumps(payload))
            if change == "duplicate_key":
                data["models"][1]["model_key"] = "first"
            elif change == "duplicate_model":
                data["models"][1]["model_id"] = "demo-first"
            elif change == "mixed_scope":
                data["models"][1].update(provider="openai_compatible", base_url="http://localhost:8000/v1")
            elif change == "missing_detector":
                data["batch"]["conditions"][1]["defense_mode"] = "D2"
            else:
                data["models"][1]["api_key"] = "must-not-be-stored"
            with self.subTest(change=change), self.assertRaises(ValueError):
                ExperimentSpec.model_validate(data)

    def test_swapped_members_and_changed_data_fail_validation(self):
        state = self.runner.create(self.spec(), settings=self.settings)
        path = self.runner.store.folder(state.experiment_id) / "manifest.json"
        original = path.read_bytes()
        payload = json.loads(original)
        payload["members"].reverse()
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ArtifactValidationError):
            self.runner.store.get(state.experiment_id)
        path.write_bytes(original)
        child = self.runner.validate_members(state)[1]
        frozen = self.runner.batches.folder(child.batch_id) / "inputs/rag/cases.v0.1.jsonl"
        frozen.write_bytes(frozen.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            self.runner.validate_members(state)


class ExperimentExecutionTests(ExperimentPlanningTests):
    def setUp(self):
        super().setUp()
        self.fixture = FixtureModelServer(ROOT / "data").__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        self.settings = replace(self.settings, evaluation_rules_path=ROOT / "configs/evaluation-starter.json")
        self.specification = self.spec().model_dump(mode="json")
        self.specification["models"] = [{"model_key": key, "model_id": "fixture-" + key,
            "provider": "fixture_http", "base_url": self.fixture.base_url, "api_key_env": key.upper() + "_KEY"}
            for key in ("first", "second")]
        self.specification["detector"] = {"model_key": "detector", "model_id": "fixture-classifier",
            "provider": "fixture_http", "base_url": self.fixture.base_url, "api_key_env": "SHARED_DETECTOR_KEY"}
        self.specification["batch"]["conditions"].append({"condition_id": "D2", "defense_mode": "D2",
                                                           "comparisons": ["technique"]})
        self.specification["batch"]["statistics"] = {"bootstrap_samples": 100}
        self.environment = patch.dict(os.environ, {"FIRST_KEY": "private-first-key",
            "SECOND_KEY": "private-second-key", "SHARED_DETECTOR_KEY": "private-shared-detector-key"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def create_experiment(self):
        return self.runner.create(ExperimentSpec.model_validate(self.specification), settings=self.settings)

    def test_wire_requests_share_prompts_and_detector_with_distinct_target_models_and_resume(self):
        state = self.create_experiment()
        with patch.object(MODEL_HTTP, "open", wraps=MODEL_HTTP.open) as transport:
            paused = self.runner.execute(state.experiment_id, max_items=2)
        self.assertEqual(paused.status, "paused")
        self.assertEqual(paused.attempt_count, 2)
        with patch.object(MODEL_HTTP, "open", wraps=MODEL_HTTP.open) as transport:
            completed = self.runner.execute(state.experiment_id)
        for invocation in transport.call_args_list:
            request = invocation.args[0]
            model = json.loads(request.data)["model"]
            expected = ("private-shared-detector-key" if model == "fixture-classifier" else
                        "private-first-key" if model == "fixture-first" else "private-second-key")
            self.assertEqual(request.get_header("Authorization"), "Bearer " + expected)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.attempt_count, 18)
        before = len(self.fixture.requests)
        self.runner.execute(state.experiment_id)
        self.assertEqual(len(self.fixture.requests), before)
        generated = {key: [p for p in self.fixture.requests if p["model"] == "fixture-" + key]
                     for key in ("first", "second")}
        self.assertTrue(generated["first"])
        self.assertEqual([{k: v for k, v in p.items() if k != "model"} for p in generated["first"]],
                         [{k: v for k, v in p.items() if k != "model"} for p in generated["second"]])
        self.assertTrue(any(p["model"] == "fixture-classifier" for p in self.fixture.requests))
        self.assertEqual(completed.budget_usage["admitted_calls"], before)
        self.assertEqual(completed.budget_limits["total_max_calls"], 200)
        serialized = json.dumps(state.model_dump(mode="json")) + completed.model_dump_json()
        for secret in ("private-first-key", "private-second-key", "private-shared-detector-key"):
            self.assertNotIn(secret, serialized)

    def test_comparison_preserves_different_security_utility_and_verified_model_costs(self):
        other = FixtureModelServer(ROOT / "data").__enter__()
        self.addCleanup(other.__exit__, None, None, None)
        other.generation_text = "A safe but unhelpful fixture answer."
        self.specification["models"][1]["base_url"] = other.base_url
        prices = Path(self.temporary.name) / "prices.json"
        prices.write_text(json.dumps({"version": "test-only-price-v1", "models": [
            {"model_id": model, "input_usd_per_million": rate, "output_usd_per_million": rate,
             "source_url": "https://example.invalid/synthetic-fixture-prices", "effective_date": "2026-10-25",
             "verified": True} for model, rate in (("fixture-first", 1), ("fixture-second", 2), ("fixture-classifier", 1))]}), encoding="utf-8")
        self.specification["pricing_file"] = str(prices)
        state = self.create_experiment()
        self.runner.execute(state.experiment_id)
        report = experiment_report(ROOT, self.runs, state.experiment_id)
        attacks = {row["model_key"]: row for row in report.rows
                   if row["cohort"]["condition_id"] == "none" and row["cohort"]["goal_kind"] == "unspecified"}
        self.assertEqual(attacks["first"]["metrics"]["asr"]["value"], 1)
        self.assertEqual(attacks["second"]["metrics"]["asr"]["value"], 0)
        self.assertGreater(attacks["first"]["metrics"]["task_success"]["value"],
                           attacks["second"]["metrics"]["task_success"]["value"])
        self.assertAlmostEqual(attacks["second"]["metrics"]["cost_per_request_usd"]["value"],
                               2 * attacks["first"]["metrics"]["cost_per_request_usd"]["value"])
        self.assertIsNotNone(report.summary.budget_usage["total_cost_usd"])
        self.assertEqual(attacks["first"]["comparison_id"], attacks["second"]["comparison_id"])

    def test_missing_later_model_credential_fails_before_any_transport(self):
        state = self.create_experiment()
        with patch.dict(os.environ, {"SECOND_KEY": ""}):
            with self.assertRaises(ValueError):
                self.runner.execute(state.experiment_id)
        self.assertEqual(self.fixture.requests, [])
        self.assertEqual(self.runner.summary(state.experiment_id).attempt_count, 0)

    def test_model_selection_and_writer_lock_do_not_create_extra_batches(self):
        state = self.create_experiment()
        with exclusive_file_lock(self.runner.store.folder(state.experiment_id) / "writer.lock"):
            with self.assertRaises(ValueError):
                self.runner.execute(state.experiment_id)
        self.assertFalse(self.fixture.requests)
        result = self.runner.execute(state.experiment_id, model_keys=["second"])
        self.assertEqual([model["status"] for model in result.models], ["planned", "completed"])
        self.assertEqual(len(list(self.runner.batches.root.glob("batch-*/manifest.json"))), 2)
        with self.assertRaises(ValueError):
            self.runner.execute(state.experiment_id, model_keys=["missing"])

    def test_uncertain_call_is_not_replayed_without_explicit_retry(self):
        state = self.create_experiment()
        with patch.object(BatchCallBudget, "after", side_effect=KeyboardInterrupt):
            result = self.runner.execute(state.experiment_id)
        self.assertEqual(result.status, "uncertain")
        before = len(self.fixture.requests)
        self.runner.execute(state.experiment_id)
        self.assertEqual(len(self.fixture.requests), before)
        self.runner.execute(state.experiment_id, retry_uncertain=True)
        self.assertGreater(len(self.fixture.requests), before)
        first = self.runner.batches.get(state.members[0].batch_id)
        self.assertTrue(any(c["status"] == "abandoned_unknown" for c in first.calls))

    def test_saved_reports_api_csv_export_and_schema_agree_without_model_calls(self):
        state = self.create_experiment()
        self.runner.execute(state.experiment_id)
        before = len(self.fixture.requests)
        with patch("app.providers.OpenAICompatibleProvider.complete", side_effect=AssertionError("Read called a model")):
            report = experiment_report(ROOT, self.runs, state.experiment_id)
            self.assertTrue(report.rows)
            self.assertTrue(any(c["status"] == "complete_membership" for c in report.comparisons))
            self.assertTrue(all(r["normal_benchmark_id"] for r in report.rows))
            self.assertIsNone(report.summary.budget_usage["total_cost_usd"])
            self.assertTrue(all(row["metrics"]["cost_per_request_usd"]["value"] is None for row in report.rows))
            schema = json.loads((ROOT / "contracts/model-experiment-v0.1.schema.json").read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
            for artifact in (state, self.runner.summary(state.experiment_id), report):
                validator.validate(artifact.model_dump(mode="json"))
            client = TestClient(create_app(replace(self.settings, runs_dir=self.runs)))
            url = "/api/v1/model-experiments/" + state.experiment_id
            self.assertEqual(client.get(url).status_code, 200)
            self.assertEqual(client.get("/api/v1/model-experiments").json()[0]["experiment_id"], state.experiment_id)
            response = client.post(url + "/report", json={})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), report.model_dump(mode="json"))
            response = client.post(url + "/export.csv", json={})
            self.assertEqual(response.headers["X-Report-SHA256"], report.report_sha256)
            self.assertEqual(response.text, experiment_csv(report))
            output = Path(self.temporary.name) / "export"
            export_experiment_report(report, output)
            self.assertEqual(json.loads((output / "report.json").read_text()), report.model_dump(mode="json"))
            with self.assertRaises(ValueError):
                export_experiment_report(report, output)
            empty = experiment_report(ROOT, self.runs, state.experiment_id, BatchFilters(condition_id=""))
            rows = list(csv.DictReader(io.StringIO(experiment_csv(empty))))
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0]["filters"]), {"condition_id": ""})
            self.assertEqual(rows[0]["report_sha256"], empty.report_sha256)
        self.assertEqual(len(self.fixture.requests), before)
