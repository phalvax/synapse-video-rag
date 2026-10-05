"""Tests de L1 Structuration SANS réseau ni modèle (LLM et SQLite en mémoire/temp)."""

from kb.schemas import Segment, Video
from kb.structure.extract import extract_fiches
from kb.structure.store import query_fiches, save_fiches

VIDEO = Video(video_id="v1", title="Migration Redis", source_uri="v1.wav", duration_s=600.0)
SEGMENTS = [
    Segment(video_id="v1", seg_id=0, start_s=10.0, end_s=20.0,
            text="Nous avons eu un problème de cache Redis qui saturait la mémoire."),
    Segment(video_id="v1", seg_id=1, start_s=20.0, end_s=35.0,
            text="La solution a été de passer en éviction LRU avec une taille maximale."),
]
TRANSCRIPT = " ".join(s.text for s in SEGMENTS)


class FakeLLM:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls = 0

    def complete(self, messages, json_schema=None, temperature=None):
        self.calls += 1
        return self.replies.pop(0) if self.replies else "{}"


def test_extract_keeps_fiche_with_verified_quote():
    llm = FakeLLM('{"fiches": [{"problem": "Cache Redis saturé", '
                  '"solution": "Éviction LRU avec taille maximale", '
                  '"technologies": ["Redis"], "client": null, "author": null, '
                  '"start_s": 10, "end_s": 35, '
                  '"evidence_quote": "problème de cache Redis qui saturait la mémoire"}]}')
    fiches = extract_fiches(VIDEO, SEGMENTS, llm)
    assert len(fiches) == 1
    f = fiches[0]
    assert f.fiche_id == "v1__01" and f.video_id == "v1"
    assert f.technologies == ["Redis"]
    assert "Redis" in f.evidence_quote  # citation recalée sur le transcript exact


def test_extract_drops_fiche_with_invented_quote():
    llm = FakeLLM('{"fiches": [{"problem": "Panne", "start_s": 0, "end_s": 10, '
                  '"evidence_quote": "un passage qui n\'existe nulle part dans la source"}]}')
    assert extract_fiches(VIDEO, SEGMENTS, llm) == []


def test_extract_empty_when_llm_finds_nothing():
    llm = FakeLLM('{"fiches": []}')
    assert extract_fiches(VIDEO, SEGMENTS, llm) == []


def test_extract_retries_once_on_invalid_json_then_gives_up():
    llm = FakeLLM("pas du json", "toujours pas du json")
    assert extract_fiches(VIDEO, SEGMENTS, llm) == []
    assert llm.calls == 2


def test_extract_retry_succeeds_on_second_attempt():
    llm = FakeLLM("pas du json", '{"fiches": [{"problem": "Cache Redis saturé", '
                  '"start_s": 10, "end_s": 35, '
                  '"evidence_quote": "saturait la mémoire"}]}')
    fiches = extract_fiches(VIDEO, SEGMENTS, llm)
    assert len(fiches) == 1 and llm.calls == 2


def test_extract_no_segments_skips_llm_call():
    llm = FakeLLM('{"fiches": []}')
    assert extract_fiches(VIDEO, [], llm) == [] and llm.calls == 0


def test_store_round_trip_and_filters(tmp_path):
    db = tmp_path / "kb.sqlite"
    llm = FakeLLM('{"fiches": [{"problem": "Cache Redis saturé", '
                  '"solution": "Éviction LRU", "technologies": ["Redis"], '
                  '"client": "Synchrone", "start_s": 10, "end_s": 35, '
                  '"evidence_quote": "problème de cache Redis qui saturait la mémoire"}]}')
    fiches = extract_fiches(VIDEO, SEGMENTS, llm)
    save_fiches(db, "v1", fiches)

    assert len(query_fiches(db, video_id="v1")) == 1
    assert len(query_fiches(db, client="Synchrone")) == 1
    assert len(query_fiches(db, client="Autre Client")) == 0
    assert len(query_fiches(db, technology="Redis")) == 1
    assert len(query_fiches(db, technology="Kubernetes")) == 0
    assert len(query_fiches(db, text="cache")) == 1
    assert len(query_fiches(db, text="introuvable")) == 0


def test_save_fiches_is_idempotent_per_video(tmp_path):
    db = tmp_path / "kb.sqlite"
    llm = FakeLLM('{"fiches": [{"problem": "Cache Redis saturé", "start_s": 10, "end_s": 35, '
                  '"evidence_quote": "problème de cache Redis qui saturait la mémoire"}]}')
    fiches = extract_fiches(VIDEO, SEGMENTS, llm)
    save_fiches(db, "v1", fiches)
    save_fiches(db, "v1", fiches)  # ré-extraction : ne doit pas dupliquer
    assert len(query_fiches(db, video_id="v1")) == 1


def test_query_fiches_on_missing_db_returns_empty(tmp_path):
    assert query_fiches(tmp_path / "absent.sqlite") == []
