"""Recherche via la Knowledge Bank native de Dataiku.

Contrairement au reste du kit, l'API ci-dessous est **confirmée par un test réel** (18/09,
Evan + Claude : création d'une KB `kb_test_claude` avec 2 documents, écriture, recherche,
puis suppression) — pas une hypothèse sourcée uniquement sur la doc.

API confirmée :
  - `project.create_knowledge_bank(name, "CHROMA", embed_llm_id)`
  - `dss_kb.as_core_knowledge_bank()` -> `dataiku.KnowledgeBank`
  - `kb_core.get_writer()` (context manager) -> `.as_langchain_vectorstore().add_documents(docs)`
    — les métadonnées des `Document` LangChain font l'aller-retour intactes.
  - `kb_core.as_langchain_vectorstore().similarity_search_with_score(query, k=..., filter=...)`
    renvoie des paires `(Document, DISTANCE)` — score **BAS = plus proche**, l'inverse de notre
    `ChromaStore` (qui renvoie une similarité, haut = plus proche). `list_knowledge_banks()`
    montre `distanceMetric: "DEFAULT"` sur la KB de test : c'est le défaut de Chroma, une
    distance L2 au carré, **pas** une distance cosinus (contrairement à notre `ChromaStore`, qui
    force `hnsw:space="cosine"`). Convertie ci-dessous par `1 - distance/2`, ce qui correspond à
    une similarité cosinus **si** les vecteurs de `text-embedding-3-small` sont normés (norme 1 —
    le cas pour les modèles `text-embedding-3-*` d'OpenAI d'après leur doc, pas revérifié sur ce
    proxy Dataiku précis). Le classement des résultats est correct dans tous les cas (distance
    basse = plus proche, quelle que soit la formule) ; seul le SCORE ABSOLU dépend de cette
    hypothèse — encore une raison de recalibrer `abstain_threshold` plutôt que le déduire.
  - ID d'embedding confirmé : `project.list_llms(purpose="TEXT_EMBEDDING_EXTRACTION")[0]["id"]`
    == `"openai:challenge_llm:text-embedding-3-small"` (absent de `list_llms()` par défaut, qui
    ne renvoie que `purpose="GENERIC_COMPLETION"`).
  - Aucun reranker via LLM Mesh (`purpose="RERANKING"` renvoie `[]`) : si la Knowledge Bank a son
    propre reranking, ce n'est pas une entrée LLM Mesh séparée — pas testé ici.

Ce que ça NE fait PAS (limites connues du kit, pas de la plateforme) :
  - Recherche **dense seule** : pas de BM25, pas de fusion RRF, pas de rerank cross-encoder.
    `kb.agent.agent.Agent` appelle toujours `searcher.search(mode="hybrid_rerank", ...)` ; cette
    classe accepte l'argument pour la même signature mais fait toujours une recherche dense.
    ponytail : upgrade = construire un `BM25Index` local depuis le dataset `chunks` (déjà dans
    le kit) et fusionner par RRF si le rappel dense seul ne suffit pas.
  - Pas de « zoom moment » (`kb.index.build.build_moments`) : `moment_s` = début du chunk. Les
    chunks durent ~2-3 min, donc la seconde renvoyée est moins précise qu'en local (±30 s visé).
  - `settings.retrieval.abstain_threshold` est calibré sur des scores de **reranker** (golden
    set, profils `free`/`dataiku`), pas sur une similarité cosinus dense : le réutiliser tel quel
    ici n'est **pas validé**. Ceiling explicite : recalibrer un seuil dense séparé sur le golden
    set avant de faire confiance à l'abstention dans ce mode.
"""

from __future__ import annotations

import time

from kb.agent.guardrails import should_abstain
from kb.config import Settings
from kb.index.search import Hit, SearchResult
from kb.schemas import Chunk


class KnowledgeBankSearcher:
    """Même entrée/sortie que `kb.index.search.Searcher` (`Hit`, `SearchResult`) : l'agent n'a
    pas à savoir qu'il parle à une Knowledge Bank Dataiku plutôt qu'à un `ChromaStore` local."""

    def __init__(self, settings: Settings, knowledge_bank_id: str) -> None:
        import dataiku

        self.settings = settings
        project = dataiku.api_client().get_default_project()
        kb_core = project.get_knowledge_bank(knowledge_bank_id).as_core_knowledge_bank()
        self._vectorstore = kb_core.as_langchain_vectorstore()

    def search(self, query: str, mode: str = "hybrid_rerank", k: int = 5,
              filters: dict | None = None) -> SearchResult:
        t0 = time.perf_counter()
        kwargs = {"filter": filters} if filters else {}
        results = self._vectorstore.similarity_search_with_score(query, k=k, **kwargs)
        hits = [
            Hit(
                chunk=_chunk_from_document(doc),
                score=max(0.0, 1.0 - distance / 2),  # L2² -> similarité ; vecteurs normés supposés
                moment_s=float(doc.metadata.get("start_s", 0.0)),
                moment_text=doc.page_content,
            )
            for doc, distance in results
        ]
        best = hits[0].score if hits else None
        elapsed = 1000 * (time.perf_counter() - t0)
        return SearchResult(
            hits=hits,
            abstain=should_abstain(best, self.settings.retrieval.abstain_threshold),
            best_score=best,
            timings_ms={"dense_kb": elapsed, "total": elapsed},
        )


def _chunk_from_document(doc) -> Chunk:
    m = doc.metadata
    return Chunk(
        chunk_id=m["chunk_id"],
        video_id=m["video_id"],
        start_s=float(m.get("start_s", 0.0)),
        end_s=float(m.get("end_s", m.get("start_s", 0.0))),
        text=doc.page_content,
        context_header=m.get("context_header", ""),
        client=m.get("client"),
    )
