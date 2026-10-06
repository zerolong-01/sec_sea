from __future__ import annotations

import os
import math
from dataclasses import dataclass
from pathlib import Path

from .shared_variables import (DefenseDecision, DetectorConsistencyPolicy, DetectorErrorPolicy,
                               DetectorResponseFormat)


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
    temperature: float = 0.0
    max_tokens: int = 512
    model_timeout_seconds: float = 30.0
    max_model_calls: int = 8
    d2_base_url: str | None = None
    d2_model_id: str | None = None
    d2_api_key: str | None = None
    d2_threshold: float = 0.5
    d2_error_policy: DetectorErrorPolicy = DetectorErrorPolicy.FAIL_CLOSED
    d2_document_action: DefenseDecision = DefenseDecision.QUARANTINE
    d2_version: str = "llm-injection-v0.1"
    d2_policy_version: str = "d2-policy-v0.2"
    d2_consistency_policy: DetectorConsistencyPolicy = DetectorConsistencyPolicy.REVIEW_ON_CONTRADICTION
    d2_response_format: DetectorResponseFormat = DetectorResponseFormat.PROMPT_ONLY
    pricing_path: Path | None = None
    evaluation_rules_path: Path | None = None

    def __post_init__(self):
        if not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2:
            raise ValueError("MODEL_TEMPERATURE must be between 0 and 2")
        if not math.isfinite(self.d2_threshold) or not 0 <= self.d2_threshold <= 1:
            raise ValueError("D2_THRESHOLD must be between 0 and 1")
        if self.max_tokens < 1 or self.max_model_calls < 1 or not math.isfinite(self.model_timeout_seconds) or self.model_timeout_seconds <= 0:
            raise ValueError("Token/call limits and timeout must be positive")
        if self.d2_document_action not in (DefenseDecision.QUARANTINE, DefenseDecision.BLOCK):
            raise ValueError("D2_DOCUMENT_ACTION must be quarantine or block")
        DetectorConsistencyPolicy(self.d2_consistency_policy)
        DetectorResponseFormat(self.d2_response_format)

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
            temperature=float(os.getenv("MODEL_TEMPERATURE", "0")),
            max_tokens=int(os.getenv("MODEL_MAX_TOKENS", "512")),
            model_timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "30")),
            max_model_calls=int(os.getenv("MAX_MODEL_CALLS", "8")),
            d2_base_url=os.getenv("D2_BASE_URL"),
            d2_model_id=os.getenv("D2_MODEL_ID"),
            d2_api_key=os.getenv("D2_API_KEY"),
            d2_threshold=float(os.getenv("D2_THRESHOLD", "0.5")),
            d2_error_policy=DetectorErrorPolicy(os.getenv("D2_ERROR_POLICY", DetectorErrorPolicy.FAIL_CLOSED)),
            d2_document_action=DefenseDecision(os.getenv("D2_DOCUMENT_ACTION", DefenseDecision.QUARANTINE)),
            d2_version=os.getenv("D2_VERSION", "llm-injection-v0.1"),
            d2_policy_version=os.getenv("D2_POLICY_VERSION", "d2-policy-v0.2"),
            d2_consistency_policy=DetectorConsistencyPolicy(os.getenv("D2_CONSISTENCY_POLICY", DetectorConsistencyPolicy.REVIEW_ON_CONTRADICTION)),
            d2_response_format=DetectorResponseFormat(os.getenv("D2_RESPONSE_FORMAT", DetectorResponseFormat.PROMPT_ONLY)),
            pricing_path=Path(os.environ["PRICING_FILE"]).resolve() if os.getenv("PRICING_FILE") else None,
            evaluation_rules_path=Path(os.environ["EVALUATION_RULES_FILE"]).resolve() if os.getenv("EVALUATION_RULES_FILE") else None,
        )
