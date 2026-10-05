"""Métriques d'évaluation (CLAUDE.md, section 8).

Fonctions pures, sans appel réseau : le runner d'évaluation (Phase 5) leur passe des
résultats déjà calculés. Toute proportion affichée passe par `rate()` (intervalle de Wilson).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

# --- Proportions + intervalle de confiance -------------------------------------------


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de confiance de Wilson (95 % par défaut) pour une proportion."""
    if n <= 0:
        raise ValueError("n doit être > 0")
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class Rate:
    """Une proportion mesurée, toujours accompagnée de son n et de son IC 95 %."""

    successes: int
    n: int

    @property
    def value(self) -> float:
        return self.successes / self.n if self.n else float("nan")

    @property
    def ci95(self) -> tuple[float, float]:
        return wilson_interval(self.successes, self.n) if self.n else (float("nan"),) * 2

    def __str__(self) -> str:
        if not self.n:
            return "n/a (n=0)"
        low, high = self.ci95
        return f"{self.value:.1%} ({self.successes}/{self.n}, IC95 [{low:.1%} ; {high:.1%}])"


def rate(flags: Sequence[bool]) -> Rate:
    return Rate(sum(bool(f) for f in flags), len(flags))


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# --- L0 Transcription -----------------------------------------------------------------

_PUNCT = re.compile(r"[^\w\s']", re.UNICODE)


def _words(text: str) -> list[str]:
    return _PUNCT.sub(" ", text.lower().replace("’", "'")).split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    """WER = (S + D + I) / N, sur des mots normalisés (minuscules, sans ponctuation)."""
    ref, hyp = _words(reference), _words(hypothesis)
    if not ref:
        raise ValueError("La référence est vide")
    prev = list(range(len(hyp) + 1))  # distance d'édition, ligne par ligne
    for i, r in enumerate(ref, start=1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


# --- L2 Recherche ---------------------------------------------------------------------


def recall_at_k(ranked_ids: Sequence[str], relevant_ids: set[str], k: int) -> float:
    """Part des éléments pertinents présents dans le top-k."""
    if not relevant_ids:
        raise ValueError("relevant_ids ne peut pas être vide")
    return len(set(ranked_ids[:k]) & relevant_ids) / len(relevant_ids)


def hit_at_k(ranked_ids: Sequence[str], relevant_ids: set[str], k: int) -> bool:
    return any(r in relevant_ids for r in ranked_ids[:k])


def reciprocal_rank(ranked_ids: Sequence[str], relevant_ids: set[str]) -> float:
    for rank, rid in enumerate(ranked_ids, start=1):
        if rid in relevant_ids:
            return 1.0 / rank
    return 0.0


def timestamp_hit(pred_s: float, true_s: float, tolerance_s: float = 30.0) -> bool:
    return abs(pred_s - true_s) <= tolerance_s


def moment_hit(
    pred_video_id: str | None,
    pred_start_s: float | None,
    true_video_id: str,
    true_start_s: float,
    tolerance_s: float = 30.0,
) -> bool:
    """Précision du moment : bonne vidéo ET |t − t_vrai| ≤ tolérance."""
    return (
        pred_video_id == true_video_id
        and pred_start_s is not None
        and timestamp_hit(pred_start_s, true_start_s, tolerance_s)
    )


# --- L1 Structuration (fiches REX) -----------------------------------------------------


def field_precision_recall_f1(
    pairs: Sequence[tuple[object | None, object | None]], fuzzy: bool = True, threshold: int = 80
) -> tuple[Rate, Rate, float]:
    """P / R / F1 d'un champ nullable, sur des paires (valeur extraite, valeur attendue).

    Précision = part des valeurs EXTRAITES (non nulles) qui sont correctes.
    Rappel    = part des valeurs ATTENDUES (non nulles) effectivement retrouvées.
    Deux `None` d'accord ne comptent dans aucun des deux : c'est `null_correctness`.
    """
    from rapidfuzz import fuzz

    def _match(pred: object, exp: object) -> bool:
        if pred is None or exp is None:
            return False
        if fuzzy and isinstance(pred, str) and isinstance(exp, str):
            return fuzz.partial_ratio(pred.lower(), exp.lower()) >= threshold
        return pred == exp

    extracted = [(p, e) for p, e in pairs if p is not None]
    expected = [(p, e) for p, e in pairs if e is not None]
    precision = rate([_match(p, e) for p, e in extracted])
    recall = rate([_match(p, e) for p, e in expected])
    if not precision.n or not recall.n:
        return precision, recall, 0.0
    denom = precision.value + recall.value
    f1 = 2 * precision.value * recall.value / denom if denom else 0.0
    return precision, recall, f1


def null_correctness(pairs: Sequence[tuple[object | None, object | None]]) -> Rate:
    """Part des champs à raison laissés vides (attendu `None` → extrait `None`)."""
    return rate([p is None for p, e in pairs if e is None])


# --- L4 Génération --------------------------------------------------------------------


def faithfulness(supported_claims: int, total_claims: int) -> float:
    """Affirmations appuyées par une source / affirmations (comptées par juge ou humain)."""
    if total_claims <= 0:
        raise ValueError("total_claims doit être > 0")
    return supported_claims / total_claims


def hallucination_rate(unsupported_per_answer: Sequence[int]) -> Rate:
    """Réponses DONNÉES avec au moins une affirmation non appuyée / réponses données."""
    return rate([u > 0 for u in unsupported_per_answer])


def citation_verified_rate(verified_flags: Sequence[bool]) -> Rate:
    return rate(verified_flags)


# --- Abstention -----------------------------------------------------------------------


@dataclass(frozen=True)
class AbstentionReport:
    correct_abstention: Rate  # questions sans réponse → le système s'abstient
    false_abstention: Rate  # questions avec réponse → le système s'abstient à tort
    coverage: Rate  # part des questions répondables auxquelles il répond
    selective_accuracy: Rate  # exactitude parmi les réponses données (répondables)


def abstention_report(
    answerable: Sequence[bool], abstained: Sequence[bool], correct: Sequence[bool]
) -> AbstentionReport:
    """`correct[i]` n'est lu que si la question est répondable et qu'on a répondu."""
    if not len(answerable) == len(abstained) == len(correct):
        raise ValueError("Listes de longueurs différentes")
    rows = list(zip(answerable, abstained, correct, strict=True))
    unans = [ab for a, ab, _ in rows if not a]
    ans = [ab for a, ab, _ in rows if a]
    answered_ok = [c for a, ab, c in rows if a and not ab]
    return AbstentionReport(
        correct_abstention=rate(unans),
        false_abstention=rate(ans),
        coverage=rate([not ab for ab in ans]),
        selective_accuracy=rate(answered_ok),
    )


def risk_coverage_curve(
    scores: Sequence[float], correct: Sequence[bool]
) -> list[tuple[float, float, float]]:
    """Pour chaque seuil possible : (seuil, couverture, risque = taux d'erreur des réponses).

    On répond si score ≥ seuil. Sert à choisir `abstain_threshold` sur le golden set.
    """
    if len(scores) != len(correct):
        raise ValueError("Listes de longueurs différentes")
    n = len(scores)
    curve = []
    for t in sorted(set(scores), reverse=True):
        kept = [c for s, c in zip(scores, correct, strict=True) if s >= t]
        curve.append((t, len(kept) / n, 1 - sum(kept) / len(kept)))
    return curve


# --- Ops ------------------------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> float:
    """Percentile par interpolation linéaire (q entre 0 et 100), ex. latence p95."""
    if not values:
        raise ValueError("Aucune valeur")
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def cost_usd(
    input_tokens: int, output_tokens: int, input_per_m: float, output_per_m: float
) -> float:
    """Coût d'un appel = tokens × tarif du profil ($ par million de tokens)."""
    return (input_tokens * input_per_m + output_tokens * output_per_m) / 1_000_000
