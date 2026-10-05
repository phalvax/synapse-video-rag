# Env de code dédié — ce qu'un admin doit créer

Confirmé (CLAUDE.md section 2) : `challenge_code_env` n'a ni `openai`, ni `chromadb`, ni
`rapidfuzz`, ni `pydantic` ; `py311_fasterwhisper` a l'ASR (faster-whisper, whisperx,
pyannote) mais pas non plus le reste de `kb`. Il faut donc un **env dédié** (un admin
Dataiku — le coach Dataiku) pour les recettes L1/L2/L4 (`recipe_structure.py`, `recipe_chunks.py`,
`code_agent.py`) — `recipe_ingest.py` reste dans `py311_fasterwhisper`, avec `kb` ajouté
dedans.

## Dépendances (= `pyproject.toml` de ce repo, + `langchain-core` pour `code_agent.py`)

```
pydantic>=2.6
pyyaml>=6.0
python-dotenv>=1.0
openai>=1.40
rapidfuzz>=3.6
numpy>=1.26
chromadb>=0.5
bm25s>=0.2
sentence-transformers>=3     # reranker (BAAI/bge-reranker-v2-m3) — lourd (torch CPU, ~1 Go)
langchain-core                # code_agent.py / kb_retrieval.py : Knowledge Bank native
```

**`langchain-core` — confirmé le 18/09 (Evan) :** absent d'un kernel `whisper_env` par défaut
(`ModuleNotFoundError`, `pip install` refusé — permissions sur un env partagé). Présent dans
l'env **`INTERNAL_retrieval_augmented_generation_v1`** (confirmé par la même KB de test, qui a
tourné dedans). `recipe_embed.py` et `code_agent.py` (via `kb_retrieval.py`) en ont besoin ;
`recipe_ingest.py`, `recipe_chunks.py` et `recipe_structure.py` non.

Plus le paquet du projet lui-même : `kb` importé comme **bibliothèque de projet depuis
Git** (CLAUDE.md section 10), ou `pip install -e .` de ce repo dans l'env si Git n'est
pas branché.

## Secrets

- `DSS_API_KEY` : la clé API personnelle (Profil → Clés d'API, CLAUDE.md section 2),
  en **secret utilisateur Dataiku**, jamais en clair dans une recette ou un notebook.
- `HF_TOKEN` (pyannote, pour `recipe_ingest.py` si la diarization whisperx/pyannote est
  activée) : idem, en secret utilisateur (CLAUDE.md section 14, question 4 — à confirmer
  avec le coach Dataiku que ce token existe côté projet).

## Non vérifié

- Taille exacte de l'image/du quota disque de l'env (le reranker + torch CPU pèsent
  environ 1 Go, cf. README).
- Que `pip install` fonctionne sans restriction réseau depuis un env Dataiku custom (à
  tester en premier, avant le reste du kit).

## Traitement des nouveaux fichiers (ajouté le 27/09, non testé sur l'instance)

| Besoin | Fichier | Où le brancher |
|---|---|---|
| Transcrire **seulement les nouveaux fichiers**, GPU détecté tout seul (`device: auto` → cuda/float16, sinon cpu/int8) | `recipe_ingest.py` | Recette Python, env `py311_fasterwhisper` |
| Lancer le scénario **dès qu'un fichier arrive** (au lieu d'attendre 30 min) | `upload_hook.py` → `save_and_process(...)` | Backend Python de la Web App, juste après l'upload |
| **Filet de sécurité** : ne lancer `INGEST` que s'il reste un fichier non traité | `scenario_trigger.py` | Scénario `INGEST` → Triggers → Custom trigger (Python), toutes les 1-2 min |

Le formulaire d'import de la Web App (titre, mission, date, auteur, contact, description, langue)
est déposé à côté du fichier (`<nom>.meta.json`) et appliqué par `recipe_ingest.py`.
Pas de conversion en WAV : PyAV décode mp4, mkv, mov… directement (mesuré le 27/09).

## Web App : le sélecteur de modèle n'a aucun effet (retour de l'équipe, 27/09)

Symptôme : on choisit Luna, Terra ou Sol, mais la réponse vient toujours du même modèle
(les autres sélecteurs, eux, fonctionnent). Trois causes possibles, à vérifier dans cet ordre :

1. **La Web App passe par notre API FastAPI** : avant le 27/09, `/ask` n'avait PAS de champ
   `model` → le choix était ignoré. Corrigé : `GET /models?profile=dataiku` donne la liste
   (id, libellé, tarif) ; envoyer `{"question": …, "profile": "dataiku", "model": "<id>"}` ;
   la réponse contient `model` = celui qui a vraiment répondu (à afficher pour vérifier).
2. **Backend Python de la Web App : modèle créé une seule fois** au chargement du module
   (`llm = project.get_llm(...)` en haut du fichier) → le choix n'est jamais relu. Le créer
   **à chaque requête**, à partir de la valeur envoyée par le front (liste blanche) :

   ```python
   # Backend Python d'une Web App Dataiku — NON TESTÉ sur l'instance, à adapter
   import dataiku
   from flask import request, jsonify

   MODELS = {
       "luna": "openai:challenge_llm:gpt-5.6-luna",
       "terra": "openai:challenge_llm:gpt-5.6-terra",
       "sol": "openai:challenge_llm:gpt-5.6-sol",
   }

   @app.route("/ask", methods=["POST"])
   def ask():
       body = request.get_json()
       model_id = MODELS.get(body.get("model"), MODELS["luna"])      # liste blanche
       llm = dataiku.api_client().get_default_project().get_llm(model_id)  # PAR requête
       completion = llm.new_completion()
       completion.with_message(body["prompt"])  # prompt = sources de la Knowledge Bank + question
       resp = completion.execute()
       return jsonify(text=resp.text, model=model_id)  # renvoyer le modèle utilisé
   ```
3. **Front de la Web App** : la valeur du `<select>` n'est pas lue au moment de l'envoi (lue une
   fois au chargement, ou champ absent du JSON envoyé). Vérifier dans l'onglet Réseau du
   navigateur que la requête contient bien `"model": "terra"` quand on choisit Terra.
