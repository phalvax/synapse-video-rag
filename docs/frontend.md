# Frontend (Evan — tâches FE-1, FE-2)

**État : FE-1 et FE-2 faits.** Stack livrée : **React + Vite + TypeScript + Tailwind v4**.
shadcn/ui et Recharts, prévus au départ, ont été laissés de côté (ponytail/YAGNI) :
Tailwind seul suffit pour 5 écrans simples, et la frontière coût-qualité tient en un petit
SVG inline (`Dashboard.tsx`) plutôt qu'une dépendance de graphes. À ajouter si le dashboard
grossit (plus de types de graphes, séries dynamiques).

```powershell
cd frontend
npm install
npm run dev      # http://localhost:5173 — proxy /api -> uvicorn kb.api.app:app (:8000)
```

**`src/api/client.ts` est entièrement branché sur le vrai backend** (`fetch`/`XMLHttpRequest`) —
plus aucun mock (`src/mocks/` supprimé le 20/09, plus rien ne s'en servait). Vérifié en
conditions réelles à deux reprises (18/09 et 20/09, Evan + Claude) : backend + front lancés
en local avec des données de test écrites dans `data/` (jamais commitées, nettoyées après
coup), vérifié dans un vrai navigateur (Playwright) :
- `GET /videos`, `GET /fiches`, `GET /videos/{id}/segments` : vraie vidéo, vraie fiche,
  vrai transcript horodaté s'affichent (plus `MOCK_TRANSCRIPTS`).
- `POST /ask` sans index construit : erreur 500 remontée proprement dans l'UI (bandeau
  rouge) au lieu d'échouer silencieusement.
- `GET /metrics` : vrais indicateurs mesurés + courbe risque-couverture (39 points réels,
  échantillonnés à 10 lignes pour rester lisible — `sampleCurve()`, `Dashboard.tsx`).
- `GET /tiers` : vrai rapport mesuré (`docs/reports/agent_free_synthese_2026-09-17.csv`,
  couverture 33 %, `gemma3:4b`) — pas une donnée inventée.

**Écrans :**
1. Recherche / chat (citations cliquables, badge de confiance, bascule strict/synthèse, sélecteur de palier, filtre client, erreurs affichées). Filtres mission/techno : pas dans l'UI — `Chunk` (schemas.py) n'a pas ces champs, seulement `client`/`date`, et étendre le contrat commun demande un accord d'équipe (règle du repo) ; `date` filtrable mais pas exposé (l'égalité stricte est peu utile en pratique).
2. Lecteur vidéo + transcript synchronisé, branché sur `GET /videos/{id}/segments` (vrai transcript, plus de mock) : un clic sur une citation (ou une fiche) ou une ligne de transcript fait `video.currentTime = start_s`.
3. Upload avec vraie progression (`XMLHttpRequest.upload.onprogress`) et polling réel de `GET /jobs/{id}` jusqu'à `done`/`failed`, erreurs du job affichées.
4. Fiches REX (liste filtrable par texte, branchée sur `GET /fiches`).
5. Dashboard KPI (8 indicateurs + frontière coût-qualité + courbe risque-couverture), branchée sur `GET /metrics` (`kb.eval.summary`) et `GET /tiers`. 3 des 8 indicateurs (faithfulness, hallucination, temps main-vs-outil) s'affichent honnêtement « non mesuré » : rien ne les calcule encore (juge LLM, chronométrage métier — décision consciente de ne pas les construire sans un choix de rubrique/modèle discuté d'abord, et CLAUDE.md section 8 demande un Kappa de Cohen juge/humain avant de leur faire confiance).

**Ce qui reste, et pourquoi ce n'est pas fait ici :**
- Juge de fidélité (faithfulness/hallucination) : demande un choix de modèle/rubrique et une validation humaine (Kappa de Cohen) — décision d'équipe, pas juste du câblage.
- Temps main-vs-outil : demande un vrai chronométrage humain.
- Filtres mission/techno : demande d'étendre `schemas.py` (accord d'équipe requis).

**Ne jamais mettre de clé API dans le front** : tout passe par le backend FastAPI (D9).
