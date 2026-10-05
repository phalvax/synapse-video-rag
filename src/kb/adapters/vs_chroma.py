"""Vector store Chroma persistant (le même moteur que la Knowledge Bank Dataiku par défaut)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from kb.schemas import Chunk

COLLECTION = "chunks"


class ChromaStore:
    def __init__(self, path: Path) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(path), settings=ChromaSettings(anonymized_telemetry=False)
        )
        self._col = self._client.get_or_create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine"}
        )

    def reset(self) -> None:
        self._client.delete_collection(COLLECTION)
        self._col = self._client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    def delete_videos(self, video_ids: list[str]) -> None:
        """Retire tous les chunks de ces vidéos (vidéo retraitée → pas de chunks orphelins)."""
        if video_ids:
            self._col.delete(where={"video_id": {"$in": list(video_ids)}})

    def count(self) -> int:
        return self._col.count()

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if not chunks:
            return
        self._col.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=[_metadata(c) for c in chunks],
        )

    def search(
        self, vector: list[float], k: int, filters: dict[str, Any] | None = None
    ) -> list[tuple[Chunk, float]]:
        """Renvoie (chunk, similarité cosinus) du plus proche au plus lointain."""
        n = min(k, self.count())
        if n == 0:
            return []
        res = self._col.query(query_embeddings=[vector], n_results=n, where=_where(filters))
        return [
            (_chunk(cid, doc, meta), 1.0 - dist)
            for cid, doc, meta, dist in zip(
                res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0],
                strict=True,
            )
        ]


def _where(filters: dict[str, Any] | None) -> dict[str, Any] | None:
    """Chroma n'accepte qu'une clé par `where` : plusieurs filtres → `$and` ; liste → `$in`."""
    if not filters:
        return None
    clauses = [{k: {"$in": list(v)}} if isinstance(v, list | tuple | set) else {k: v}
               for k, v in filters.items()]
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _metadata(c: Chunk) -> dict[str, Any]:
    meta = {
        "video_id": c.video_id,
        "start_s": c.start_s,
        "end_s": c.end_s,
        "context_header": c.context_header,
        "client": c.client,
        "date": c.date.isoformat() if c.date else None,
    }
    return {k: v for k, v in meta.items() if v is not None}  # Chroma refuse les None


def _chunk(chunk_id: str, text: str, meta: dict[str, Any]) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        video_id=meta["video_id"],
        start_s=meta["start_s"],
        end_s=meta["end_s"],
        text=text,
        context_header=meta.get("context_header", ""),
        client=meta.get("client"),
        date=dt.date.fromisoformat(meta["date"]) if meta.get("date") else None,
    )
