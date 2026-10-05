"""L0 : dossier de médias → `data/transcripts/<video_id>.jsonl` + `data/videos.jsonl`."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from kb.adapters.base import Transcriber
from kb.adapters.transcribe_fw import NoAudioTrack, load_audio
from kb.config import Settings
from kb.ingest.dedup import file_sha256
from kb.ingest.documents import detect_language, discover_documents, extract_pdf
from kb.ingest.frames import has_video, keyframes, merge_timeline, screen_segments
from kb.ingest.metadata import apply_meta, load_meta
from kb.ingest.sources import MediaGroup, discover_media, slugify
from kb.ingest.vision import IMAGE_EXTENSIONS
from kb.jsonl import read_jsonl, write_jsonl
from kb.schemas import Video


@dataclass
class IngestStat:
    video_id: str
    model: str
    audio_s: float
    decode_s: float
    transcribe_s: float
    segments: int
    words: int
    language: str | None

    @property
    def rtf(self) -> float:
        """Real-time factor : secondes de calcul par seconde d'audio (< 1 = plus vite que réel)."""
        return self.transcribe_s / self.audio_s if self.audio_s else float("nan")


def ingest_group(
    group: MediaGroup, transcriber: Transcriber, settings: Settings, model_name: str
) -> tuple[Video, IngestStat]:
    meta = load_meta(settings.data_dir, group.video_id)  # formulaire d'import, s'il existe
    # Langue saisie à l'import → Whisper saute la détection ; sinon réglage du profil / auto.
    language = (meta.language if meta else None) or settings.transcription.language
    t0 = time.perf_counter()
    audio = load_audio(group.parts)
    t1 = time.perf_counter()
    result = transcriber.transcribe(audio, group.video_id, language)
    t2 = time.perf_counter()

    segments, kind = result.segments, "video" if has_video(group.parts[0]) else "audio"
    if kind == "video" and settings.vision.frames and len(group.parts) == 1:
        # Ce qui est MONTRÉ (diapos, tableau), horodaté et mêlé à ce qui est dit.
        t_screen = time.perf_counter()
        frames = keyframes(group.parts[0])
        screen = screen_segments(frames, group.video_id, result.duration_s,
                                 _vision_llm(settings), settings.vision.max_video_descriptions)
        segments = merge_timeline(result.segments, screen)
        print(f"  écran : {len(frames)} changement(s), {len(screen)} segment(s) lus/décrits, "
              f"{time.perf_counter() - t_screen:.0f} s", flush=True)
    write_jsonl(settings.transcripts_dir / f"{group.video_id}.jsonl", segments)
    video = apply_meta(Video(
        video_id=group.video_id,
        title=group.title,
        source_uri=";".join(p.name for p in group.parts),
        duration_s=round(result.duration_s, 2),
        language=result.language,
        sha256=file_sha256(group.parts[0]) if len(group.parts) == 1 else None,
        kind=kind,
    ), meta)
    stat = IngestStat(
        video_id=group.video_id,
        model=model_name,
        audio_s=round(result.duration_s, 2),
        decode_s=round(t1 - t0, 2),
        transcribe_s=round(t2 - t1, 2),
        segments=len(result.segments),
        words=sum(len(s.text.split()) for s in result.segments),
        language=result.language,
    )
    return video, stat


def _vision_llm(settings: Settings):
    """LLM de vision (le même que celui des réponses : gemma3 sait lire les images), ou None."""
    if not settings.vision.describe:
        return None
    from kb.adapters.factory import build_llm

    return build_llm(settings)


def ingest_image(path: Path, settings: Settings) -> tuple[Video, IngestStat]:
    """Image seule (schéma, photo de tableau, capture) → texte lu + description, « page » 1."""
    from PIL import Image

    from kb.ingest.vision import image_segments

    t0 = time.perf_counter()
    video_id = slugify(path.stem)
    with Image.open(path) as img:
        segments = image_segments(img, video_id, 1, 0, _vision_llm(settings),
                                  always_describe=True)
    write_jsonl(settings.transcripts_dir / f"{video_id}.jsonl", segments)
    text = " ".join(s.text for s in segments if s.modality == "ocr")
    meta = load_meta(settings.data_dir, video_id)
    video = apply_meta(Video(
        video_id=video_id, title=path.stem.replace("_", " ").strip().capitalize(),
        source_uri=path.name, duration_s=0.0, sha256=file_sha256(path), kind="image",
        # langue saisie à l'import, sinon devinée (un schéma a souvent trop peu de mots)
        language=(meta.language if meta else None) or detect_language(text),
    ), meta)
    stat = IngestStat(video_id=video_id, model="ocr+vision", audio_s=0.0, decode_s=0.0,
                      transcribe_s=round(time.perf_counter() - t0, 2), segments=len(segments),
                      words=sum(len(s.text.split()) for s in segments), language=video.language)
    print(f"→ {video_id} : image, {sum(s.modality == 'ocr' for s in segments)} unité(s) lue(s), "
          f"{sum(s.modality == 'visual' for s in segments)} de description, "
          f"{stat.transcribe_s:.0f} s", flush=True)
    return video, stat


def ingest_document(path: Path, settings: Settings) -> tuple[Video, IngestStat]:
    """PDF → segments par page (`data/transcripts/<id>.jsonl`) + fiche `Video` (kind=document)."""
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return ingest_image(path, settings)
    t0 = time.perf_counter()
    doc = extract_pdf(path, llm=_vision_llm(settings), read_scans=True)
    write_jsonl(settings.transcripts_dir / f"{doc.video_id}.jsonl", doc.segments)
    meta = load_meta(settings.data_dir, doc.video_id)
    video = apply_meta(Video(
        video_id=doc.video_id, title=doc.title, source_uri=path.name, duration_s=0.0,
        language=(meta.language if meta else None) or doc.language,
        sha256=file_sha256(path), kind="document",
    ), meta)
    stat = IngestStat(
        video_id=doc.video_id, model="pypdf", audio_s=0.0, decode_s=0.0,
        transcribe_s=round(time.perf_counter() - t0, 2), segments=len(doc.segments),
        words=sum(len(s.text.split()) for s in doc.segments), language=doc.language,
    )
    note = (f", {len(doc.empty_pages)} page(s) scannée(s) lue(s) par OCR/vision"
            if doc.empty_pages else "")
    print(f"→ {doc.video_id} : document de {doc.pages} page(s), {stat.segments} unités, "
          f"langue={doc.language}{note}", flush=True)
    return video, stat


def ingest_folder(
    folder: Path, transcriber: Transcriber, settings: Settings, model_name: str, force: bool = False
) -> list[IngestStat]:
    """Transcrit chaque enregistrement (déjà transcrit → ignoré, sauf `force`)."""
    videos = {v.video_id: v for v in read_jsonl(settings.videos_file, Video)} if (
        settings.videos_file.exists()
    ) else {}
    stats = []
    for group in discover_media(folder):
        done = (settings.transcripts_dir / f"{group.video_id}.jsonl").exists()
        if done and group.video_id in videos and not force:
            print(f"= {group.video_id} déjà transcrit (--force pour refaire)")
            continue
        print(f"→ {group.video_id} ({len(group.parts)} morceau(x))", flush=True)
        try:
            video, stat = ingest_group(group, transcriber, settings, model_name)
        except NoAudioTrack as exc:  # un média illisible ne doit pas arrêter le lot
            print(f"  ⚠ ignoré : {exc}", flush=True)
            continue
        videos[video.video_id] = video
        write_jsonl(settings.videos_file, videos.values())  # sauvegarde au fil de l'eau
        stats.append(stat)
        print(f"  {stat.audio_s / 60:.1f} min d'audio, {stat.segments} segments, "
              f"langue={stat.language}, RTF={stat.rtf:.2f}", flush=True)
    for path in discover_documents(folder):  # PDF… : même dossier, même sortie (segments)
        video_id = slugify(path.stem)
        done = (settings.transcripts_dir / f"{video_id}.jsonl").exists()
        if done and video_id in videos and not force:
            print(f"= {video_id} déjà extrait (--force pour refaire)")
            continue
        video, stat = ingest_document(path, settings)
        videos[video.video_id] = video
        write_jsonl(settings.videos_file, videos.values())
        stats.append(stat)
    if stats:
        log = settings.data_dir / "ingest_runs.jsonl"
        with log.open("a", encoding="utf-8") as f:
            for s in stats:
                f.write(json.dumps({**asdict(s), "rtf": round(s.rtf, 3)}) + "\n")
    return stats
