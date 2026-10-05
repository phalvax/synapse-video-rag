"""Tests de kb.eval.summary SANS réseau ni modèle : lit des rapports CSV/MD écrits à la main."""

import csv

import kb.eval.summary as summary

SEARCH_FIELDS = ["id", "type", "lang", "mode", "answerable", "hit1", "hit5", "rr",
                 "moment_hit", "chunk_start_hit", "top_video", "top_moment_s", "best_score",
                 "latency_ms", "n_relevant"]
AGENT_FIELDS = ["id", "type", "lang", "answerable", "abstained", "llm_calls", "citations",
               "citations_verified", "moment_hit", "indice_reponse", "retrieval_score",
               "latency_ms", "input_tokens", "output_tokens", "cost_usd", "note", "answer"]


def _write_csv(path, fields, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_compute_kpis_with_no_reports_returns_all_none(tmp_path, monkeypatch):
    monkeypatch.setattr(summary, "REPORTS_DIR", tmp_path)
    result = summary.compute_kpis("free")
    assert all(v is None for v in result["kpis"].values())
    assert result["sources"] == {}


def test_compute_kpis_parses_wer_from_asr_report(tmp_path, monkeypatch):
    monkeypatch.setattr(summary, "REPORTS_DIR", tmp_path)
    (tmp_path / "asr_2026-09-17.md").write_text(
        "Global : `small` : WER **2.6%** sur 3502 mots. "
        "`large-v3-turbo` : WER **2.0%** sur 3502 mots (26.1 min).", "utf-8")
    result = summary.compute_kpis("free")
    assert result["kpis"]["wer"] == 0.02
    assert result["sources"]["asr"] == "asr_2026-09-17.md"


def test_compute_kpis_from_search_report_only_uses_hybrid_rerank_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(summary, "REPORTS_DIR", tmp_path)
    rows = [
        {"id": "P01", "type": "single_fact", "lang": "en", "mode": "dense", "answerable": "True",
         "hit1": "False", "hit5": "False", "rr": "0", "moment_hit": "False",
         "chunk_start_hit": "False", "top_video": "v", "top_moment_s": "0", "best_score": "0.1",
         "latency_ms": "10", "n_relevant": "1"},
        {"id": "P01", "type": "single_fact", "lang": "en", "mode": "hybrid_rerank",
         "answerable": "True", "hit1": "True", "hit5": "True", "rr": "1", "moment_hit": "True",
         "chunk_start_hit": "True", "top_video": "v", "top_moment_s": "0", "best_score": "0.9",
         "latency_ms": "10", "n_relevant": "1"},
    ]
    _write_csv(tmp_path / "search_free_2026-09-17.csv", SEARCH_FIELDS, rows)
    result = summary.compute_kpis("free")
    assert result["kpis"]["recall_at_5"] == 1.0
    assert result["kpis"]["moment_precision"] == 1.0
    assert result["sources"]["search"] == "search_free_2026-09-17.csv"


def test_compute_kpis_from_agent_report(tmp_path, monkeypatch):
    monkeypatch.setattr(summary, "REPORTS_DIR", tmp_path)
    rows = [
        {"id": "P01", "type": "single_fact", "lang": "en", "answerable": "True",
         "abstained": "False", "llm_calls": "1", "citations": "1", "citations_verified": "1",
         "moment_hit": "True", "indice_reponse": "1.0", "retrieval_score": "0.9",
         "latency_ms": "1000", "input_tokens": "100", "output_tokens": "10",
         "cost_usd": "0.002", "note": "", "answer": "ok"},
        {"id": "U01", "type": "unanswerable", "lang": "en", "answerable": "False",
         "abstained": "True", "llm_calls": "0", "citations": "0", "citations_verified": "0",
         "moment_hit": "False", "indice_reponse": "0.0", "retrieval_score": "",
         "latency_ms": "50", "input_tokens": "0", "output_tokens": "0",
         "cost_usd": "0.0", "note": "abstention", "answer": ""},
    ]
    _write_csv(tmp_path / "agent_free_synthese_2026-09-17.csv", AGENT_FIELDS, rows)
    result = summary.compute_kpis("free")
    assert result["kpis"]["abstention_correct"] == 1.0
    assert result["kpis"]["false_abstention"] == 0.0
    assert result["kpis"]["cost_per_question_usd"] == 0.001
    assert result["kpis"]["latency_p95_s"] is not None
    assert result["sources"]["agent"] == "agent_free_synthese_2026-09-17.csv"


def test_compute_kpis_never_fabricates_unmeasured_metrics(tmp_path, monkeypatch):
    """Faithfulness, hallucination et temps main-vs-outil ne sont mesurés nulle part (D10)."""
    monkeypatch.setattr(summary, "REPORTS_DIR", tmp_path)
    _write_csv(tmp_path / "agent_free_synthese_2026-09-17.csv", AGENT_FIELDS, [
        {"id": "P01", "type": "single_fact", "lang": "en", "answerable": "True",
         "abstained": "False", "llm_calls": "1", "citations": "1", "citations_verified": "1",
         "moment_hit": "True", "indice_reponse": "1.0", "retrieval_score": "0.9",
         "latency_ms": "1000", "input_tokens": "100", "output_tokens": "10",
         "cost_usd": "0.002", "note": "", "answer": "ok"},
    ])
    result = summary.compute_kpis("free")
    assert result["kpis"]["faithfulness"] is None
    assert result["kpis"]["hallucination_rate"] is None
    assert result["kpis"]["time_manual_min"] is None
    assert result["kpis"]["time_tool_s"] is None


def test_risk_coverage_is_none_without_a_search_report(tmp_path, monkeypatch):
    monkeypatch.setattr(summary, "REPORTS_DIR", tmp_path)
    assert summary.compute_risk_coverage("free") is None


def test_risk_coverage_trades_coverage_for_risk(tmp_path, monkeypatch):
    monkeypatch.setattr(summary, "REPORTS_DIR", tmp_path)
    rows = [
        {"id": "P01", "type": "single_fact", "lang": "en", "mode": "hybrid_rerank",
         "answerable": "True", "hit1": "True", "hit5": "True", "rr": "1", "moment_hit": "True",
         "chunk_start_hit": "True", "top_video": "v", "top_moment_s": "0", "best_score": "0.9",
         "latency_ms": "10", "n_relevant": "1"},
        {"id": "P02", "type": "single_fact", "lang": "en", "mode": "hybrid_rerank",
         "answerable": "True", "hit1": "False", "hit5": "False", "rr": "0", "moment_hit": "False",
         "chunk_start_hit": "False", "top_video": "v", "top_moment_s": "0", "best_score": "0.2",
         "latency_ms": "10", "n_relevant": "1"},
        # mode="dense" doit être ignoré même s'il a un best_score
        {"id": "P02", "type": "single_fact", "lang": "en", "mode": "dense",
         "answerable": "True", "hit1": "True", "hit5": "True", "rr": "1", "moment_hit": "True",
         "chunk_start_hit": "True", "top_video": "v", "top_moment_s": "0", "best_score": "0.99",
         "latency_ms": "10", "n_relevant": "1"},
    ]
    _write_csv(tmp_path / "search_free_2026-09-17.csv", SEARCH_FIELDS, rows)
    curve = summary.compute_risk_coverage("free")
    assert curve is not None and len(curve) == 2
    assert curve[0] == {"threshold": 0.9, "coverage": 0.5, "risk": 0.0}
    assert curve[1] == {"threshold": 0.2, "coverage": 1.0, "risk": 0.5}
