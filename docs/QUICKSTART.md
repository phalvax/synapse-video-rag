# BDD-1 — Team 16 · Mémoire vidéo de Synchrone

Transformer des enregistrements (réunions, formations, explications entre ingénieurs) en **réponses vérifiables** : résumé + **extrait exact + [vidéo, mm:ss]** + contact, ou **« non trouvé »**.

> 📘 Tout le contexte (décisions, architecture, rôles, coûts, questions du jury) est dans **[CLAUDE.md](CLAUDE.md)**. Claude Code le lit automatiquement.
> 📊 Résultats mesurés : **[docs/reports/](docs/reports/)** · journal des essais : **[docs/LOG.md](docs/LOG.md)**.

## Démarrage rapide (Windows / PowerShell)

```powershell
# 1. Environnement Python 3.11
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Installer le projet
python -m pip install --upgrade pip
pip install -e ".[dev]"                 # socle + tests
pip install -e ".[dev,asr,index]"       # + transcription, Chroma, BM25, reranker (torch CPU, ~1 Go)
# Erreur « CERTIFICATE_VERIFY_FAILED » (antivirus / proxy) ? Utiliser les certificats Windows :
#   $env:PIP_USE_FEATURE = 'truststore'; pip install -e ".[dev,asr,index]"

# 3. Configuration
Copy-Item .env.example .env             # puis remplir si besoin

# 4. Vérifier
pytest
python -m kb.cli check --no-call
```

**Modèles gratuits (palier 0)** : installer [Ollama](https://ollama.com), puis `ollama pull bge-m3` (embeddings).
Whisper et le reranker se téléchargent seuls depuis Hugging Face au premier lancement.
Si le réseau coupe les gros fichiers, les déposer dans `data/models/<nom>/` (ex. `data/models/bge-reranker-v2-m3/`) : le code les utilise en priorité.

## De la vidéo à la recherche

```powershell
# Déposer vidéos ou audios dans data/videos/  (les morceaux nom_seg01, nom_seg02… sont regroupés)
python -m kb.cli ingest data/videos --model large-v3-turbo   # → data/transcripts/*.jsonl + data/videos.jsonl
python -m kb.cli index                                      # → chunks, embeddings bge-m3, Chroma
python -m kb.cli search "Quelle est la taille des exosomes ?"

# Réponse prouvée (citations vérifiées par le code) ou « non trouvé »
python -m kb.cli ask "Quelle est la taille des exosomes ?"
python -m kb.cli ask "Quelle est la taille des exosomes ?" --strict   # extraits seuls, zéro génération
python -m kb.cli ask "…" --json                                      # objet Answer brut

# Fiches REX (Phase 4) : extraction LLM → data/kb.sqlite, interrogeable (outil query_fiches)
python -m kb.cli structure                                  # transcript → fiches (problème/solution/…)
python -m kb.cli fiches "cache" --tech Redis --client Acme

# Mesures
python -m kb.cli eval-asr --models small large-v3-turbo     # WER vs transcription humaine TED + vitesse
python -m kb.cli eval-search                                # golden set : Hit@k, MRR, moment, abstention
python -m kb.cli eval-agent --ids P01 S05 U06                # agent : abstention, citations, coût
python -m kb.cli eval                                       # recherche + agent + synthèse (un profil)
python -m kb.cli compare-tiers --profiles free dataiku       # frontière coût-qualité (rapports déjà générés)
```

**Formats acceptés :** tous les conteneurs lus par ffmpeg (mp4, mkv, avi, mov, wmv, mpeg, ts, webm…) et les audios (wav, mp3, m4a, opus, aac, flac…). L'audio est extrait en mémoire par PyAV : rien à installer.

**LLM local lent ?** Mesuré sur CPU : `gemma3:4b` 85 s par réponse, `qwen3:4b` 477 s (mode « thinking »). Pour la démo, pointer le profil `free` vers **Ollama Cloud** (`OLLAMA_BASE_URL=https://ollama.com/v1` + clé) ou utiliser le profil `dataiku`.

## API (Phase 6)

```powershell
pip install -e ".[api]"
uvicorn kb.api.app:app --reload --port 8000     # docs interactives : http://localhost:8000/docs
```

Le backend garde les clés (aucune clé côté navigateur). Routes : `POST /videos` (upload → job),
`GET /jobs/{id}`, `GET /videos`, `GET /videos/{id}`, `GET /videos/{id}/media` (lecteur),
`GET /videos/{id}/fiches`, `GET /videos/{id}/segments`, `GET /fiches?text=&client=&tech=`,
`POST /ask`, `GET /metrics`,
`GET /tiers`, `GET /experts?topic=`.

## Les 3 paliers (même code, une variable)

| `PROFILE=` | Contenu | Coût |
|---|---|---|
| `free` | Ollama (local ou cloud), faster-whisper, bge-m3, bge-reranker-v2-m3 | 0 € |
| `dataiku` | GPT-5.6 Luna / Terra / Sol + Embedding v3 Small via le LLM Mesh Dataiku | Tarifs Dataiku |
| `market` | Autre fournisseur compatible OpenAI | Estimé |

## Structure

```
src/kb/
  cli.py  config.py  schemas.py (CONTRAT COMMUN)  jsonl.py
  adapters/   les « prises » : LLM, embeddings, Whisper, Chroma, reranker
  ingest/     L0 — découverte des fichiers, transcription horodatée
  index/      L2 — chunks, BM25, RRF, recherche hybride + rerank
  agent/      L4 — garde-fous (agent : Phase 3)
  structure/  L1 — extraction LLM → fiches REX, stockage SQLite (Phase 4)
  eval/       L5 — métriques, WER, évaluation de la recherche/agent, comparaison des paliers
  api/        FastAPI : upload, jobs, /ask, fiches, métriques, experts (Phase 6)
profiles/     free.yaml · dataiku.yaml · market.yaml
tests/        pytest (sans réseau ni modèle)
docs/         LOG.md · reports/ · dataiku.md · frontend.md
data/         (ignoré par git) videos/ transcripts/ index/ models/ …
frontend/     React + Vite + TS + Tailwind, sur mocks (Phase 7) — voir ci-dessous
dataiku_kit/  Recettes Dataiku (Phase 8, kit non testé) — voir docs/dataiku.md
```

## Front (Phase 7)

```powershell
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxy /api -> backend FastAPI :8000)
```

Écrans : Recherche (chat + citations cliquables → lecteur), Fiches REX (filtrable),
Upload (progression + statut du job), Dashboard (8 indicateurs + frontière coût-qualité).
**Sur mocks** (`src/mocks/data.ts`) pour l'instant — `src/api/client.ts` a une fonction par
route de l'API (Phase 6) ; brancher le vrai backend consiste à remplacer le corps de chaque
fonction par un `fetch("/api/...")`, sans toucher aux composants.

## Règles d'équipe

1. On ne code **jamais** sur `main`. Une branche par tâche, par exemple `feat/ingest-diarization`.
2. `git pull` avant de commencer ; ensuite une **pull request**, relue avant fusion.
3. **Aucune vidéo, aucun audio, aucune clé dans git.** Le `.gitignore` bloque `data/`, les médias et `.env`.
4. On ne modifie `schemas.py` qu'après accord de l'équipe.
5. Chaque essai (réussi ou raté) est noté dans `docs/LOG.md`.
6. `pytest` et `ruff check .` doivent passer avant chaque PR (la CI GitHub les relance).

## Équipe

| Rôle | Personne | Tâches |
|---|---|---|
| Lead, agent, garde-fous, kit Dataiku | Aymeric | SET-1, AGT-*, BENCH-1, KIT-1 |
| Ingestion | Maire | ING-* |
| Structuration & index | Wael | STR-1, IDX-* |
| Évaluation & business | Rany | DATA-1, EVAL-*, BIZ-1 |
| Front, API, démo | Evan | FE-*, API-*, DEMO-1 |
