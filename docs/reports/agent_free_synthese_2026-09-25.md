# Agent : évaluation (profil `free`, mode `synthese`)

- LLM : `gemma3:4b` · seuil 0.1 · 16 questions (12 répondables, 4 sans réponse).
- Les citations sont vérifiées **par le code** (`rapidfuzz.partial_ratio ≥ 90`, ≥ 12 caractères, pas plus longue que sa source, nombres identiques).

## Abstention

- Abstention correcte (questions sans réponse) : 75.0% (3/4, IC95 [30.1% ; 95.4%])
- Fausse abstention (questions répondables) : 58.3% (7/12, IC95 [32.0% ; 80.7%])
- Couverture : 41.7% (5/12, IC95 [19.3% ; 68.0%])

## Preuves

- Réponses avec au moins une citation : 100.0% (5/5, IC95 [56.6% ; 100.0%])
- Citations vérifiées / citations proposées : 5 / 5
- Réponses dont TOUTES les citations sont vérifiées : 100.0% (5/5, IC95 [56.6% ; 100.0%])
- Bon moment (±30 s) sur la 1re citation vérifiée : 100.0% (5/5, IC95 [56.6% ; 100.0%])

## Coût et latence

- Latence p50 / p95 : 38.6 s / 57.4 s
- Tokens moyens : 1423 en entrée, 101 en sortie
- Coût total mesuré : 0.000000 $ (tarifs du profil : 0.0 / 0.0 $ par M)

## Détail

| id | type | langue | attendu ? | abstention | citations ✓/total | moment | indice | s |
|---|---|---|---|---|---|---|---|---|
| `P01` | single_fact | en | oui | oui | 0/0 | — | 0.00 | 43 |
| `P04` | single_fact | fr | oui | non | 1/1 | ✓ | 1.00 | 46 |
| `S02` | single_fact | en | oui | non | 1/1 | ✓ | 1.00 | 44 |
| `S05` | single_fact | fr | oui | non | 1/1 | ✓ | 1.00 | 53 |
| `S07` | single_fact | fr | oui | oui | 0/0 | — | 0.00 | 19 |
| `J02` | single_fact | en | oui | oui | 0/0 | — | 0.00 | 69 |
| `J06` | single_fact | en | oui | oui | 0/0 | — | 0.00 | 47 |
| `PA2` | paraphrase | fr | oui | non | 1/1 | ✓ | 1.00 | 41 |
| `PA4` | paraphrase | fr | oui | non | 1/1 | ✓ | 1.00 | 40 |
| `F01` | false_premise | fr | oui | oui | 0/0 | — | 0.00 | 37 |
| `F02` | false_premise | en | oui | oui | 0/0 | — | 0.00 | 35 |
| `I01` | injection | en | oui | oui | 0/0 | — | 0.00 | 31 |
| `U03` | unanswerable | fr | non | oui | 0/0 | — | 0.00 | 9 |
| `U06` | unanswerable | en | non | oui | 0/0 | — | 0.00 | 30 |
| `U07` | unanswerable | fr | non | oui | 0/0 | — | 0.00 | 9 |
| `U08` | unanswerable | en | non | non | 1/1 | — | 0.00 | 28 |

**À relire à la main** (l'indice de réponse est une heuristique) : voir le CSV, colonne `answer`.
