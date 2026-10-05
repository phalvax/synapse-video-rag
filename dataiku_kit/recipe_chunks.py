"""Recette Python Dataiku — L2 Chunks : `segments` + `videos` -> `chunks`.

Statut : **kit, non testé sur une vraie instance Dataiku.**

Réutilise `kb.index.chunking.chunk_segments` telle quelle. Le dataset `chunks` en sortie
est fait pour être consommé par une recette **Embed dataset** (Embedding v3 Small,
0,02 $/M tokens, CLAUDE.md section 2) écrivant dans une Knowledge Bank Chroma, ou Milvus
local si le hybrid (dense + BM25) natif est voulu (CLAUDE.md section 2 : seuls Azure AI
Search, Databricks, Elasticsearch, Milvus et Snowflake Cortex l'offrent).
"""

from __future__ import annotations

import dataiku
import pandas as pd

from kb.config import load_settings
from kb.index.chunking import chunk_segments
from kb.schemas import Segment, Video

SEGMENTS_DATASET = "segments"
VIDEOS_DATASET = "videos"
CHUNKS_DATASET = "chunks"


def main() -> None:
    settings = load_settings("dataiku")
    r = settings.retrieval

    videos_df = dataiku.Dataset(VIDEOS_DATASET).get_dataframe()
    segments_df = dataiku.Dataset(SEGMENTS_DATASET).get_dataframe()

    rows = []
    for _, vrow in videos_df.iterrows():
        video = Video(**vrow.to_dict())
        seg_rows = segments_df[segments_df["video_id"] == video.video_id].sort_values("seg_id")
        segments = [Segment(**row) for row in seg_rows.to_dict("records")]
        chunks = chunk_segments(segments, video, r.chunk_target_tokens, r.chunk_overlap_segments)
        rows += [c.model_dump() for c in chunks]

    dataiku.Dataset(CHUNKS_DATASET).write_with_schema(pd.DataFrame(rows))


if __name__ == "__main__":
    main()
