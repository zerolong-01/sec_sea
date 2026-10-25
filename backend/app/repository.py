from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .models import RUN_ID_PATTERN, CaseRecord, RunTrace, SourceDocument
from .shared_variables import CANONICAL_PATHS, KEYS
from .storage import atomic_json, exclusive_file_lock

ModelType = TypeVar("ModelType", bound=BaseModel)


class RepositoryError(Exception):
    """Base class for controlled data and run-store errors."""


class ArtifactNotFound(RepositoryError):
    pass


class ArtifactValidationError(RepositoryError):
    pass


def _read_jsonl(
    path: Path, model_type: type[ModelType], identifier_field: str, *, content: bytes | None = None
) -> list[ModelType]:
    content = _read_data(path) if content is None else content
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise ArtifactValidationError(f"{path.name} must use UTF-8") from exc

    records: list[ModelType] = []
    identifiers: set[str] = set()
    for line_number, line in enumerate(lines, 1):
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


def _read_data(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise ArtifactNotFound(f"필수 데이터 파일이 없습니다: {path}") from exc
    except OSError as exc:
        raise ArtifactValidationError(f"Cannot read data file: {path.name}") from exc


class ExperimentRepository:
    """Loads versioned case and corpus artifacts without mutating them."""

    def __init__(self, data_dir: Path, *, expected_hashes: dict[str, str] | None = None) -> None:
        self._data_dir = data_dir
        self._expected_hashes = dict(expected_hashes or {})
        self._indexes = {}

    def _index(self, path, model_type, identifier_field):
        # Compare actual bytes rather than mtime/size. Same-size edits and
        # atomic replacements must never reuse stale cases or documents.
        content = _read_data(path)
        expected = self._expected_hashes.get(path.name)
        if expected and hashlib.sha256(content).hexdigest() != expected:
            raise ArtifactValidationError("Frozen batch data hash mismatch")
        cached = self._indexes.get(path)
        if cached is not None and cached[0] == content:
            return cached[1]
        records = _read_jsonl(path, model_type, identifier_field, content=content)
        index = {getattr(record, identifier_field): record for record in records}
        self._indexes[path] = (content, index)
        return index

    @property
    def cases_path(self) -> Path:
        return self._data_dir / Path(CANONICAL_PATHS["CASES"]).name

    @property
    def corpus_path(self) -> Path:
        return self._data_dir / Path(CANONICAL_PATHS["CORPUS"]).name

    def get_case(self, case_id: str) -> CaseRecord:
        case = self._index(self.cases_path, CaseRecord, KEYS["CASE_ID"]).get(case_id)
        if case is None:
            raise ArtifactNotFound(f"case_id를 찾을 수 없습니다: {case_id}")
        return case.model_copy(deep=True)

    def get_documents(
        self, document_ids: list[str], corpus_version: str
    ) -> list[SourceDocument]:
        by_id = self._index(self.corpus_path, SourceDocument, KEYS["DOCUMENT_ID"])

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
            result.append(document.model_copy(deep=True))
        return result


class RunTraceStore:
    """Persists presentation-safe traces and private raw execution logs separately."""

    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir

    def _path(self, run_id: str, kind: str) -> Path:
        # Use the full legacy trace ID contract, including IDs without the
        # newer run- prefix. Neither OS's path separators may enter filenames.
        if not re.fullmatch(RUN_ID_PATTERN, run_id):
            raise ValueError("Invalid run ID")
        path = self._runs_dir / f"{run_id}.{kind}.json"
        if path.is_symlink():
            raise ArtifactValidationError("Run artifacts must not be symlinks")
        return path

    @staticmethod
    def _read_json(path: Path, expected_type: type, default):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except (ValueError, UnicodeError, OSError) as exc:
            raise ArtifactValidationError(f"Invalid stored artifact: {path.name}") from exc
        if (not isinstance(payload, expected_type) or
                expected_type is list and any(not isinstance(item, dict) for item in payload)):
            raise ArtifactValidationError(f"Invalid stored artifact: {path.name}")
        return payload

    def save(self, trace: RunTrace) -> Path:
        target = self._path(trace.run_id, "trace")
        return self._save_json(target, trace.model_dump(mode="json", by_alias=True))

    def save_raw(self, run_id: str, raw_log: dict[str, object]) -> Path:
        """Save a local-only raw log. This artifact is never returned by the API."""

        target = self._path(run_id, "raw")
        return self._save_json(target, raw_log)

    def save_evaluation(self, run_id: str, evaluation: dict) -> Path:
        return self._append_history(run_id, "evaluation", evaluation)

    def save_detector_gold(self, run_id: str, evaluation: dict) -> Path:
        return self._append_history(run_id, "detector-gold", evaluation)

    def review_lock(self, run_id: str):
        """Own the entire read/update/save across independent API workers."""
        return exclusive_file_lock(self._path(run_id, "review").with_suffix(".lock"))

    def _append_history(self, run_id: str, kind: str, evaluation: dict) -> Path:
        target = self._path(run_id, kind)
        with exclusive_file_lock(target.with_suffix(".lock")):
            history = self._read_json(target, list, [])
            history.append(evaluation)
            return self._save_json(target, history)

    def get_raw(self, run_id: str) -> dict:
        payload = self._read_json(self._path(run_id, "raw"), dict, {})
        if payload.get("run_id", run_id) != run_id:
            raise ArtifactValidationError("Raw log run ID does not match its filename")
        return payload

    def _save_json(self, target: Path, payload: object) -> Path:
        return atomic_json(target, payload)

    def get(self, run_id: str) -> RunTrace:
        path = self._path(run_id, "trace")
        try:
            trace = RunTrace.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ArtifactNotFound(f"run_id를 찾을 수 없습니다: {run_id}") from exc
        except (ValidationError, UnicodeError, OSError) as exc:
            raise ArtifactValidationError(
                f"저장된 trace가 통합 스키마와 맞지 않습니다: {run_id}"
            ) from exc
        if trace.run_id != run_id:
            raise ArtifactValidationError("Trace run ID does not match its filename")
        return trace
