"""L2 : transcripts → chunks → embeddings → Chroma (+ « moments » pour pointer la bonne seconde)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import numpy as np

from kb.adapters.factory import build_embedder, build_store
from kb.config import Settings
from kb.index.chunking import chunk_document, chunk_media, estimate_tokens
from kb.jsonl import read_jsonl, write_jsonl
from kb.schemas import Chunk, Segment, Video

MOMENT_SEGMENTS = 3  # un « moment » = 3 segments consécutifs (~10-20 s)
BATCH = 16


@dataclass
class Moment:
    video_id: str
    start_s: float
    end_s: float
    text: str
    page: int | None = None  # documents : la page du moment (jamais à cheval sur deux pages)
    modality: str | None = None  # parole / texte, ou « ocr » / « visual » (écran, image)


def build_moments(segments: list[Segment]) -> list[Moment]:
    """Fenêtres glissantes de segments : l'unité fine pour pointer la bonne seconde (ou, pour un
    document, le bon passage de la page — une fenêtre ne franchit jamais une page)."""
    out = []
    for i in range(len(segments)):
        head = segments[i]
        # Même page, même nature ; et pour l'écran d'une vidéo, la même image affichée
        # (les segments d'une image partagent sa fin d'affichage) — sinon un moment « écran »
        # mélangerait deux diapos et pointerait la mauvaise (vu le 27/09 : 1:10 au lieu de 0:35).
        screen = head.modality is not None and head.page is None
        window = [s for s in segments[i : i + MOMENT_SEGMENTS]
                  if s.page == head.page and s.modality == head.modality
                  and (not screen or s.end_s == head.end_s)]
        out.append(Moment(window[0].video_id, window[0].start_s, window[-1].end_s,
                          " ".join(s.text for s in window), window[0].page, head.modality))
    return out


def embed_all(embedder, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        vectors += embedder.embed(texts[i : i + BATCH])
    return vectors


def _video_units(settings: Settings, video: Video) -> tuple[list[Chunk], list[Moment]]:
    r = settings.retrieval
    segments = read_jsonl(settings.transcripts_dir / f"{video.video_id}.jsonl", Segment)
    chunker = chunk_document if video.kind in ("document", "image") else chunk_media
    return (chunker(segments, video, r.chunk_target_tokens, r.chunk_overlap_segments),
            build_moments(segments))


def update_index(settings: Settings, video_ids: list[str]) -> dict:
    """Indexation INCRÉMENTALE : n'embarque que ces vidéos et les ajoute à l'index existant.

    Pourquoi : `build_index` réembarque tout le corpus (~13 min pour 11 vidéos sur CPU) à
    chaque upload. Ici, seule la nouvelle vidéo est découpée et vectorisée ; une vidéo déjà
    indexée (retraitée) voit ses anciens chunks et moments remplacés. Sans index existant,
    on reconstruit tout.
    """
    idx = settings.index_dir
    if not (idx / "chunks.jsonl").exists() or not (idx / "moments.npy").exists():
        return build_index(settings)
    t0 = time.perf_counter()
    wanted = set(video_ids)
    videos = [v for v in read_jsonl(settings.videos_file, Video) if v.video_id in wanted]

    chunks = [c for c in read_jsonl(idx / "chunks.jsonl", Chunk) if c.video_id not in wanted]
    lines = (idx / "moments.jsonl").read_text("utf-8").splitlines()
    old_vectors = np.load(idx / "moments.npy")
    keep = [i for i, line in enumerate(lines) if json.loads(line)["video_id"] not in wanted]
    moments = [Moment(**json.loads(lines[i])) for i in keep]
    moment_vectors = old_vectors[keep] if keep else old_vectors[:0]

    new_chunks: list[Chunk] = []
    new_moments: list[Moment] = []
    for video in videos:
        c, m = _video_units(settings, video)
        new_chunks += c
        new_moments += m

    embedder = build_embedder(settings)
    store = build_store(settings)
    store.delete_videos(list(wanted))
    store.upsert(new_chunks, embed_all(embedder, [c.text_for_embedding() for c in new_chunks]))
    new_vectors = np.asarray(embed_all(embedder, [m.text for m in new_moments]), dtype=np.float32)
    if len(new_moments):
        moment_vectors = (np.vstack([moment_vectors, new_vectors]) if len(moment_vectors)
                          else new_vectors)

    write_jsonl(idx / "chunks.jsonl", chunks + new_chunks)
    np.save(idx / "moments.npy", np.asarray(moment_vectors, dtype=np.float32))
    (idx / "moments.jsonl").write_text(
        "".join(json.dumps(m.__dict__, ensure_ascii=False) + "\n" for m in moments + new_moments),
        "utf-8",
    )
    stats = {"mode": "incrémental", "videos_added": sorted(v.video_id for v in videos),
             "chunks_added": len(new_chunks), "moments_added": len(new_moments),
             "chunks_total": len(chunks) + len(new_chunks),
             "total_s": round(time.perf_counter() - t0, 2)}
    print(json.dumps(stats, ensure_ascii=False))
    return stats


def build_index(settings: Settings) -> dict:
    t0 = time.perf_counter()
    videos = read_jsonl(settings.videos_file, Video)
    chunks: list[Chunk] = []
    moments: list[Moment] = []
    for video in videos:
        c, m = _video_units(settings, video)
        chunks += c
        moments += m

    embedder = build_embedder(settings)
    t1 = time.perf_counter()
    chunk_vectors = embed_all(embedder, [c.text_for_embedding() for c in chunks])
    t2 = time.perf_counter()
    moment_vectors = embed_all(embedder, [m.text for m in moments])
    t3 = time.perf_counter()

    store = build_store(settings)
    store.reset()  # on reconstruit tout : pas de chunks orphelins d'une version précédente
    store.upsert(chunks, chunk_vectors)

    idx = settings.index_dir
    write_jsonl(idx / "chunks.jsonl", chunks)
    np.save(idx / "moments.npy", np.asarray(moment_vectors, dtype=np.float32))
    (idx / "moments.jsonl").write_text(
        "".join(json.dumps(m.__dict__, ensure_ascii=False) + "\n" for m in moments), "utf-8"
    )
    stats = {
        "profile": settings.profile,
        "embedding_model": settings.embedding.model,
        "videos": len(videos),
        "chunks": len(chunks),
        "moments": len(moments),
        "avg_chunk_tokens_est": round(np.mean([estimate_tokens(c.text) for c in chunks]), 1),
        "avg_chunk_duration_s": round(np.mean([c.end_s - c.start_s for c in chunks]), 1),
        "embedding_tokens": embedder.usage.input_tokens,
        "embed_chunks_s": round(t2 - t1, 2),
        "embed_moments_s": round(t3 - t2, 2),
        "total_s": round(time.perf_counter() - t0, 2),
    }
    (idx / "index_stats.json").write_text(json.dumps(stats, indent=2), "utf-8")
    for k, v in stats.items():
        print(f"{k:22}: {v}")
    return stats
