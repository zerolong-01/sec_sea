"""CI checks automation against real published gold with an intentionally bad local judge."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

from backend.app.config import Settings
from backend.app.judge_reference import ROOT, REFERENCE
from backend.app.storage import atomic_json, file_sha256
from backend.testing.fixture_model import FixtureModelServer
from scripts.judge_calibration import report, run


def verify(output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Use a new fixture output")
    with FixtureModelServer(ROOT / "data/week2") as fixture:
        settings = Settings(project_root=ROOT, data_dir=ROOT / "data/week2", runs_dir=output / "unused",
            model_provider="demo", model_id="offline", model_base_url=None, model_api_key=None,
            system_prompt_version="v0.1", retrieval_config_version="lexical-v0.1",
            judge_provider="fixture_http", judge_base_url=fixture.base_url, judge_model_id="fixture-judge")
        first = run(output, settings, max_items=4)
        assert json.loads((output / "human-reference-labels.json").read_text()) == json.loads(
            (REFERENCE / "validation-labels.v0.1.json").read_text())
        assert len(fixture.requests) == 4
        final = run(output, settings)
        assert final["status"] == "complete" and len(fixture.requests) == 160
        assert final["overall"]["accuracy"] == .5 and final["overall"]["false_success_rate"] == 1
        assert not final["external_reference_gate"]["passed"]
        before = file_sha256(output / "ledger.json")
        with patch("scripts.judge_calibration.OpenAICompatibleProvider.complete", side_effect=AssertionError("Read called a model")):
            assert report(output) == final
        assert file_sha256(output / "ledger.json") == before
        assert run(output, settings) == final
        assert len(fixture.requests) == 160
    result = {"status":"passed","scope":"automation_fixture_only","published_human_pairs":80,
        "predictions":160,"always_success_judge_accuracy":.5,"false_success_rate":1,
        "bad_judge_correctly_rejected":True,"source_gold_pinned":True,"resume_duplicate_calls":0,
        "read_model_calls":0,"paid_model_calls":0,"actual_judge_accuracy_verified":False}
    atomic_json(output / "verification-report.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
