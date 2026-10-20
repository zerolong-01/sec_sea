"""Reject mutated sidecars and raw evidence before publishing an overlay."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import BatchRunner, file_hash
from backend.app.batch_models import BatchSpec
from backend.app.config import Settings
from backend.app.models import ModelCall, RunRequest
from backend.app.providers import OpenAICompatibleProvider, ProviderResponse
from backend.app.repository import ExperimentRepository, RunTraceStore
from backend.app.service import RunService
from scripts.data_contract import ROOT
from scripts.week3_quote_controls import prepare
from scripts import week3_control_observations as observations


class EchoSource:
    def generate_prepared(self, prompt, parameters):
        output = "\n".join(document.content for document in prompt.documents)
        call = ModelCall(purpose="generation", model_id="offline-test", messages=prompt.messages,
                         parameters=parameters, latency_ms=0, response_text=output)
        return ProviderResponse(output, None, None, None, call)


class ControlObservationTests(unittest.TestCase):
    def test_shared_targets_read_only_and_all_tampered_inputs_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            prepared, runs = folder / "prepared", folder / "runs"
            prepare(prepared)
            spec_payload = observations.read(prepared / "batch-spec.json")
            spec_payload["repeats"] = 1
            spec_payload["conditions"] = [spec_payload["conditions"][0]]
            (prepared / "batch-spec.json").write_text(json.dumps(spec_payload), encoding="utf-8")
            provenance = observations.read(prepared / "preparation.json")
            provenance["generated_sha256"]["batch-spec.json"] = file_hash(prepared / "batch-spec.json")
            # A changed current generator does not invalidate an executed
            # historical profile whose own generated artifacts still match.
            provenance["source_sha256"]["scripts/week3_quote_controls.py"] = "0" * 64
            (prepared / "preparation.json").write_text(json.dumps(provenance), encoding="utf-8")
            settings = Settings(project_root=ROOT, data_dir=prepared / "rag", runs_dir=runs,
                model_provider="demo", model_id="offline-test", system_prompt_version="v0.1",
                retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None,
                evaluation_rules_path=prepared / "evaluation-rules.json")
            runner = BatchRunner(settings)
            state = runner.create(BatchSpec.model_validate(spec_payload))
            frozen = runner.store.folder(state.batch_id)
            service_settings = replace(settings, data_dir=frozen / "inputs/quote_controls",
                evaluation_rules_path=frozen / "evaluation_rules.snapshot",
                common_policy_path=frozen / "common_policy.snapshot")
            service = RunService(service_settings, ExperimentRepository(service_settings.data_dir),
                                 RunTraceStore(runs), EchoSource())
            for entry in state.plan:
                run_id = "run-" + state.batch_id[6:] + "-" + entry["entry_id"] + "-attempt-1"
                trace = service.execute(RunRequest(schema_version="0.3", artifact_type="run_request",
                    case_id=entry["case_id"], scenario="rag_chat", defense_mode="none",
                    dataset_version=state.source_snapshots[0]["dataset_version"],
                    corpus_version=state.source_snapshots[0]["corpus_version"], requested_by=state.batch_id), run_id=run_id)
                entry["status"] = str(trace.status)
                entry["attempts"] = [{"run_id": run_id, "attempt_id": "fixture", "status": str(trace.status)}]
            state.status = "completed"
            runner.store.save(state)
            before = observations.inventory(runs, prepared)
            with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("model API called")):
                report = observations.write_report(runs, state.batch_id, prepared, folder / "valid.json")
            self.assertEqual(report["coverage"]["matched_pair_observation_count"], 3)
            self.assertEqual(report["coverage"]["inherited_family_count"], 3)
            marker = next(result for result in report["payload_comparisons"] if result["goal_kind"] == "marker")
            self.assertEqual(marker["control_exposure"]["value"], 1)
            self.assertEqual(marker["target_exposure_delta"]["value"], 0)
            self.assertEqual(before, observations.inventory(runs, prepared))
            self.assertFalse(report["measurement_is_human_review"])
            # Exact control emission is measured with the attack's target even
            # though this control intentionally has no automatic canary rule.
            control_id = next(pair["case_ids"]["quoted"] for pair in report["pairmap"] if pair["goal_kind"] == "marker")
            control_rule = next(rule for rule in observations.read(prepared / "evaluation-rules.json")["rules"]
                                if rule["case_id"] == control_id)
            self.assertIsNone(control_rule["canary"])
            self.assertTrue(next(row for row in report["observations"] if row["case_id"] == control_id)["exact_target_emitted"])
            text = (folder / "valid.json").read_text(encoding="utf-8")
            self.assertNotIn("CANARY_", text)
            raw_path = runs / (state.plan[0]["attempts"][0]["run_id"] + ".raw.json")
            original_raw = raw_path.read_bytes()
            changed = observations.read(raw_path)
            changed["model_calls"][-1]["response_text"] = "tampered generation response"
            raw_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "generation response"):
                observations.write_report(runs, state.batch_id, prepared, folder / "bad-raw.json")
            self.assertFalse((folder / "bad-raw.json").exists())
            raw_path.write_bytes(original_raw)
            preparation_path = prepared / "preparation.json"
            original_preparation = preparation_path.read_bytes()
            broken = observations.read(preparation_path)
            broken["pairs"][0]["case_ids"]["quoted"] = broken["pairs"][1]["case_ids"]["quoted"]
            preparation_path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(ValueError):
                observations.write_report(runs, state.batch_id, prepared, folder / "bad-pair.json")
            self.assertFalse((folder / "bad-pair.json").exists())
            preparation_path.write_bytes(original_preparation)
            corpus = prepared / "rag/corpus.v0.1.jsonl"
            corpus.write_bytes(corpus.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "generated artifact hash"):
                observations.write_report(runs, state.batch_id, prepared, folder / "bad-generated.json")
            self.assertFalse((folder / "bad-generated.json").exists())


if __name__ == "__main__":
    unittest.main()
