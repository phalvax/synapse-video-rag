"""L0 Vidéo : ce qui est MONTRÉ à l'écran (diapositives, tableau blanc), en plus de ce qui est dit.

Une image est échantillonnée toutes les `every_s` secondes ; elle n'est gardée que si l'écran a
CHANGÉ : plus de `threshold` des pixels d'une vignette 160×90 varient franchement (> 0,15).
Calibré le 27/09 : l'écart MOYEN ratait une diapo (0,029 entre deux diapos texte sur fond
blanc) ; la part de pixels changés vaut 9,5-11,5 % pour un vrai changement et 0 % pour la même
diapo avec un bruit de caméra SIMULÉ (luminosité ±8 %, flou, grain) — à revalider sur une vraie
vidéo filmée. Chaque image gardée est lue par `kb.ingest.vision` (OCR, et description si
peu de texte) et produit des segments horodatés, mêlés au transcript de la parole.

Coût maîtrisé : une diapo fixe pendant 5 min ne produit qu'UNE image ; le nombre de
descriptions par le LLM de vision (≈ 1 min chacune sur CPU) est plafonné.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from kb.ingest.documents import page_units
from kb.schemas import Segment

if TYPE_CHECKING:
    from PIL.Image import Image

    from kb.adapters.base import LLM

EVERY_S = 1.0  # précision de datation d'une nouvelle diapo : ±1 s
THRESHOLD = 0.03  # part des pixels qui changent franchement → l'écran a « changé »
PIXEL_DELTA = 0.15  # variation (0-1) d'un pixel au-delà de laquelle il « change franchement »
MAX_FRAMES = 120  # garde-fou : une vidéo très animée ne doit pas produire des centaines d'images
THUMB = (160, 90)
# Une diapo = du texte : l'OCR suffit (mesuré le 27/09 : 4 diapos décrites = 234 s pour
# presque rien de plus, et une erreur « lecteur MP3 »). On ne décrit qu'un écran presque sans
# texte (croquis, tableau blanc, photo) : OCR < 40 caractères (« LCD 4 boutons » = 13).
DESCRIBE_IF_OCR_BELOW = 40


@dataclass
class KeyFrame:
    t: float  # seconde où l'écran apparaît
    image: Image


def has_video(path: Path) -> bool:
    """Le fichier contient-il une vraie piste vidéo (pas seulement une pochette d'album) ?"""
    import av

    try:
        with av.open(str(path)) as c:
            return any(s.type == "video" and (s.frames or 0) != 1 for s in c.streams)
    except Exception:  # noqa: BLE001 — fichier illisible : pas de vidéo
        return False


def _thumb(image: Image) -> np.ndarray:
    return np.asarray(image.convert("L").resize(THUMB), dtype=np.float32) / 255.0


def changed_fraction(a: np.ndarray, b: np.ndarray, delta: float = PIXEL_DELTA) -> float:
    """Part des pixels qui changent franchement entre deux vignettes (0 à 1)."""
    return float((np.abs(a - b) > delta).mean())


def keyframes(path: Path, every_s: float = EVERY_S, threshold: float = THRESHOLD,
              max_frames: int = MAX_FRAMES) -> list[KeyFrame]:
    """Images où l'écran change (la première est toujours gardée)."""
    import av

    kept: list[KeyFrame] = []
    last: np.ndarray | None = None
    next_t = 0.0
    with av.open(str(path)) as c:
        stream = next(s for s in c.streams if s.type == "video")
        for frame in c.decode(stream):
            if frame.time is None or frame.time < next_t:
                continue
            next_t = frame.time + every_s
            image = frame.to_image()
            thumb = _thumb(image)
            if last is None or changed_fraction(thumb, last) > threshold:
                kept.append(KeyFrame(round(float(frame.time), 2), image))
                last = thumb
                if len(kept) >= max_frames:
                    break
    return kept


def screen_segments(frames: list[KeyFrame], video_id: str, duration_s: float,
                    llm: LLM | None, max_descriptions: int = 8) -> list[Segment]:
    """Segments « à l'écran » : texte lu (ocr) et, si peu de texte, description (visual).

    Chaque segment couvre la durée d'affichage de son image (jusqu'au changement suivant) ;
    `seg_id` est provisoire (renuméroté à la fusion avec la parole)."""
    from kb.ingest.vision import describe, ocr, ocr_available

    can_ocr = ocr_available()
    out: list[Segment] = []
    described = 0
    for i, kf in enumerate(frames):
        end = frames[i + 1].t if i + 1 < len(frames) else max(duration_s, kf.t + 0.1)
        units: list[tuple[str, str]] = []
        text = ocr(kf.image) if can_ocr else ""
        units += [(u, "ocr") for u in page_units(text)]
        if llm is not None and len(text) < DESCRIBE_IF_OCR_BELOW and described < max_descriptions:
            units += [(u, "visual") for u in page_units(describe(llm, kf.image))]
            described += 1
        step = min(0.5, (end - kf.t) / max(1, len(units) + 1))
        for j, (unit, modality) in enumerate(units):
            start = kf.t + j * step  # positions distinctes, dans la fenêtre d'affichage
            out.append(Segment(video_id=video_id, seg_id=len(out), start_s=round(start, 2),
                               end_s=round(max(end, start), 2), text=unit, modality=modality))
    return out


def merge_timeline(speech: list[Segment], screen: list[Segment]) -> list[Segment]:
    """Parole + écran, triés par temps, `seg_id` renumérotés (l'ordre = la chronologie)."""
    merged = sorted([*speech, *screen], key=lambda s: (s.start_s, s.modality or ""))
    return [s.model_copy(update={"seg_id": i}) for i, s in enumerate(merged)]
