from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import BatchRunner
from backend.app.batch_models import BatchSpec
from backend.app.config import Settings
from backend.app.prompts import prepare_prompt
from backend.app.shared_variables import Scenario
from backend.testing.fixture_model import FixtureModelServer
from scripts.data_contract import ROOT, DataContractError, load_bundle
from scripts.week3_prepare import prepare, validate
from scripts.week3_pipeline import verify
from scripts.verify_real_api import VerificationError


class Week3PreparationTests(unittest.TestCase):
    def test_compiled_cases_keep_payloads_and_sources_separate_and_labels_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "prepared"
            result = prepare(output)
            self.assertEqual((result["selected_rag_cases"], result["selected_email_cases"], result["planned_runs"]), (15, 3, 324))
            self.assertEqual(validate(output), result)
            bundle = load_bundle(output / "rag")
            original = load_bundle(ROOT / "data/week2")
            spec = BatchSpec.model_validate_json((output / "batch-spec.json").read_text(encoding="utf-8"))
            selected = spec.sources[0].case_ids
            self.assertEqual(len(set(selected)), 15)
            self.assertTrue(all(bundle.cases[k].split == "dev" for k in selected))
            self.assertEqual(bundle.cases["w3_a006_instruction_removed"].label, "benign")
            self.assertEqual(bundle.cases["w3_a001_instruction_removed"].label, "attack")
            self.assertEqual(bundle.cases["w3_a021_d2_instruction_removed"].label, "attack")
            self.assertEqual(bundle.cases["w3_a021_all_attack_removed"].attack_goal, None)
            for parent in ("a001", "a006", "a021"):
                case = bundle.cases["w3_" + parent + "_original"]
                self.assertEqual(case.user_input, original.cases[parent].user_input)
                self.assertEqual([bundle.documents[d].content for d in case.source_document_ids],
                                 [original.documents[d].content for d in original.cases[parent].source_document_ids])
            protected = [bundle.cases["w3pv_" + c] for c in ("c00", "c01", "a10", "a11")]
            self.assertEqual(len({c.user_input for c in protected}), 1)
            self.assertEqual(len({bundle.documents[c.source_document_ids[0]].title for c in protected}), 1)
            self.assertEqual(len({c.source_document_ids[0] for c in protected}), 4)
            for case in protected:
                docs = [bundle.documents[d] for d in case.source_document_ids]
                for d in docs:
                    self.assertRegex(d.document_id, r"^doc[0-9a-f]{16}$")
                prompt = prepare_prompt(case.user_input, docs, Scenario.RAG_CHAT, d1=True)
                sent = json.dumps([m.model_dump() for m in prompt.messages], ensure_ascii=False)
                for excluded in ("w3pv_", "parent-a006-protected", '"condition"', '"label"', "review_status", "expected_protected_value"):
                    self.assertNotIn(excluded, sent)
            before = result["generated_sha256"]
            another = prepare(Path(temp) / "second")
            self.assertEqual({k: v for k, v in before.items() if k != "batch-spec.json"},
                             {k: v for k, v in another["generated_sha256"].items() if k != "batch-spec.json"})
            (output / "rag/corpus.v0.1.jsonl").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(DataContractError, "hash mismatch"):
                validate(output)

    def test_http_pipeline_resume_exact_output_measurement_and_no_paid_refresh(self):
        with tempfile.TemporaryDirectory() as temp, FixtureModelServer(ROOT / "data/week2") as fixture:
            folder = Path(temp)
            pricing = folder / "pricing.json"
            pricing.write_text(json.dumps({"version": "test-only", "currency": "USD", "models": [
                {"model_id": model, "input_usd_per_million": .4, "output_usd_per_million": 1.6,
                 "source_url": "https://example.invalid/test", "effective_date": "2026-10-20", "verified": True}
                for model in ("fixture-generation", "fixture-classifier")]}), encoding="utf-8")
            settings = Settings(project_root=ROOT, data_dir=ROOT / "data/week2", runs_dir=folder / "unused",
                model_provider="fixture_http", model_id="fixture-generation", system_prompt_version="v0.1",
                retrieval_config_version="lexical-v0.1", model_base_url=fixture.base_url,
                model_api_key="private-fixture-key", d2_model_id="fixture-classifier", pricing_path=pricing)
            fixture.generation_text = "CANARY_PRIVATE_6F83B2"
            output = folder / "pipeline"
            partial = verify(output, settings=settings, max_items=2, allow_fixture=True)
            self.assertEqual((partial["status"], partial["planned_runs"]), ("paused", 324))
            before = len(fixture.requests)
            replay = verify(output, settings=settings, allow_fixture=True, report_only=True)
            self.assertEqual(len(fixture.requests), before)
            self.assertEqual(partial, replay)
            with patch("scripts.week3_pipeline.file_hash", return_value="changed"):
                with self.assertRaisesRegex(VerificationError, "PIPELINE_IMPLEMENTATION_CHANGED"):
                    verify(output, settings=settings, allow_fixture=True)
            self.assertEqual(len(fixture.requests), before)
            final = verify(output, settings=settings, allow_fixture=True)
            self.assertEqual((final["status"], final["execution_scope"], final["real_model_verified"]), ("passed", "fixture", False))
            runner = BatchRunner(replace(settings, runs_dir=output / "runs"))
            state = runner.store.get(final["batch_id"])
            self.assertTrue(all(len(e["attempts"]) == 1 for e in state.plan))
            observed = json.loads((output / "exact-observations.json").read_text(encoding="utf-8"))
            a11 = [r for r in observed["observations"] if r["variant"] == "A11"]
            self.assertTrue(all(r["exact_target_exposed"] is True for r in a11))
            self.assertTrue(all(r["human_review"] == "pending" for r in observed["observations"]))
            for pair in observed["paired_comparisons"]:
                self.assertEqual(pair["exact_target_exposure_delta"]["denominator"], 3)
                self.assertIsNone(pair["exact_target_exposure_delta"]["ci95"])
            self.assertEqual(len(fixture.requests), final["reconciled_calls"])
            before = len(fixture.requests)
            self.assertEqual(verify(output, settings=settings, allow_fixture=True), final)
            self.assertEqual(len(fixture.requests), before)
            self.assertFalse((runner.store.folder(state.batch_id) / "reviews.json").exists())
            for path in (output / "public-samples").glob("*.json"):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("CANARY_PRIVATE_6F83B2", text)
                self.assertNotIn(settings.model_api_key, text)


if __name__ == "__main__":
    unittest.main()
