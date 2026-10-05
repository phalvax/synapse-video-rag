# Recherche : évaluation sur le golden set v0 (profil `free`)

- Corpus : 13 chunks. Questions répondables à cible unique : 31 ; sans réponse : 8.
- Embeddings : `bge-m3` · reranker : `BAAI/bge-reranker-v2-m3` · RRF k=60.
- Chaque proportion : valeur (succès/n, IC 95 % de Wilson). **Golden set rédigé par Claude à partir des transcripts, à relire par l'équipe.**
- Référence hasard : Hit@1 ≈ 8%, Hit@5 ≈ 41% (classement aléatoire, calculé).

## Ablation

| Mode | Hit@1 | Hit@5 | MRR@20 | Moment ±30 s (zoom) | Moment ±30 s (début de chunk) | Latence p50 / p95 |
|---|---|---|---|---|---|---|
| `dense` | 83.9% (26/31, IC95 [67.4% ; 92.9%]) | 100.0% (31/31, IC95 [89.0% ; 100.0%]) | 0.91 | 80.6% (25/31, IC95 [63.7% ; 90.8%]) | 32.3% (10/31, IC95 [18.6% ; 49.9%]) | 166 / 224 ms |
| `bm25` | 80.6% (25/31, IC95 [63.7% ; 90.8%]) | 90.3% (28/31, IC95 [75.1% ; 96.7%]) | 0.85 | 74.2% (23/31, IC95 [56.8% ; 86.3%]) | 25.8% (8/31, IC95 [13.7% ; 43.2%]) | 165 / 206 ms |
| `hybrid` | 83.9% (26/31, IC95 [67.4% ; 92.9%]) | 100.0% (31/31, IC95 [89.0% ; 100.0%]) | 0.91 | 77.4% (24/31, IC95 [60.2% ; 88.6%]) | 38.7% (12/31, IC95 [23.7% ; 56.2%]) | 163 / 205 ms |
| `hybrid_rerank` | 96.8% (30/31, IC95 [83.8% ; 99.4%]) | 100.0% (31/31, IC95 [89.0% ; 100.0%]) | 0.98 | 93.5% (29/31, IC95 [79.3% ; 98.2%]) | 32.3% (10/31, IC95 [18.6% ; 49.9%]) | 16776 / 18063 ms |

## Par langue de la question (Hit@5)

| Mode | FR | EN |
|---|---|---|
| `dense` | 100.0% (16/16, IC95 [80.6% ; 100.0%]) | 100.0% (15/15, IC95 [79.6% ; 100.0%]) |
| `bm25` | 81.2% (13/16, IC95 [57.0% ; 93.4%]) | 100.0% (15/15, IC95 [79.6% ; 100.0%]) |
| `hybrid` | 100.0% (16/16, IC95 [80.6% ; 100.0%]) | 100.0% (15/15, IC95 [79.6% ; 100.0%]) |
| `hybrid_rerank` | 100.0% (16/16, IC95 [80.6% ; 100.0%]) | 100.0% (15/15, IC95 [79.6% ; 100.0%]) |

## Abstention (mode `hybrid_rerank`, seuil actuel 0.35 sur le score du reranker)

- Abstention correcte (questions sans réponse) : 75.0% (6/8, IC95 [40.9% ; 92.9%])
- Fausse abstention (questions répondables) : 32.3% (10/31, IC95 [18.6% ; 49.9%])
- Couverture : 67.7% (21/31, IC95 [50.1% ; 81.4%])
- Exactitude sélective (Hit@1 parmi les réponses données) : 100.0% (21/21, IC95 [84.5% ; 100.0%])

Scores du reranker : répondables min 0.00 / médiane 0.69 ; sans réponse médiane 0.02 / max 0.92.

### Courbe risque-couverture

Répondre si score ≥ seuil. Risque = part des réponses données qui sont fausses (mauvais passage en tête, ou question sans réponse).

| Seuil | Couverture | Risque | Abstention correcte | Fausse abstention |
|---|---|---|---|---|
| 0.999 | 3% | 0% | 8/8 | 30/31 |
| 0.987 | 5% | 0% | 8/8 | 29/31 |
| 0.981 | 8% | 0% | 8/8 | 28/31 |
| 0.979 | 10% | 0% | 8/8 | 27/31 |
| 0.971 | 13% | 0% | 8/8 | 26/31 |
| 0.963 | 15% | 0% | 8/8 | 25/31 |
| 0.961 | 18% | 0% | 8/8 | 24/31 |
| 0.939 | 21% | 0% | 8/8 | 23/31 |
| 0.920 | 23% | 11% | 7/8 | 23/31 |
| 0.911 | 26% | 10% | 7/8 | 22/31 |
| 0.898 | 28% | 9% | 7/8 | 21/31 |
| 0.884 | 31% | 8% | 7/8 | 20/31 |
| 0.872 | 33% | 15% | 6/8 | 20/31 |
| 0.819 | 36% | 14% | 6/8 | 19/31 |
| 0.786 | 38% | 13% | 6/8 | 18/31 |
| 0.741 | 41% | 12% | 6/8 | 17/31 |
| 0.730 | 44% | 12% | 6/8 | 16/31 |
| 0.692 | 46% | 11% | 6/8 | 15/31 |
| 0.610 | 49% | 11% | 6/8 | 14/31 |
| 0.505 | 51% | 10% | 6/8 | 13/31 |
| 0.452 | 54% | 10% | 6/8 | 12/31 |
| 0.377 | 56% | 9% | 6/8 | 11/31 |
| 0.361 | 59% | 9% | 6/8 | 10/31 |
| 0.269 | 62% | 8% | 6/8 | 9/31 |
| 0.221 | 64% | 8% | 6/8 | 8/31 |
| 0.178 | 67% | 8% | 6/8 | 7/31 |
| 0.126 | 69% | 7% | 6/8 | 6/31 |
| 0.111 | 72% | 7% | 6/8 | 5/31 |
| 0.108 | 74% | 7% | 6/8 | 4/31 |
| 0.097 | 77% | 7% | 6/8 | 3/31 |
| 0.051 | 79% | 10% | 5/8 | 3/31 |
| 0.027 | 82% | 9% | 5/8 | 2/31 |
| 0.025 | 85% | 12% | 4/8 | 2/31 |
| 0.024 | 87% | 15% | 3/8 | 2/31 |
| 0.009 | 90% | 17% | 3/8 | 1/31 |
| 0.008 | 92% | 19% | 2/8 | 1/31 |
| 0.002 | 95% | 22% | 1/8 | 1/31 |
| 0.001 | 97% | 21% | 1/8 | 0/31 |
| 0.000 | 100% | 23% | 0/8 | 0/31 |

## Échecs (mode `hybrid_rerank`, Hit@1 raté)

- `S07` (single_fact, fr) → top-1 : joshua_smith_new_nanotech_to_catch_cancer_early, score 0.01
