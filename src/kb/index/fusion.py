"""Reciprocal Rank Fusion : le « classement combiné des deux détectives »."""

from __future__ import annotations

from collections.abc import Sequence


def rrf(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """score(d) = Σ 1 / (k + rang_d) sur chaque classement où d apparaît (rang à partir de 1).

    Ne dépend que des rangs : pas besoin de rendre comparables un cosinus et un score BM25.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
