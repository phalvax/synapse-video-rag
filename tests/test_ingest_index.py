from pathlib import Path

import pytest

from kb.index.chunking import chunk_segments, fmt_ts
from kb.index.fusion import rrf
from kb.ingest.sources import discover_media, slugify
from kb.schemas import Segment, Video

VIDEO = Video(video_id="v1", title="Cache Redis", source_uri="v1.wav", duration_s=100)


def _segments(n: int, words: int = 10) -> list[Segment]:
    return [
        Segment(video_id="v1", seg_id=i, start_s=i * 5, end_s=i * 5 + 5,
                text=" ".join([f"mot{i}"] * words))
        for i in range(n)
    ]


def test_discover_groups_parts_in_order(tmp_path: Path):
    for name in ("talk_seg02.wav", "talk_seg01.wav", "other.mp4", "notes.txt", "talk_seg10.wav"):
        (tmp_path / name).write_bytes(b"")
    groups = {g.video_id: g for g in discover_media(tmp_path)}
    assert set(groups) == {"talk", "other"}
    assert [p.name for p in groups["talk"].parts] == [
        "talk_seg01.wav", "talk_seg02.wav", "talk_seg10.wav"
    ]


def test_slugify():
    assert slugify("Joy Buolamwini — Bias!") == "joy_buolamwini_bias"


def test_chunks_cover_all_segments_with_overlap():
    segs = _segments(10)  # 13 tokens estimés par segment
    chunks = chunk_segments(segs, VIDEO, target_tokens=40, overlap_segments=1)
    assert [c.chunk_id for c in chunks][:2] == ["v1__000", "v1__001"]
    assert chunks[0].start_s == 0 and chunks[-1].end_s == 50
    # chevauchement : le dernier segment d'un chunk ouvre le suivant
    assert chunks[1].start_s == chunks[0].end_s - 5
    assert "mot9" in chunks[-1].text
    assert "Cache Redis" in chunks[0].context_header


def test_chunking_always_progresses_with_big_overlap():
    chunks = chunk_segments(_segments(5, words=100), VIDEO, target_tokens=10, overlap_segments=3)
    assert len(chunks) == 5


def test_rrf_rewards_agreement():
    fused = dict(rrf([["a", "b", "c"], ["b", "c", "a"]], k=60))
    assert max(fused, key=fused.get) == "b"
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_fmt_ts():
    assert fmt_ts(754) == "12:34"
    assert fmt_ts(3725) == "1:02:05"


def test_filters_match_on_chunk_fields():
    from kb.index.search import matches
    from kb.schemas import Chunk

    c = Chunk(chunk_id="v__000", video_id="v", start_s=0, end_s=60, context_header="",
              text="t", client="ACME")
    assert matches(c, None) and matches(c, {}) and matches(c, {"client": "ACME"})
    assert matches(c, {"client": "ACME", "video_id": "v"})
    assert not matches(c, {"client": "Other"}) and not matches(c, {"video_id": "w"})


def test_chroma_where_uses_and_for_several_filters():
    from kb.adapters.vs_chroma import _where

    assert _where(None) is None and _where({}) is None
    assert _where({"client": "ACME"}) == {"client": "ACME"}
    assert _where({"client": "ACME", "video_id": "v"}) == {
        "$and": [{"client": "ACME"}, {"video_id": "v"}]}


def test_list_filter_means_one_of():
    from kb.adapters.vs_chroma import _where
    from kb.index.search import matches
    from kb.schemas import Chunk

    c = Chunk(chunk_id="a__1", video_id="a", start_s=0, end_s=1, context_header="", text="t")
    assert matches(c, {"video_id": ["a", "b"]}) and not matches(c, {"video_id": ["b"]})
    assert _where({"video_id": ["a", "b"]}) == {"video_id": {"$in": ["a", "b"]}}
