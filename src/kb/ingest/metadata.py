"""Formulaire d'import : le contexte saisi par l'humain (titre, auteur, date, mission…).

Il est enregistré à côté des données (`data/metadata/<video_id>.json`) au moment de l'upload,
puis appliqué à la `Video` lors de la transcription. Pourquoi : ces informations ne sont
presque jamais prononcées dans l'enregistrement (« réunion du 12/09, équipe ES2002, contact
Laura ») ; les saisir rend la recherche et le point mission plus précis (en-tête des chunks).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from pydantic import BaseModel, field_validator

from kb.schemas import Video

LANGUAGES = {"fr", "en", "de", "es", "it"}  # « auto » = détection par Whisper


class UploadMeta(BaseModel):
    title: str | None = None
    author: str | None = None
    date: dt.date | None = None
    mission: str | None = None
    client: str | None = None
    contact: str | None = None
    description: str | None = None
    language: str | None = None  # connue → Whisper saute la détection de langue

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("language")
    @classmethod
    def _known_language(cls, v: str | None) -> str | None:
        if v is None or v == "auto":
            return None
        if v not in LANGUAGES:
            known = ", ".join(sorted(LANGUAGES))
            raise ValueError(f"langue inconnue : {v} (attendu : auto, {known})")
        return v


def meta_path(data_dir: Path, video_id: str) -> Path:
    return data_dir / "metadata" / f"{video_id}.json"


def save_meta(data_dir: Path, video_id: str, meta: UploadMeta) -> None:
    path = meta_path(data_dir, video_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(meta.model_dump_json(indent=1), encoding="utf-8")


def load_meta(data_dir: Path, video_id: str) -> UploadMeta | None:
    path = meta_path(data_dir, video_id)
    if not path.exists():
        return None
    return UploadMeta.model_validate(json.loads(path.read_text(encoding="utf-8")))


def apply_meta(video: Video, meta: UploadMeta | None) -> Video:
    """Les champs saisis remplacent ceux déduits du nom de fichier ; un vide ne change rien."""
    if meta is None:
        return video
    update = {k: v for k, v in meta.model_dump(exclude={"language"}).items() if v is not None}
    return video.model_copy(update=update)
