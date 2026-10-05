"""Ce qui est MONTRÉ dans une vidéo (diapos, tableau), SANS Tesseract ni modèle."""

import numpy as np
import pytest
from PIL import Image, ImageDraw

import kb.ingest.frames as frames
import kb.ingest.vision as vision
from kb.index.chunking import chunk_media, chunk_segments
from kb.schemas import Segment, Video


def slide(text: str) -> Image.Image:
    """Diapo blanche avec une ligne de texte sombre (le cas le plus difficile à détecter)."""
    img = Image.new("RGB", (320, 180), "white")
    ImageDraw.Draw(img).rectangle([20, 60, 20 + 12 * len(text), 110], fill="black")
    return img


def test_changed_fraction_sees_a_new_slide_but_not_the_same_one():
    a, b = (frames._thumb(slide(t)) for t in ("Titre", "Tableau des coûts unitaires"))
    assert frames.changed_fraction(a, a) == 0.0
    assert frames.changed_fraction(a, b) > frames.THRESHOLD


def test_keyframes_are_found_at_each_slide_change(tmp_path):
    av = pytest.importorskip("av")  # PyAV vient avec faster-whisper (absent de la CI)
    path = tmp_path / "diapos.mp4"
    images = [slide("Titre"), slide("Tableau des coûts unitaires du prototype"), slide("Fin")]
    with av.open(str(path), "w") as c:
        v = c.add_stream("mpeg4", rate=2)
        v.width, v.height, v.pix_fmt = 320, 180, "yuv420p"
        for i in range(2 * 30):  # 30 s à 2 images/s ; diapos à 0, 10 et 20 s
            f = av.VideoFrame.from_ndarray(np.asarray(images[min(2, i // 20)]), format="rgb24")
            f.pts = i
            for p in v.encode(f):
                c.mux(p)
        for p in v.encode(None):
            c.mux(p)
    assert frames.has_video(path)
    assert [k.t for k in frames.keyframes(path)] == [0.0, 10.0, 20.0]


def test_screen_segments_are_timed_and_labelled(monkeypatch):
    texts = iter(["Coûts unitaires : boutons Polytech 1,20 € ; puce 2,50 € ; total 12,50 € " * 4,
                  "LCD"])  # une diapo pleine de texte, puis un croquis presque sans texte
    monkeypatch.setattr(vision, "ocr_available", lambda: True)
    monkeypatch.setattr(vision, "ocr", lambda image, languages="fra+eng": next(texts))
    described = []
    monkeypatch.setattr(vision, "describe", lambda llm, image: described.append(1) or
                        "Croquis d'une télécommande en bonhomme de neige avec 4 boutons.")
    kfs = [frames.KeyFrame(35.0, slide("a")), frames.KeyFrame(70.0, slide("b"))]
    segs = frames.screen_segments(kfs, "v", 140.0, llm=object())
    assert described == [1]  # seul le croquis est décrit (la diapo texte : OCR seul)
    assert {s.modality for s in segs if s.start_s < 70} == {"ocr"}
    assert [s.modality for s in segs if s.start_s >= 70] == ["ocr", "visual"]
    assert all(35 <= s.start_s < 70 and s.end_s == 70 for s in segs if s.start_s < 70)


def test_description_budget_is_capped(monkeypatch):
    monkeypatch.setattr(vision, "ocr_available", lambda: False)
    monkeypatch.setattr(vision, "describe", lambda llm, image: "Un croquis.")
    kfs = [frames.KeyFrame(float(t), slide("x")) for t in range(5)]
    segs = frames.screen_segments(kfs, "v", 10.0, llm=object(), max_descriptions=2)
    assert sum(s.modality == "visual" for s in segs) == 2


def _speech() -> list[Segment]:
    return [Segment(video_id="v", seg_id=i, start_s=i * 10, end_s=i * 10 + 9,
                    text=f"parole {i} " + "mot " * 80) for i in range(6)]


def test_timeline_merges_speech_and_screen_in_time_order():
    screen = [Segment(video_id="v", seg_id=0, start_s=35, end_s=70, text="Total 12,50 €",
                      modality="ocr")]
    merged = frames.merge_timeline(_speech(), screen)
    assert [s.seg_id for s in merged] == list(range(7))
    assert [s.start_s for s in merged] == sorted(s.start_s for s in merged)


def test_video_chunks_keep_speech_ids_and_isolate_the_screen():
    video = Video(video_id="v", title="Revue budget", source_uri="v.mp4", duration_s=60,
                  kind="video")
    screen = [Segment(video_id="v", seg_id=99, start_s=35, end_s=70, text="Total 12,50 €",
                      modality="ocr"),
              Segment(video_id="v", seg_id=100, start_s=70, end_s=80,
                      text="Croquis d'une télécommande", modality="visual")]
    chunks = chunk_media(frames.merge_timeline(_speech(), screen), video, target_tokens=150)
    speech_only = chunk_segments(_speech(), video, target_tokens=150)
    assert [c.chunk_id for c in chunks[: len(speech_only)]] == [c.chunk_id for c in speech_only]
    extra = chunks[len(speech_only):]
    assert [c.modality for c in extra] == ["ocr", "visual"]
    assert "À l'écran — description générée" in extra[1].context_header
    assert all("parole" not in c.text for c in extra)


def test_screen_moments_never_span_two_slides():
    from kb.index.build import build_moments

    segs = [Segment(video_id="v", seg_id=0, start_s=35.0, end_s=70.0, text="Coûts unitaires",
                    modality="ocr"),
            Segment(video_id="v", seg_id=1, start_s=35.5, end_s=70.0, text="Écran LCD 4,20 €",
                    modality="ocr"),
            Segment(video_id="v", seg_id=2, start_s=70.0, end_s=105.0, text="LCD 4 boutons",
                    modality="ocr")]
    moments = build_moments(segs)
    assert moments[0].text == "Coûts unitaires Écran LCD 4,20 €"  # s'arrête à la diapo suivante
    assert moments[2].start_s == 70.0 and moments[2].text == "LCD 4 boutons"


def test_citation_time_is_where_the_quote_appears():
    from kb.index.build import Moment
    from kb.index.search import Searcher
    from kb.schemas import Chunk

    chunk = Chunk(chunk_id="v__006", video_id="v", start_s=0, end_s=140, text="…",
                  modality="ocr")
    s = Searcher.__new__(Searcher)  # sans charger de modèle : seul locate_quote est testé
    s.moments = [Moment("v", 35.0, 70.0, "Coûts unitaires Écran LCD 4,20 €", None, "ocr"),
                 Moment("v", 70.0, 105.0, "LCD 4 boutons", None, "ocr"),
                 Moment("v", 36.0, 40.0, "écran lcd 4,20 € dit à l'oral", None, None)]
    assert s.locate_quote(chunk, "Écran LCD 4,20 €") == 35.0  # pas 70 (croquis), pas la parole
    assert s.locate_quote(chunk, "absent de la vidéo") is None


def test_quote_time_is_the_window_that_starts_at_the_quote():
    from kb.index.build import Moment
    from kb.index.search import Searcher
    from kb.schemas import Chunk

    chunk = Chunk(chunk_id="v__000", video_id="v", start_s=0, end_s=100, text="…")
    s = Searcher.__new__(Searcher)
    s.moments = [Moment("v", 80.0, 110.0, "bla bla the teletext is outdated", None, None),
                 Moment("v", 95.0, 120.0, "bla the teletext is outdated now", None, None),
                 Moment("v", 105.0, 130.0, "the teletext is outdated now okay", None, None)]
    assert s.locate_quote(chunk, "the teletext is outdated") == 95.0  # 105 hors du chunk
    chunk.end_s = 200
    assert s.locate_quote(chunk, "the teletext is outdated") == 105.0
