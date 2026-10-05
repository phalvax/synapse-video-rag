"""Import enrichi SANS réseau ni modèle : formulaire, doublons, index incrémental, dates."""

import datetime as dt
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

import kb.api.app as api
import kb.index.build as build
from kb.adapters.openai_compat import Usage
from kb.config import load_settings
from kb.ingest.dedup import containment, file_sha256, find_near_duplicate, shingles
from kb.ingest.metadata import UploadMeta, apply_meta, load_meta
from kb.jsonl import read_jsonl, write_jsonl
from kb.schemas import Chunk, Segment, Video

MEETING = ("okay so according to the brief we are going to be selling this remote control "
           "for twenty five euro and we are aiming to make fifty million euro on an "
           "international scale and we do not want it to cost more than twelve fifty")


# --- Formulaire d'import -----------------------------------------------------------------------


def test_upload_meta_blank_fields_and_language():
    m = UploadMeta(title="  ", author="Laura", date="2026-09-12", language="auto")
    assert m.title is None and m.author == "Laura" and m.date == dt.date(2026, 9, 12)
    assert m.language is None  # « auto » = détection par Whisper
    assert UploadMeta(language="fr").language == "fr"
    with pytest.raises(ValueError):
        UploadMeta(language="klingon")


def test_apply_meta_overrides_only_filled_fields():
    v = Video(video_id="r1", title="R1", source_uri="r1.wav", duration_s=60, language="en")
    out = apply_meta(v, UploadMeta(title="Réunion de lancement", mission="ES2002"))
    assert (out.title, out.mission, out.language, out.author) == (
        "Réunion de lancement", "ES2002", "en", None)
    assert apply_meta(v, None) is v


def test_context_header_carries_the_form_metadata():
    from kb.index.chunking import context_header

    v = Video(video_id="r1", title="Lancement", source_uri="r1.wav", duration_s=60,
              mission="ES2002", author="Laura", date=dt.date(2026, 9, 12),
              description="Kick-off du projet télécommande " + "très " * 60 + "long")
    h = context_header(v, 0, 30)
    assert "Mission : ES2002" in h and "Auteur : Laura" in h and "Date : 2026-09-12" in h
    assert h.endswith("…") and len(h) < 300  # description tronquée


# --- Doublons ----------------------------------------------------------------------------------


def test_near_duplicate_is_found_and_different_content_is_not():
    other = "we talked about rubber buttons and a kinetic charger for the remote " * 3
    found = find_near_duplicate(MEETING.upper() + " !", {"a": MEETING, "b": other})
    assert found is not None and found[0] == "a" and found[1] == 1.0  # casse/ponctuation ignorées
    assert find_near_duplicate(other, {"a": MEETING}) is None


def test_an_extract_of_an_existing_meeting_is_contained():
    extract = " ".join(MEETING.split()[5:25])
    assert containment(shingles(extract), shingles(MEETING)) == 1.0
    assert containment(set(), shingles(MEETING)) == 0.0


def test_file_hash_is_content_based(tmp_path):
    a, b, c = tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "c.wav"
    a.write_bytes(b"RIFF same")
    b.write_bytes(b"RIFF same")
    c.write_bytes(b"RIFF other")
    assert file_sha256(a) == file_sha256(b) != file_sha256(c)


# --- API d'import ------------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = load_settings("free")
    s.data_dir = tmp_path
    monkeypatch.setattr(api, "load_settings", lambda profile=None: s)
    monkeypatch.setattr(api, "run_in_background", lambda *a: None)
    return s


@pytest.fixture
def client(settings):
    return TestClient(api.app)


def test_upload_saves_the_form(client, settings):
    resp = client.post("/videos", files={"file": ("Kickoff_ES2002.wav", b"audio", "audio/wav")},
                       data={"title": "Réunion de lancement", "mission": "ES2002",
                             "date": "2026-09-12", "language": "en", "contact": " "})
    assert resp.status_code == 200 and resp.json()["video_id"] == "kickoff_es2002"
    meta = load_meta(settings.data_dir, "kickoff_es2002")
    assert (meta.title, meta.mission, meta.language, meta.contact) == (
        "Réunion de lancement", "ES2002", "en", None)


def test_upload_refuses_exact_duplicates_and_taken_names(client, settings):
    (settings.data_dir / "videos").mkdir(parents=True)
    (settings.data_dir / "videos" / "old.wav").write_bytes(b"same bytes")
    write_jsonl(settings.videos_file, [Video(video_id="old", title="Old", source_uri="old.wav",
                                             duration_s=1)])
    dup = client.post("/videos", files={"file": ("renamed.wav", b"same bytes", "audio/wav")})
    assert dup.status_code == 409 and "old" in dup.json()["detail"]
    assert not (settings.data_dir / "videos" / "renamed.wav").exists()  # rien n'est gardé
    assert read_jsonl(settings.videos_file, Video)[0].sha256  # empreinte calculée une fois
    name = client.post("/videos", files={"file": ("old.wav", b"other", "audio/wav")})
    assert name.status_code == 409


def test_upload_rejects_bad_format_and_bad_language(client):
    assert client.post("/videos", files={"file": ("notes.txt", b"x", "text/plain")}
                       ).status_code == 415
    assert client.post("/videos", files={"file": ("a.wav", b"x", "audio/wav")},
                       data={"language": "klingon"}).status_code == 422


def test_near_duplicate_is_set_aside_not_indexed(settings):
    videos_dir = settings.data_dir / "videos"
    videos_dir.mkdir(parents=True)
    (videos_dir / "copy.mp4").write_bytes(b"x")
    write_jsonl(settings.videos_file, [
        Video(video_id="orig", title="Orig", source_uri="orig.wav", duration_s=60),
        Video(video_id="copy", title="Copy", source_uri="copy.mp4", duration_s=60)])
    for vid in ("orig", "copy"):
        write_jsonl(settings.transcripts_dir / f"{vid}.jsonl",
                    [Segment(video_id=vid, seg_id=0, start_s=0, end_s=9, text=MEETING)])
    dup = api._near_duplicate(settings, "copy")
    assert dup == ("orig", 1.0)
    api._set_aside(settings, "copy")
    assert [v.video_id for v in read_jsonl(settings.videos_file, Video)] == ["orig"]
    assert (settings.data_dir / "duplicates" / "copy.mp4").exists()  # déplacé, pas supprimé
    assert not (settings.transcripts_dir / "copy.jsonl").exists()


# --- Index incrémental -------------------------------------------------------------------------


class FakeEmbedder:
    def __init__(self):
        self.usage = Usage()
        self.seen: list[str] = []

    def embed(self, texts):
        self.seen += texts
        return [[float(len(t)), 1.0] for t in texts]


class FakeStore:
    def __init__(self):
        self.chunks: dict[str, Chunk] = {}

    def reset(self):
        self.chunks = {}

    def upsert(self, chunks, vectors):
        self.chunks.update({c.chunk_id: c for c in chunks})

    def delete_videos(self, ids):
        self.chunks = {k: c for k, c in self.chunks.items() if c.video_id not in ids}


def test_update_index_only_embeds_new_videos_and_replaces_reingested_ones(tmp_path, monkeypatch):
    s = load_settings("free")
    s.data_dir = tmp_path
    store, embedder = FakeStore(), FakeEmbedder()
    monkeypatch.setattr(build, "build_store", lambda settings: store)
    monkeypatch.setattr(build, "build_embedder", lambda settings: embedder)

    def add(vid: str, text: str) -> None:
        videos = read_jsonl(s.videos_file, Video) if s.videos_file.exists() else []
        videos = [v for v in videos if v.video_id != vid]
        write_jsonl(s.videos_file, videos + [Video(video_id=vid, title=vid, source_uri=f"{vid}.wav",
                                                    duration_s=9)])
        write_jsonl(s.transcripts_dir / f"{vid}.jsonl",
                    [Segment(video_id=vid, seg_id=i, start_s=i, end_s=i + 1, text=f"{text} {i}")
                     for i in range(3)])

    add("a", "alpha")
    build.build_index(s)
    embedder.seen.clear()
    add("b", "bravo")
    build.update_index(s, ["b"])
    assert all("bravo" in t for t in embedder.seen)  # « a » n'est pas réembarqué
    chunks = read_jsonl(s.index_dir / "chunks.jsonl", Chunk)
    assert {c.video_id for c in chunks} == {"a", "b"} == {c.video_id for c in store.chunks.values()}
    lines = (s.index_dir / "moments.jsonl").read_text().splitlines()
    moments = [json.loads(line) for line in lines]
    assert len(moments) == np.load(s.index_dir / "moments.npy").shape[0] == 6

    add("a", "ALPHA-v2")  # vidéo retraitée : ses anciens chunks et moments disparaissent
    build.update_index(s, ["a"])
    texts = " ".join(c.text for c in read_jsonl(s.index_dir / "chunks.jsonl", Chunk))
    assert "ALPHA-v2" in texts and "alpha 0" not in texts
    assert np.load(s.index_dir / "moments.npy").shape[0] == 6


# --- Sources datées (contradictions) -----------------------------------------------------------


def test_sources_carry_date_and_context_for_contradictions():
    from kb.agent.guardrails import wrap_sources

    ch = Chunk(chunk_id="a__000", video_id="a", start_s=0, end_s=9, text="price is 25 euro",
               context_header='Vidéo : "Kick-off" · Mission : ES2002', date=dt.date(2026, 9, 12))
    out = wrap_sources([ch])
    assert 'date="2026-09-12"' in out and "context=\"Vidéo : 'Kick-off' · Mission : ES2002\"" in out


def test_device_auto_picks_gpu_only_when_available(monkeypatch):
    import kb.adapters.factory as factory

    monkeypatch.setattr(factory, "cuda_available", lambda: True)
    assert factory.resolve_device("auto", "auto") == ("cuda", "float16")
    monkeypatch.setattr(factory, "cuda_available", lambda: False)
    assert factory.resolve_device("auto", "auto") == ("cpu", "int8")
    assert factory.resolve_device("cpu", "int8") == ("cpu", "int8")  # réglage explicite gardé
