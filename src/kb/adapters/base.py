"""Interfaces communes à tous les paliers (free / dataiku / market).

Le code métier ne dépend QUE de ces interfaces : changer de modèle = changer de profil.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from kb.schemas import Chunk, Segment


class LLM(Protocol):
    def complete(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str: ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class TranscriptionResult:
    segments: list[Segment]
    language: str | None
    duration_s: float


class Transcriber(Protocol):
    def transcribe(
        self, audio: np.ndarray, video_id: str, language: str | None = None
    ) -> TranscriptionResult: ...


class Diarizer(Protocol):
    def diarize(self, audio_path: str) -> list[tuple[float, float, str]]: ...


class Reranker(Protocol):
    def rerank(self, query: str, docs: list[str]) -> list[float]: ...


class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...

    def search(
        self, vector: list[float], k: int, filters: dict[str, Any] | None = None
    ) -> list[tuple[Chunk, float]]: ...
