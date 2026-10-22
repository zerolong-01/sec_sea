"""Two-app HTTP fixture plus original/AI public replay; no paid model calls."""
from __future__ import annotations

import argparse
import csv
import io
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import requests

from backend.app.batch import atomic_json
from backend.app.research_models import ResearchFilters
from backend.app.research_reports import research_report, research_csv
from scripts.data_contract import ROOT, load_bundle, require
from scripts.mvp import services
from scripts.verify_week3 import verify as verify_fixture
from scripts.week4_package import inventory, replay, tree_hashes


def verify(output, fixture_output=None):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    fixture_output = fixture_output.resolve() if fixture_output else output / "fixture"
    if not fixture_output.exists():
        verify_fixture(fixture_output)
    fixture = json.loads((fixture_output / "verification-report.json").read_text(encoding="utf-8"))
    require(fixture["status"] == "passed" and fixture["execution_scope"] == "fixture", "Expected verified fixture source")
    runs, batch_id = fixture_output / "runs", fixture["batch_id"]
    before = tree_hashes(runs)
    original = replay(batch_id, output / "original-first", runs_dir=runs)
    repeated = replay(batch_id, output / "original-second", runs_dir=runs)
    require(original["artifacts"] == repeated["artifacts"], "Repeated saved exports differ")
    public_id = "batch-8fb19849d67c"
    filters = {"condition_id": "none", "goal_kind": "secret_leak", "ablation_variant": "original"}
    overlay = replay(public_id, output / "overlay", source="overlay", filters=filters)
    expected = research_report(public_id, ResearchFilters(**filters))
    with services(load_bundle(ROOT / "data"), runs, 0, 0, demo=True, service_logs_dir=output / "service-logs") as (url, _, _, _):
        report = requests.post(f"{url}/api/v1/batches/{batch_id}/report", json={}, timeout=30)
        require(report.status_code == 200, "Original HTTP report failed")
        require(report.json() == json.loads((output / "original-first/report.json").read_text(encoding="utf-8")), "Original API/artifact mismatch")
        base = f"{url}/api/v1/batches/{public_id}"
        response = requests.post(base + "/research/report", json=filters, timeout=30)
        require(response.status_code == 200 and response.json() == expected.model_dump(mode="json"), "Research HTTP report differs")
        response = requests.post(base + "/research/export.csv", json=filters, timeout=30)
        require(response.status_code == 200 and response.text == research_csv(expected), "Research CSV differs")
        for row in csv.DictReader(io.StringIO(response.text)):
            require(row["report_sha256"] == overlay["report_sha256"], "CSV report identity lost")
        require(requests.post(base + "/research/report", json={"family_id": "unsupported"}, timeout=10).status_code == 422, "Unsupported dimension silently accepted")
        require(requests.post(base + "/research/report", json={"language": "en"}, timeout=10).json()["counts"]["members"] == 0, "Empty cohort changed to a value")
        require(requests.get(base + "/evaluation-sources", timeout=10).json()["research"]["available"], "Missing source inventory")
        require(requests.post(base + "/report", json={}, timeout=10).status_code == 404, "Overlay replaced missing original store")
    require(tree_hashes(runs) == before, "HTTP/replay modified original artifacts")
    result = {"status": "passed", "verified_at": datetime.now(timezone.utc).isoformat(),
              "platform": platform.platform(), "python": platform.python_version(),
              "fixture": fixture, "original_report_sha256": original["report_sha256"],
              "overlay_report_sha256": overlay["report_sha256"], "api_csv_artifact_match": True,
              "repeated_export_match": True, "original_source_unchanged": True,
              "replay_model_calls": original["model_calls"] + repeated["model_calls"] + overlay["model_calls"],
              "saved_private_real_replay": "not_performed_private_evidence_not_in_checkout",
              "real_model_rerun": "not_performed", "human_ABC_acceptance": "pending",
              "holdout_executed": False, "candidate_remote_CI": "check_this_commit_on_ubuntu_and_windows"}
    atomic_json(output / "release-manifest.json", inventory())
    atomic_json(output / "verification-report.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture-output", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.output, args.fixture_output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
