"""L5 : résumé structuré des indicateurs mesurés, pour le dashboard (`GET /metrics`).

Ne calcule QUE ce qui est réellement mesuré par les rapports existants (`agent_*`,
`search_*`, `asr_*`, déjà écrits par `kb.cli eval-agent`/`eval-search`/`eval-asr`).
Faithfulness, taux d'hallucination et temps main-vs-outil ne sont mesurés nulle part dans
ce repo (CLAUDE.md, D10 : jamais un chiffre inventé) : `None` plutôt qu'un calcul plausible
— au front de l'afficher comme « non mesuré ».
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from kb.eval.metrics import abstention_report, mean, percentile, rate, risk_coverage_curve
from kb.eval.tiers import REPORTS_DIR

_WER = re.compile(r"`large-v3-turbo`\s*:\s*WER\s*\*\*([\d.]+)%\*\*")


def _latest(pattern: str) -> Path | None:
    candidates = sorted(REPORTS_DIR.glob(pattern))
    return candidates[-1] if candidates else None


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


CORPORA = {"ted": "", "ami": "ami_"}  # préfixe des rapports (kb.eval.retrieval.report_prefix)


def compute_kpis(profile: str, prefix: str = "") -> dict:
    """`prefix` : « » = golden set TED (défaut), « ami_ » = réunions AMI. Le WER n'est mesuré
    que sur TED (référence humaine ted.com) : `None` pour un autre corpus."""
    kpis: dict[str, float | None] = {
        "wer": None, "recall_at_5": None, "moment_precision": None,
        "faithfulness": None, "hallucination_rate": None,
        "abstention_correct": None, "false_abstention": None,
        "latency_p95_s": None, "cost_per_question_usd": None,
        "time_manual_min": None, "time_tool_s": None,
    }
    sources: dict[str, str] = {}

    asr_path = _latest("asr_*.md") if not prefix else None
    if asr_path:
        m = _WER.search(asr_path.read_text("utf-8"))
        if m:
            kpis["wer"] = float(m.group(1)) / 100
            sources["asr"] = asr_path.name

    search_path = _latest(f"{prefix}search_{profile}_*.csv")
    if search_path:
        rows = [r for r in _read_csv(search_path) if r["mode"] == "hybrid_rerank"]
        ans = [r for r in rows if r["answerable"] == "True"]
        if ans:
            kpis["recall_at_5"] = rate([r["hit5"] == "True" for r in ans]).value
            kpis["moment_precision"] = rate([r["moment_hit"] == "True" for r in ans]).value
            sources["search"] = search_path.name

    agent_path = _latest(f"{prefix}agent_{profile}_*.csv")
    if agent_path:
        rows = _read_csv(agent_path)
        if rows:
            rep = abstention_report([r["answerable"] == "True" for r in rows],
                                    [r["abstained"] == "True" for r in rows],
                                    [r["moment_hit"] == "True" for r in rows])
            kpis["abstention_correct"] = rep.correct_abstention.value
            kpis["false_abstention"] = rep.false_abstention.value
            lat = [float(r["latency_ms"]) for r in rows]
            kpis["latency_p95_s"] = percentile(lat, 95) / 1000
            kpis["cost_per_question_usd"] = mean([float(r["cost_usd"]) for r in rows])
            sources["agent"] = agent_path.name

    return {"kpis": kpis, "sources": sources}


def compute_risk_coverage(profile: str, prefix: str = "") -> list[dict] | None:
    """Courbe risque-couverture (mode `hybrid_rerank`) : sert à choisir `abstain_threshold`.

    `None` si aucun rapport search_<profil>_*.csv n'existe encore (pas un [] ambigu).
    """
    search_path = _latest(f"{prefix}search_{profile}_*.csv")
    if not search_path:
        return None
    rows = [r for r in _read_csv(search_path) if r["mode"] == "hybrid_rerank" and r["best_score"]]
    if not rows:
        return None
    scores = [float(r["best_score"]) for r in rows]
    correct = [r["answerable"] == "True" and r["hit1"] == "True" for r in rows]
    return [
        {"threshold": t, "coverage": cov, "risk": risk}
        for t, cov, risk in risk_coverage_curve(scores, correct)
    ]
