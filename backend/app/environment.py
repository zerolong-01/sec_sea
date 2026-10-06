"""Load only the repository's local .env; existing process settings take priority."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_project_environment(project_root: Path = PROJECT_ROOT) -> bool:
    # The launcher passes its merged environment to child processes. Do not
    # reload local real-model credentials into an isolated verification profile.
    if os.getenv("MVP_LOAD_DOTENV") == "0":
        return False
    return load_dotenv(project_root / ".env", override=False, encoding="utf-8-sig", interpolate=False)


def resolve_project_path(value: str | Path, project_root: Path = PROJECT_ROOT) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else project_root / path).resolve()
