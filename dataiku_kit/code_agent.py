"""Code Agent Dataiku — L4 Agent : `dataiku.llm.python.BaseLLM.process`.

Ce qui est confirmé par CLAUDE.md (section 2, vérifié par le coach Dataiku) : la classe de base est
`dataiku.llm.python.BaseLLM`, la méthode à implémenter est `process(query, settings,
trace)`, et elle doit renvoyer `{"text": ...}`. Ce qui n'est **pas confirmé** : la forme
exacte de `query` (probablement un objet proche d'une requête de chat — messages, rôles —
plutôt qu'une simple chaîne). `_question_from_query` ci-dessous essaie plusieurs formes
plausibles avec repli ; **à vérifier et corriger au premier essai réel.**

Réutilise `kb.agent.agent.Agent` telle quelle (garde-fous inclus) ; seule la recherche
change : `KnowledgeBankSearcher` (kb_retrieval.py) plutôt que `Searcher`/`ChromaStore`,
puisque l'API de la Knowledge Bank native est maintenant confirmée par un test réel
(18/09) et que les embeddings ne sont de toute façon pas accessibles par notre adapter
REST (docs/LOG.md, 18/09) — voir les limites documentées en tête de `kb_retrieval.py`
(pas de BM25/rerank/zoom moment dans ce mode, seuil d'abstention non recalibré).

Déploiement : env de code dédié avec `langchain-core` en plus (voir envs.md — confirmé
absent d'un kernel `whisper_env` par défaut, présent dans `INTERNAL_retrieval_augmented_
generation_v1`), bibliothèque de projet `kb` importée depuis Git (CLAUDE.md section 10).
La Knowledge Bank `kb_index` doit exister au préalable (`recipe_embed.py`).
"""

from __future__ import annotations

from dataiku.llm.python import BaseLLM

from kb.agent.agent import Agent
from kb.config import load_settings

from .kb_retrieval import KnowledgeBankSearcher

KNOWLEDGE_BANK_NAME = "kb_index"


class KbAgent(BaseLLM):
    def __init__(self) -> None:
        import dataiku

        self.settings = load_settings("dataiku")
        project = dataiku.api_client().get_default_project()
        kb_id = next(
            kb["id"] for kb in project.list_knowledge_banks() if kb["name"] == KNOWLEDGE_BANK_NAME
        )
        searcher = KnowledgeBankSearcher(self.settings, kb_id)
        self.agent = Agent(self.settings, searcher)

    def process(self, query, settings, trace):  # noqa: ANN001 — signature imposée par Dataiku
        question = _question_from_query(query)
        if not question:
            return {"text": "Aucune question reçue."}
        result = self.agent.ask(question)
        answer = result.answer
        if answer.not_found:
            return {"text": f"Non trouvé. {result.note}".strip()}
        cites = "; ".join(
            f"[{c.video_id}, {int(c.start_s)}s]" for c in answer.citations if c.verified
        )
        return {"text": f"{answer.answer}\n\nSources : {cites}" if cites else answer.answer}


def _question_from_query(query) -> str | None:  # noqa: ANN001
    """À VÉRIFIER : forme exacte de `query` sur cette instance (doc Dataiku Code Agent)."""
    if isinstance(query, str):
        return query
    if isinstance(query, dict):
        if query.get("question"):
            return query["question"]
        messages = query.get("messages") or []
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
                return m["content"]
    return None
