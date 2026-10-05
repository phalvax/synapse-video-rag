# PASSATION — état réel du projet RAG16 (équipe 16), au 27/09/2026 au soir

> **Pour le prochain agent.** Ce fichier remplace les parties datées de `CLAUDE.md` (sections 18-19,
> « État du repo » : figées au 17/09). `CLAUDE.md` reste la référence pour le **contexte** (brief
> Synchrone, décisions D1-D11, Dataiku, jury, notation). Ici : **ce qui existe vraiment**, ce qui a
> été **mesuré**, les **pièges**, et **la suite**. Le détail de chaque essai (hypothèse → réglage →
> résultat → leçon) est dans `docs/LOG.md` (journal chronologique, échecs compris).

---

## 1. En 30 secondes

- **RAG16** (nom choisi par Aymeric) = « mémoire des réunions » pour Synchrone : on importe des
  réunions (vidéo/audio), des **PDF** (même scannés) et des **images** ; on pose une question ; la
  réponse cite l'**extrait exact** + la **minute** (ou la **page**) ; clic → lecture au bon moment.
  Sans preuve vérifiée par le code → **abstention** (+ « pistes » : passages proches).
- Backend **FastAPI** (`src/kb/`) + front **React/Vite/TS/Tailwind v4** (`frontend/`), LLM local
  **gemma3:4b** via **Ollama** (profil `free`), embeddings **bge-m3**, reranker **bge-reranker-v2-m3**,
  transcription **faster-whisper large-v3-turbo** (CPU int8), OCR **Tesseract**.
- **Échéances** : démo vidéo ≤ 4 min + slides **mar. 29/09 23:59** ; peer review 01/10 ; finale 02/10.
- **Utilisateur** : Aymeric (lead, 2e année). Parle **français**, veut des chiffres **étiquetés**
  (mesuré / estimé / hypothèse, avec n), **commit + push sur `main` après chaque fonctionnalité
  testée** (autorisation durable), et des explications simples. Son collègue fait l'intégration
  **Dataiku** (Web App + Knowledge Bank) de son côté, hors de ce repo.

## 2. Lancer et vérifier (PC d'Aymeric : Windows, CPU seul, HTTPS intercepté)

```powershell
.\.venv\Scripts\Activate.ps1
ruff check . ; pytest                      # 183 tests verts au 27/09 (sans réseau ni modèle)
uvicorn kb.api.app:app --port 8000         # backend (PAS de --reload : relancer après chaque modif)
cd frontend ; npm ci ; npx vite --port 5173 # front → http://localhost:5173 (proxy /api → :8000)
```
- `pip` : `$env:PIP_USE_FEATURE='truststore'` (HTTPS intercepté). Extras : `.[dev,asr,index,api,docs]`.
- Ollama doit tourner (gemma3:4b, bge-m3). Pas de `.env` : pas de clé Dataiku ni Ollama Cloud.
- **Tesseract** : `C:\Program Files\Tesseract-OCR\tesseract.exe` ; langues **fra + eng** copiées dans
  `data/models/tessdata/` (le code l'utilise en priorité ; `fra.traineddata` vient de tessdata_fast).
- Le backend garde l'agent en cache : **après un changement de code, un réindex ou un recap,
  relancer uvicorn** (sinon anciens comportements).

## 3. Corpus local (`data/`, **jamais versionné**)

| Source | Détail |
|---|---|
| 3 talks **TED** (WAV découpés `_segNN`) | golden set v0 `src/kb/eval/golden_set.jsonl` (42 q.) |
| 8 réunions **AMI** ES2002a-d, ES2004a-d (CC BY 4.0, ~4,6 h) + **ES2006a** (importée par l'API) | 2 équipes × 4 réunions, même projet (télécommande) ; `Video.mission` = ES2002/ES2004/ES2006 ; golden set `golden_ami.jsonl` (20 q., **écrites par Claude, à relire**) |
| **Fichiers FICTIFS** de démo (marqués « FICTIF ») | `compte_rendu_technique_es2002` (PDF 3 p., FR), `note_revue_qualite_scan` (PDF image seule), `schema_architecture_v2` (PNG), `revue_budget_es2002_video` (MP4 : 4 diapos sur 140 s d'audio AMI) — sources HTML/scripts dans le scratchpad de la session, pas dans le repo |

Index `data/index/free/` : 161 chunks. Points mission : `data/recaps/missions/ES2002.json`, `ES2004.json`.
Doublons mis de côté : `data/duplicates/`. Formulaires d'import : `data/metadata/<id>.json`.
Médias recollés (vidéos en morceaux) : `data/media/`.

## 4. Architecture réelle (ce qui tourne)

```
Import (API POST /videos + formulaire) ──► doublon exact ? (SHA-256 → 409)
  ├─ audio/vidéo : PyAV → faster-whisper (VAD) → segments horodatés
  │    └─ vidéo : 1 image/s, gardée si l'écran change → OCR (+ description si < 40 car.)  [frames.py]
  ├─ PDF : pypdf page par page ; page sans texte → rendu pypdfium2 → OCR/vision            [documents.py]
  └─ image : OCR + description gemma3 vision                                              [vision.py]
  → quasi-doublon ? (5-grammes, containment ≥ 0,3 → data/duplicates/, non indexé)          [dedup.py]
  → index INCRÉMENTAL : chunks ~400 tokens (jamais à cheval sur 2 pages ni 2 natures),
     en-tête contextuel (titre, mission, auteur, date, description), bge-m3 → Chroma ; « moments »
     (3 segments) pour la seconde/page précise                                             [index/build.py]
Question (/ask) ──► « point / récap / où en est + mission » ? → point mission (sans LLM)     [agent/router.py]
  └─ agent : traduction dans CHAQUE langue du corpus (EN + FR) → recherche dense + BM25 → RRF
     → rerank → fusion (meilleur score par passage) → filtre mission auto (« l'équipe ES2004 »)
     → seuil d'abstention (0,10) → gemma3 (JSON) → garde-fous → réponse ou abstention + pistes
```

**Contrat** (`src/kb/schemas.py`, champs ajoutés tous optionnels) : `Video.kind`
(video/audio/document/image), `description`, `contact`, `sha256` ; `Segment/Chunk/Citation.page`
(documents : position = page + rang/1000) et `.modality` (None = parole/texte ; `ocr` = lu dans une
image ; `visual` = **description GÉNÉRÉE** — jamais une preuve).

**Garde-fous (tous en code, dans cet ordre)** : seuil de rerank (pas d'appel LLM) → sources en
`<source … date=… context=…>` → JSON validé (1 retry) → citation recalée sur le transcript
(`snap_quote`), **rattachée à la source qui la contient vraiment** (le LLM se trompe de S1/S2) →
**chaque nombre de la réponse doit figurer dans une citation** (sinon extrait exact ajouté, sinon
abstention) → sans citation → abstention → réponse appuyée **uniquement** sur des descriptions
générées → note + bandeau « à vérifier sur l'image ». **Seconde d'une citation = moment qui contient
la citation** (27/09 ; avant : moment le plus proche de la question).

**Point mission (L3)** : `kb.cli recap MISSION video_ids…` : fenêtres ~6-9 min → points prouvés
(citation recalée, chiffre prouvé par l'extrait qui le contient) → fiche réunion (le LLM choisit des
**identifiants** P1…) → mission (K1…, statut basé sur la dernière réunion). Phrases avec un nombre
jamais prononcé retirées ; noms de fichiers retirés par le code. ~55 min CPU pour 8 réunions.

**API** (`src/kb/api/app.py`) : `/videos` (GET liste, POST upload + formulaire), `/videos/{id}`,
`/media` (recolle les `_segNN` en WAV), `/segments`, `/jobs/{id}` (queued/transcribing/indexing/
done/failed/**duplicate**), `/ask` (→ `AskResponse` = Answer + `leads`, `note`, `mission`),
`/missions`, `/missions/{m}/recap`, `/metrics?corpus=ted|ami`, `/tiers`, `/fiches`, `/experts`.

**Front** (refonte du 25/09, choix d'Aymeric) : barre latérale RAG16 (Recherche · Point mission ·
Importer · Indicateurs), thème clair par défaut + sombre, Inter, accent bleu, **pas de sélecteur de
palier**, **pas d'onglet Fiches REX**. Recherche : exemples cliquables, étapes d'attente
(indicatives), cartes source (▶, minute ou « p. N », badge de nature), jauge « score, pas une
probabilité », abstention ambre + pistes, bandeau point mission. À droite : lecteur audio/vidéo,
visionneuse PDF (`#page=N`), visionneuse d'image, transcript qui suit la lecture, métadonnées du
formulaire, case « Chercher seulement dans cette vidéo/ce document ». Import : glisser-déposer +
formulaire (titre, mission, date, auteur, contact, description, langue). Indicateurs : TED / AMI.

**Kit Dataiku** (`dataiku_kit/`, **non testé sur l'instance**) : `recipe_ingest.py` (GPU auto
`device: auto`, seulement les nouveaux fichiers, formulaire `<nom>.meta.json`), `upload_hook.py`
(lance le scénario INGEST dès l'upload), `scenario_trigger.py` (ne lance que s'il reste un fichier),
`kb_retrieval.py` (Knowledge Bank, testée par Evan le 18/09). Ne gère **pas encore PDF/images**.

## 5. Chiffres mesurés (à citer tels quels ; détail et n dans `docs/LOG.md`, `docs/reports/`)

| Mesure | Valeur | Contexte |
|---|---|---|
| WER turbo / small | 2,0 % / 2,6 % | TED, 26 min, réf. humaine |
| Recherche TED (hybrid_rerank) | Hit@1 30/31, moment ±30 s 29/31 | 13 chunks — cas facile |
| Recherche AMI | Hit@1 10/14, **Hit@5 12/14**, moment 7/14, abstention correcte 4/4 | 144 chunks, golden écrit par Claude |
| Traduction de la question | fausses abstentions FR 6 → 3 / 18 | TED, +2,2 s/question |
| Agent AMI (27/09, 2e passage) | couverture **13/16**, abstention correcte 4/4, citations vérifiées 20/20, moment ±30 s 7/13 (ancienne règle 6/13), p50 57 s | `docs/reports/ami_agent_free_synthese_2026-09-27.md` ; exactitude non relue (M09 douteuse) |
| Agent TED (25/09) | couverture 5/12, 3/4 abstentions correctes ; 6 fausses abstentions sur 7 dues au LLM (citation reformulée) | gemma3:4b CPU, p50 39 s |
| Import | réunion 21 min : 736 s (transcription 658 s RTF 0,51 ; index incrémental 65 s vs ~770 s complet) ; PDF 36 s ; scan 18 s ; image 91 s | CPU |
| Détection de langue Whisper | surcoût **fixe** ~10-17 s/fichier | 60 s : 37 vs 20 s ; 180 s : 102 vs 92 s |
| Doublons | exact refusé en 0,9 s ; même audio re-transcrit : containment 0,54 ; réunions différentes ≤ 0,03 → seuil 0,3 | **1 seul** vrai doublon mesuré |
| Changements d'écran | 4/4 diapos à la seconde près (part de pixels changés, seuil 3 %) | bruit de caméra **simulé** seulement |
| OCR / vision | OCR 1-1,5 s/image ; description gemma3 ~60 s/image | CPU |

## 6. Pièges déjà rencontrés (ne pas les refaire)

- **Heredocs + Python/JS sous Git Bash** : les `\n`, `\\s`, `\d` dans du code écrit via
  `cat <<EOF` / `node -` / scripts de patch **perdent leurs antislashs** (bug réel du 25/09 : tous les
  « d » retirés des réponses par `/s*[Sd+]/`). Écrire le code avec l'outil Write/Edit, ou vérifier
  par `grep` après coup.
- Fichiers du front en **CRLF** : un remplacement de texte exact doit normaliser les fins de ligne.
- `summary.py` / `tiers.py` lisent le **dernier** rapport par ordre alphabétique : les rapports d'un
  autre golden set sont **préfixés** (`ami_search_…`) pour ne pas écraser le dashboard TED.
- Whisper ne re-transcrit jamais mot pour mot le même audio (doublons : ne pas exiger l'identique).
- gemma3:4b : reformule / réordonne les citations, se trompe d'étiquette S1/S2, répond parfois faux
  sur une image ou un tableau → les garde-fous rattrapent la plupart ; **Luna (Dataiku) jamais
  mesuré** faute de clé (test prioritaire dès qu'elle est dans `.env` : `DSS_API_KEY`, profil
  `dataiku`, IDs `openai:challenge_llm:gpt-5.6-luna|terra|sol`).
- Un **tableau** extrait d'un PDF devient une suite de mots à plat → mal classé par le reranker.
- Mesures à la seconde près : le temps d'une question inclut ~60 s de rechargement de l'agent après
  un import (cache invalidé).
- Stash git local d'Aymeric (`stash@{0}`, restructuration « étapes 00-08 » du 18/09) : **abandonné**
  au profit du code d'Evan, garder pour mémoire, ne pas appliquer.

## 7. Ce qui reste à faire (par priorité pour la démo du 29/09)

1. ~~Mesurer le correctif « seconde = là où la citation apparaît »~~ — fait le 27/09 : gain
   +1/13 (non significatif) ; la mesure a surtout révélé le bug « ES2002 pris pour un nombre »
   (couverture AMI 7/16 → 13/16 une fois corrigé). **Relire à la main les 13 réponses AMI**
   (exactitude, ex. M09) avant de citer la couverture comme « taux de bonnes réponses ».
2. **Souci remonté par le collègue** (Web App Dataiku, sélection du modèle bloquée) — voir §8.
3. **Luna/Terra/Sol** sur les mêmes golden sets dès que la clé Dataiku est disponible (frontière
   coût-qualité, question « est-ce le LLM local ? »).
4. Relire les 20 questions AMI ; ajouter des questions sur les documents/images/vidéo fictifs.
5. Juge de fidélité (faithfulness / hallucination : toujours « non mesuré ») ; chronométrage
   humain « à la main vs outil ».
6. Kit Dataiku : PDF/images (réutiliser `ingest_document`) ; mettre à jour `CLAUDE.md` §18-19.
7. Tableaux PDF (extraction par cellules) ; valider le seuil d'écran sur une vraie vidéo filmée.

## 8. Contexte du souci du collègue (27/09)

Message transmis tel quel par Aymeric : « Il m'a dit d'adapter la dernière version de l'app web. La
sélection du modèle empêche le fait qu'on puisse choisir un différent contrairement aux deux autres.
Puis, il a essayé de connecter Dataiku à ça, c'est peut-être là d'où vient le problème, étant donné
que la première était juste en fonction de la sélection de recherche dans les chunks. »
Lecture retenue : sa Web App Dataiku (v1 = recherche dans les chunks de la Knowledge Bank, sans LLM ;
v2 = branchée sur un LLM Dataiku) a un sélecteur de modèle dont la valeur ne change pas / n'est pas
prise en compte. Traitement : voir la dernière entrée de `docs/LOG.md`.
