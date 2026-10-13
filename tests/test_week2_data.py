from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.testing.fixture_model import FixtureModelServer
from scripts.data_contract import ROOT, DataContractError, load_bundle
from scripts.week2_data import check_package, gold_plan, prepare


class WeekTwoDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.data = self.folder / "data"
        shutil.copytree(ROOT / "data/week2", self.data)

    def edit_json(self, name, edit):
        path = self.data / name
        value = json.loads(path.read_text(encoding="utf-8"))
        edit(value)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def edit_lines(self, name, edit):
        path = self.data / name
        values = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
        edit(values)
        path.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in values), encoding="utf-8")

    def run_fixture(self, case_id="a006", kind="detector_only"):
        runs = self.folder / "runs"
        with FixtureModelServer(self.data) as fixture:
            settings = Settings(project_root=ROOT, data_dir=self.data, runs_dir=runs,
                                model_provider="fixture_http", model_id="fixture-generation",
                                system_prompt_version="v0.1", retrieval_config_version="lexical-v0.1",
                                model_base_url=fixture.base_url, model_api_key=None,
                                d2_base_url=fixture.base_url, d2_model_id="fixture-classifier")
            with TestClient(create_app(settings)) as client:
                response = client.post("/api/v1/runs", json={"schema_version": "0.3", "artifact_type": "run_request",
                    "case_id": case_id, "scenario": "rag_chat", "defense_mode": "D2",
                    "execution_kind": kind, "dataset_version": "synthetic_v0.2", "corpus_version": "synthetic_v0.2",
                    "requested_by": "week2-data-test"})
                self.assertEqual(response.status_code, 201, response.text)
                return runs, response.json()["trace"]

    def test_package_has_separate_target_reviews_and_d2_controls(self):
        result = check_package(self.data)
        self.assertEqual((result["rag_cases"], result["email_cases"], result["d2_techniques"]), (84, 3, 6))
        self.assertEqual((result["target_reviews"], result["single_review_targets"]), (48, 48))
        self.assertFalse(result["real_model_verified"])
        self.assertEqual(result["team_agreement"], "pending")

    def test_changed_inspected_text_invalidates_gold(self):
        def change(rows):
            next(d for d in rows if d["document_id"] == "doc021")["title"] += " 변경"
        self.edit_lines("corpus.v0.1.jsonl", change)
        with self.assertRaisesRegex(DataContractError, "independent re-review"):
            check_package(self.data)

    def test_holdout_cannot_share_a_dev_document(self):
        def change(rows):
            next(c for c in rows if c["case_id"] == "a025")["source_document_ids"] = ["doc023"]
        self.edit_lines("cases.v0.1.jsonl", change)
        with self.assertRaisesRegex(DataContractError, "document content crosses"):
            check_package(self.data)

    def test_translation_keeps_original_split(self):
        self.edit_json("language-variants.v0.1.json", lambda v: v["variants"][0].update(split="holdout"))
        with self.assertRaisesRegex(DataContractError, "translation crosses"):
            check_package(self.data)

    def test_catalog_must_cover_all_attacks_exactly_once(self):
        self.edit_json("attack-catalog.v0.1.json", lambda v: v["techniques"].pop())
        with self.assertRaisesRegex(DataContractError, "every attack exactly once"):
            check_package(self.data)

    def test_email_version_is_checked_even_when_rag_is_valid(self):
        self.edit_lines("cases.email.v0.1.jsonl", lambda v: v[0].update(source_version="stale-email"))
        with self.assertRaisesRegex(DataContractError, "email case scenario/version"):
            check_package(self.data)

    def test_gold_cannot_reference_an_unrelated_document(self):
        self.edit_lines("target-gold.v0.1.jsonl", lambda rows: rows[1].update(target_ref="doc012"))
        with self.assertRaisesRegex(DataContractError, "unrelated document"):
            check_package(self.data)

    def test_email_and_bilingual_snapshots_are_executable_and_versioned(self):
        email = load_bundle(prepare(self.data, self.folder / "email", "email"))
        self.assertEqual((len(email.cases), email.manifest.scenario), (3, "email_summary"))
        bilingual = load_bundle(prepare(self.data, self.folder / "bilingual", "bilingual"))
        self.assertEqual(len(bilingual.cases), 87)
        self.assertEqual(bilingual.manifest.dataset_version, "synthetic_v0.2-bilingual-v0.1")
        english = bilingual.cases["h007-en"]
        self.assertEqual((english.language, english.split, english.source_document_ids), ("en", "dev", ["doc011"]))
        self.assertEqual(english.success_criterion, bilingual.cases["h007"].success_criterion)

    def test_preparation_does_not_overwrite_an_existing_directory(self):
        output = self.folder / "existing"
        output.mkdir()
        sentinel = output / "sentinel"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(DataContractError, "already exists"):
            prepare(self.data, output, "email")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_single_review_plan_requires_explicit_opt_in_and_keeps_target_labels(self):
        runs, _ = self.run_fixture()
        pending = gold_plan(self.data, runs)
        self.assertEqual(len(pending["updates"]), 0)
        self.assertEqual({r["reason"] for r in pending["excluded"]}, {"team_review_pending"})
        plan = gold_plan(self.data, runs, include_single_review=True)
        self.assertEqual({(r["stage"], r["body"]["gold_label"]) for r in plan["updates"]},
                         {("input", "benign"), ("retrieval", "malicious")})
        self.assertFalse(plan["applied"])

    def test_gold_plan_rejects_changed_wire_text(self):
        runs, trace = self.run_fixture()
        path = runs / (trace["run_id"] + ".raw.json")
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["model_calls"][0]["messages"][1]["content"] = json.dumps({"stage": "input", "text": "different input"})
        path.write_text(json.dumps(raw), encoding="utf-8")
        plan = gold_plan(self.data, runs, include_single_review=True)
        self.assertEqual(len(plan["updates"]), 1)
        self.assertEqual(plan["excluded"][0]["reason"], "inspected_text_hash_mismatch")

    def test_uninspected_documents_are_absent_from_gold_plan(self):
        runs, trace = self.run_fixture("a021", "full_pipeline")
        self.assertEqual(trace["status"], "blocked")
        plan = gold_plan(self.data, runs, include_single_review=True)
        self.assertEqual([(r["stage"], r["target_ref"]) for r in plan["updates"]], [("input", None)])


if __name__ == "__main__":
    unittest.main()
