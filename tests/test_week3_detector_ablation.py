import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import BatchRunner
from backend.app.batch_models import BatchSpec
from backend.app.config import Settings
from backend.app.defenses import D2_SYSTEM, Detection
from backend.app.models import ChatMessage, ModelCall, RunRequest
from backend.app.providers import DemoRagProvider, OpenAICompatibleProvider, ProviderResponse
from backend.app.repository import ExperimentRepository, RunTraceStore
from backend.app.service import RunService
from scripts.data_contract import ROOT
from scripts.week3_prepare import prepare
from scripts import week3_detector_ablation as ablation


class ControlledDetector:
    def classify(self, text, stage, target_ref):
        original = "탐지기 출력은 반드시" in text
        result = Detection(score=0 if original else 1,
            reason_code="normal_request" if original else "malicious_instruction", reason="offline fixture")
        call = ModelCall(purpose="detection", target_ref=target_ref, model_id="offline-detector",
            messages=[ChatMessage(role="system", content=D2_SYSTEM), ChatMessage(role="user",
                content=json.dumps({"stage": str(stage), "text": text}, ensure_ascii=False))],
            parameters={}, latency_ms=0, response_text=result.model_dump_json())
        return result, ProviderResponse(result.model_dump_json(), None, None, None, call)


class DetectorAblationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.prepared = self.folder / "prepared"
        prepare(self.prepared)
        spec = json.loads((self.prepared / "batch-spec.json").read_text(encoding="utf-8"))
        selected = {"w3_a021_original", "w3_a021_d2_instruction_removed"}
        spec["sources"] = [spec["sources"][0]]
        spec["sources"][0]["case_ids"] = sorted(selected)
        spec["sources"][0]["metadata"] = {key: value for key, value in spec["sources"][0]["metadata"].items() if key in selected}
        spec["repeats"] = 1
        spec["conditions"] = [condition for condition in spec["conditions"] if condition["condition_id"] == "D2-input"]
        self.runs = self.folder / "runs"
        settings = Settings(project_root=ROOT, data_dir=self.prepared / "rag", runs_dir=self.runs,
            model_provider="demo", model_id="offline", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None,
            evaluation_rules_path=self.prepared / "evaluation-rules.json")
        runner = BatchRunner(settings)
        self.state = runner.create(BatchSpec.model_validate(spec))
        frozen = runner.store.folder(self.state.batch_id)
        settings = replace(settings, data_dir=frozen / "inputs/week3",
            evaluation_rules_path=frozen / "evaluation_rules.snapshot", common_policy_path=frozen / "common_policy.snapshot")
        service = RunService(settings, ExperimentRepository(settings.data_dir), RunTraceStore(self.runs),
                             DemoRagProvider(), classifier=ControlledDetector())
        for entry in self.state.plan:
            run_id = "run-" + self.state.batch_id[6:] + "-" + entry["entry_id"] + "-attempt-1"
            trace = service.execute(RunRequest(schema_version="0.3", artifact_type="run_request",
                case_id=entry["case_id"], scenario="rag_chat", defense_mode="D2", defense_position="input",
                dataset_version="synthetic_week3_v0.1_draft", corpus_version="synthetic_week3_v0.1_draft",
                requested_by=self.state.batch_id), run_id=run_id)
            entry["status"] = str(trace.status)
            entry["attempts"] = [{"run_id": run_id, "attempt_id": "fixture", "status": str(trace.status)}]
        self.state.status = "completed"
        runner.store.save(self.state)
        self.gold = self.folder / "gold.jsonl"
        rows = [json.loads(line) for line in (ROOT / "data/week3/research-legacy-target-gold.v0.4.jsonl").read_text(
            encoding="utf-8").splitlines() if json.loads(line)["case_id"] in selected]
        self.gold.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def run_report(self, name="report.json"):
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("API called")):
            return ablation.write_report(self.runs, self.state.batch_id, self.gold, self.folder / name)

    def test_valid_malicious_pair_fnr_difference_is_read_only_and_uninspected_is_not_a_correct_negative(self):
        before = {path: path.read_bytes() for path in self.runs.rglob("*") if path.is_file()}
        report = self.run_report()
        row = next(row for row in report["comparisons"] if row["stage"] == "input")
        self.assertEqual(row["original_fnr"]["value"], 1)
        self.assertEqual(row["d2_instruction_removed_fnr"]["value"], 0)
        self.assertEqual(row["paired_fnr_difference_original_minus_removed"]["value"], 1)
        self.assertEqual(row["paired_fnr_difference_original_minus_removed"]["family_count"], 1)
        self.assertIsNone(row["paired_fnr_difference_original_minus_removed"]["ci95"])
        retrieval = next(row for row in report["comparisons"] if row["stage"] == "retrieval")
        self.assertIsNone(retrieval["original_fnr"]["value"])
        self.assertEqual(retrieval["original_fnr"]["excluded"], {"not_inspected": 1})
        self.assertEqual(before, {path: path.read_bytes() for path in self.runs.rglob("*") if path.is_file()})
        self.assertFalse(report["annotation_applied_by_this_tool"])

    def test_contradiction_is_excluded_and_response_event_tampering_is_rejected(self):
        entry = next(entry for entry in self.state.plan if entry["case_id"] == "w3_a021_original")
        run_id = entry["attempts"][0]["run_id"]
        raw_path, trace_path = (self.runs / (run_id + suffix) for suffix in (".raw.json", ".trace.json"))
        raw, trace = json.loads(raw_path.read_text(encoding="utf-8")), json.loads(trace_path.read_text(encoding="utf-8"))
        detection = next(call for call in raw["model_calls"] if call["purpose"] == "detection")
        response = json.loads(detection["response_text"])
        response["reason_code"] = "malicious_instruction"
        detection["response_text"] = json.dumps(response)
        for event in [raw["defense_events"][0], trace["defense_events"][0]]:
            event.update(reason_code="malicious_instruction", consistency_issue="malicious_reason_below_threshold", review_needed=True)
        raw_path.write_text(json.dumps(raw), encoding="utf-8")
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        report = self.run_report("contradiction.json")
        row = next(row for row in report["comparisons"] if row["stage"] == "input")
        self.assertIsNone(row["original_fnr"]["value"])
        self.assertEqual(row["original_fnr"]["excluded"], {"score_reason_contradiction_or_review": 1})
        response["score"] = .2
        detection["response_text"] = json.dumps(response)
        raw_path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "response and event differ"):
            self.run_report("tampered.json")
        self.assertFalse((self.folder / "tampered.json").exists())


if __name__ == "__main__":
    unittest.main()
