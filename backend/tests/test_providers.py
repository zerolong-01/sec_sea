from __future__ import annotations

import json
import io
import http.client
import threading
import urllib.error
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from app.models import ChatMessage, SourceDocument
from app.providers import OpenAICompatibleProvider, ProviderError
from app.shared_variables import CallPurpose


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status = 200

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return io.BytesIO(json.dumps(self._payload).encode("utf-8")).read(size)


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

    @patch("app.providers.MODEL_HTTP.open")
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

    @patch("app.providers.MODEL_HTTP.open")
    def test_wraps_transport_failures_as_provider_errors(self, mocked_urlopen: object) -> None:
        mocked_urlopen.side_effect = urllib.error.URLError("connection refused")

        with self.assertRaises(ProviderError):
            self.provider.generate("What does the document say?", [self.document])


    @patch("app.providers.MODEL_HTTP.open")
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

    @patch("app.providers.MODEL_HTTP.open")
    def test_falsey_malformed_usage_is_not_treated_as_missing(self, mocked_urlopen):
        for usage in ([], "", 0, False):
            with self.subTest(usage=usage):
                mocked_urlopen.return_value = FakeHttpResponse({
                    "choices": [{"message": {"content": "Answer"}}], "usage": usage})
                with self.assertRaises(ProviderError) as caught:
                    self.provider.generate("Question", [self.document])
                self.assertEqual(caught.exception.code, "INVALID_MODEL_RESPONSE")

    @patch("app.providers.MODEL_HTTP.open")
    def test_null_or_missing_usage_remains_unknown(self, mocked_urlopen):
        for extra in ({}, {"usage": None}):
            with self.subTest(extra=extra):
                mocked_urlopen.return_value = FakeHttpResponse({
                    "choices": [{"message": {"content": "Answer"}}], **extra})
                result = self.provider.generate("Question", [self.document])
                self.assertEqual(result.text, "Answer")
                self.assertIsNone(result.input_tokens)
                self.assertIsNone(result.output_tokens)

    def test_invalid_endpoints_and_timeouts_are_rejected_without_echoing_credentials(self):
        for endpoint in ("file:///tmp/model", "https://key:secret@model.example/v1",
                         "https://model.example:bad/v1", "https://model.example:0/v1",
                         "https://model.example:70000/v1", "https://model.example/v1?api_key=secret",
                         "https://model.example/v1#secret", "https://model.example/\nv1",
                         "https://:443/v1", "https://model.example/has space"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError) as caught:
                OpenAICompatibleProvider(endpoint, "secret", "model")
            self.assertNotIn("secret", str(caught.exception))
        for timeout in (0, -1, float("nan"), float("inf"), True, "30"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                OpenAICompatibleProvider("http://127.0.0.1:8000/v1", None, "model", timeout)

    @patch("app.providers.MODEL_HTTP.open")
    def test_invalid_model_envelopes_keep_a_failed_call_and_settle_once(self, opened):
        bodies = (None, [], {}, {"choices": []}, {"choices": [{"message": {"content": None}}]},
                  {"choices": [{"message": {"content": "Answer"}}], "usage": {"prompt_tokens": True}})
        for payload in bodies:
            with self.subTest(payload=payload):
                opened.return_value = FakeHttpResponse(payload)
                observer = Mock()
                observer.before.return_value = {"index": 0, "timeout_seconds": 5}
                self.provider.observer = observer
                with self.assertRaises(ProviderError) as caught:
                    self.provider.generate("Question", [self.document])
                self.assertEqual(caught.exception.code, "INVALID_MODEL_RESPONSE")
                self.assertEqual(caught.exception.call.http_status, 200)
                observer.after.assert_called_once_with(observer.before.return_value, caught.exception.call)


class TransportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.status, self.body = 200, b""
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.do_POST()

            def do_POST(self):
                fixture.requests.append((self.path, self.headers.get("Authorization")))
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(fixture.status)
                if 300 <= fixture.status < 400:
                    self.send_header("Location", fixture.redirect_url)
                self.send_header("Content-Length", str(len(fixture.body)))
                self.end_headers()
                self.wfile.write(fixture.body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        base_url = f"http://127.0.0.1:{self.server.server_port}"
        # A distinct host spelling also exercises cross-host redirects.
        self.redirect_url = f"http://localhost:{self.server.server_port}/redirected"
        self.provider = OpenAICompatibleProvider(base_url + "/v1", "private-fixture-key", "fixture")
        self.observer = Mock()
        self.observer.before.return_value = {"index": 0, "timeout_seconds": 5}
        self.provider.observer = self.observer

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def complete(self):
        return self.provider.complete([ChatMessage(role="user", content="Question")],
                                      {"max_tokens": 10}, CallPurpose.GENERATION)

    def test_redirects_are_not_followed_and_failed_calls_settle_once(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                self.status, self.body = status, b"private-redirect-body"
                self.requests.clear()
                self.observer.reset_mock()
                with self.assertRaises(ProviderError) as caught:
                    self.complete()
                self.assertEqual(caught.exception.code, "MODEL_REDIRECT_BLOCKED")
                self.assertEqual(caught.exception.call.http_status, status)
                self.assertEqual(self.requests, [("/v1/chat/completions", "Bearer private-fixture-key")])
                self.assertNotIn("private", str(caught.exception))
                self.assertIsNone(caught.exception.call.response_text)
                self.observer.after.assert_called_once_with(self.observer.before.return_value,
                                                            caught.exception.call)

    def test_response_limit_accepts_exact_boundary_and_rejects_extra_byte(self):
        valid = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
        limit = len(valid) + 16
        with patch("app.providers.MAX_RESPONSE_BYTES", limit):
            self.body = valid + b" " * 16
            self.assertEqual(self.complete().text, "OK")
            self.observer.reset_mock()
            self.body += b" "
            with self.assertRaises(ProviderError) as caught:
                self.complete()
        self.assertEqual(caught.exception.code, "MODEL_RESPONSE_TOO_LARGE")
        self.assertEqual(caught.exception.call.http_status, 200)
        self.assertIsNone(caught.exception.call.response_text)
        self.observer.after.assert_called_once()

    def test_invalid_encoding_and_deep_json_are_controlled_failures(self):
        for body in (b"\xff", b"[" * 2000 + b"]" * 2000):
            with self.subTest(body_size=len(body)):
                self.body = body
                with self.assertRaises(ProviderError) as caught:
                    self.complete()
                self.assertEqual(caught.exception.code, "INVALID_MODEL_RESPONSE")


if __name__ == "__main__":
    unittest.main()
