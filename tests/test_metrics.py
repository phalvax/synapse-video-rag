import pytest

from kb.eval.metrics import (
    abstention_report,
    cost_usd,
    faithfulness,
    field_precision_recall_f1,
    hallucination_rate,
    hit_at_k,
    mean,
    moment_hit,
    null_correctness,
    percentile,
    rate,
    recall_at_k,
    reciprocal_rank,
    risk_coverage_curve,
    timestamp_hit,
    wilson_interval,
    word_error_rate,
)


def test_recall_and_hit_at_k():
    ranked = ["c3", "c1", "c7", "c2"]
    assert recall_at_k(ranked, {"c1", "c2"}, k=2) == 0.5
    assert hit_at_k(ranked, {"c7"}, k=3)
    assert not hit_at_k(ranked, {"c2"}, k=3)


def test_reciprocal_rank_and_mean():
    assert reciprocal_rank(["a", "b", "c"], {"c"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(["a"], {"z"}) == 0.0
    assert mean([1.0, 0.5, 0.0]) == pytest.approx(0.5)


def test_timestamp_tolerance():
    assert timestamp_hit(754, 780)
    assert not timestamp_hit(754, 800)


def test_moment_needs_right_video_and_time():
    assert moment_hit("v1", 754, "v1", 780)
    assert not moment_hit("v2", 754, "v1", 780)
    assert not moment_hit("v1", None, "v1", 780)


def test_wilson_matches_reference_values():
    low, high = wilson_interval(45, 50)
    assert low == pytest.approx(0.786, abs=1e-3)
    assert high == pytest.approx(0.957, abs=1e-3)
    low0, high0 = wilson_interval(0, 50)
    assert low0 == 0.0
    assert high0 == pytest.approx(0.071, abs=1e-3)


def test_rate_formats_value_and_interval():
    r = rate([True] * 45 + [False] * 5)
    assert r.value == 0.9
    assert str(r) == "90.0% (45/50, IC95 [78.6% ; 95.7%])"
    assert str(rate([])) == "n/a (n=0)"


def test_wer_counts_substitution_deletion_insertion():
    assert word_error_rate("le cache Redis", "le cache Redis") == 0.0
    assert word_error_rate("le cache Redis", "Le cache, Redis !") == 0.0  # normalisation
    assert word_error_rate("le cache Redis", "le cash Redis") == pytest.approx(1 / 3)
    assert word_error_rate("le cache Redis", "le Redis") == pytest.approx(1 / 3)
    assert word_error_rate("le cache Redis", "le gros cache Redis") == pytest.approx(1 / 3)


def test_faithfulness_and_hallucination_rate():
    assert faithfulness(3, 4) == 0.75
    r = hallucination_rate([0, 0, 2, 0])  # une réponse sur 4 contient une invention
    assert (r.successes, r.n) == (1, 4)


def test_abstention_report():
    answerable = [True, True, True, False, False]
    abstained = [False, False, True, True, False]
    correct = [True, False, False, False, False]
    rep = abstention_report(answerable, abstained, correct)
    assert (rep.correct_abstention.successes, rep.correct_abstention.n) == (1, 2)
    assert (rep.false_abstention.successes, rep.false_abstention.n) == (1, 3)
    assert (rep.coverage.successes, rep.coverage.n) == (2, 3)
    assert (rep.selective_accuracy.successes, rep.selective_accuracy.n) == (1, 2)


def test_risk_coverage_curve_trades_coverage_for_risk():
    curve = risk_coverage_curve([0.9, 0.8, 0.3, 0.2], [True, True, False, True])
    assert curve[0] == (0.9, 0.25, 0.0)
    assert curve[1] == (0.8, 0.5, 0.0)
    assert curve[-1] == pytest.approx((0.2, 1.0, 0.25))


def test_percentile_and_cost():
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([1, 2, 3, 4, 5], 95) == pytest.approx(4.8)
    # Luna : 8 000 tokens en entrée + 500 en sortie à 0,2 / 1,2 $/M
    assert cost_usd(8_000, 500, 0.2, 1.2) == pytest.approx(0.0022)


def test_field_prf1_counts_extra_and_missed_values():
    # extrait "Redis" attendu "Redis" (ok) ; extrait "Kafka" attendu None (bruit, en trop) ;
    # extrait None attendu "Docker" (raté) ; les deux None sont hors calcul P/R.
    pairs = [("Redis", "Redis"), ("Kafka", None), (None, "Docker"), (None, None)]
    precision, recall, f1 = field_precision_recall_f1(pairs, fuzzy=False)
    assert (precision.successes, precision.n) == (1, 2)  # 1 correct / 2 extraits non nuls
    assert (recall.successes, recall.n) == (1, 2)  # 1 correct / 2 attendus non nuls
    assert f1 == pytest.approx(0.5)


def test_field_prf1_fuzzy_matches_near_identical_text():
    pairs = [("Éviction LRU avec taille max.", "Éviction LRU avec taille maximale")]
    precision, _, _ = field_precision_recall_f1(pairs, fuzzy=True)
    assert precision.successes == 1
    precision_strict, _, _ = field_precision_recall_f1(pairs, fuzzy=False)
    assert precision_strict.successes == 0


def test_field_prf1_all_null_pairs_are_undefined_not_wrong():
    precision, recall, f1 = field_precision_recall_f1([(None, None), (None, None)])
    assert precision.n == 0 and recall.n == 0 and f1 == 0.0


def test_null_correctness_only_scores_expected_nulls():
    # attendu None deux fois (une bien laissée vide, une bruitée) ; le 3e n'attend pas None.
    pairs = [(None, None), ("bruit", None), ("Redis", "Redis")]
    nc = null_correctness(pairs)
    assert (nc.successes, nc.n) == (1, 2)
