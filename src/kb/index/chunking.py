"""Découpage des segments en chunks (~400 tokens, ~2-3 min) avec chevauchement."""

from __future__ import annotations

from kb.schemas import Chunk, Segment, Video

TOKENS_PER_WORD = 1.3  # hypothèse (ordre de grandeur pour l'anglais/français), pas un tokenizer


def estimate_tokens(text: str) -> int:
    return round(len(text.split()) * TOKENS_PER_WORD)


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


HEADER_DESCRIPTION_CHARS = 160


def context_header(video: Video, start_s: float, end_s: float) -> str:
    """En-tête déterministe recopié devant chaque chunk (et donc embarqué avec lui) : titre,
    position, puis le contexte saisi à l'import (mission, auteur, date, description courte).
    Une question sur « la mission ES2002 » ou « la réunion de Laura » peut ainsi matcher,
    alors que ces mots ne sont jamais prononcés dans l'enregistrement."""
    parts = [f"Vidéo : {video.title}", f"[{fmt_ts(start_s)}–{fmt_ts(end_s)}]"]
    return " · ".join([*parts, *_meta_parts(video)])


def _meta_parts(video: Video) -> list[str]:
    parts = []
    if video.mission:
        parts.append(f"Mission : {video.mission}")
    if video.author:
        parts.append(f"Auteur : {video.author}")
    if video.date:
        parts.append(f"Date : {video.date.isoformat()}")
    if video.description:
        d = " ".join(video.description.split())
        parts.append(d if len(d) <= HEADER_DESCRIPTION_CHARS
                     else d[:HEADER_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…")
    return parts


NATURE = {"ocr": "Texte lu dans l'image", "visual": "Description générée de l'image"}


def document_header(video: Video, page: int, modality: str | None = None) -> str:
    """En-tête d'un chunk de document : « Document : titre · p. 3 · [nature] · Mission : … »."""
    kind = "Image" if video.kind == "image" else "Document"
    parts = [f"{kind} : {video.title}", f"p. {page}"]
    if modality in NATURE:
        parts.append(NATURE[modality])
    return " · ".join([*parts, *_meta_parts(video)])


def chunk_document(segments: list[Segment], video: Video, target_tokens: int = 400,
                   overlap_segments: int = 1) -> list[Chunk]:
    """Chunks d'un document : même découpage que les médias, mais JAMAIS à cheval sur deux
    pages (une citation renvoie à une seule page)."""
    groups: dict[tuple[int, str], list[Segment]] = {}
    for s in segments:  # par page, et par nature (texte / lu dans l'image / description IA)
        groups.setdefault((s.page or 1, s.modality or ""), []).append(s)
    chunks: list[Chunk] = []
    for (page, modality), segs in sorted(groups.items()):
        for c in chunk_segments(segs, video, target_tokens, overlap_segments):
            chunks.append(c.model_copy(update={
                "chunk_id": f"{video.video_id}__{len(chunks):03d}", "page": page,
                "modality": modality or None,
                "context_header": document_header(video, page, modality or None)}))
    return chunks


SCREEN = {"ocr": "À l'écran — texte lu", "visual": "À l'écran — description générée"}


def chunk_media(segments: list[Segment], video: Video, target_tokens: int = 400,
                overlap_segments: int = 1) -> list[Chunk]:
    """Chunks d'une vidéo : la PAROLE comme avant (mêmes identifiants), puis ce qui est
    MONTRÉ à l'écran dans des chunks séparés (une citation ne mélange jamais parole et écran,
    et une description générée garde son étiquette)."""
    speech = [s for s in segments if not s.modality]
    chunks = chunk_segments(speech, video, target_tokens, overlap_segments)
    for modality, label in SCREEN.items():
        screen = [s for s in segments if s.modality == modality]
        for c in chunk_segments(screen, video, target_tokens, 0):
            chunks.append(c.model_copy(update={
                "chunk_id": f"{video.video_id}__{len(chunks):03d}", "modality": modality,
                "context_header": f"{c.context_header} · {label}"}))
    return chunks


def chunk_segments(
    segments: list[Segment], video: Video, target_tokens: int = 400, overlap_segments: int = 1
) -> list[Chunk]:
    """Regroupe des segments consécutifs jusqu'à ~`target_tokens`.

    Chaque chunk reprend les `overlap_segments` derniers segments du précédent, pour
    qu'une idée coupée à la frontière reste entière dans au moins un chunk.
    """
    if overlap_segments < 0:
        raise ValueError("overlap_segments doit être >= 0")
    chunks: list[Chunk] = []
    i = 0
    while i < len(segments):
        j, tokens = i, 0
        while j < len(segments) and (tokens < target_tokens or j == i):
            tokens += estimate_tokens(segments[j].text)
            j += 1
        window = segments[i:j]
        start_s, end_s = window[0].start_s, window[-1].end_s
        chunks.append(
            Chunk(
                chunk_id=f"{video.video_id}__{len(chunks):03d}",
                video_id=video.video_id,
                start_s=start_s,
                end_s=end_s,
                text=" ".join(s.text for s in window),
                context_header=context_header(video, start_s, end_s),
                client=video.client,
                date=video.date,
            )
        )
        if j >= len(segments):
            break
        i = max(j - overlap_segments, i + 1)  # toujours avancer
    return chunks
