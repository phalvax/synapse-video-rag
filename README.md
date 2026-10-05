# 🎥 Synapse — Video Memory RAG for Synchrone

> Turn hours of meeting & training recordings into **verifiable answers**: summary + exact quote + `[video, mm:ss]` timestamp + who to contact — or an honest *"not found"*.

**Team project · Albert School × Synchrone · September 2026 · Team 16 (5 people)**
**My role: tech lead** — agent & guardrails, Dataiku integration kit, benchmarking.

> Code snapshot of the team project (Team 16: Aymeric, Evan, Maire, Wael, Rany). Media, transcripts, indexes and models are **not** versioned — bring your own videos.
> ▶️ Setup & commands: [`docs/QUICKSTART.md`](docs/QUICKSTART.md) · architecture & measured results: [`docs/HANDOFF.md`](docs/HANDOFF.md), [`docs/reports/`](docs/reports)

---

## The problem
Engineering knowledge at Synchrone is trapped in recordings (meetings, trainings, peer explanations). Nobody re-watches a 1-hour video to find a 30-second answer.

## What we built
```
videos/audio ─► L0 ingest (faster-whisper, timestamped) ─► L1 structuring (LLM → "REX" lesson cards, SQLite)
                                                        └► L2 index (chunks, bge-m3 embeddings, BM25, RRF, reranker, Chroma)
question ─► L4 agent with guardrails ─► answer = summary + exact quote + [video, mm:ss] + contact   (or "not found")
                                     └► L5 evaluation (WER, Hit@k, MRR, abstention, cost per question)
```

- **Hybrid retrieval**: dense `bge-m3` + BM25 fused with RRF, then `bge-reranker-v2-m3`; FR→EN cross-lingual search.
- **Proven answers**: citations are verified *by code* against the transcript; a strict mode returns quotes only, zero generation.
- **Multimodal**: OCR of slides/whiteboards shown on screen, scanned PDFs, vision-LLM descriptions — all timestamped.
- **3 cost tiers, one code base**: `free` (Ollama, local models, 0 €), `dataiku` (LLM Mesh), `market` (any OpenAI-compatible API) — switched with one env variable; a cost/quality frontier compares them.
- **Product**: FastAPI backend (upload → job, `/ask`, lesson cards, metrics, experts) + React/Vite/TypeScript/Tailwind front (chat with clickable citations → video player at the right second, dashboard with 8 KPIs).
- **Engineering hygiene**: shared schema contract, branch-per-task + reviewed PRs, pytest + ruff in GitHub CI, every experiment logged.

## My contribution
- Led the team and the architecture; owned the **agent and its guardrails** (abstention, citation & number checks).
- Built the **Dataiku integration kit** (Knowledge Bank search, LLM Mesh models).
- Ran the measurements, e.g. agent coverage on the AMI meeting benchmark improved from **7/16 → 13/16** after a bug fix.

## Stack
`Python 3.11` `faster-whisper` `bge-m3` `BM25` `bge-reranker-v2-m3` `ChromaDB` `SQLite` `Ollama` `Dataiku LLM Mesh` `FastAPI` `React` `TypeScript` `Vite` `Tailwind` `pytest` `GitHub Actions`

---

### 🇫🇷 En bref
Projet d'équipe (Albert School × Synchrone, sept. 2026) : une **mémoire vidéo d'entreprise**. On interroge des heures de réunions et de formations, et le système répond avec un résumé, l'extrait exact, l'horodatage `[vidéo, mm:ss]` et la personne à contacter — ou « non trouvé ». Recherche hybride (bge-m3 + BM25 + reranker), citations vérifiées par le code, OCR de l'écran, API FastAPI, front React, intégration Dataiku et trois paliers de coût.
**Mon rôle : lead technique** — agent et garde-fous, kit Dataiku, mesures.
