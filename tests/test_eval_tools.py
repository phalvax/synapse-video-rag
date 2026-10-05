import json

import pytest

from kb.eval.references import Cue, align_to_reference, parse_ted_page, reference_text
from kb.eval.retrieval import is_relevant, load_golden, random_hit_at_k
from kb.index.build import build_moments
from kb.schemas import Chunk, Segment


def _seg(i: int, start: float, text: str) -> Segment:
    return Segment(video_id="v", seg_id=i, start_s=start, end_s=start + 4, text=text)


def test_parse_ted_page_extracts_cues_in_order():
    data = {"props": {"paragraphs": [
        {"__typename": "Paragraph", "cues": [
            {"__typename": "Cue", "text": "second\nline", "time": 4200},
            {"__typename": "Cue", "text": "first", "time": 1000},
        ]},
    ]}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    assert parse_ted_page(html) == [Cue(1.0, "first"), Cue(4.2, "second line")]


def test_reference_text_drops_stage_directions():
    cues = [Cue(0, "Hello there."), Cue(5, "(Applause)"), Cue(9, "Too late")]
    assert reference_text(cues, until_s=8).split() == ["Hello", "there."]


def test_alignment_measures_constant_offset():
    cues = [Cue(4.2, "You have cancer and this is a long enough sentence"),
            Cue(30.0, "Exosomes are important biomarkers for early warning")]
    segs = [_seg(0, 16.4, "You have cancer and this is a long enough sentence."),
            _seg(1, 42.1, "Exosomes are important biomarkers for early warning systems")]
    al = align_to_reference(segs, cues)
    assert al.matches == 2
    assert al.offset_s == pytest.approx(12.15)
    assert al.median_abs_error_s == pytest.approx(0.05)


def test_random_baseline():
    assert random_hit_at_k(10, 1, 1) == pytest.approx(0.1)
    assert random_hit_at_k(10, 2, 5) == pytest.approx(1 - 10 / 45)  # 1 - C(8,5)/C(10,5)
    assert random_hit_at_k(3, 1, 5) == 1.0


def test_relevance_uses_video_and_time_span():
    ch = Chunk(chunk_id="c", video_id="v", start_s=100, end_s=220, text="…")
    assert is_relevant(ch, "v", 150) and is_relevant(ch, "v", 98)
    assert not is_relevant(ch, "v", 230) and not is_relevant(ch, "w", 150)


def test_moments_are_sliding_windows():
    moments = build_moments([_seg(i, i * 5, f"s{i}") for i in range(4)])
    assert len(moments) == 4
    assert moments[0].text == "s0 s1 s2" and moments[0].end_s == 14
    assert moments[-1].text == "s3"


def test_golden_set_is_well_formed():
    from kb.config import ROOT

    rows = load_golden(ROOT / "src" / "kb" / "eval" / "golden_set.jsonl")
    assert len({r["id"] for r in rows}) == len(rows)
    for r in rows:
        assert r["type"] in {"single_fact", "paraphrase", "cross_video", "aggregation",
                             "unanswerable", "false_premise", "injection"}
        if r["type"] in {"single_fact", "paraphrase", "false_premise", "injection"}:
            assert r["answerable"] and r["expected_video_id"] and r["expected_start_s"] is not None
        if r["type"] == "unanswerable":
            assert not r["answerable"] and r["expected_video_id"] is None


def test_other_golden_sets_do_not_overwrite_dashboard_reports():
    from kb.eval.retrieval import DEFAULT_GOLDEN, report_prefix

    assert report_prefix(DEFAULT_GOLDEN) == ""
    assert report_prefix(DEFAULT_GOLDEN.with_name("golden_ami.jsonl")) == "ami_"
