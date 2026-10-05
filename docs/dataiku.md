# Kit d'intégration Dataiku (KIT-1)

Objectif (décision D4) : Synchrone réalise l'intégration dans son projet Dataiku, **sans
réécrire notre code** — ce kit fournit les recettes qui font le pont. La plupart des
scripts n'ont pas tourné sur une vraie instance (pas d'accès direct depuis ce repo) et
restent marqués **kit, à tester** dans leur docstring. Exception : la connexion LLM et la
Knowledge Bank ont été testées pour de vrai le 18/09 (Evan, via sa clé API personnelle et
un notebook Dataiku) — voir `docs/LOG.md`. Chaque script distingue explicitement ce qui
est confirmé (sourcé sur CLAUDE.md/le coach Dataiku, ou mesuré le 18/09) de ce qui reste une
hypothèse.

## Vue d'ensemble

| Étape | Dans ce repo | Dans Dataiku | Fichier du kit | Statut |
|---|---|---|---|---|
| Vidéos | `data/videos/` | Managed folder `video` (existe déjà) | — | — |
| Code | `src/kb/` | Bibliothèque de projet importée depuis Git | — | — |
| Transcription + diarization | `kb.ingest` | Recette Python, env `py311_fasterwhisper` → `segments`, `videos` | `recipe_ingest.py` | kit, à tester |
| Fiches REX | `kb.structure` | Recette Python, LLM Mesh (Luna) → `fiches_rex` | `recipe_structure.py` | kit, à tester (LLM confirmé OK) |
| Chunks | `kb.index.chunking` | Recette Python → `chunks` | `recipe_chunks.py` | kit, à tester |
| Embeddings + index | `kb.adapters.vs_chroma` (Chroma local) | **Knowledge Bank native** (pas notre `ChromaStore` — REST `/embeddings` indisponible, `docs/LOG.md` 18/09) | `recipe_embed.py` | API confirmée 18/09, volume réel non testé |
| Recherche (agent) | `kb.index.search.Searcher` | `KnowledgeBankSearcher` (dense seul, pas de BM25/rerank/zoom moment) | `kb_retrieval.py` | **API + scores confirmés par un test réel** 18/09 |
| Agent + garde-fous | `kb.agent` | Code Agent (`dataiku.llm.python.BaseLLM.process`) | `code_agent.py` | kit, forme de `query` non confirmée |
| Env de code dédié | `pyproject.toml` | À créer par un admin (le coach Dataiku) | `envs.md` | `langchain-core` confirmé nécessaire + présent dans `INTERNAL_retrieval_augmented_generation_v1` |
| Évaluation | `kb.eval` | Recette Python + `Evaluate Agent` → Dashboard | — | pas commencé |
| Orchestration | `python -m kb.cli` | Scénarios `INGEST` et `EVAL` | — | pas commencé |
| Chat interne | — | Agent Hub (déjà installé) | — | — |
| Front | FastAPI `PROFILE=free`/`dataiku` | Même API, juste `PROFILE=dataiku` (D9) | — | — |

## Recherche : Knowledge Bank native, pas notre ChromaStore

Décision initialement prise par prudence (pas d'API confirmée) puis **inversée après
test réel** le 18/09 : `code_agent.py` utilisait au départ notre propre `ChromaStore`
(téléchargée depuis un managed folder), pour éviter de deviner l'API d'une Knowledge
Bank. Deux choses ont changé ce jour-là :

1. **Les embeddings ne marchent pas via notre adapter REST** (`docs/LOG.md`, 18/09) :
   `/embeddings` sur l'endpoint compatible OpenAI renvoie un 404 générique de passerelle,
   contrairement à `/chat/completions` et `/models` qui fonctionnent. Impossible de
   construire un `ChromaStore` avec l'Embedding v3 Small sans passer par Dataiku lui-même.
2. **L'API Python de la Knowledge Bank a été testée pour de vrai** (création, écriture,
   recherche avec score, suppression — 2 documents, coût négligeable) plutôt que déduite
   de la doc seule. Elle **fonctionne**, y compris `similarity_search_with_score`.

Donc : `recipe_embed.py` écrit les `chunks` dans une Knowledge Bank (embeddings calculés
côté Dataiku, contourne le blocage REST) et `kb_retrieval.py` l'interroge à la place de
notre `Searcher`/`ChromaStore`. Limites connues de ce chemin (documentées en tête de
`kb_retrieval.py`) : recherche **dense seule** (pas de BM25/RRF/rerank cross-encoder), pas
de zoom moment (`moment_s` = début du chunk, ±2-3 min au lieu de ±30 s), et
`abstain_threshold` (calibré sur des scores de reranker) **pas recalibré** pour une
similarité dense — à refaire sur le golden set avant de faire confiance à l'abstention
dans ce mode.

**API confirmée (test réel du 18/09, pas seulement la doc) :**

```python
# Création (une seule fois) — dédoublonne PAS par nom, vérifier list_knowledge_banks() d'abord
dss_kb = project.create_knowledge_bank(name, "CHROMA", "openai:challenge_llm:text-embedding-3-small")
kb_core = dss_kb.as_core_knowledge_bank()

# Écriture — métadonnées des Document LangChain conservées intactes
with kb_core.get_writer() as writer:
    writer.as_langchain_vectorstore().add_documents(docs)   # docs: list[langchain_core.documents.Document]

# Lecture — score = DISTANCE (bas = proche), pas une similarité comme notre ChromaStore
vs = kb_core.as_langchain_vectorstore()
vs.similarity_search_with_score(query, k=5, filter={...})   # -> list[(Document, float)]

# Suppression
project.get_knowledge_bank(dss_kb.id).delete()
```

ID d'embedding confirmé (absent de `project.list_llms()` par défaut, qui ne renvoie que
`purpose="GENERIC_COMPLETION"`) :
`project.list_llms(purpose="TEXT_EMBEDDING_EXTRACTION")[0]["id"]` ==
`"openai:challenge_llm:text-embedding-3-small"`. Aucun reranker via LLM Mesh
(`purpose="RERANKING"` renvoie `[]`).

## Ordre d'exécution

1. Un admin crée l'env de code dédié avec `langchain-core` en plus (`envs.md`).
2. `recipe_ingest.py` (env `py311_fasterwhisper` + `kb`) : `video` → `segments`, `videos`.
3. `recipe_chunks.py` : `segments` + `videos` → `chunks`.
4. `recipe_embed.py` : `chunks` → Knowledge Bank `kb_index` (confirmé fonctionnel).
5. `recipe_structure.py` : `segments` + `videos` → `fiches_rex`.
6. `code_agent.py`, déployé comme Code Agent, appelable depuis Agent Hub ou l'API
   publique (`get_llm("agent:…")`, CLAUDE.md section 2).

## Reste à faire (pas dans ce kit)

- Recette `Evaluate Agent` (évaluation dans Dataiku, section 10) : pas commencée.
- Scénarios `INGEST`/`EVAL` (orchestration) : pas commencés.
- Recalibrer `abstain_threshold` sur le golden set pour le mode dense-seul de
  `KnowledgeBankSearcher` (actuellement le seuil `hybrid_rerank` du profil, pas validé).
- Ajouter BM25 + fusion RRF au-dessus de la Knowledge Bank si le rappel dense seul ne
  suffit pas (construire un `BM25Index` local depuis le dataset `chunks`, déjà présent).
- Confirmer avec le coach Dataiku : forme exacte de `query` dans `BaseLLM.process` (CLAUDE.md
  section 14), présence d'un GPU derrière `py311_fasterwhisper`, token Hugging Face pour
  pyannote, un chemin REST existe-t-il pour les embeddings ou est-ce structurellement
  recette/Knowledge-Bank-only ?

## Pièges connus

- `whisper==1.1.10` dans `challenge_code_env` n'est **pas** Whisper d'OpenAI (c'est la
  base de séries temporelles Graphite) — utiliser `py311_fasterwhisper`.
- La recette Speech Recognition (plugin absent de toute façon) ne fournit pas de
  timestamps.
- GPT-5.6 peut refuser `temperature` ≠ 1 (D8) : `profiles/dataiku.yaml` met
  `temperature: null` (paramètre non envoyé) par précaution, à revalider.
- `/embeddings` sur l'endpoint compatible OpenAI renvoie un 404 HTML générique de
  passerelle, pas une erreur JSON applicative — ne pas y passer de temps à déboguer un ID
  de modèle, ce n'est pas le problème (`docs/LOG.md`, 18/09).
- Un kernel `whisper_env` standard n'a pas `langchain` et n'a pas les droits `pip
  install` (env partagé) — utiliser `INTERNAL_retrieval_augmented_generation_v1`.
