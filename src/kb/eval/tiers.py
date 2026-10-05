"""Comparaison des paliers (section 9 : « menu prix / goût », frontière coût-qualité).

N'appelle AUCUN modèle : agrège les rapports `agent_<profil>_<mode>_*.csv` déjà produits par
`kb.cli eval-agent --profile <profil>` sur chaque palier. Un palier sans rapport est signalé,
jamais inventé (CLAUDE.md, section 9-10 : chiffres mesurés ou explicitement estimés/sourcés).
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from kb.config import ROOT, load_settings
from kb.eval.metrics import mean, percentile, rate

REPORTS_DIR = ROOT / "docs" / "reports"


def _latest_report(profile: str, mode: str) -> Path | None:
    candidates = sorted(REPORTS_DIR.glob(f"agent_{profile}_{mode}_*.csv"))
    return candidates[-1] if candidates else None


def _bool(v: str) -> bool:
    return v == "True"


def aggregate_tiers(profiles: list[str], mode: str = "synthese") -> tuple[list[dict], list[str]]:
    """Lit les rapports déjà générés et calcule une ligne coût-qualité par profil.

    Renvoie `(lignes, profils_manquants)` — aucune écriture de fichier, aucun appel réseau.
    Réutilisé par le CLI (`compare_tiers`, qui écrit aussi un rapport) et par l'API (`GET /tiers`).
    """
    missing, csv_rows = [], []
    for p in profiles:
        path = _latest_report(p, mode)
        if path is None:
            missing.append(p)
            continue
        with path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        s = load_settings(p)
        ans = [r for r in rows if _bool(r["answerable"])]
        given = [r for r in ans if not _bool(r["abstained"])]
        cost = [float(r["cost_usd"]) for r in rows]
        lat = [float(r["latency_ms"]) for r in rows]
        cov = rate([not _bool(r["abstained"]) for r in ans])
        moment = rate([_bool(r["moment_hit"]) for r in given])
        avg_cost = mean(cost)
        csv_rows.append({
            "profile": p, "model": s.llm.model, "n": len(rows),
            "coverage": cov.value, "coverage_str": str(cov),
            "moment_hit": moment.value, "moment_hit_str": str(moment),
            "avg_cost_usd": avg_cost, "cost_per_1000q_usd": avg_cost * 1000,
            "latency_p50_ms": percentile(lat, 50), "latency_p95_ms": percentile(lat, 95),
        })
    return csv_rows, missing


def compare_tiers(profiles: list[str], mode: str = "synthese") -> None:
    csv_rows, missing = aggregate_tiers(profiles, mode)
    if missing:
        print(f"⚠ Aucun rapport agent_<profil>_{mode}_*.csv pour : {', '.join(missing)}. "
              f"Lancer d'abord : kb.cli eval-agent --profile <profil> --mode {mode}")
    if not csv_rows:
        print("Aucun profil avec un rapport à comparer.")
        return

    lines = [
        "# Comparaison des paliers (frontière coût-qualité)",
        "",
        f"Chiffres **mesurés** depuis les rapports `agent_<profil>_{mode}_*.csv` déjà générés "
        "— aucun appel réseau ici.",
        "",
        "| Profil | LLM | Questions | Couverture | Moment ±30 s | Coût moyen / question | "
        "Coût / 1000 questions | Latence p50 / p95 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in csv_rows:
        lines.append(
            f"| `{r['profile']}` | `{r['model']}` | {r['n']} | {r['coverage_str']} | "
            f"{r['moment_hit_str']} | {r['avg_cost_usd']:.6f} $ | "
            f"{r['cost_per_1000q_usd']:.2f} $ | "
            f"{r['latency_p50_ms'] / 1000:.1f} / {r['latency_p95_ms'] / 1000:.1f} s |"
        )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = REPORTS_DIR / f"tiers_{dt.date.today().isoformat()}"
    flat_rows = [{k: v for k, v in r.items() if not k.endswith("_str")} for r in csv_rows]
    with stem.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(flat_rows[0]))
        w.writeheader()
        w.writerows(flat_rows)
    stem.with_suffix(".md").write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines))
    print(f"\nComparaison : {stem}.md / .csv")
