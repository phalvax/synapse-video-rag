"""Transcriptions de référence HUMAINES pour mesurer le WER.

Nos données de test sont des talks TED publics : TED publie une transcription faite par des
humains, horodatée à la phrase (« cues »). On la télécharge une fois dans `data/references/`
(jamais dans git : droits TED).

Limite connue : TED « nettoie » l'oral (hésitations, faux départs supprimés) → le WER mesuré
contre cette référence est légèrement pessimiste.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from kb.schemas import Segment

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_STAGE = re.compile(r"\([^)]*\)")  # (Applause), (Laughter)…


@dataclass(frozen=True)
class Cue:
    start_s: float
    text: str


def parse_ted_page(html: str) -> list[Cue]:
    m = _NEXT_DATA.search(html)
    if not m:
        raise ValueError("Page TED sans __NEXT_DATA__ (format changé ?)")
    cues: list[Cue] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("__typename") == "Cue" and "time" in node:
                cues.append(Cue(node["time"] / 1000, " ".join(node["text"].split())))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(json.loads(m.group(1)))
    return sorted(set(cues), key=lambda c: c.start_s)


def fetch_ted_reference(video_id: str, cache_dir: Path) -> list[Cue]:
    """Télécharge (ou relit depuis le cache) la transcription TED du talk `video_id`."""
    path = cache_dir / f"{video_id}.json"
    if not path.exists():
        import httpx

        url = f"https://www.ted.com/talks/{video_id}?view=transcript"
        resp = httpx.get(url, follow_redirects=True, timeout=30, headers={"User-Agent": "kb-eval"})
        resp.raise_for_status()
        cues = parse_ted_page(resp.text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([c.__dict__ for c in cues], ensure_ascii=False), "utf-8")
    return [Cue(**c) for c in json.loads(path.read_text("utf-8"))]


def reference_text(cues: list[Cue], until_s: float) -> str:
    """Texte de référence jusqu'à `until_s`, sans les didascalies (Applause)."""
    return " ".join(_STAGE.sub(" ", c.text) for c in cues if c.start_s < until_s)


@dataclass(frozen=True)
class Alignment:
    offset_s: float  # à ajouter à un temps TED pour obtenir le temps de notre fichier
    matches: int
    median_abs_error_s: float  # écart résiduel entre débuts de phrase alignés


def align_to_reference(
    segments: list[Segment], cues: list[Cue], around_s: float | None = None, window_s: float = 150
) -> Alignment:
    """Compare les débuts de phrase de notre transcript et de la référence humaine.

    Notre fichier audio n'a pas forcément la même chronologie que la vidéo TED (générique,
    coupe) : on mesure le décalage au lieu de le supposer nul. Si `around_s` est donné, on
    ne garde que les correspondances proches de ce moment (décalage local).
    """
    from rapidfuzz import fuzz

    deltas = []
    for cue in cues:
        ref = _norm(_STAGE.sub(" ", cue.text))
        if len(ref) < 20:
            continue
        for seg in segments:
            if around_s is not None and not (around_s - window_s <= seg.start_s <= around_s):
                continue
            if fuzz.ratio(ref, _norm(seg.text)[: len(ref)]) >= 85:
                deltas.append(seg.start_s - cue.start_s)
                break
    if not deltas:
        return Alignment(0.0, 0, float("nan"))
    offset = statistics.median(deltas)
    return Alignment(round(offset, 2), len(deltas),
                     round(statistics.median(abs(d - offset) for d in deltas), 2))


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())
