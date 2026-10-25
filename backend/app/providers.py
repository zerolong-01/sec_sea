from __future__ import annotations

import json
import http.client
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from .models import ChatMessage, ModelCall, SourceDocument
from .prompts import PreparedPrompt, prepare_prompt
from .retrieval import token_count
from .shared_variables import CallPurpose, Scenario, UsageSource


MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A model endpoint must never forward credentials or replay a paid
        # request to an address chosen by its HTTP response.
        return None


MODEL_HTTP = urllib.request.build_opener(_NoRedirect())


class ProviderError(Exception):
    def __init__(self, message: str, code: str = "MODEL_PROVIDER_ERROR", call: ModelCall | None = None):
        super().__init__(message)
        self.code, self.call = code, call


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    call: ModelCall | None = None


class DemoRagProvider:
    """Offline integration fixture; never a measurement of model quality."""
    observer = None
    def generate(self, question: str, documents: list[SourceDocument]) -> ProviderResponse:
        return self.generate_prepared(prepare_prompt(question, documents, Scenario.RAG_CHAT), {})

    def generate_prepared(self, prompt: PreparedPrompt, parameters: dict) -> ProviderResponse:
        pending = ModelCall(purpose=CallPurpose.GENERATION, model_id="demo-rag-v0.1",
                            messages=prompt.messages, parameters=parameters, latency_ms=0)
        ticket = self.observer.before(pending) if self.observer else None
        started = time.perf_counter()
        if prompt.documents:
            first = prompt.documents[0]
            answer = f"참조 문서 '{first.title}'를 바탕으로 한 응답입니다.\n\n" + " ".join(first.content.split())[:500]
        else:
            answer = "검색된 문서가 없어 답변을 생성할 수 없습니다."
        input_tokens = sum(token_count(message.content) for message in prompt.messages)
        output_tokens = token_count(answer)
        call = ModelCall(purpose=CallPurpose.GENERATION, model_id="demo-rag-v0.1", messages=prompt.messages,
                         parameters=parameters, latency_ms=round((time.perf_counter()-started)*1000),
                         input_tokens=input_tokens, output_tokens=output_tokens, usage_source=UsageSource.ESTIMATED,
                         estimated_cost_usd=0.0, cost_reason="offline_demo_no_external_charge", response_text=answer)
        if self.observer:
            self.observer.after(ticket, call)
        return ProviderResponse(answer, input_tokens, output_tokens, 0.0, call)


class OpenAICompatibleProvider:
    """One shared transport for generation and LLM-based injection classification."""
    def __init__(self, base_url: str, api_key: str | None, model_id: str, timeout: float = 30):
        try:
            url = urlsplit(base_url)
            valid = (url.scheme in ("http", "https") and url.hostname and
                     not (url.username or url.password or url.query or url.fragment) and
                     not any(ord(char) <= 32 or ord(char) == 127 for char in base_url) and
                     (url.port is None or 1 <= url.port <= 65535))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("Model endpoint must be an http(s) URL without credentials, query or fragment")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Model timeout must be a finite positive number")
        self._base_url, self._api_key, self._model_id, self._timeout = base_url.rstrip("/"), api_key, model_id, timeout
        self.observer = None

    def generate(self, question: str, documents: list[SourceDocument]) -> ProviderResponse:
        return self.generate_prepared(prepare_prompt(question, documents, Scenario.RAG_CHAT), {"temperature": 0})

    def generate_prepared(self, prompt: PreparedPrompt, parameters: dict) -> ProviderResponse:
        return self.complete(prompt.messages, parameters, CallPurpose.GENERATION)

    def complete(self, messages: list[ChatMessage], parameters: dict, purpose: CallPurpose,
                 target_ref: str | None = None) -> ProviderResponse:
        payload = {"model": self._model_id, "messages": [m.model_dump() for m in messages], **parameters}
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(f"{self._base_url}/chat/completions",
                                         data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                         headers=headers, method="POST")
        started = time.perf_counter()
        call = ModelCall(purpose=purpose, target_ref=target_ref, model_id=self._model_id,
                         endpoint=f"{self._base_url}/chat/completions", messages=messages,
                         parameters=parameters, latency_ms=0)
        # Persist a reservation before any external call. A crash keeps that
        # reservation unresolved rather than silently replaying a paid request.
        ticket = self.observer.before(call) if self.observer else None
        try:
            timeout = min(self._timeout, ticket["timeout_seconds"]) if ticket else self._timeout
            with MODEL_HTTP.open(request, timeout=timeout) as response:
                call.http_status = response.status
                content = response.read(MAX_RESPONSE_BYTES + 1)
                if len(content) > MAX_RESPONSE_BYTES:
                    call.error_code = "MODEL_RESPONSE_TOO_LARGE"
                    raise ProviderError("모델 응답이 허용 크기를 초과했습니다.", call.error_code, call)
                body = json.loads(content.decode("utf-8"))
            text = body["choices"][0]["message"]["content"]
            if not isinstance(text, str):
                raise TypeError("Response content must be text")
            call.response_text = text
            usage = body.get("usage")
            if usage is None:
                usage = {}
            if not isinstance(usage, dict):
                raise TypeError("Usage must be an object")
            for key in ("prompt_tokens", "completion_tokens"):
                if usage.get(key) is not None and (type(usage[key]) is not int or usage[key] < 0):
                    raise ValueError("Invalid provider usage")
            call.input_tokens, call.output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
            call.usage_source = (UsageSource.OBSERVED if call.input_tokens is not None and call.output_tokens is not None
                                 else UsageSource.UNKNOWN)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                call.http_status = exc.code
                exc.close()
            timed_out = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
            redirected = isinstance(exc, urllib.error.HTTPError) and 300 <= exc.code < 400
            call.error_code = ("MODEL_REDIRECT_BLOCKED" if redirected else
                               "MODEL_TIMEOUT" if timed_out else "MODEL_PROVIDER_ERROR")
            raise ProviderError(f"모델 호출에 실패했습니다 ({type(exc).__name__})", call.error_code, call) from exc
        except (ValueError, KeyError, IndexError, TypeError, RecursionError) as exc:
            call.error_code = "INVALID_MODEL_RESPONSE"
            raise ProviderError("모델 응답 형식 또는 사용량이 잘못되었습니다.", call.error_code, call) from exc
        finally:
            call.latency_ms = round((time.perf_counter()-started)*1000)
            if self.observer:
                self.observer.after(ticket, call)
        return ProviderResponse(text, call.input_tokens, call.output_tokens, None, call)
