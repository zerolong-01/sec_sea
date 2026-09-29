from __future__ import annotations

import json
import urllib.error
import unittest
from unittest.mock import patch

from app.models import SourceDocument
from app.providers import OpenAICompatibleProvider, ProviderError


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class OpenAICompatibleProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = OpenAICompatibleProvider(
            "https://model.example/v1/", "test-api-key", "test-model"
        )
        self.document = SourceDocument(
            schema_version="0.1",
            artifact_type="source_document",
            document_id="doc-001",
            title="Controlled document",
            content="Controlled source content.",
            language="en",
            source_type="seed_corpus",
            source_version="corpus-v0.1",
            is_untrusted_content=True,
        )

    @patch("app.providers.urllib.request.urlopen")
    def test_sends_chat_completion_request_and_reads_usage(self, mocked_urlopen: object) -> None:
        mocked_urlopen.return_value = FakeHttpResponse(
            {
                "choices": [{"message": {"content": "Grounded answer."}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }
        )

        response = self.provider.generate("What does the document say?", [self.document])

        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://model.example/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-api-key")
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["temperature"], 0)
        self.assertIn("doc-001", payload["messages"][1]["content"])
        self.assertEqual(response.text, "Grounded answer.")
        self.assertEqual(response.input_tokens, 12)
        self.assertEqual(response.output_tokens, 4)
        self.assertIsNone(response.estimated_cost_usd)

    @patch("app.providers.urllib.request.urlopen")
    def test_wraps_transport_failures_as_provider_errors(self, mocked_urlopen: object) -> None:
        mocked_urlopen.side_effect = urllib.error.URLError("connection refused")

        with self.assertRaises(ProviderError):
            self.provider.generate("What does the document say?", [self.document])


if __name__ == "__main__":
    unittest.main()
