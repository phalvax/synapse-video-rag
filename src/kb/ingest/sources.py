"""Découverte des fichiers médias et regroupement des morceaux d'un même enregistrement.

`talk_seg01.wav`, `talk_seg02.wav`… forment UNE vidéo `talk` : on les met bout à bout,
et les timestamps restent ceux de l'enregistrement complet (seg02 commence après seg01).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Tout ce que PyAV (ffmpeg) sait décoder : vidéo, audio, conteneurs de réunion.
VIDEO_EXTENSIONS = {
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".mpg", ".mpeg",
    ".mts", ".m2ts", ".ts", ".3gp", ".ogv", ".asf", ".vob", ".rm", ".rmvb",
}
AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".oga", ".opus", ".aac", ".wma", ".aif",
    ".aiff", ".alac", ".amr", ".ac3", ".mp2", ".caf", ".w64", ".au",
}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
_PART = re.compile(r"^(?P<base>.+?)[_-](?:seg|part)(?P<num>\d+)$", re.IGNORECASE)
_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class MediaGroup:
    video_id: str
    title: str
    parts: tuple[Path, ...]


def slugify(name: str) -> str:
    return _SLUG.sub("_", name.lower()).strip("_")


def _split_part(stem: str) -> tuple[str, int]:
    m = _PART.match(stem)
    return (m.group("base"), int(m.group("num"))) if m else (stem, 0)


def discover_media(folder: Path) -> list[MediaGroup]:
    """Liste les enregistrements d'un dossier, morceaux regroupés et triés par numéro."""
    groups: dict[str, list[tuple[int, Path]]] = {}
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            base, num = _split_part(path.stem)
            groups.setdefault(base, []).append((num, path))
    return [
        MediaGroup(
            video_id=slugify(base),
            title=base.replace("_", " ").strip().capitalize(),
            parts=tuple(p for _, p in sorted(parts)),
        )
        for base, parts in sorted(groups.items())
    ]
