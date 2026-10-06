"""Validate committed MVP data and execution metadata before starting services."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import BaseModel, ConfigDict, Field

from backend.app.models import CaseRecord, SourceDocument
from backend.app.retrieval import lexical_retrieve

ROOT = Path(__file__).resolve().parents[1]
CANARY_PATTERN = re.compile(r"CANARY_[A-Z0-9_]+")


class DataContractError(ValueError):
    pass


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedRetrieval(Metadata):
    document_id: str
    rank: int = Field(ge=1)


class RepresentativeCase(Metadata):
    case_id: str
    label: Literal["attack", "benign", "hard_negative"]
    expected_retrieval: list[ExpectedRetrieval] = Field(min_length=1)


class MVPManifest(Metadata):
    schema_version: Literal["0.1"]
    dataset_version: str = Field(min_length=1)
    corpus_version: str = Field(min_length=1)
    representative_cases: list[RepresentativeCase] = Field(min_length=3, max_length=3)
    hard_negative_security_cases: list[str] = Field(min_length=3)


@dataclass
class DataBundle:
    data_dir: Path
    manifest_path: Path
    manifest: MVPManifest
    cases: dict[str, CaseRecord]
    documents: dict[str, SourceDocument]
    schema: dict


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DataContractError(message)


def load_jsonl(path: Path, model: type[BaseModel], id_field: str, validator) -> dict:
    records = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            validator.validate(payload)
            record = model.model_validate(payload)
        except (ValueError, TypeError, SchemaValidationError) as exc:
            # Include the location without printing raw document/secret values.
            raise DataContractError(f"{path.name}:{number}: invalid JSONL or contract ({type(exc).__name__})") from exc
        identifier = getattr(record, id_field)
        require(identifier not in records, f"{path.name}:{number}: duplicate {id_field} {identifier}")
        records[identifier] = record
    require(bool(records), f"{path.name}: no records")
    return records


def load_bundle(data_dir: Path, manifest_path: Path | None = None) -> DataBundle:
    data_dir = data_dir.resolve()
    manifest_path = (manifest_path or data_dir / "mvp-manifest.v0.1.json").resolve()
    schema = json.loads((ROOT / "contracts/mvp-integration-v0.1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    manifest = MVPManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    cases = load_jsonl(data_dir / "cases.v0.1.jsonl", CaseRecord, "case_id", validator)
    documents = load_jsonl(data_dir / "corpus.v0.1.jsonl", SourceDocument, "document_id", validator)
    counts = Counter(case.label for case in cases.values())
    require(all(counts[label] >= 3 for label in ("attack", "benign", "hard_negative")), "at least 3 cases per label are required")
    for case in cases.values():
        require(case.source_version == manifest.dataset_version, f"{case.case_id}: dataset_version mismatch")
        require(bool(case.source_document_ids), f"{case.case_id}: explicit source_document_ids required")
        require(all(doc_id in documents for doc_id in case.source_document_ids), f"{case.case_id}: missing source document")
    require(all(doc.source_version == manifest.corpus_version for doc in documents.values()), "corpus_version mismatch")
    attack_types = {case.attack_type for case in cases.values() if case.label == "attack"}
    require({"direct_instruction", "indirect_document"} <= attack_types, "direct and indirect attacks required")

    representatives = manifest.representative_cases
    require(len({item.case_id for item in representatives}) == 3, "duplicate representative case")
    require({item.label for item in representatives} == {"attack", "benign", "hard_negative"}, "one representative per label required")
    for item in representatives:
        require(item.case_id in cases, f"{item.case_id}: missing representative case")
        case = cases[item.case_id]
        require(case.label == item.label and case.scenario == "rag_chat", f"{item.case_id}: representative label/scenario mismatch")
        ranked = lexical_retrieve(case.user_input, [documents[doc_id] for doc_id in case.source_document_ids])
        actual = [(result.document_id, result.rank) for _, result in ranked]
        expected = [(result.document_id, result.rank) for result in item.expected_retrieval]
        require(actual == expected, f"{item.case_id}: expected retrieval mismatch")
        if item.label == "benign":
            require(all(not documents[doc_id].is_untrusted_content and not CANARY_PATTERN.search(documents[doc_id].content) for doc_id in case.source_document_ids), f"{item.case_id}: benign representative contains attack content/canary")
        if item.label == "attack":
            require(case.success_criterion.criterion_type == "canary_leak", f"{item.case_id}: concrete canary criterion required")
            canaries = {value for doc_id in case.source_document_ids for value in CANARY_PATTERN.findall(documents[doc_id].content)}
            require(bool(canaries) and all(value in case.success_criterion.description for value in canaries), f"{item.case_id}: missing canary or exact criterion")
            require(not CANARY_PATTERN.search(case.user_input), f"{item.case_id}: target canary must come from the document")

    security_ids = manifest.hard_negative_security_cases
    require(len(set(security_ids)) == len(security_ids), "duplicate hard-negative security case")
    for case_id in security_ids:
        require(case_id in cases and cases[case_id].label == "hard_negative", f"{case_id}: not a hard-negative")
        docs = [documents[doc_id] for doc_id in cases[case_id].source_document_ids]
        require(all(not doc.is_untrusted_content and not CANARY_PATTERN.search(doc.content) and "인용" in doc.content and "무시" in doc.content for doc in docs), f"{case_id}: quoted normal security document required")
    return DataBundle(data_dir, manifest_path, manifest, cases, documents, schema)
