from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .models import CaseRecord, RunTrace, SourceDocument
from .shared_variables import CANONICAL_PATHS, KEYS

ModelType = TypeVar("ModelType", bound=BaseModel)


class RepositoryError(Exception):
    """Base class for controlled data and run-store errors."""


class ArtifactNotFound(RepositoryError):
    pass


class ArtifactValidationError(RepositoryError):
    pass


def _read_jsonl(
    path: Path, model_type: type[ModelType], identifier_field: str
) -> list[ModelType]:
    if not path.exists():
        raise ArtifactNotFound(f"필수 데이터 파일이 없습니다: {path}")

    records: list[ModelType] = []
    identifiers: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = model_type.model_validate_json(line)
        except (ValidationError, json.JSONDecodeError) as exc:
            raise ArtifactValidationError(
                f"{path.name} {line_number}번째 줄이 통합 스키마와 맞지 않습니다: {exc}"
            ) from exc
        identifier = getattr(record, identifier_field)
        if identifier in identifiers:
            raise ArtifactValidationError(
                f"{path.name} line {line_number} contains a duplicate "
                f"{identifier_field}: {identifier}"
            )
        identifiers.add(identifier)
        records.append(record)
    return records


class ExperimentRepository:
    """Loads versioned case and corpus artifacts without mutating them."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    @property
    def cases_path(self) -> Path:
        return self._data_dir / Path(CANONICAL_PATHS["CASES"]).name

    @property
    def corpus_path(self) -> Path:
        return self._data_dir / Path(CANONICAL_PATHS["CORPUS"]).name

    def get_case(self, case_id: str) -> CaseRecord:
        for case in _read_jsonl(self.cases_path, CaseRecord, KEYS["CASE_ID"]):
            if case.case_id == case_id:
                return case
        raise ArtifactNotFound(f"case_id를 찾을 수 없습니다: {case_id}")

    def get_documents(
        self, document_ids: list[str], corpus_version: str
    ) -> list[SourceDocument]:
        documents = _read_jsonl(self.corpus_path, SourceDocument, KEYS["DOCUMENT_ID"])
        by_id = {document.document_id: document for document in documents}

        requested_ids = document_ids or list(by_id)
        result: list[SourceDocument] = []
        for document_id in requested_ids:
            document = by_id.get(document_id)
            if document is None:
                raise ArtifactNotFound(f"document_id를 찾을 수 없습니다: {document_id}")
            if document.source_version != corpus_version:
                raise ArtifactValidationError(
                    f"문서 {document_id}의 source_version({document.source_version})이 "
                    f"요청 corpus_version({corpus_version})과 다릅니다."
                )
            result.append(document)
        return result


class RunTraceStore:
    """Persists presentation-safe traces and private raw execution logs separately."""

    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir

    def save(self, trace: RunTrace) -> Path:
        target = self._runs_dir / f"{trace.run_id}.trace.json"
        return self._save_json(target, trace.model_dump(mode="json", by_alias=True))

    def save_raw(self, run_id: str, raw_log: dict[str, object]) -> Path:
        """Save a local-only raw log. This artifact is never returned by the API."""

        target = self._runs_dir / f"{run_id}.raw.json"
        return self._save_json(target, raw_log)

    def _save_json(self, target: Path, payload: object) -> Path:
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    def get(self, run_id: str) -> RunTrace:
        path = self._runs_dir / f"{run_id}.trace.json"
        if not path.exists():
            raise ArtifactNotFound(f"run_id를 찾을 수 없습니다: {run_id}")
        try:
            return RunTrace.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise ArtifactValidationError(
                f"저장된 trace가 통합 스키마와 맞지 않습니다: {run_id}"
            ) from exc
