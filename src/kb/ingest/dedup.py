"""Doublons : un enregistrement déjà présent ne doit pas être retraité ni indexé deux fois.

Deux niveaux, du moins cher au plus cher :
1. **Doublon exact** : même empreinte SHA-256 du fichier → refusé dès l'upload (0 calcul).
2. **Quasi-doublon** : même contenu sous un autre encodage (mp4 ↔ wav), ou extrait d'une
   réunion déjà présente → détecté APRÈS transcription, en comparant les transcripts.
   Mesure : part des « shingles » (suites de 5 mots) du nouveau transcript déjà présentes
   dans un transcript existant (*containment*). Déterministe, rapide, explicable :
   « 93 % des phrases de ce fichier existent déjà dans la réunion ES2002a ».
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

SHINGLE_WORDS = 5
# Calibré le 27/09 sur le corpus (10 réunions) : le MÊME audio re-transcrit (extrait mp4 de
# 60 s d'ES2002a) ne partage que 0,54 de ses 5-grammes (Whisper ne transcrit pas mot pour mot
# pareil : découpage, compression) ; des réunions DIFFÉRENTES, même sur le même projet et le
# même brief, ≤ 0,03 (extraits de 150 mots tirés au hasard, 50 essais). Seuil au milieu.
# Un seul vrai doublon mesuré : à revalider sur d'autres cas.
NEAR_DUPLICATE = 0.3
_WORD = re.compile(r"[a-z0-9àâäçéèêëîïôöùûüÿœ']+")


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _stable_hash(s: str) -> int:
    """Empreinte stable d'une exécution à l'autre (`hash()` de Python est aléatoire)."""
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


def shingles(text: str, k: int = SHINGLE_WORDS) -> set[int]:
    """Suites de k mots (normalisés) : insensibles à la casse, à la ponctuation, aux espaces."""
    words = _WORD.findall(text.lower())
    if len(words) < k:
        return {_stable_hash(" ".join(words))} if words else set()
    return {_stable_hash(" ".join(words[i:i + k])) for i in range(len(words) - k + 1)}


def containment(new: set[int], existing: set[int]) -> float:
    """Part du nouveau contenu déjà présente dans l'existant (0 à 1)."""
    return len(new & existing) / len(new) if new else 0.0


def find_near_duplicate(new_text: str, others: dict[str, str],
                        threshold: float = NEAR_DUPLICATE) -> tuple[str, float] | None:
    """(video_id, score) de l'enregistrement existant qui contient déjà ce contenu, ou None."""
    new = shingles(new_text)
    best = max(((vid, containment(new, shingles(text))) for vid, text in others.items()),
               key=lambda x: x[1], default=None)
    return best if best and best[1] >= threshold else None
