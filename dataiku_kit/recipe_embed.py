"""Recette Python Dataiku — L2 Index : dataset `chunks` -> Knowledge Bank `kb_index`.

Statut : API **confirmée par un test réel** (18/09, cf. `kb_retrieval.py`) — la seule partie
non testée ici est le volume réel (le test faisait 2 documents).

Entrée : dataset `chunks` (écrit par `recipe_chunks.py`).
Sortie : une Knowledge Bank Dataiku nommée `KB_NAME`, créée si absente (confirmé le 18/09 :
`create_knowledge_bank` ne dédoublonne PAS par nom — l'appeler deux fois crée deux Knowledge
Banks distinctes de même nom, chacune avec son propre `id` ; d'où le `list_knowledge_banks()`
en tête de `main()`). `add_documents` n'écrase pas non plus par id de chunk : si cette recette
tourne deux fois sur la même KB, les chunks sont dupliqués. Pour une ré-ingestion propre,
supprimer la KB avant de relancer (`project.get_knowledge_bank(id).delete()` — confirmé le
18/09 sur une KB de test).
"""

from __future__ import annotations

import dataiku
import pandas as pd

try:
    from langchain_core.documents import Document
except ImportError:
    from langchain.docstore.document import Document

CHUNKS_DATASET = "chunks"
KB_NAME = "kb_index"
EMBED_ID = "openai:challenge_llm:text-embedding-3-small"  # confirmé le 18/09 (Evan)
BATCH = 64


def main() -> None:
    client = dataiku.api_client()
    project = client.get_default_project()

    existing = {kb["name"]: kb["id"] for kb in project.list_knowledge_banks()}
    if KB_NAME in existing:
        dss_kb = project.get_knowledge_bank(existing[KB_NAME])
    else:
        dss_kb = project.create_knowledge_bank(KB_NAME, "CHROMA", EMBED_ID)
    kb_core = dss_kb.as_core_knowledge_bank()

    df = dataiku.Dataset(CHUNKS_DATASET).get_dataframe()
    docs = [
        Document(
            page_content=row["text"],
            metadata={
                "chunk_id": row["chunk_id"], "video_id": row["video_id"],
                "start_s": float(row["start_s"]), "end_s": float(row["end_s"]),
                "context_header": row.get("context_header") or "",
                **({"client": row["client"]} if pd.notna(row.get("client")) else {}),
            },
        )
        for _, row in df.iterrows()
    ]

    with kb_core.get_writer() as writer:
        vs = writer.as_langchain_vectorstore()
        for i in range(0, len(docs), BATCH):
            vs.add_documents(docs[i : i + BATCH])

    print(f"{len(docs)} chunks écrits dans la Knowledge Bank « {KB_NAME} » ({dss_kb.id}).")


if __name__ == "__main__":
    main()
