from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .models import SourceDocument
from .retrieval import token_count


class ProviderError(Exception):
    pass


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None


class DemoRagProvider:
    """Deterministic, offline provider for reproducible week-one integration."""

    def generate(self, question: str, documents: list[SourceDocument]) -> ProviderResponse:
        if documents:
            first_document = documents[0]
            excerpt = " ".join(first_document.content.split())[:500]
            answer = (
                f"참조 문서 '{first_document.title}'를 바탕으로 한 응답입니다.\n\n"
                f"{excerpt}"
            )
        else:
            answer = "검색된 문서가 없어 답변을 생성할 수 없습니다."

        return ProviderResponse(
            text=answer,
            input_tokens=token_count(question)
            + sum(token_count(document.content) for document in documents),
            output_tokens=token_count(answer),
            estimated_cost_usd=0.0,
        )


class OpenAICompatibleProvider:
    """Minimal stdlib client for an explicitly configured OpenAI-compatible endpoint."""

    def __init__(self, base_url: str, api_key: str | None, model_id: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id

    def generate(self, question: str, documents: list[SourceDocument]) -> ProviderResponse:
        context = "\n\n".join(
            f"[문서 {document.document_id}: {document.title}]\n{document.content}"
            for document in documents
        )
        payload = {
            "model": self._model_id,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": "당신은 검색 문서를 근거로 답하는 RAG 챗봇입니다.",
                },
                {
                    "role": "user",
                    "content": f"질문:\n{question}\n\n검색 문서:\n{context}",
                },
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            raise ProviderError(f"모델 호출에 실패했습니다: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError("모델 응답이 JSON 형식이 아닙니다.") from exc

        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("모델 응답에 choices[0].message.content가 없습니다.") from exc

        usage = body.get("usage", {})
        return ProviderResponse(
            text=text,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            estimated_cost_usd=None,
        )
