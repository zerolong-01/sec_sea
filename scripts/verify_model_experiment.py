"""Two synthetic target models, one detector, real CLI/HTTP and zero paid calls."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from backend.app.batch import file_hash
from backend.app.config import Settings
from backend.app.experiment_reports import source_inventory
from backend.app.experiments import ExperimentRunner
from backend.app.storage import atomic_json
from backend.testing.fixture_model import FixtureModelServer
from scripts.data_contract import ROOT, require


def verify(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runs = output / "runs"
    spec = json.loads((ROOT / "configs/model-experiment.example.json").read_text(encoding="utf-8"))
    credentials = {"MODEL_A_API_KEY": "synthetic-model-a-credential",
                   "MODEL_B_API_KEY": "synthetic-model-b-credential",
                   "EXPERIMENT_DETECTOR_API_KEY": "synthetic-detector-credential"}
    prices = {"version": "synthetic-model-comparison-prices-v1", "models": [
        {"model_id": model, "input_usd_per_million": rate, "output_usd_per_million": rate,
         "source_url": "https://example.invalid/synthetic-fixture-prices", "effective_date": "2026-10-25",
         "verified": True} for model, rate in (("fixture-model-a", 1), ("fixture-model-b", 2), ("fixture-detector", 1))]}
    atomic_json(output / "prices.fixture.json", prices)
    with FixtureModelServer(ROOT / "data") as first, FixtureModelServer(ROOT / "data") as second:
        second.generation_text = "A safe but unhelpful synthetic answer."
        for model, fixture, key in zip(spec["models"], (first, second), ("a", "b")):
            model.update(provider="fixture_http", base_url=fixture.base_url, model_id="fixture-model-" + key)
        spec["detector"].update(provider="fixture_http", base_url=first.base_url, model_id="fixture-detector")
        spec["pricing_file"] = str(output / "prices.fixture.json")
        spec["batch"]["statistics"] = {"bootstrap_samples": 100}
        atomic_json(output / "spec.fixture.json", spec)
        isolated = {key: value for key, value in os.environ.items() if not key.startswith(("MODEL_", "D2_"))
                    and key not in ("PRICING_FILE", "EVALUATION_RULES_FILE", "COMMON_POLICY_FILE", "MAX_MODEL_CALLS")}
        env = dict(isolated, **credentials, MVP_LOAD_DOTENV="0", MODEL_PROVIDER="demo",
                   PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")

        def cli(arguments, expected=0, *, environment=env):
            result = subprocess.run([sys.executable, "-m", "scripts.model_experiment", "--runs-dir", str(runs),
                                     *arguments], cwd=ROOT, env=environment, capture_output=True,
                                    text=True, encoding="utf-8", timeout=180)
            require(result.returncode == expected, "Model experiment CLI failed: " + result.stderr)
            require(not any(value in result.stdout for value in credentials.values()), "Credential in CLI response")
            return json.loads(result.stdout)

        created = cli(["create", "--spec", str(output / "spec.fixture.json")])
        experiment_id = created["experiment_id"]
        require(created["planned_count"] == 108, "Expected two models x three cases x six conditions x three repeats")
        require(not first.requests and not second.requests, "Planning called a model")
        missing = dict(env, MODEL_B_API_KEY="")
        cli(["run", experiment_id], expected=1, environment=missing)
        require(not first.requests and not second.requests, "Missing key preflight sent requests")
        paused = cli(["run", experiment_id, "--max-items", "5"], expected=2)
        require(paused["attempt_count"] == 5, "Cross-model item limit lost")
        completed = cli(["run", experiment_id])
        require(completed["status"] == "completed" and completed["attempt_count"] == 108, "Model batches incomplete")
        wire_count = len(first.requests) + len(second.requests)
        cli(["run", experiment_id])
        require(len(first.requests) + len(second.requests) == wire_count, "Resume replayed completed requests")
        # Compare transmitted prompts while excluding only the target model ID.
        targets = [[{k: v for k, v in p.items() if k != "model"} for p in fixture.requests
                    if p["model"] == "fixture-model-" + key]
                   for fixture, key in ((first, "a"), (second, "b"))]
        require(targets[0] and targets[0] == targets[1], "Model prompts or generation settings differ")
        require(not any(p["model"] == "fixture-detector" for p in second.requests), "Detector not shared")
        runner = ExperimentRunner(ROOT, runs)
        state = runner.store.get(experiment_id)
        before = source_inventory(runner, state)
        # Saved comparison must not depend on credentials or current .env.
        offline = {key: value for key, value in env.items() if key not in credentials}
        report = cli(["report", experiment_id], environment=offline)
        exported = output / "export"
        require(cli(["export", experiment_id, "--output", str(exported)], environment=offline) == report,
                "CLI report/export differs")
        require(cli(["show", experiment_id], environment=offline) == completed, "Show requires live settings")
        require(cli(["list"], environment=offline)[0] == completed, "List differs")
        validator = Draft202012Validator(json.loads((ROOT / "contracts/model-experiment-v0.1.schema.json").read_text(encoding="utf-8")))
        for artifact in (created, completed, state.model_dump(mode="json"), report):
            validator.validate(artifact)
        settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=runs, model_provider="demo",
            model_id="demo-rag-v0.1", system_prompt_version="v0.1", retrieval_config_version="lexical-v0.1",
            model_base_url=None, model_api_key=None)
        # main.py creates its default app on first import. Keep the verifier
        # independent of any live or invalid local model configuration.
        with patch.object(Settings, "from_environment", return_value=settings):
            from backend.app.main import create_app
        with TestClient(create_app(settings)) as client:
            base = "/api/v1/model-experiments/" + experiment_id
            require(client.get(base).json() == completed, "HTTP/CLI summary differs")
            require(client.post(base + "/report", json={}).json() == report, "HTTP/CLI report differs")
            response = client.post(base + "/export.csv", json={})
            require(response.status_code == 200 and response.headers["X-Report-SHA256"] == report["report_sha256"],
                    "CSV report identity missing")
            require(response.text.replace("\r\n", "\n") == (exported / "metrics.csv").read_text(encoding="utf-8-sig"),
                    "CSV API/export differs")
            empty = client.post(base + "/export.csv", json={"condition_id": ""})
            rows = list(csv.DictReader(io.StringIO(empty.text)))
            require(len(rows) == 1 and json.loads(rows[0]["filters"]) == {"condition_id": ""}, "Empty filters lost")
        rows = {row["model_key"]: row for row in report["rows"]
                if row["cohort"]["condition_id"] == "none" and row["cohort"]["goal_kind"] == "secret_leak"}
        require(rows["model-a"]["metrics"]["asr"]["value"] == 1 and
                rows["model-b"]["metrics"]["asr"]["value"] == 0, "Security outcomes not separated")
        require(rows["model-a"]["metrics"]["task_success"]["value"] >
                rows["model-b"]["metrics"]["task_success"]["value"], "Normal benchmark not preserved")
        require(rows["model-b"]["metrics"]["cost_per_request_usd"]["value"] ==
                2 * rows["model-a"]["metrics"]["cost_per_request_usd"]["value"], "Model prices not separated")
        require(source_inventory(runner, state) == before, "Read/export modified source evidence")
        require(len(first.requests) + len(second.requests) == wire_count, "Read/export called a model")
        public = json.dumps(report)
        require(not any(value in public for value in credentials.values()), "Credential in report")
        require("CANARY_EDU_SECRET_2026" not in public, "Private output in comparison")
    result = {"status": "passed", "execution_scope": "fixture", "paid_model_calls": 0,
        "real_model_quality_verified": False, "experiment_id": experiment_id, "planned_runs": 108,
        "model_count": 2, "shared_detector": True, "wire_calls": wire_count, "resume_duplicate_calls": 0,
        "same_transmitted_prompts": True, "missing_key_calls": 0, "api_cli_csv_consistent": True,
        "read_model_calls": 0, "source_unchanged": True, "different_security_utility_cost_preserved": True,
        "report_sha256": report["report_sha256"], "report_file_sha256": file_hash(exported / "report.json")}
    atomic_json(output / "verification-report.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
