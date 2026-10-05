# Recherche : évaluation sur `golden_ami.jsonl` (profil `free`)

- Question envoyée à la recherche : traduite en en (comme le produit).

- Corpus : 144 chunks. Questions répondables à cible unique : 14 ; sans réponse : 4.
- Embeddings : `bge-m3` · reranker : `BAAI/bge-reranker-v2-m3` · RRF k=60.
- Chaque proportion : valeur (succès/n, IC 95 % de Wilson). **Golden set rédigé par Claude à partir des transcripts, à relire par l'équipe.**
- Référence hasard : Hit@1 ≈ 1%, Hit@5 ≈ 5% (classement aléatoire, calculé).

## Ablation

| Mode | Hit@1 | Hit@5 | MRR@20 | Moment ±30 s (zoom) | Moment ±30 s (début de chunk) | Latence p50 / p95 |
|---|---|---|---|---|---|---|
| `dense` | 28.6% (4/14, IC95 [11.7% ; 54.6%]) | 78.6% (11/14, IC95 [52.4% ; 92.4%]) | 0.50 | 28.6% (4/14, IC95 [11.7% ; 54.6%]) | 14.3% (2/14, IC95 [4.0% ; 39.9%]) | 126 / 647 ms |
| `bm25` | 42.9% (6/14, IC95 [21.4% ; 67.4%]) | 64.3% (9/14, IC95 [38.8% ; 83.7%]) | 0.54 | 42.9% (6/14, IC95 [21.4% ; 67.4%]) | 0.0% (0/14, IC95 [0.0% ; 21.5%]) | 105 / 140 ms |
| `hybrid` | 28.6% (4/14, IC95 [11.7% ; 54.6%]) | 78.6% (11/14, IC95 [52.4% ; 92.4%]) | 0.53 | 14.3% (2/14, IC95 [4.0% ; 39.9%]) | 7.1% (1/14, IC95 [1.3% ; 31.5%]) | 107 / 208 ms |
| `hybrid_rerank` | 71.4% (10/14, IC95 [45.4% ; 88.3%]) | 85.7% (12/14, IC95 [60.1% ; 96.0%]) | 0.77 | 50.0% (7/14, IC95 [26.8% ; 73.2%]) | 14.3% (2/14, IC95 [4.0% ; 39.9%]) | 20154 / 30600 ms |

## Par langue de la question (Hit@5)

| Mode | FR | EN |
|---|---|---|
| `dense` | 62.5% (5/8, IC95 [30.6% ; 86.3%]) | 100.0% (6/6, IC95 [61.0% ; 100.0%]) |
| `bm25` | 62.5% (5/8, IC95 [30.6% ; 86.3%]) | 66.7% (4/6, IC95 [30.0% ; 90.3%]) |
| `hybrid` | 62.5% (5/8, IC95 [30.6% ; 86.3%]) | 100.0% (6/6, IC95 [61.0% ; 100.0%]) |
| `hybrid_rerank` | 75.0% (6/8, IC95 [40.9% ; 92.9%]) | 100.0% (6/6, IC95 [61.0% ; 100.0%]) |

## Abstention (mode `hybrid_rerank`, seuil actuel 0.1 sur le score du reranker)

- Abstention correcte (questions sans réponse) : 100.0% (4/4, IC95 [51.0% ; 100.0%])
- Fausse abstention (questions répondables) : 14.3% (2/14, IC95 [4.0% ; 39.9%])
- Couverture : 85.7% (12/14, IC95 [60.1% ; 96.0%])
- Exactitude sélective (Hit@1 parmi les réponses données) : 75.0% (9/12, IC95 [46.8% ; 91.1%])

Scores du reranker : répondables min 0.09 / médiane 0.67 ; sans réponse médiane 0.02 / max 0.03.

### Courbe risque-couverture

Répondre si score ≥ seuil. Risque = part des réponses données qui sont fausses (mauvais passage en tête, ou question sans réponse).

| Seuil | Couverture | Risque | Abstention correcte | Fausse abstention |
|---|---|---|---|---|
| 0.988 | 6% | 0% | 4/4 | 13/14 |
| 0.980 | 11% | 0% | 4/4 | 12/14 |
| 0.919 | 17% | 0% | 4/4 | 11/14 |
| 0.913 | 22% | 0% | 4/4 | 10/14 |
| 0.856 | 28% | 20% | 4/4 | 9/14 |
| 0.828 | 33% | 17% | 4/4 | 8/14 |
| 0.716 | 39% | 29% | 4/4 | 7/14 |
| 0.620 | 44% | 25% | 4/4 | 6/14 |
| 0.619 | 50% | 22% | 4/4 | 5/14 |
| 0.579 | 56% | 20% | 4/4 | 4/14 |
| 0.555 | 61% | 18% | 4/4 | 3/14 |
| 0.196 | 67% | 25% | 4/4 | 2/14 |
| 0.098 | 72% | 31% | 4/4 | 1/14 |
| 0.095 | 78% | 29% | 4/4 | 0/14 |
| 0.032 | 83% | 33% | 3/4 | 0/14 |
| 0.026 | 89% | 38% | 2/4 | 0/14 |
| 0.011 | 94% | 41% | 1/4 | 0/14 |
| 0.000 | 100% | 44% | 0/4 | 0/14 |

## Échecs (mode `hybrid_rerank`, Hit@1 raté)

- `M05` (single_fact, fr) → top-1 : ami_es2002b, score 0.72
- `M06` (single_fact, en) → top-1 : ami_es2002d, score 0.86
- `M09` (single_fact, fr) → top-1 : ami_es2004b, score 0.20
- `M14` (false_premise, fr) → top-1 : ami_es2004d, score 0.10
