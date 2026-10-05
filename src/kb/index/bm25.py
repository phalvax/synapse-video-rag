"""Détective lexical : BM25 (le « Ctrl+F intelligent »), via la bibliothèque bm25s."""

from __future__ import annotations

import re

from kb.schemas import Chunk

_WORD = re.compile(r"\w+", re.UNICODE)
# Mots vides FR + EN (courts, volontairement) : on ne veut pas que « the » ou « le » décident.
STOPWORDS = frozenset(
    """a an and are as at be but by for from has have i in is it its of on or so that the
    their there they this to was we were what when which who will with you your do does did
    not no can how why me my our us he she him her them than then these those been being
    le la les un une des du de d l et ou est sont a au aux en dans pour par sur avec ce cet
    cette ces qui que quoi quel quelle quels quelles il elle ils elles on nous vous je tu se
    sa son ses leur leurs ne pas plus y t il qu c s n j m est-ce comment pourquoi quand""".split()
)


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


class BM25Index:
    def __init__(self, chunks: list[Chunk]) -> None:
        import bm25s

        self.chunks = chunks
        self._retriever = bm25s.BM25()
        corpus = [tokenize(c.text_for_embedding()) for c in chunks]
        self._retriever.index(corpus, show_progress=False)
        self._vocab = set(self._retriever.vocab_dict)

    def search(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        tokens = [t for t in tokenize(query) if t in self._vocab]
        if not tokens or not self.chunks:
            return []  # aucun mot connu (ex. question FR sur un corpus EN) → rien à proposer
        k = min(k, len(self.chunks))
        docs, scores = self._retriever.retrieve([tokens], k=k, show_progress=False)
        pairs = zip(docs[0], scores[0], strict=True)
        return [(self.chunks[int(d)], float(s)) for d, s in pairs if s > 0]
