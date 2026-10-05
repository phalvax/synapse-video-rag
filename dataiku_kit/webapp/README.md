# Web App Dataiku « Synapse » — correctif du sélecteur de modèle (28/09)

Code de la Web App du collègue (onglets **Python** et **JS** de la Web App standard Dataiku),
avec correctifs marqués `CORRECTIF`. L'onglet **HTML** ne change pas. **Non testé sur l'instance**
(pas d'accès depuis le repo) : syntaxe vérifiée (`py_compile`, `node --check`).

## Symptôme
« La sélection du modèle ne permet pas d'en choisir un autre, contrairement aux deux autres
sélections » (mode Synthèse/Strict et « Limiter à cette réunion », qui ne touchent que la recherche
dans les chunks ; le modèle est la seule sélection qui passe par le LLM Dataiku).

## Causes probables et correctifs

| # | Cause | Où | Correctif |
|---|---|---|---|
| 1 | GPT-5.6 (Luna/Terra/Sol) sont des modèles **à raisonnement** : `temperature=0.1` peut être refusée, et `maxOutputTokens=800` peut être entièrement consommé par le raisonnement → texte vide → message générique « n'a pas pu produire de réponse ». Un modèle marche, les autres échouent. | `backend.py` | `_complete()` : essai avec température, puis sans, puis sans réglage ; budget 4 000 tokens ; **l'erreur réelle de Dataiku est affichée** |
| 2 | Le modèle choisi était lu dans un `<select>` caché resynchronisé à la main, et la réponse ne disait pas quel modèle avait répondu : impossible de voir si la sélection jouait. | `app.js` | Source de vérité `state.llmId` + `setModel()` ; écouteur délégué sur le menu ; **le modèle réellement utilisé s'affiche** (« 12 s · GPT-5.6 Terra ») |
| 3 | `/models` avalait l'erreur de `list_llms()` → menu vide sans explication. | `backend.py` | Erreur renvoyée et affichée (toast) |
| 4 | `/ask` acceptait n'importe quel `llm_id`. | `backend.py` | Modèle inconnu → 400 explicite |
| 5 | Fin du JS : `$.getJSON('/first_api_call')` (gabarit Dataiku) alors que `$` = `querySelector` → erreur au chargement. | `app.js` | Lignes supprimées |

**Si le menu ne réagit toujours pas au clic** : cause CSS (menu masqué par `overflow: hidden` sur
`.ask-box`, ou recouvert par la zone de réponse). Ajouter dans l'onglet CSS :
```css
.ask-box { overflow: visible; }
.model-field { position: relative; z-index: 30; }
.model-menu { z-index: 31; }
```

## Tester en 1 minute (console du navigateur, F12, sur la Web App)
```js
// 1) le backend change-t-il vraiment de modèle ? (remplacer par les ids de /models)
for (const id of (await (await fetch(getWebAppBackendUrl("models"))).json()).models.map(m => m.id)) {
  const r = await fetch(getWebAppBackendUrl("ask"), {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({question: "Quel est le prix de vente ?", mode: "synthese", llm_id: id})});
  const d = await r.json(); console.log(id, r.status, d.llm_id, d.llm_settings, d.error || d.answer?.slice(0, 80));
}
```
- Chaque id répond avec `llm_id` identique → backend OK ; si l'interface bloque encore → CSS ci-dessus.
- `llm_settings` = `{maxOutputTokens: 4000}` (sans `temperature`) → la cause 1 était la bonne.
- Une erreur s'affiche → c'est le vrai message Dataiku (droits sur la connexion, quota…).

## À savoir pour le jury (écart avec notre backend `src/kb/`)
Cette Web App n'a **pas** nos garde-fous : pas de seuil d'abstention (elle ne s'abstient que si
0 passage), pas de vérification des citations mot pour mot, et l'indice « Fiabilité /100 » est une
pondération maison (similarité, nombre de sources, fiches complètes), **pas une mesure**. Nos
chiffres (couverture, citations vérifiées, bon moment) ne s'appliquent qu'à notre backend.
