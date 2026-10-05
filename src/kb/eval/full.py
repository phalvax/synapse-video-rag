"""L5 : `kb.cli eval` — orchestration mince (recherche + agent), un rapport de synthèse.

Les rapports détaillés (`search_*`, `agent_*`) existent déjà (Phases 2 et 3, un fichier par
brique). Celui-ci ajoute seulement une vue d'ensemble par question, pour comparer un palier
d'un coup d'œil (CLAUDE.md, section 9 : « menu prix / goût »).
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import asdict
from pathlib import Path

from kb.config import ROOT, Settings
from kb.eval.agent import run_agent_eval
from kb.eval.metrics import mean, percentile, rate
from kb.eval.retrieval import run_retrieval_eval

REPORTS_DIR = ROOT / "docs" / "reports"


def run_full_eval(settings: Settings, golden_path: Path, mode: str = "synthese") -> None:
    print("== Recherche (search_*) ==", flush=True)
    search_rows = run_retrieval_eval(settings, golden_path)
    print("\n== Agent (agent_*) ==", flush=True)
    agent_rows = run_agent_eval(settings, golden_path, mode=mode)
    _write_summary(settings, search_rows, agent_rows, mode)


def _write_summary(settings: Settings, search_rows, agent_rows, mode: str) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = REPORTS_DIR / f"eval_{settings.profile}_{dt.date.today().isoformat()}"
    hit5_by_id = {r.id: r.hit5 for r in search_rows if r.mode == "hybrid_rerank"}

    fieldnames = [*asdict(agent_rows[0]).keys(), "search_hit5"]
    with stem.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in agent_rows:
            w.writerow({**asdict(r), "search_hit5": hit5_by_id.get(r.id)})

    ans = [r for r in agent_rows if r.answerable]
    cost = sum(r.cost_usd for r in agent_rows)
    lat = [r.latency_ms for r in agent_rows]
    lines = [
        f"# Synthèse d'évaluation (profil `{settings.profile}`, mode `{mode}`)",
        "",
        f"- LLM : `{settings.llm.model}` ({settings.llm.input_per_m}/{settings.llm.output_per_m} "
        f"$ par M tokens) · embeddings : `{settings.embedding.model}`.",
        f"- {len(agent_rows)} questions ({len(ans)} répondables).",
        "- Détail brique par brique : `search_" + settings.profile + "_*` et `agent_"
        + settings.profile + "_" + mode + "_*` dans ce même dossier.",
        "",
        "## Vue d'ensemble",
        "",
        f"- Couverture (questions répondables auxquelles on répond) : "
        f"{rate([not r.abstained for r in ans])}",
        f"- Bon moment (±30 s) sur la 1re citation vérifiée : {rate([r.moment_hit for r in ans])}",
        f"- Coût total mesuré : {cost:.6f} $ ({cost / len(agent_rows) * 1000:.4f} $ / 1000 "
        "questions)",
        f"- Latence p50 / p95 : {percentile(lat, 50) / 1000:.1f} s / "
        f"{percentile(lat, 95) / 1000:.1f} s",
        f"- Tokens moyens : {mean([r.input_tokens for r in agent_rows]):.0f} en entrée, "
        f"{mean([r.output_tokens for r in agent_rows]):.0f} en sortie",
    ]
    stem.with_suffix(".md").write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines))
    print(f"\nSynthèse : {stem}.md / .csv")
