"""Request-scoped display redaction; private execution evidence stays unchanged."""
from __future__ import annotations

import base64
import re

CANARY_PATTERN = re.compile(r"CANARY_[A-Z0-9_]+")
BASE64_CONTAINER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_-]{8,}={0,2}(?![A-Za-z0-9+/_=-])")


def mask_display_text(text: str) -> tuple[str, bool]:
    masked = CANARY_PATTERN.sub("[MASKED_CANARY]", text)
    return masked, masked != text


def _encoded_pattern(value: str):
    # Permit mixed literal/percent-encoded UTF-8 and whitespace-separated text.
    def token(character):
        encoded = "".join(f"%{byte:02x}" for byte in character.encode("utf-8"))
        return f"(?:{re.escape(character)}|(?i:{encoded}))"
    return re.compile(r"\s*".join(token(character) for character in value))


class ProtectedValueMasker:
    """Compile each target once for all fields of one public projection."""

    def __init__(self, value: str, replacement: str):
        self.replacement = replacement
        self.target_pattern = _encoded_pattern(value)
        encoded = base64.b64encode(value.encode()).decode()
        urlsafe = base64.urlsafe_b64encode(value.encode()).decode()
        self.patterns = [_encoded_pattern(variant) for variant in sorted(
            {value, encoded, urlsafe, encoded.rstrip("="), urlsafe.rstrip("=")}, key=len, reverse=True)]

    def _container(self, match):
        candidate = match.group(0)
        try:
            decoded = base64.b64decode(candidate + "=" * (-len(candidate) % 4),
                                       altchars=b"-_", validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return candidate
        return self.replacement if self.target_pattern.search(decoded) else candidate

    def __call__(self, text: str) -> str:
        # A target inside an encoded sentence has a different Base64 alignment.
        # Inspect the whole container, including URL-safe/unpadded variants.
        text = BASE64_CONTAINER_PATTERN.sub(self._container, text)
        for pattern in self.patterns:
            text = pattern.sub(self.replacement, text)
        return text


def mask_value(text: str, value: str, replacement: str) -> str:
    """Single-value compatibility entry point for archived review consumers."""
    return ProtectedValueMasker(value, replacement)(text)


class DisplayRedactor:
    def __init__(self, *, canaries=(), protected_values=(), credentials=()):
        # No process-wide cache retains targets or credentials between requests.
        self.maskers = [ProtectedValueMasker(target, "[MASKED_CANARY]" if CANARY_PATTERN.fullmatch(target)
                                           else "[MASKED_PROTECTED]")
                        for target in sorted(set(canaries) | set(protected_values), key=len, reverse=True)]
        self.credentials = tuple(secret for secret in credentials if secret)

    def __call__(self, value):
        if isinstance(value, str):
            for masker in self.maskers:
                value = masker(value)
            value = mask_display_text(value)[0]
            for secret in self.credentials:
                value = value.replace(secret, "[MASKED_CREDENTIAL]")
            return value
        if isinstance(value, dict):
            return {self(key): self(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self(item) for item in value]
        return value
