from __future__ import annotations

import re
from collections import Counter

from .models import RetrievalItem, SourceDocument

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[가-힣]+", re.IGNORECASE)


def token_count(text: str) -> int:
    """A deterministic local token estimate used until provider usage is available."""

    return len(TOKEN_PATTERN.findall(text))


def lexical_retrieve(
    query: str, documents: list[SourceDocument], top_k: int = 3
) -> list[tuple[SourceDocument, RetrievalItem]]:
    """Rank the controlled corpus without adding an embedding dependency for week one."""

    query_terms = Counter(TOKEN_PATTERN.findall(query.lower()))
    ranked: list[tuple[SourceDocument, float]] = []

    for document in documents:
        document_terms = Counter(
            TOKEN_PATTERN.findall(f"{document.title} {document.content}".lower())
        )
        overlap = sum(
            min(query_count, document_terms.get(term, 0))
            for term, query_count in query_terms.items()
        )
        normalized_score = overlap / max(len(query_terms), 1)
        ranked.append((document, normalized_score))

    ranked.sort(key=lambda item: (-item[1], item[0].document_id))
    selected = ranked[:top_k]
    return [
        (
            document,
            RetrievalItem(
                document_id=document.document_id,
                rank=index,
                score=round(score, 6),
                included_in_prompt=True,
            ),
        )
        for index, (document, score) in enumerate(selected, start=1)
    ]
