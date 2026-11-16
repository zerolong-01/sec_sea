from __future__ import annotations

import json
import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from pydantic import ValidationError

from app.models import CaseRecord
from app.repository import ArtifactNotFound, ArtifactValidationError, ExperimentRepository, RunTraceStore, _read_jsonl


class RepositoryIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary_directory.name)
        self.repository = ExperimentRepository(self.data_dir)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def case(case_id: str = "case-001", document_ids: list[str] | None = None) -> dict:
        return {
            "schema_version": "0.1",
            "artifact_type": "case",
            "case_id": case_id,
            "scenario": "rag_chat",
            "language": "en",
            "split": "dev",
            "label": "benign",
            "user_input": "Summarize the policy.",
            "source_document_ids": document_ids or ["doc-001"],
            "attack_type": None,
            "attack_goal": None,
            "expected_normal_task": "Summarize the policy.",
            "success_criterion": {
                "criterion_type": "task_quality",
                "description": "The answer cites the supplied policy.",
            },
            "source_version": "cases-v0.1",
        }

    @staticmethod
    def document(document_id: str = "doc-001") -> dict:
        return {
            "schema_version": "0.1",
            "artifact_type": "source_document",
            "document_id": document_id,
            "title": "Policy",
            "content": "The policy requires a security review.",
            "language": "en",
            "source_type": "seed_corpus",
            "source_version": "corpus-v0.1",
            "is_untrusted_content": True,
        }

    def write_jsonl(self, name: str, records: list[dict]) -> None:
        (self.data_dir / name).write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )

    def test_case_rejects_duplicate_document_references(self) -> None:
        with self.assertRaises(ValidationError):
            CaseRecord.model_validate(self.case(document_ids=["doc-001", "doc-001"]))

    def test_repository_rejects_duplicate_case_ids(self) -> None:
        self.write_jsonl(
            "cases.v0.1.jsonl", [self.case(), self.case("case-001")]
        )

        with self.assertRaises(ArtifactValidationError):
            self.repository.get_case("case-001")

    def test_repository_rejects_duplicate_document_ids(self) -> None:
        self.write_jsonl("corpus.v0.1.jsonl", [self.document(), self.document("doc-001")])

        with self.assertRaises(ArtifactValidationError):
            self.repository.get_documents(["doc-001"], "corpus-v0.1")


    def test_run_store_rejects_invalid_ids_before_reading_or_writing(self):
        store = RunTraceStore(self.data_dir / "runs")
        for run_id in ("../outside", "..\\outside", "/absolute", "run-test\n", "x", "run-" + "a" * 61):
            for method, args in ((store.get, ()), (store.get_raw, ()),
                                 (store.save_raw, ({},)), (store.save_evaluation, ({},)),
                                 (store.save_detector_gold, ({},))):
                with self.subTest(run_id=run_id, method=method.__name__), self.assertRaises(ValueError):
                    method(run_id, *args)
        self.assertFalse((self.data_dir / "runs").exists())

    def test_corrupt_private_artifacts_fail_without_overwriting_history(self):
        store = RunTraceStore(self.data_dir)
        for suffix, reader in (("raw", lambda: store.get_raw("run-test")),
                               ("evaluation", lambda: store.save_evaluation("run-test", {})),
                               ("detector-gold", lambda: store.save_detector_gold("run-test", {}))):
            path = self.data_dir / f"run-test.{suffix}.json"
            for payload in (b"{invalid", b"null", b"42", b"\xff"):
                with self.subTest(suffix=suffix, payload=payload):
                    path.write_bytes(payload)
                    with self.assertRaises(ArtifactValidationError):
                        reader()
                    self.assertEqual(path.read_bytes(), payload)

    def test_run_store_refuses_symlink_artifacts(self):
        outside = self.data_dir / "outside.json"
        outside.write_text('{"private":"sentinel"}', encoding="utf-8")
        runs = self.data_dir / "runs"
        runs.mkdir()
        try:
            (runs / "run-test.raw.json").symlink_to(outside)
        except OSError:
            self.skipTest("OS does not allow creating symlinks")
        with self.assertRaises(ArtifactValidationError):
            RunTraceStore(runs).get_raw("run-test")

    def test_raw_identity_and_legacy_trace_ids_are_validated(self):
        store = RunTraceStore(self.data_dir)
        store.save_raw("legacy-001", {"run_id": "legacy-001"})
        self.assertEqual(store.get_raw("legacy-001"), {"run_id": "legacy-001"})
        store.save_raw("run-swapped", {"run_id": "run-other"})
        with self.assertRaises(ArtifactValidationError):
            store.get_raw("run-swapped")

    def test_indexes_parse_unchanged_bytes_once_and_return_independent_models(self):
        self.write_jsonl("cases.v0.1.jsonl", [self.case()])
        self.write_jsonl("corpus.v0.1.jsonl", [self.document()])
        with patch("app.repository._read_jsonl", wraps=_read_jsonl) as parse:
            for _ in range(5):
                case = self.repository.get_case("case-001")
                case.source_document_ids.clear()
                doc = self.repository.get_documents(["doc-001"], "corpus-v0.1")[0]
                doc.content = "caller mutation"
            self.assertEqual(parse.call_count, 2)
        self.assertEqual(self.repository.get_case("case-001").source_document_ids, ["doc-001"])
        self.assertEqual(self.repository.get_documents(["doc-001"], "corpus-v0.1")[0].content,
                         self.document()["content"])

    def test_same_size_same_timestamp_change_invalidates_index_and_bad_updates_fail(self):
        self.write_jsonl("cases.v0.1.jsonl", [self.case()])
        path = self.repository.cases_path
        self.assertEqual(self.repository.get_case("case-001").user_input, "Summarize the policy.")
        stamp = path.stat()
        changed = path.read_bytes().replace(b"Summarize", b"SUMMARIZE")
        path.write_bytes(changed)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertEqual(self.repository.get_case("case-001").user_input, "SUMMARIZE the policy.")
        path.write_bytes(changed + changed)
        with self.assertRaises(ArtifactValidationError):
            self.repository.get_case("case-001")
        path.unlink()
        with self.assertRaises(ArtifactNotFound):
            self.repository.get_case("case-001")

    def test_frozen_repository_rejects_changed_bytes_even_after_index_is_warm(self):
        self.write_jsonl("cases.v0.1.jsonl", [self.case()])
        path = self.repository.cases_path
        repository = ExperimentRepository(self.data_dir,
            expected_hashes={path.name: hashlib.sha256(path.read_bytes()).hexdigest()})
        repository.get_case("case-001")
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ArtifactValidationError, "Frozen batch data"):
            repository.get_case("case-001")


if __name__ == "__main__":
    unittest.main()
