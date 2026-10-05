"""Évaluation de l'agent : abstention, citations vérifiées, moment, latence, coût.

Ce que ce runner mesure **automatiquement** :
- abstention correcte / fausse abstention (le « taux d'hallucination » se juge à la main) ;
- taux de citations vérifiées par le code ;
- précision du moment de la première citation (±30 s) ;
- latence, tokens, coût par question.

Ce qu'il **n'évalue pas** : l'exactitude du texte rédigé. La colonne `indice_reponse` est une
heuristique (nombres et noms propres attendus retrouvés dans la réponse) : elle sert à trier les
réponses à relire, pas à annoncer un score d'exactitude. Un juge LLM viendra en Phase 5.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from kb.agent.agent import Agent
from kb.config import ROOT, Settings
from kb.eval.metrics import abstention_report, percentile, rate, timestamp_hit
from kb.eval.retrieval import load_golden, report_prefix, targets

REPORTS_DIR = ROOT / "docs" / "reports"
_KEY = re.compile(r"\d+(?:[.,]\d+)?|\b[A-ZÉÈÀÎÔÜ][\w'’-]{2,}")


@dataclass
class AgentRow:
    id: str
    type: str
    lang: str
    answerable: bool
    abstained: bool
    llm_calls: int
    citations: int
    citations_verified: int
    moment_hit: bool
    # Même 1re citation, seconde de l'ANCIENNE règle (moment le plus proche de la question) :
    # mesure l'effet du correctif « seconde = là où la citation apparaît » (27/09) sur les
    # mêmes réponses, sans relancer le LLM.
    moment_hit_before: bool
    indice_reponse: float  # heuristique : part des éléments clés attendus présents
    retrieval_score: float | None
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    note: str
    answer: str


def key_elements(expected: str | None) -> list[str]:
    """Nombres et noms propres attendus (heuristique de tri, pas une note d'exactitude)."""
    return list(dict.fromkeys(_KEY.findall(expected or ""))) if expected else []


def answer_hint(expected: str | None, answer: str | None) -> float:
    keys = key_elements(expected)
    if not keys or not answer:
        return 0.0
    low = answer.lower()
    return sum(k.lower() in low for k in keys) / len(keys)


def run_agent_eval(settings: Settings, golden_path: Path, types: list[str] | None = None,
                   limit: int | None = None, mode: str = "synthese",
                   ids: list[str] | None = None) -> list[AgentRow]:
    questions = load_golden(golden_path)
    if ids:
        questions = [q for q in questions if q["id"] in set(ids)]
    if types:
        questions = [q for q in questions if q["type"] in types]
    if limit:
        questions = questions[:limit]
    agent = Agent.load(settings)
    rows: list[AgentRow] = []
    for i, q in enumerate(questions, start=1):
        t0 = time.perf_counter()
        res = agent.ask(q["question"], mode=mode)
        a = res.answer
        verified = [c for c in a.citations if c.verified]
        moment = before = False
        if verified and q.get("expected_start_s") is not None:
            first = verified[0]
            old_s = next((h.moment_s for h in res.hits if h.chunk.chunk_id == first.chunk_id),
                         first.start_s)
            moment = any(first.video_id == vid and timestamp_hit(first.start_s, t)
                         for vid, t in targets(q))
            before = any(first.video_id == vid and timestamp_hit(old_s, t)
                         for vid, t in targets(q))
        rows.append(AgentRow(
            id=q["id"], type=q["type"], lang=q.get("lang", "?"), answerable=q["answerable"],
            abstained=a.not_found, llm_calls=res.llm_calls, citations=len(a.citations),
            citations_verified=len(verified), moment_hit=moment, moment_hit_before=before,
            indice_reponse=round(answer_hint(q.get("expected_answer"), a.answer), 2),
            retrieval_score=res.retrieval_score,
            latency_ms=round(1000 * (time.perf_counter() - t0)),
            input_tokens=res.input_tokens, output_tokens=res.output_tokens,
            cost_usd=res.cost_usd, note=res.note, answer=(a.answer or "")[:500],
        ))
        print(f"[{i}/{len(questions)}] {q['id']} "
              f"{'ABSTENTION' if a.not_found else 'réponse'} "
              f"({rows[-1].latency_ms / 1000:.0f} s) {rows[-1].note}", flush=True)
    _write_report(settings, rows, mode, report_prefix(golden_path))
    return rows


def _write_report(settings: Settings, rows: list[AgentRow], mode: str, prefix: str = "") -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = REPORTS_DIR / f"{prefix}agent_{settings.profile}_{mode}_{dt.date.today().isoformat()}"
    with stem.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0])))
        w.writeheader()
        w.writerows(asdict(r) for r in rows)

    ans = [r for r in rows if r.answerable]
    given = [r for r in ans if not r.abstained]
    rep = abstention_report([r.answerable for r in rows], [r.abstained for r in rows],
                            [r.moment_hit for r in rows])
    lat = [r.latency_ms for r in rows]
    cited = [r for r in given if r.citations]
    lines = [
        f"# Agent : évaluation (profil `{settings.profile}`, mode `{mode}`)",
        "",
        f"- LLM : `{settings.llm.model}` · seuil {settings.retrieval.abstain_threshold} · "
        f"{len(rows)} questions ({len(ans)} répondables, {len(rows) - len(ans)} sans réponse).",
        "- Les citations sont vérifiées **par le code** (`rapidfuzz.partial_ratio ≥ 90`, ≥ 12 "
        "caractères, pas plus longue que sa source, nombres identiques).",
        "",
        "## Abstention",
        "",
        f"- Abstention correcte (questions sans réponse) : {rep.correct_abstention}",
        f"- Fausse abstention (questions répondables) : {rep.false_abstention}",
        f"- Couverture : {rep.coverage}",
        "",
        "## Preuves",
        "",
        f"- Réponses avec au moins une citation : {rate([bool(r.citations) for r in given])}",
        f"- Citations vérifiées / citations proposées : "
        f"{sum(r.citations_verified for r in given)} / {sum(r.citations for r in given)}",
        f"- Réponses dont TOUTES les citations sont vérifiées : "
        f"{rate([r.citations_verified == r.citations for r in cited])}",
        f"- Bon moment (±30 s) sur la 1re citation vérifiée : "
        f"{rate([r.moment_hit for r in given])}",
        f"  - avec l'ancienne règle (moment le plus proche de la question, mêmes réponses) : "
        f"{rate([r.moment_hit_before for r in given])}",
        "",
        "## Coût et latence",
        "",
        f"- Latence p50 / p95 : {percentile(lat, 50) / 1000:.1f} s / "
        f"{percentile(lat, 95) / 1000:.1f} s",
        f"- Tokens moyens : {sum(r.input_tokens for r in rows) / max(len(rows), 1):.0f} en entrée, "
        f"{sum(r.output_tokens for r in rows) / max(len(rows), 1):.0f} en sortie",
        f"- Coût total mesuré : {sum(r.cost_usd for r in rows):.6f} $ "
        f"(tarifs du profil : {settings.llm.input_per_m} / {settings.llm.output_per_m} $ par M)",
        "",
        "## Détail",
        "",
        "| id | type | langue | attendu ? | abstention | citations ✓/total | moment | indice | s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| `{r.id}` | {r.type} | {r.lang} | {'oui' if r.answerable else 'non'} | "
            f"{'oui' if r.abstained else 'non'} | {r.citations_verified}/{r.citations} | "
            f"{'✓' if r.moment_hit else '—'} | {r.indice_reponse:.2f} | {r.latency_ms / 1000:.0f} |"
        )
    lines += ["", "**À relire à la main** (l'indice de réponse est une heuristique) : voir le CSV, "
                  "colonne `answer`."]
    stem.with_suffix(".md").write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines))
    print(f"\nRapports : {stem}.md / .csv")
