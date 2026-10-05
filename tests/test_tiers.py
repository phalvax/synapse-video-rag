"""Tests de `compare_tiers` SANS réseau ni modèle : il ne fait qu'agréger des CSV existants."""

import csv

import kb.eval.tiers as tiers

FIELDS = ["id", "type", "lang", "answerable", "abstained", "llm_calls", "citations",
          "citations_verified", "moment_hit", "indice_reponse", "retrieval_score",
          "latency_ms", "input_tokens", "output_tokens", "cost_usd", "note", "answer"]

ROW_OK = {"id": "Q1", "type": "single_fact", "lang": "fr", "answerable": True,
          "abstained": False, "llm_calls": 1, "citations": 1, "citations_verified": 1,
          "moment_hit": True, "indice_reponse": 1.0, "retrieval_score": 0.9,
          "latency_ms": 1200, "input_tokens": 1000, "output_tokens": 50,
          "cost_usd": 0.002, "note": "", "answer": "Réponse."}
ROW_ABSTAIN = {**ROW_OK, "id": "Q2", "abstained": True, "citations": 0,
              "citations_verified": 0, "moment_hit": False, "answer": ""}


def _write_report(reports_dir, profile: str, mode: str, date: str, rows: list[dict]) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"agent_{profile}_{mode}_{date}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def test_compare_tiers_aggregates_existing_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tiers, "REPORTS_DIR", tmp_path)
    _write_report(tmp_path, "free", "synthese", "2026-09-18", [ROW_OK, ROW_ABSTAIN])

    tiers.compare_tiers(["free"], mode="synthese")

    out = capsys.readouterr().out
    assert "free" in out
    written = sorted(tmp_path.glob("tiers_*.md"))
    assert len(written) == 1
    assert "gemma3:4b" in written[0].read_text("utf-8")  # modèle du profil free


def test_compare_tiers_reports_missing_profile_without_crashing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tiers, "REPORTS_DIR", tmp_path)
    _write_report(tmp_path, "free", "synthese", "2026-09-18", [ROW_OK])

    tiers.compare_tiers(["free", "dataiku"], mode="synthese")

    out = capsys.readouterr().out
    assert "dataiku" in out and "Aucun rapport" in out
    assert (tmp_path / next(tmp_path.glob("tiers_*.md")).name).exists()


def test_compare_tiers_with_no_reports_at_all_does_not_crash(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tiers, "REPORTS_DIR", tmp_path)
    tiers.compare_tiers(["free"], mode="synthese")
    assert "Aucun profil" in capsys.readouterr().out
    assert list(tmp_path.glob("tiers_*.md")) == []


def test_uses_latest_report_when_several_dates_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(tiers, "REPORTS_DIR", tmp_path)
    _write_report(tmp_path, "free", "synthese", "2026-09-01", [ROW_ABSTAIN])  # ancien : 0 % couv.
    _write_report(tmp_path, "free", "synthese", "2026-09-18", [ROW_OK])       # récent : 100 %

    tiers.compare_tiers(["free"], mode="synthese")

    csv_path = next(tmp_path.glob("tiers_*.csv"))
    row = next(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert row["coverage"] == "1.0"
