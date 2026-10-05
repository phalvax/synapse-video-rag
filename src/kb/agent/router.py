"""Routage des questions « point de situation » vers le point mission (L3), sans appel LLM.

« Fais-moi un point sur la mission ES2002 » n'est pas une question ponctuelle : aucun passage
n'y répond seul (le reranker les note tous bas → abstention). Le point mission, lui, est déjà
calculé. Règle déterministe, donc testable et instantanée :
- une INTENTION de synthèse (point, récap, résumé, avancement, où en est…) ;
- ET une mission désignée : son nom dans la question, ou le seul projet disponible quand la
  question parle de « la mission » / « le projet ».
"""

from __future__ import annotations

import re
import unicodedata

INTENT = re.compile(
    r"\b(point|recap\w*|resume\w*|synthese|bilan|avancement|avancee?s?|etat|statut|status|"
    r"summary|summari[sz]e|progress|update|ou en est|where (are|is) (we|the))\b"
)
PROJECT_WORD = re.compile(r"\b(mission|projet|project|reunions?|meetings?)\b")


def _fold(text: str) -> str:
    """Minuscules sans accents (« Où en est » → « ou en est »)."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def named_missions(question: str, missions: list[str]) -> list[str]:
    """Missions citées par leur nom dans la question (« l'équipe ES2004 » → ["ES2004"])."""
    q = _fold(question)
    return [m for m in missions if re.search(rf"\b{re.escape(_fold(m))}\b", q)]


def recap_target(question: str, missions: list[str]) -> str | None:
    """Mission dont on demande le point, ou None (question ordinaire → agent)."""
    q = _fold(question)
    if not INTENT.search(q):
        return None
    named = named_missions(question, missions)
    if len(named) == 1:
        return named[0]
    if not named and len(missions) == 1 and PROJECT_WORD.search(q):
        return missions[0]
    return None
