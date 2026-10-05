"""Évaluation de la recherche sur le golden set : ablation dense → BM25 → hybride → +rerank.

Pour chaque question répondable à cible unique : Hit@1, Hit@5, MRR, précision du moment
(bonne vidéo ET |t − t_attendu| ≤ 30 s). Pour les questions sans réponse : abstention au seuil
du reranker, et courbe risque-couverture pour choisir ce seuil.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from dataclasses import asdict, dataclass
from math import comb
from pathlib import Path

from kb.config import ROOT, Settings
from kb.eval.metrics import (
    abstention_report,
    mean,
    percentile,
    rate,
    risk_coverage_curve,
    timestamp_hit,
)
from kb.index.search import MODES, Searcher
from kb.schemas import Chunk

REPORTS_DIR = ROOT / "docs" / "reports"
DEFAULT_GOLDEN = ROOT / "src" / "kb" / "eval" / "golden_set.jsonl"
SINGLE_TARGET = {"single_fact", "paraphrase", "false_premise", "injection"}
BOUNDARY_S = 3.0  # tolérance sur les bornes de chunk (segmentations légèrement différentes)
LIST_K = 20  # profondeur de liste pour le MRR


@dataclass
class Row:
    id: str
    type: str
    lang: str
    mode: str
    answerable: bool
    hit1: bool = False
    hit5: bool = False
    rr: float = 0.0
    moment_hit: bool = False  # zoom sur le moment (fenêtre de 3 segments)
    chunk_start_hit: bool = False  # sans zoom : début du chunk
    top_video: str | None = None
    top_moment_s: float | None = None
    best_score: float | None = None
    latency_ms: float = 0.0
    n_relevant: int = 0


def report_prefix(golden_path: Path) -> str:
    """« » pour le golden set par défaut (lu par le dashboard), « ami_ » pour golden_ami.jsonl…

    Un autre corpus ne doit pas remplacer en silence les chiffres affichés du dashboard."""
    if Path(golden_path).resolve() == DEFAULT_GOLDEN.resolve():
        return ""
    return Path(golden_path).stem.removeprefix("golden_").removeprefix("set_") + "_"


def load_golden(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def is_relevant(chunk: Chunk, video_id: str, t: float) -> bool:
    return chunk.video_id == video_id and chunk.start_s - BOUNDARY_S <= t <= chunk.end_s


def targets(q: dict) -> list[tuple[str, float]]:
    """(vidéo, seconde) acceptées : la cible principale + `also_relevant` (même info dite
    ailleurs, ex. le brief lu par les deux équipes)."""
    out = [(q["expected_video_id"], float(q["expected_start_s"]))]
    out += [(v, float(t)) for v, t in q.get("also_relevant", [])]
    return out


def evaluate_question(searcher: Searcher, q: dict, mode: str) -> Row:
    res = searcher.search(q.get("_search_query", q["question"]), mode=mode, k=LIST_K,
                          filters=q.get("_filters"))
    row = Row(id=q["id"], type=q["type"], lang=q.get("lang", "?"), mode=mode,
              answerable=q["answerable"], best_score=res.best_score,
              latency_ms=res.timings_ms.get("total", 0.0))
    if res.hits:
        row.top_video, row.top_moment_s = res.hits[0].chunk.video_id, res.hits[0].moment_s
    if q["type"] in SINGLE_TARGET:
        tg = targets(q)

        def relevant(c: Chunk) -> bool:
            return any(is_relevant(c, vid, t) for vid, t in tg)

        flags = [relevant(h.chunk) for h in res.hits]
        row.n_relevant = sum(relevant(c) for c in searcher.chunks.values())
        row.hit1, row.hit5 = any(flags[:1]), any(flags[:5])
        row.rr = next((1 / i for i, f in enumerate(flags, start=1) if f), 0.0)
        if res.hits:
            top = res.hits[0]
            same = [t for vid, t in tg if vid == top.chunk.video_id]
            row.moment_hit = any(timestamp_hit(top.moment_s, t) for t in same)
            row.chunk_start_hit = any(timestamp_hit(top.chunk.start_s, t) for t in same)
    return row


def random_hit_at_k(n_chunks: int, n_relevant: int, k: int) -> float:
    """Probabilité qu'un classement ALÉATOIRE mette un chunk pertinent dans le top-k."""
    if n_relevant == 0:
        return 0.0
    k = min(k, n_chunks)
    return 1 - comb(n_chunks - n_relevant, k) / comb(n_chunks, k)


def run_retrieval_eval(settings: Settings, golden_path: Path) -> list[Row]:
    kept = SINGLE_TARGET | {"unanswerable"}  # cross_video / aggregation : évalués avec l'agent
    questions = [q for q in load_golden(golden_path) if q["type"] in kept]
    if settings.retrieval.query_language:  # même question que celle que voit le produit
        from kb.adapters.factory import build_llm
        from kb.agent.query import translate_query

        llm = build_llm(settings)
        for q in questions:
            q["_search_query"] = translate_query(llm, q["question"],
                                                 settings.retrieval.query_language)
    from kb.agent.agent import load_missions, scope_to_mission

    missions = load_missions(settings)
    for q in questions:  # même périmètre que le produit (« l'équipe ES2004 » → ses réunions)
        q["_filters"] = scope_to_mission(q["question"], None, missions)[0]
    searcher = Searcher.load(settings, with_reranker=True)
    searcher.search("warm-up", mode="hybrid_rerank")  # charge les modèles avant de chronométrer
    rows = []
    for mode in MODES:
        print(f"→ mode {mode}", flush=True)
        rows += [evaluate_question(searcher, q, mode) for q in questions]
    _write_reports(settings, rows, len(searcher.chunks), golden_path)
    return rows


def _write_reports(settings: Settings, rows: list[Row], n_chunks: int,
                   golden_path: Path = DEFAULT_GOLDEN) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = REPORTS_DIR / (f"{report_prefix(golden_path)}search_{settings.profile}_"
                          f"{dt.date.today().isoformat()}")
    with stem.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0])))
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)

    ans = [r for r in rows if r.answerable]
    n_q = len({r.id for r in ans})
    base = [r for r in ans if r.mode == "dense"]
    rand1 = mean([random_hit_at_k(n_chunks, r.n_relevant, 1) for r in base])
    rand5 = mean([random_hit_at_k(n_chunks, r.n_relevant, 5) for r in base])
    lang = settings.retrieval.query_language
    query_mode = f"traduite en {lang} (comme le produit)" if lang else "telle quelle"
    lines = [
        f"# Recherche : évaluation sur `{Path(golden_path).name}` (profil `{settings.profile}`)",
        "",
        f"- Question envoyée à la recherche : {query_mode}.",
        "",
        f"- Corpus : {n_chunks} chunks. Questions répondables à cible unique : {n_q} ; "
        f"sans réponse : {len({r.id for r in rows if not r.answerable})}.",
        f"- Embeddings : `{settings.embedding.model}` · reranker : "
        f"`{settings.retrieval.reranker_model}` · RRF k={settings.retrieval.rrf_k}.",
        "- Chaque proportion : valeur (succès/n, IC 95 % de Wilson). "
        "**Golden set rédigé par Claude à partir des transcripts, à relire par l'équipe.**",
        f"- Référence hasard : Hit@1 ≈ {rand1:.0%}, Hit@5 ≈ {rand5:.0%} "
        "(classement aléatoire, calculé).",
        "",
        "## Ablation",
        "",
        "| Mode | Hit@1 | Hit@5 | MRR@20 | Moment ±30 s (zoom) | Moment ±30 s (début de chunk) "
        "| Latence p50 / p95 |",
        "|---|---|---|---|---|---|---|",
    ]
    for mode in MODES:
        m = [r for r in ans if r.mode == mode]
        lat = [r.latency_ms for r in rows if r.mode == mode]
        lines.append(
            f"| `{mode}` | {rate([r.hit1 for r in m])} | {rate([r.hit5 for r in m])} | "
            f"{mean([r.rr for r in m]):.2f} | {rate([r.moment_hit for r in m])} | "
            f"{rate([r.chunk_start_hit for r in m])} | "
            f"{percentile(lat, 50):.0f} / {percentile(lat, 95):.0f} ms |"
        )

    lines += ["", "## Par langue de la question (Hit@5)", "", "| Mode | FR | EN |", "|---|---|---|"]
    for mode in MODES:
        by = {lg: rate([r.hit5 for r in ans if r.mode == mode and r.lang == lg])
              for lg in ("fr", "en")}
        lines.append(f"| `{mode}` | {by['fr']} | {by['en']} |")

    rr = [r for r in rows if r.mode == "hybrid_rerank"]
    tau = settings.retrieval.abstain_threshold
    abst = [r.best_score is None or r.best_score < tau for r in rr]
    rep = abstention_report([r.answerable for r in rr], abst, [r.hit1 for r in rr])
    lines += [
        "",
        f"## Abstention (mode `hybrid_rerank`, seuil actuel {tau} sur le score du reranker)",
        "",
        f"- Abstention correcte (questions sans réponse) : {rep.correct_abstention}",
        f"- Fausse abstention (questions répondables) : {rep.false_abstention}",
        f"- Couverture : {rep.coverage}",
        f"- Exactitude sélective (Hit@1 parmi les réponses données) : {rep.selective_accuracy}",
        "",
        "Scores du reranker : répondables "
        f"min {min(r.best_score for r in rr if r.answerable):.2f} / médiane "
        f"{percentile([r.best_score for r in rr if r.answerable], 50):.2f} ; sans réponse "
        f"médiane {percentile([r.best_score for r in rr if not r.answerable], 50):.2f} / max "
        f"{max(r.best_score for r in rr if not r.answerable):.2f}.",
        "",
        "### Courbe risque-couverture",
        "",
        "Répondre si score ≥ seuil. Risque = part des réponses données qui sont fausses "
        "(mauvais passage en tête, ou question sans réponse).",
        "",
        "| Seuil | Couverture | Risque | Abstention correcte | Fausse abstention |",
        "|---|---|---|---|---|",
    ]
    correct = [r.answerable and r.hit1 for r in rr]
    scores = [r.best_score or 0.0 for r in rr]
    for t_, cov, risk in risk_coverage_curve(scores, correct):
        a = [s < t_ for s in scores]
        rep_t = abstention_report([r.answerable for r in rr], a, [r.hit1 for r in rr])
        lines.append(f"| {t_:.3f} | {cov:.0%} | {risk:.0%} | "
                     f"{rep_t.correct_abstention.successes}/{rep_t.correct_abstention.n} | "
                     f"{rep_t.false_abstention.successes}/{rep_t.false_abstention.n} |")

    misses = [r for r in rr if r.answerable and not r.hit1]
    lines += ["", "## Échecs (mode `hybrid_rerank`, Hit@1 raté)", ""]
    lines += [f"- `{r.id}` ({r.type}, {r.lang}) → top-1 : {r.top_video}, score {r.best_score:.2f}"
              for r in misses] or ["- aucun"]
    stem.with_suffix(".md").write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines))
    print(f"\nRapports : {stem}.md / .csv")
