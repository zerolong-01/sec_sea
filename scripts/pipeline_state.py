"""Own one pipeline output across preparation, checkpointing and verification."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path

from backend.app.storage import ConcurrentWriterError, atomic_json, exclusive_file_lock


class VerificationError(Exception):
    """Only controlled error identifiers may reach a verification CLI."""


def require(condition, code):
    if not condition:
        raise VerificationError(code)


@contextmanager
def record_verification_failure(output: Path, version: str, *, marker: str, version_key="version"):
    """A failed refresh must not leave a stale passed completion record."""
    try:
        yield
    except (Exception, KeyboardInterrupt) as exc:
        try:
            owned = json.loads((output / marker).read_text(encoding="utf-8")).get(version_key) == version
        except (ValueError, OSError, AttributeError):
            owned = False
        if owned:
            atomic_json(output / "verification-report.json", {"version": version, "status": "failed",
                "error": str(exc) if isinstance(exc, VerificationError) else type(exc).__name__})
        raise


@contextmanager
def locked_output(output: Path, marker: str, *, read_only=False):
    """Lock before discovering/creating a batch, so two plans cannot be charged."""
    ownership = output / marker
    if read_only:
        require(ownership.is_file(), "PIPELINE_NOT_CREATED")
    elif not ownership.exists():
        require(not output.exists() or not any(p.name != ".pipeline.lock" for p in output.iterdir()),
                "OUTPUT_DIRECTORY_NOT_OWNED")
    try:
        with exclusive_file_lock(output / ".pipeline.lock"):
            yield
    except ConcurrentWriterError as exc:
        raise VerificationError("PIPELINE_ALREADY_RUNNING") from exc
