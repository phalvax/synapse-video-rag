# Agent : évaluation (profil `free`, mode `synthese`)

- LLM : `gemma3:4b` · seuil 0.1 · 20 questions (16 répondables, 4 sans réponse).
- Les citations sont vérifiées **par le code** (`rapidfuzz.partial_ratio ≥ 90`, ≥ 12 caractères, pas plus longue que sa source, nombres identiques).

## Abstention

- Abstention correcte (questions sans réponse) : 100.0% (4/4, IC95 [51.0% ; 100.0%])
- Fausse abstention (questions répondables) : 18.8% (3/16, IC95 [6.6% ; 43.0%])
- Couverture : 81.2% (13/16, IC95 [57.0% ; 93.4%])

## Preuves

- Réponses avec au moins une citation : 100.0% (13/13, IC95 [77.2% ; 100.0%])
- Citations vérifiées / citations proposées : 20 / 20
- Réponses dont TOUTES les citations sont vérifiées : 100.0% (13/13, IC95 [77.2% ; 100.0%])
- Bon moment (±30 s) sur la 1re citation vérifiée : 53.8% (7/13, IC95 [29.1% ; 76.8%])
  - avec l'ancienne règle (moment le plus proche de la question, mêmes réponses) : 46.2% (6/13, IC95 [23.2% ; 70.9%])

## Coût et latence

- Latence p50 / p95 : 57.1 s / 73.6 s
- Tokens moyens : 1411 en entrée, 101 en sortie
- Coût total mesuré : 0.000000 $ (tarifs du profil : 0.0 / 0.0 $ par M)

## Détail

| id | type | langue | attendu ? | abstention | citations ✓/total | moment | indice | s |
|---|---|---|---|---|---|---|---|---|
| `M01` | single_fact | en | oui | non | 1/1 | ✓ | 1.00 | 82 |
| `M02` | single_fact | fr | oui | non | 1/1 | ✓ | 0.17 | 52 |
| `M03` | single_fact | en | oui | oui | 0/0 | — | 0.00 | 27 |
| `M04` | single_fact | fr | oui | non | 1/1 | ✓ | 0.00 | 67 |
| `M05` | single_fact | fr | oui | non | 2/2 | — | 0.67 | 67 |
| `M06` | single_fact | en | oui | non | 1/1 | — | 0.00 | 50 |
| `M07` | single_fact | fr | oui | non | 1/1 | ✓ | 0.00 | 58 |
| `M08` | single_fact | en | oui | non | 1/1 | ✓ | 1.00 | 71 |
| `M09` | single_fact | fr | oui | non | 1/1 | — | 0.00 | 56 |
| `M10` | single_fact | en | oui | non | 3/3 | ✓ | 0.00 | 63 |
| `M11` | single_fact | fr | oui | non | 1/1 | ✓ | 0.00 | 73 |
| `M12` | single_fact | en | oui | non | 4/4 | — | 0.00 | 64 |
| `M13` | paraphrase | fr | oui | non | 1/1 | — | 1.00 | 60 |
| `M14` | false_premise | fr | oui | oui | 0/0 | — | 0.00 | 20 |
| `M15` | cross_video | en | oui | non | 2/2 | — | 0.00 | 61 |
| `M16` | cross_video | fr | oui | oui | 0/0 | — | 0.00 | 19 |
| `MU1` | unanswerable | en | non | oui | 0/0 | — | 0.00 | 18 |
| `MU2` | unanswerable | fr | non | oui | 0/0 | — | 0.00 | 22 |
| `MU3` | unanswerable | en | non | oui | 0/0 | — | 0.00 | 19 |
| `MU4` | unanswerable | fr | non | oui | 0/0 | — | 0.00 | 16 |

**À relire à la main** (l'indice de réponse est une heuristique) : voir le CSV, colonne `answer`.
