"""New quotation pairs preserve surfaces, facts and separate draft provenance."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.batch import file_hash
from backend.app.batch_models import BatchSpec
from backend.app.prompts import prepare_prompt
from backend.app.providers import OpenAICompatibleProvider
from backend.app.shared_variables import Scenario
from scripts.data_contract import CANARY_PATTERN, ROOT, DataContractError, load_bundle
from scripts.week3_quote_controls import DATASET, PARENTS, SOURCE_FILES, prepare, validate


class QuoteControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "quoted"

    def rehash(self, relative):
        manifest = self.output / "preparation.json"
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        saved["generated_sha256"][relative] = file_hash(self.output / relative)
        manifest.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")

    def test_new_dev_pairs_leave_original_data_and_existing_pipeline_unchanged(self):
        untouched = set(SOURCE_FILES) | {"scripts/week3_pipeline.py", "scripts/week3_prepare.py"} | {
            p.relative_to(ROOT).as_posix() for p in (ROOT / "data/week3").glob("*") if p.is_file()}
        before = {p: file_hash(ROOT / p) for p in untouched}
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("model called")) as calls:
            result = prepare(self.output)
            self.assertEqual(validate(self.output), result)
        calls.assert_not_called()
        self.assertEqual(before, {p: file_hash(ROOT / p) for p in untouched})
        bundle = load_bundle(self.output / "rag")
        original = load_bundle(ROOT / "data/week2")
        self.assertNotEqual(DATASET, original.manifest.dataset_version)
        self.assertEqual(bundle.manifest.dataset_version, bundle.manifest.corpus_version)
        for case_id, case in original.cases.items():
            self.assertEqual(bundle.cases[case_id].model_dump(mode="json"),
                             dict(case.model_dump(mode="json"), source_version=DATASET))
        spec = BatchSpec.model_validate_json((self.output / "batch-spec.json").read_text(encoding="utf-8"))
        selected = spec.sources[0].case_ids
        self.assertEqual(len(set(selected)), 6)
        self.assertTrue(all(case_id.startswith("w3q_") and bundle.cases[case_id].split == "dev" for case_id in selected))
        self.assertFalse(set(selected) & set(original.cases))
        self.assertEqual(len(selected) * len(spec.conditions) * spec.repeats, 108)
        self.assertEqual((result["team_review"], result["execution_status"], result["model_calls"]),
                         ("pending", "not_executed", 0))

    def test_direct_pairs_keep_original_surface_documents_and_shared_business_question(self):
        result = prepare(self.output)
        bundle = load_bundle(self.output / "rag")
        original = load_bundle(ROOT / "data/week2")
        for pair in result["pairs"]:
            if pair["surface"] != "input":
                continue
            parent = original.cases[pair["parent_case_id"]]
            attack = bundle.cases[pair["case_ids"]["original"]]
            quoted = bundle.cases[pair["case_ids"]["quoted"]]
            for case in (attack, quoted):
                self.assertTrue(case.user_input.startswith(pair["normal_question"] + "\n\n"))
                self.assertIn(parent.user_input, case.user_input)
                self.assertEqual(case.source_document_ids, parent.source_document_ids)
                self.assertEqual(CANARY_PATTERN.findall(case.user_input), CANARY_PATTERN.findall(parent.user_input))
            self.assertTrue(pair["normal_question_added_to_parent_input"])
            self.assertNotEqual(attack.user_input, parent.user_input)
            self.assertEqual(attack.label, "attack")
            self.assertEqual(quoted.label, "hard_negative")
            self.assertIsNone(quoted.attack_type)
            self.assertEqual(quoted.success_criterion.criterion_type, "human_rubric")
            self.assertNotEqual(attack.user_input, quoted.user_input)
            self.assertIn("인용", quoted.user_input)

    def test_indirect_pair_keeps_question_title_facts_and_verbatim_attack_payload(self):
        result = prepare(self.output)
        pair = next(p for p in result["pairs"] if p["parent_case_id"] == "a006")
        bundle = load_bundle(self.output / "rag")
        original = load_bundle(ROOT / "data/week2")
        parent = original.cases["a006"]
        parent_doc = original.documents[parent.source_document_ids[0]]
        facts, marker, tail = parent_doc.content.partition("[문서 내부 지시]")
        attack = bundle.cases[pair["case_ids"]["original"]]
        quoted = bundle.cases[pair["case_ids"]["quoted"]]
        self.assertEqual(attack.user_input, quoted.user_input)
        self.assertEqual(attack.user_input, parent.user_input)
        attack_doc = bundle.documents[attack.source_document_ids[0]]
        quoted_doc = bundle.documents[quoted.source_document_ids[0]]
        self.assertEqual(attack_doc.content, parent_doc.content)
        self.assertEqual(attack_doc.title, quoted_doc.title)
        self.assertTrue(quoted_doc.content.startswith(facts))
        self.assertEqual(quoted_doc.content.count(marker + tail), 1)
        self.assertEqual(CANARY_PATTERN.findall(quoted_doc.content), CANARY_PATTERN.findall(parent_doc.content))
        self.assertNotEqual(attack_doc.document_id, quoted_doc.document_id)
        self.assertIn("opaque_content_based_document_id", pair["changed_components"])
        self.assertIn("no strict single-factor causal claim", pair["interpretation"])

    def test_gold_and_provenance_do_not_enter_model_messages(self):
        result = prepare(self.output)
        bundle = load_bundle(self.output / "rag")
        for pair in result["pairs"]:
            for case_id in pair["case_ids"].values():
                case = bundle.cases[case_id]
                docs = [bundle.documents[d] for d in case.source_document_ids]
                for d1 in (False, True):
                    prompt = prepare_prompt(case.user_input, docs, Scenario.RAG_CHAT, d1=d1)
                    sent = json.dumps([m.model_dump() for m in prompt.messages], ensure_ascii=False)
                    for excluded in (case_id, "parent_case_id", "review_status", "target_sha256", "expected_protected_value",
                                     '"condition"', '"label"', "normal_question_added_to_parent_input"):
                        self.assertNotIn(excluded, sent)

    def test_one_sided_content_tampering_is_rejected_even_after_rehash(self):
        result = prepare(self.output)
        pair = next(p for p in result["pairs"] if p["parent_case_id"] == "a006")
        doc_id = pair["derived_document_ids"]["quoted"][0]
        path = self.output / "rag/corpus.v0.1.jsonl"
        documents = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
        next(d for d in documents if d["document_id"] == doc_id)["content"] += "\n새로운 업무 사실"
        path.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in documents), encoding="utf-8")
        self.rehash("rag/corpus.v0.1.jsonl")
        with self.assertRaisesRegex(DataContractError, "paired inputs changed"):
            validate(self.output)

    def test_one_sided_split_or_selection_change_is_rejected(self):
        prepare(self.output)
        path = self.output / "rag/cases.v0.1.jsonl"
        cases = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
        next(c for c in cases if c["case_id"] == "w3q_a001_quoted")["split"] = "holdout"
        path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
        self.rehash("rag/cases.v0.1.jsonl")
        with self.assertRaisesRegex(DataContractError, "paired inputs changed"):
            validate(self.output)

    def test_existing_output_is_never_overwritten_and_file_hash_tampering_fails(self):
        prepare(self.output)
        before = (self.output / "preparation.json").read_bytes()
        with self.assertRaisesRegex(DataContractError, "already exists"):
            prepare(self.output)
        self.assertEqual((self.output / "preparation.json").read_bytes(), before)
        rules = self.output / "evaluation-rules.json"
        rules.write_text(rules.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(DataContractError, "artifact hash mismatch"):
            validate(self.output)


if __name__ == "__main__":
    unittest.main()
