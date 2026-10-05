"""L2 Recherche : dense + BM25 → RRF → reranker → zoom sur le bon moment.

Modes (pour les ablations) :
- `dense`         : embeddings seuls (bge-m3 / Embedding v3 Small)
- `bm25`          : mots-clés seuls
- `hybrid`        : dense + BM25 fusionnés par RRF
- `hybrid_rerank` : hybrid, puis cross-encoder sur les `top_k` candidats (mode par défaut)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

from kb.adapters.factory import build_embedder, build_reranker, build_store
from kb.agent.guardrails import should_abstain
from kb.config import Settings
from kb.index.bm25 import BM25Index
from kb.index.build import Moment
from kb.index.fusion import rrf
from kb.jsonl import read_jsonl
from kb.schemas import Chunk

MODES = ("dense", "bm25", "hybrid", "hybrid_rerank")


@dataclass
class Hit:
    chunk: Chunk
    score: float  # score du dernier étage utilisé (cosinus, BM25, RRF ou rerank)
    dense_rank: int | None = None
    bm25_rank: int | None = None
    rerank_score: float | None = None
    moment_s: float = 0.0  # seconde précise à ouvrir dans la vidéo
    moment_text: str = ""


@dataclass
class SearchResult:
    hits: list[Hit]
    abstain: bool = False  # seulement évalué en mode hybrid_rerank (score calibrable)
    best_score: float | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)


class Searcher:
    def __init__(self, settings: Settings, chunks: list[Chunk], moments: list[Moment],
                 moment_vectors: np.ndarray, with_reranker: bool = True) -> None:
        self.settings = settings
        self.chunks = {c.chunk_id: c for c in chunks}
        self.bm25 = BM25Index(chunks)
        self.store = build_store(settings)
        self.embedder = build_embedder(settings)
        self.moments = moments
        norms = np.linalg.norm(moment_vectors, axis=1, keepdims=True)
        self.moment_vectors = moment_vectors / np.clip(norms, 1e-9, None)
        self.reranker = build_reranker(settings) if with_reranker else None

    @classmethod
    def load(cls, settings: Settings, with_reranker: bool = True) -> Searcher:
        idx = settings.index_dir
        if not (idx / "chunks.jsonl").exists():
            raise FileNotFoundError(f"Index absent ({idx}) : lancer `python -m kb.cli index`")
        chunks = read_jsonl(idx / "chunks.jsonl", Chunk)
        lines = (idx / "moments.jsonl").read_text("utf-8").splitlines()
        moments = [Moment(**json.loads(line)) for line in lines if line]
        return cls(settings, chunks, moments, np.load(idx / "moments.npy"), with_reranker)

    def search(self, query: str, mode: str = "hybrid_rerank", k: int = 5,
               filters: dict | None = None) -> SearchResult:
        import time

        if mode not in MODES:
            raise ValueError(f"mode inconnu : {mode}")
        r = self.settings.retrieval
        timings: dict[str, float] = {}

        t = time.perf_counter()
        qvec = np.asarray(self.embedder.embed([query])[0], dtype=np.float32)
        timings["embed"] = 1000 * (time.perf_counter() - t)

        dense_ids: list[str] = []
        bm25_ids: list[str] = []
        scores: dict[str, float] = {}
        if mode != "bm25":
            t = time.perf_counter()
            dense = self.store.search(qvec.tolist(), r.top_k, filters)
            dense_ids = [c.chunk_id for c, _ in dense]
            scores.update({c.chunk_id: s for c, s in dense})
            timings["dense"] = 1000 * (time.perf_counter() - t)
        if mode != "dense":
            t = time.perf_counter()
            # BM25 ne connaît pas les métadonnées : on filtre ses résultats nous-mêmes, sinon un
            # filtre (client, vidéo) laisserait passer des passages hors périmètre.
            lexical = self.bm25.search(query, len(self.chunks) if filters else r.top_k)
            lexical = [(c, s) for c, s in lexical if matches(c, filters)][: r.top_k]
            bm25_ids = [c.chunk_id for c, _ in lexical]
            if mode == "bm25":
                scores.update({c.chunk_id: s for c, s in lexical})
            timings["bm25"] = 1000 * (time.perf_counter() - t)

        if mode == "dense":
            ranked = [(cid, scores[cid]) for cid in dense_ids]
        elif mode == "bm25":
            ranked = [(cid, scores[cid]) for cid in bm25_ids]
        else:
            ranked = rrf([dense_ids, bm25_ids], k=r.rrf_k)[: r.top_k]

        rerank: dict[str, float] = {}
        if mode == "hybrid_rerank":
            if self.reranker is None:
                raise RuntimeError("Searcher chargé sans reranker")
            t = time.perf_counter()
            cands = [cid for cid, _ in ranked[: r.rerank_candidates]]
            docs = [self.chunks[cid].text_for_embedding() for cid in cands]
            rerank = dict(zip(cands, self.reranker.rerank(query, docs), strict=True))
            ranked = sorted(rerank.items(), key=lambda kv: kv[1], reverse=True)
            timings["rerank"] = 1000 * (time.perf_counter() - t)

        hits = []
        for cid, score in ranked[:k]:
            chunk = self.chunks[cid]
            moment = self._best_moment(qvec, chunk)
            hits.append(Hit(
                chunk=chunk, score=float(score),
                dense_rank=dense_ids.index(cid) + 1 if cid in dense_ids else None,
                bm25_rank=bm25_ids.index(cid) + 1 if cid in bm25_ids else None,
                rerank_score=rerank.get(cid),
                moment_s=moment.start_s if moment else chunk.start_s,
                moment_text=moment.text if moment else chunk.text,
            ))
        timings["total"] = sum(timings.values())

        best = hits[0].rerank_score if hits and mode == "hybrid_rerank" else None
        abstain = mode == "hybrid_rerank" and should_abstain(best, r.abstain_threshold)
        return SearchResult(hits=hits, abstain=abstain, best_score=best, timings_ms=timings)

    def locate_quote(self, chunk: Chunk, quote: str) -> float | None:
        """Position (seconde, ou page+rang) du premier moment du chunk qui CONTIENT la citation.

        La seconde d'une preuve doit être celle où la phrase citée est dite (ou affichée),
        pas celle du passage le plus proche de la question."""
        target = " ".join(quote.lower().split())[:60]
        if len(target) < 12:
            return None
        # Les moments sont des fenêtres GLISSANTES de 3 segments : la citation est contenue dans
        # jusqu'à 3 d'entre elles ; la dernière commence au segment de la citation (la première,
        # jusqu'à 2 segments trop tôt — mesuré le 27/09 : M04 ratait le ±30 s).
        found = None
        for m in self.moments:
            same_chunk = (m.video_id == chunk.video_id and m.modality == chunk.modality
                          and chunk.start_s <= m.start_s < chunk.end_s)
            if same_chunk and target in " ".join(m.text.lower().split()):
                found = m.start_s if found is None else max(found, m.start_s)
        return found

    def _best_moment(self, qvec: np.ndarray, chunk: Chunk) -> Moment | None:
        """Dans le chunk retenu, le moment (≈3 segments) le plus proche de la question."""
        idx = [i for i, m in enumerate(self.moments)
               if m.video_id == chunk.video_id and chunk.start_s <= m.start_s < chunk.end_s
               and m.modality == chunk.modality]  # un chunk « écran » pointe un moment « écran »
        if not idx:
            return None
        q = qvec / max(float(np.linalg.norm(qvec)), 1e-9)
        sims = self.moment_vectors[idx] @ q
        return self.moments[idx[int(np.argmax(sims))]]


def matches(chunk: Chunk, filters: dict | None) -> bool:
    """Le chunk respecte-t-il tous les filtres ? Valeur simple = égalité ; liste = « parmi »."""
    if not filters:
        return True
    for k, v in filters.items():
        value = getattr(chunk, k, None)
        if (value not in v) if isinstance(v, list | tuple | set) else (value != v):
            return False
    return True
