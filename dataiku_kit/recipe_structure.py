"""Recette Python Dataiku — L1 Structuration : `segments` + `videos` -> `fiches_rex`.

Statut : **kit, non testé sur une vraie instance Dataiku.**

Réutilise `kb.structure.extract.extract_fiches` telle quelle. Le LLM passe par l'endpoint
compatible OpenAI de Dataiku (CLAUDE.md section 2 : `{DSS}/public/api/projects/TEAM_16/
llms/openai/v1/`, clé API personnelle) — c'est déjà ce que fait `profiles/dataiku.yaml`,
donc `build_llm(load_settings("dataiku"))` fonctionne SANS adapter Dataiku-natif
supplémentaire. `DSS_API_KEY` doit être un **secret utilisateur Dataiku** (jamais en clair
dans la recette), et `DSS_LLM_ID` l'ID exact de Luna (`project.list_llms()`, CLAUDE.md
section 14, question inutile ici car déjà répondue par KEY-1).

Entrées : datasets `segments`, `videos` (écrits par `recipe_ingest.py`).
Sortie : dataset `fiches_rex` — alternative « recette Prompt » possible pour une équipe
sans Python (CLAUDE.md section 10), mais perd la vérification par code de `evidence_quote`
(guardrails.snap_quote/verify_quote) : à garder en recette Python pour ça.
"""

from __future__ import annotations

import dataiku
import pandas as pd

from kb.adapters.factory import build_llm
from kb.config import load_settings
from kb.schemas import Segment, Video
from kb.structure.extract import extract_fiches

SEGMENTS_DATASET = "segments"
VIDEOS_DATASET = "videos"
FICHES_DATASET = "fiches_rex"


def main() -> None:
    settings = load_settings("dataiku")
    llm = build_llm(settings)

    videos_df = dataiku.Dataset(VIDEOS_DATASET).get_dataframe()
    segments_df = dataiku.Dataset(SEGMENTS_DATASET).get_dataframe()

    rows = []
    for _, vrow in videos_df.iterrows():
        video = Video(**vrow.to_dict())
        seg_rows = segments_df[segments_df["video_id"] == video.video_id]
        segments = [Segment(**r) for r in seg_rows.to_dict("records")]
        for fiche in extract_fiches(video, segments, llm):
            rows.append(fiche.model_dump())

    dataiku.Dataset(FICHES_DATASET).write_with_schema(pd.DataFrame(rows))


if __name__ == "__main__":
    main()
