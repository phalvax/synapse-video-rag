import pytest
from pydantic import ValidationError

from kb.schemas import Answer, Citation, Segment


def test_answer_with_citation_is_valid():
    ans = Answer(
        answer="Ajouter un cache devant la base.",
        confidence=0.8,
        citations=[Citation(chunk_id="c1", video_id="v1", start_s=754, quote="un cache Redis")],
    )
    assert ans.citations[0].verified is False  # la vérification est faite par le code


def test_abstention_cannot_carry_citations():
    with pytest.raises(ValidationError):
        Answer(
            not_found=True,
            citations=[Citation(chunk_id="c1", video_id="v1", start_s=0, quote="x")],
        )


def test_answer_needs_text_unless_not_found():
    with pytest.raises(ValidationError):
        Answer(answer=None, not_found=False)
    assert Answer(not_found=True).answer is None


def test_segment_times_must_be_ordered():
    with pytest.raises(ValidationError):
        Segment(video_id="v1", seg_id=0, start_s=10, end_s=5, text="…")
