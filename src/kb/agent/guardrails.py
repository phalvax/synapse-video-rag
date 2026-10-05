"""Garde-fous déterministes (les « ralentisseurs ») — CLAUDE.md, section 7.

Ils ne font confiance ni au LLM ni aux sources : tout est vérifié par du code.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from rapidfuzz import fuzz

from kb.schemas import Answer, Chunk

MIN_QUOTE_CHARS = 12  # une citation trop courte (« le projet ») matcherait n'importe quoi
_SPACES = re.compile(r"\s+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_CLOSE_SOURCE = re.compile(r"<\s*/\s*source\s*>", re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

M = TypeVar("M", bound=BaseModel)


def normalize(text: str) -> str:
    return _SPACES.sub(" ", text.lower()).strip()


def verify_quote(quote: str, source_text: str, threshold: int = 90) -> bool:
    """Vrai si `quote` apparaît (quasi) mot pour mot dans `source_text`.

    Trois contrôles en plus du score flou :
    - citation trop courte → refusée ;
    - citation plus longue que la source → refusée (sinon `partial_ratio` aligne la
      source DANS la citation, et du texte inventé autour passerait) ;
    - chaque nombre de la citation doit exister dans la source (« 800 ms » ≠ « 80 ms »).
    """
    q, src = normalize(quote), normalize(source_text)
    if len(q) < MIN_QUOTE_CHARS or len(q) > len(src):
        return False
    if not set(_NUMBER.findall(q)) <= set(_NUMBER.findall(src)):
        return False
    return fuzz.partial_ratio(q, src) >= threshold


def snap_quote(quote: str, source_text: str, threshold: int = 90) -> str | None:
    """Remplace la citation par le passage EXACT de la source auquel elle correspond.

    Les petits modèles reformulent légèrement au lieu de recopier (majuscule, ponctuation,
    mot oublié) : la citation est alors refusée alors que l'information est bien là. On
    recale donc la citation sur le texte réel de la source ; si l'alignement est moins bon
    que `threshold`, on renvoie None (la citation sera refusée).
    """
    compact = _SPACES.sub(" ", source_text).strip()  # source, espaces normalisés, casse d'origine
    low = compact.lower()
    q = normalize(quote)
    if len(q) < MIN_QUOTE_CHARS or len(q) > len(low) or len(low) != len(compact):
        return None
    align = fuzz.partial_ratio_alignment(q, low)
    if align is None or align.score < threshold:
        return None
    window = compact[align.dest_start : align.dest_end].strip()
    if not set(_NUMBER.findall(q)) <= set(_NUMBER.findall(window)):
        return None  # un nombre inventé (« 12 » au lieu de « 120 ») reste refusé
    return window or None


def verify_citations(answer: Answer, chunks: dict[str, Chunk], threshold: int = 90,
                     snap: bool = True) -> Answer:
    """Renvoie une copie de `answer` où chaque citation porte `verified=True/False`.

    Avec `snap`, une citation quasi exacte est recalée sur le texte de la source, pour que
    ce qui s'affiche soit toujours du transcript et non une reformulation du modèle.
    """
    checked = []
    for c in answer.citations:
        source = chunks.get(c.chunk_id)
        if source is None or source.video_id != c.video_id:
            checked.append(c.model_copy(update={"verified": False}))
            continue
        # La source citée d'abord ; puis les autres sources fournies : les petits modèles
        # recopient bien la phrase mais se trompent d'étiquette (S2 au lieu de S1). Le code
        # rattache alors la citation à la source où elle figure VRAIMENT (lien et seconde).
        others = [ch for cid, ch in chunks.items() if cid != c.chunk_id]
        found = None
        for cand in [source, *others]:
            snapped = snap_quote(c.quote, cand.text, threshold) if snap else None
            if snapped is not None:
                found = (cand, snapped)
            elif verify_quote(c.quote, cand.text, threshold):
                found = (cand, c.quote)
            if found:
                break
        if found is None:
            checked.append(c.model_copy(update={"verified": False}))
        else:
            cand, quote = found
            checked.append(c.model_copy(update={"verified": True, "quote": quote,
                                                "chunk_id": cand.chunk_id,
                                                "video_id": cand.video_id}))
    return answer.model_copy(update={"citations": checked})


# Un nombre collé à des lettres (ES2002, es2004d, mp3, v2) est un IDENTIFIANT, pas un chiffre
# affirmé. Bug mesuré le 27/09 : « l'équipe ES2002 a choisi… » → « 2002 n'apparaît dans aucune
# source » → 5 fausses abstentions sur 16 questions AMI.
_DIGITS = re.compile(r"(?<![A-Za-z\d])\d+(?![A-Za-z\d])")
_SOURCE_REF = re.compile(r"\[S\d+\]")


def answer_numbers(text: str | None) -> set[str]:
    """Nombres affirmés dans la réponse (les renvois [S1], [S2]… ne comptent pas)."""
    return set(_DIGITS.findall(_SOURCE_REF.sub(" ", text or "")))


def number_window(source_text: str, number: str, words: int = 12) -> str | None:
    """Extrait EXACT de la source autour de la 1re occurrence de `number` (± `words` mots)."""
    tokens = _SPACES.sub(" ", source_text).strip().split(" ")
    for i, tok in enumerate(tokens):
        if number in _DIGITS.findall(tok):
            return " ".join(tokens[max(0, i - words): i + words + 1])
    return None


def enforce_verified(answer: Answer) -> Answer:
    """Politique : on ne montre que les citations vérifiées ; sans preuve → abstention."""
    if answer.not_found:
        return answer
    kept = [c for c in answer.citations if c.verified]
    if not kept:
        return Answer(not_found=True, confidence=0.0)
    return answer.model_copy(update={"citations": kept})


def should_abstain(best_score: float | None, threshold: float) -> bool:
    """Seuil d'abstention AVANT génération : pas de bon passage → pas d'appel LLM."""
    return best_score is None or best_score < threshold


def wrap_sources(chunks: list[Chunk]) -> str:
    """Encadre les extraits comme des DONNÉES (anti prompt-injection)."""
    parts = []
    for i, ch in enumerate(chunks, start=1):
        text = _CLOSE_SOURCE.sub("[/source]", ch.text)
        # Contexte (titre, mission, date…) : permet au LLM de dire QUELLE source dit quoi, et
        # laquelle est la plus récente en cas de contradiction.
        date = f' date="{ch.date.isoformat()}"' if ch.date else ""
        context = _CLOSE_SOURCE.sub("[/source]", ch.context_header).replace('"', "'")
        parts.append(
            f'<source id="S{i}" chunk_id="{ch.chunk_id}" video_id="{ch.video_id}" '
            f'start_s="{ch.start_s:.0f}"{date} context="{context}">\n{text}\n</source>'
        )
    return "\n".join(parts)


def extract_json(raw: str) -> str:
    """Retire ce qui entoure le JSON : bloc <think> (qwen3), balises ```json, texte parasite."""
    text = _FENCE.sub("", _THINK.sub("", raw).strip()).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("Aucun objet JSON dans la sortie du LLM.")
    return text[start : end + 1]


def parse_output(raw: str, model: type[M]) -> M:
    """Valide la sortie du LLM contre un schéma Pydantic (lève ValueError si invalide).

    L'appelant fait UNE nouvelle tentative, puis renvoie une erreur (CLAUDE.md, section 7).
    """
    try:
        return model.model_validate(json.loads(extract_json(raw)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"Sortie LLM non conforme à {model.__name__} : {exc}") from exc
