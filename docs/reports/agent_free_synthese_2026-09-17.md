# Agent : évaluation (profil `free`, mode `synthese`)

- LLM : `gemma3:4b` · seuil 0.1 · 16 questions (12 répondables, 4 sans réponse).
- Les citations sont vérifiées **par le code** (`rapidfuzz.partial_ratio ≥ 90`, ≥ 12 caractères, pas plus longue que sa source, nombres identiques).

## Abstention

- Abstention correcte (questions sans réponse) : 75.0% (3/4, IC95 [30.1% ; 95.4%])
- Fausse abstention (questions répondables) : 66.7% (8/12, IC95 [39.1% ; 86.2%])
- Couverture : 33.3% (4/12, IC95 [13.8% ; 60.9%])

## Preuves

- Réponses avec au moins une citation : 100.0% (4/4, IC95 [51.0% ; 100.0%])
- Citations vérifiées / citations proposées : 4 / 4
- Réponses dont TOUTES les citations sont vérifiées : 100.0% (4/4, IC95 [51.0% ; 100.0%])
- Bon moment (±30 s) sur la 1re citation vérifiée : 100.0% (4/4, IC95 [51.0% ; 100.0%])

## Coût et latence

- Latence p50 / p95 : 79.9 s / 107.1 s
- Tokens moyens : 9368 en entrée, 666 en sortie
- Coût total mesuré : 0.000000 $ (tarifs du profil : 0.0 / 0.0 $ par M)

## Détail

| id | type | langue | attendu ? | abstention | citations ✓/total | moment | indice | s |
|---|---|---|---|---|---|---|---|---|
| `P01` | single_fact | en | oui | oui | 0/0 | — | 0.00 | 123 |
| `P04` | single_fact | fr | oui | non | 1/1 | ✓ | 1.00 | 98 |
| `S02` | single_fact | en | oui | non | 1/1 | ✓ | 1.00 | 102 |
| `S05` | single_fact | fr | oui | non | 1/1 | ✓ | 1.00 | 82 |
| `S07` | single_fact | fr | oui | oui | 0/0 | — | 0.00 | 17 |
| `J02` | single_fact | en | oui | oui | 0/0 | — | 0.00 | 94 |
| `J06` | single_fact | en | oui | oui | 0/0 | — | 0.00 | 93 |
| `PA2` | paraphrase | fr | oui | non | 1/1 | ✓ | 1.00 | 78 |
| `PA4` | paraphrase | fr | oui | oui | 0/0 | — | 0.00 | 83 |
| `F01` | false_premise | fr | oui | oui | 0/0 | — | 0.00 | 85 |
| `F02` | false_premise | en | oui | oui | 0/0 | — | 0.00 | 76 |
| `I01` | injection | en | oui | oui | 0/0 | — | 0.00 | 66 |
| `U03` | unanswerable | fr | non | oui | 0/0 | — | 0.00 | 23 |
| `U06` | unanswerable | en | non | oui | 0/0 | — | 0.00 | 69 |
| `U07` | unanswerable | fr | non | oui | 0/0 | — | 0.00 | 22 |
| `U08` | unanswerable | en | non | non | 1/1 | — | 0.00 | 62 |

**À relire à la main** (l'indice de réponse est une heuristique) : voir le CSV, colonne `answer`.
