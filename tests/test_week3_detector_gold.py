from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import BatchRunner, file_hash
from backend.app.batch_models import BatchSpec
from backend.app.config import Settings
from backend.app.defenses import D2_SYSTEM, Detection
from backend.app.models import ChatMessage, ModelCall, RunRequest
from backend.app.providers import DemoRagProvider, OpenAICompatibleProvider, ProviderResponse
from backend.app.repository import ExperimentRepository, RunTraceStore
from backend.app.service import RunService
from scripts import week3_detector_gold as registration
from scripts.data_contract import ROOT
from scripts.week2_data import text_hash


class OfflineClassifier:
    def classify(self, text, stage, target_ref):
        detection = Detection(score=.1, reason_code="normal_request", reason="offline fixture")
        call = ModelCall(purpose="detection", target_ref=target_ref, model_id="offline-classifier",
            messages=[ChatMessage(role="system", content=D2_SYSTEM), ChatMessage(role="user",
                content=json.dumps({"stage": str(stage), "text": text}, ensure_ascii=False))],
            parameters={}, latency_ms=0, response_text=detection.model_dump_json())
        return detection, ProviderResponse(detection.model_dump_json(), None, None, None, call)


class DetectorGoldRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.runs = self.folder / "runs"
        self.gold = self.folder / "target-gold.v0.4.jsonl"
        self.output = self.folder / "plan.json"
        settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=self.runs,
            model_provider="demo", model_id="demo-rag-v0.1", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None,
            evaluation_rules_path=ROOT / "configs/evaluation-starter.json")
        runner = BatchRunner(settings)
        spec = BatchSpec.model_validate({"sources": [{"source_id": "rag", "data_dir": "data",
            "split": "dev", "case_ids": ["a006"]}], "repeats": 2,
            "conditions": [{"condition_id": mode, "defense_mode": mode, "comparisons": ["technique"]}
                           for mode in ("none", "D2")],
            "budget": {"max_calls": 30, "max_reserved_tokens": 1000000, "max_seconds": 60,
                       "unknown_price_policy": "calls_tokens"}})
        self.state = runner.create(spec)
        self.batch_id = self.state.batch_id
        self.frozen = runner.store.folder(self.batch_id)
        frozen_settings = replace(settings, data_dir=self.frozen / "inputs/rag",
            evaluation_rules_path=self.frozen / "evaluation_rules.snapshot",
            common_policy_path=self.frozen / "common_policy.snapshot")
        service = RunService(frozen_settings, ExperimentRepository(frozen_settings.data_dir),
                            RunTraceStore(self.runs), DemoRagProvider(), classifier=OfflineClassifier())
        for entry in self.state.plan:
            run_id = "run-" + self.batch_id[6:] + "-" + entry["entry_id"] + "-attempt-1"
            request = RunRequest(schema_version="0.3", artifact_type="run_request", case_id="a006",
                scenario="rag_chat", defense_mode=entry["condition_id"],
                dataset_version="synthetic_v0.1.1", corpus_version="synthetic_v0.1.1", requested_by=self.batch_id)
            trace = service.execute(request, run_id=run_id)
            entry["status"] = str(trace.status)
            entry["attempts"] = [{"run_id": run_id, "attempt_id": "fixture", "status": str(trace.status)}]
        self.state.status = "completed"
        runner.store.save(self.state)
        repository = ExperimentRepository(frozen_settings.data_dir)
        case = repository.get_case("a006")
        doc = repository.get_documents(case.source_document_ids, "synthetic_v0.1.1")[0]
        self.gold_rows = [{"case_id": "a006", "dataset_version": "synthetic_v0.1.1", "split": "dev",
            "stage": stage, "target_ref": ref, "gold_label": label, "gold_version": "fixture-source-v0.4",
            "reviewer": "Codex", "review_method": "ai_evidence_review", "review_status": "ai_authored_human_pending",
            "human_independent_review": "pending", "target_sha256": text_hash(text), "reason": reason}
            for stage, ref, label, text, reason in (
                ("input", None, "benign", case.user_input, "A legitimate task request, separate from the attack document."),
                ("retrieval", doc.document_id, "malicious", doc.title + "\n" + doc.content,
                 "An active instruction crossing the document trust boundary."))]
        self.write_gold()
        self.before = self.hashes()

    def write_gold(self):
        self.gold.write_text("".join(json.dumps(row) + "\n" for row in self.gold_rows), encoding="utf-8")

    def hashes(self):
        return {str(path): file_hash(path) for path in self.runs.rglob("*") if path.is_file()}

    def run_registration(self, *, apply=False):
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("model API called")), \
             patch.object(DemoRagProvider, "generate_prepared", side_effect=AssertionError("generation called")):
            return registration.register(self.runs, self.batch_id, self.gold, self.output, apply=apply)

    def test_plan_only_is_read_only_and_uses_inspected_target_labels_not_case_labels(self):
        result = self.run_registration()
        self.assertEqual(result["status"], "planned")
        self.assertFalse(result["applied"])
        self.assertEqual(len(result["updates"]), 4)
        self.assertEqual({row["body"]["gold_label"] for row in result["updates"] if row["stage"] == "input"}, {"benign"})
        self.assertEqual({row["body"]["gold_label"] for row in result["updates"] if row["stage"] == "retrieval"}, {"malicious"})
        self.assertTrue(all(row["body"]["reviewer"] == registration.REVIEWER for row in result["updates"]))
        self.assertTrue(all("human_independent_review=pending" in row["body"]["reason"] for row in result["updates"]))
        self.assertEqual(self.before, self.hashes())

    def test_apply_and_reapply_preserve_raw_sources_manifest_and_audit_without_duplicate_appends(self):
        applied = self.run_registration(apply=True)
        self.assertEqual(len(applied["applied_ids"]), 4)
        self.assertTrue(applied["immutable_artifacts_unchanged"])
        for run_id in {row["run_id"] for row in applied["updates"]}:
            self.assertTrue((self.runs / f"{run_id}.review.lock").is_file())
            self.assertTrue((self.runs / f"{run_id}.detector-gold.lock").is_file())
        after = self.hashes()
        for path, sha in self.before.items():
            if not path.endswith(".trace.json"):
                self.assertEqual(after[path], sha)
        for path in self.runs.glob("*.detector-gold.json"):
            history = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(history), 2)
        repeated = self.run_registration(apply=True)
        self.assertEqual(len(repeated["already_applied_ids"]), 4)
        self.assertEqual(repeated["applied_ids"], [])
        self.assertEqual(after, self.hashes())
        self.assertTrue(repeated["immutable_artifacts_unchanged"])

    def test_bad_source_or_raw_hash_is_rejected_before_any_annotation(self):
        for mutation in ("unknown_case", "dataset", "holdout", "target_hash"):
            with self.subTest(mutation=mutation):
                original = dict(self.gold_rows[-1])
                key, value = {"unknown_case": ("case_id", "unknown-case"), "dataset": ("dataset_version", "wrong"),
                    "holdout": ("split", "holdout"), "target_hash": ("target_sha256", "0" * 64)}[mutation]
                self.gold_rows[-1][key] = value
                self.write_gold()
                with self.assertRaises(ValueError):
                    self.run_registration(apply=True)
                self.assertEqual(self.before, self.hashes())
                self.gold_rows[-1] = original
        self.write_gold()
        d2_entry = next(entry for entry in self.state.plan if entry["condition_id"] == "D2")
        raw_path = self.runs / (d2_entry["attempts"][0]["run_id"] + ".raw.json")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        raw["model_calls"][-2]["messages"][1]["content"] = json.dumps({"stage": "retrieval", "text": "changed"})
        raw_path.write_text(json.dumps(raw), encoding="utf-8")
        before_rejection = self.hashes()
        with self.assertRaises(ValueError):
            self.run_registration(apply=True)
        self.assertEqual(before_rejection, self.hashes())
        self.assertEqual(list(self.runs.glob("*.detector-gold.json")), [])

    def test_partial_failure_reports_completed_and_remaining_targets_and_resume_is_idempotent(self):
        original = RunService.update_detector_gold
        calls = []

        def fail_second(service, run_id, body):
            calls.append(run_id)
            if len(calls) == 2:
                raise OSError("synthetic write failure; do not print private source")
            return original(service, run_id, body)

        with patch.object(RunService, "update_detector_gold", new=fail_second):
            partial = self.run_registration(apply=True)
        self.assertEqual(partial["status"], "partial_failure")
        self.assertEqual(len(partial["applied_ids"]), 1)
        self.assertEqual(len(partial["remaining_ids"]), 3)
        resumed = self.run_registration(apply=True)
        self.assertEqual(resumed["status"], "applied")
        self.assertEqual(len(resumed["already_applied_ids"]), 1)
        self.assertEqual(len(resumed["applied_ids"]), 3)
        self.assertEqual(resumed["remaining_ids"], [])
        self.assertEqual(sum(len(json.loads(path.read_text(encoding="utf-8")))
                             for path in self.runs.glob("*.detector-gold.json")), 4)
        self.gold_rows[0]["gold_label"] = "malicious"
        self.write_gold()
        before = self.hashes()
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.run_registration(apply=True)
        self.assertEqual(before, self.hashes())

    def test_apply_still_detects_changes_to_unrelated_lock_files(self):
        unrelated = self.runs / "unrelated.lock"
        unrelated.write_bytes(b"unchanged")
        original = RunService.update_detector_gold

        def mutate_unrelated(service, run_id, body):
            result = original(service, run_id, body)
            unrelated.write_bytes(b"changed")
            return result

        with patch.object(RunService, "update_detector_gold", new=mutate_unrelated):
            result = self.run_registration(apply=True)
        self.assertEqual(result["status"], "partial_failure")
        self.assertFalse(result["immutable_artifacts_unchanged"])
        self.assertEqual(result["error_type"], "ImmutableArtifactChanged")
        self.assertEqual(len(result["applied_ids"]), 1)

    def test_cli_defaults_to_plan_and_prints_only_status_counts_and_hash(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), patch.dict("os.environ", {"MODEL_TEMPERATURE": "invalid"}):
            code = registration.main(["--runs-dir", str(self.runs), "--batch-id", self.batch_id,
                                      "--gold", str(self.gold), "--output", str(self.output)])
        self.assertEqual(code, 0)
        printed = json.loads(stdout.getvalue())
        self.assertEqual(printed["status"], "planned")
        self.assertEqual(printed["model_calls"], 0)
        self.assertEqual(printed["gold_sha256"], file_hash(self.gold))
        self.assertNotIn("a006", stdout.getvalue())
        self.assertNotIn("legitimate", stdout.getvalue())
        self.assertEqual(self.before, self.hashes())
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = registration.main(["--runs-dir", str(self.runs), "--batch-id", "batch-000000000000",
                                      "--gold", str(self.gold), "--output", str(self.folder / "other-plan.json")])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue()), {"status": "preflight_rejected", "error_type": "ArtifactNotFound"})
        self.assertEqual(self.before, self.hashes())


if __name__ == "__main__":
    unittest.main()
