"""Stockage des fiches REX dans SQLite (`data/kb.sqlite`) + l'outil `query_fiches`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from kb.schemas import FicheREX

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fiches (
    fiche_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    problem TEXT NOT NULL,
    solution TEXT,
    technologies TEXT NOT NULL,  -- JSON list
    client TEXT,
    author TEXT,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    evidence_quote TEXT NOT NULL
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(_SCHEMA)
    return conn


def _row_to_fiche(row: tuple) -> FicheREX:
    (fiche_id, video_id, problem, solution, technologies, client, author,
     start_s, end_s, evidence_quote) = row
    return FicheREX(fiche_id=fiche_id, video_id=video_id, problem=problem, solution=solution,
                    technologies=json.loads(technologies), client=client, author=author,
                    start_s=start_s, end_s=end_s, evidence_quote=evidence_quote)


def save_fiches(db_path: Path, video_id: str, fiches: list[FicheREX]) -> None:
    """Remplace les fiches d'une vidéo (ré-extraction idempotente)."""
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM fiches WHERE video_id = ?", (video_id,))
            conn.executemany(
                "INSERT INTO fiches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(f.fiche_id, f.video_id, f.problem, f.solution, json.dumps(f.technologies),
                  f.client, f.author, f.start_s, f.end_s, f.evidence_quote) for f in fiches],
            )
    finally:
        conn.close()


def query_fiches(
    db_path: Path,
    text: str | None = None,
    client: str | None = None,
    technology: str | None = None,
    video_id: str | None = None,
    limit: int = 50,
) -> list[FicheREX]:
    """Outil `query_fiches` (SQL) : filtres combinables, tous optionnels."""
    if not db_path.exists():
        return []
    conn = _connect(db_path)
    try:
        where, params = [], []
        if text:
            where.append("(problem LIKE ? OR solution LIKE ?)")
            params += [f"%{text}%", f"%{text}%"]
        if client:
            where.append("client LIKE ?")
            params.append(f"%{client}%")
        if technology:
            where.append("technologies LIKE ?")
            params.append(f'%"{technology}%')
        if video_id:
            where.append("video_id = ?")
            params.append(video_id)
        sql = "SELECT * FROM fiches"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY video_id, start_s LIMIT ?"
        params.append(limit)
        return [_row_to_fiche(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
