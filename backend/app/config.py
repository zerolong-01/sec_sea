from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Runtime paths and model provider settings.

    The project root is deliberately the default location for data and run logs
    so every role shares the same versioned artifacts.
    """

    project_root: Path
    data_dir: Path
    runs_dir: Path
    model_provider: str
    model_id: str
    system_prompt_version: str
    retrieval_config_version: str
    model_base_url: str | None
    model_api_key: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        project_root = Path(__file__).resolve().parents[2]

        def resolve_path(name: str, default: Path) -> Path:
            value = os.getenv(name)
            return Path(value).resolve() if value else default

        return cls(
            project_root=project_root,
            data_dir=resolve_path("DATA_DIR", project_root / "data"),
            runs_dir=resolve_path("RUNS_DIR", project_root / "runs"),
            model_provider=os.getenv("MODEL_PROVIDER", "demo").lower(),
            model_id=os.getenv("MODEL_ID", "demo-rag-v0.1"),
            system_prompt_version=os.getenv("SYSTEM_PROMPT_VERSION", "v0.1"),
            retrieval_config_version=os.getenv(
                "RETRIEVAL_CONFIG_VERSION", "lexical-v0.1"
            ),
            model_base_url=os.getenv("MODEL_BASE_URL"),
            model_api_key=os.getenv("MODEL_API_KEY"),
        )
