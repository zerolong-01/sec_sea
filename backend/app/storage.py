"""Durable JSON replacement, tolerating short Windows read-sharing locks."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


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
