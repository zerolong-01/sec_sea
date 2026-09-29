from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.models import CaseRecord
from app.repository import ArtifactValidationError, ExperimentRepository


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


if __name__ == "__main__":
    unittest.main()
