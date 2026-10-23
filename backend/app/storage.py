"""Durable JSON replacement, tolerating short Windows read-sharing locks."""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class ConcurrentWriterError(ValueError):
    """Another process or thread currently owns this writer session."""


@contextmanager
def exclusive_file_lock(path: Path):
    """Nonblocking OS lock, released on crash; the file is never a PID lease."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ConcurrentWriterError("Already has an active writer") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + 1
        while True:
            try:
                temporary.replace(path)
                break
            except PermissionError as exc:
                # Python read handles on Windows can temporarily deny replace.
                # A persistent ACL/filesystem error still fails; never report a
                # reservation durable unless the replacement actually succeeds.
                if os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32) or time.monotonic() >= deadline:
                    raise
                time.sleep(.01)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path
