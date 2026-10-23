from __future__ import annotations

import json
import http.client
import urllib.error
import unittest
from unittest.mock import patch

from app.models import SourceDocument
from app.providers import OpenAICompatibleProvider, ProviderError


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status = 200

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


    @patch("app.providers.urllib.request.urlopen")
    def test_truncated_http_response_retains_failed_call_and_settles_once(self, mocked_urlopen):
        from unittest.mock import Mock
        response = FakeHttpResponse({})
        response.read = Mock(side_effect=http.client.IncompleteRead(b"partial", 20))
        mocked_urlopen.return_value = response
        observer = Mock()
        observer.before.return_value = {"index": 0, "timeout_seconds": 5}
        self.provider.observer = observer
        with self.assertRaises(ProviderError) as caught:
            self.provider.generate("Question", [self.document])
        self.assertEqual(caught.exception.code, "MODEL_PROVIDER_ERROR")
        self.assertEqual(caught.exception.call.http_status, 200)
        self.assertIsNone(caught.exception.call.input_tokens)
        observer.after.assert_called_once_with(observer.before.return_value, caught.exception.call)
        self.assertEqual(mocked_urlopen.call_count, 1)

    @patch("app.providers.urllib.request.urlopen")
    def test_falsey_malformed_usage_is_not_treated_as_missing(self, mocked_urlopen):
        for usage in ([], "", 0, False):
            with self.subTest(usage=usage):
                mocked_urlopen.return_value = FakeHttpResponse({
                    "choices": [{"message": {"content": "Answer"}}], "usage": usage})
                with self.assertRaises(ProviderError) as caught:
                    self.provider.generate("Question", [self.document])
                self.assertEqual(caught.exception.code, "INVALID_MODEL_RESPONSE")

    @patch("app.providers.urllib.request.urlopen")
    def test_null_or_missing_usage_remains_unknown(self, mocked_urlopen):
        for extra in ({}, {"usage": None}):
            with self.subTest(extra=extra):
                mocked_urlopen.return_value = FakeHttpResponse({
                    "choices": [{"message": {"content": "Answer"}}], **extra})
                result = self.provider.generate("Question", [self.document])
                self.assertEqual(result.text, "Answer")
                self.assertIsNone(result.input_tokens)
                self.assertIsNone(result.output_tokens)


if __name__ == "__main__":
    unittest.main()
