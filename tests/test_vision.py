"""Images et pages scannées SANS Tesseract ni modèle : OCR et LLM de vision factices."""

import pytest
from PIL import Image

import kb.ingest.vision as vision
from kb.index.chunking import chunk_document
from kb.ingest.documents import extract_pdf
from kb.schemas import Video

SCAN_TEXT = ("Note de reunion. Le taux de defaut des boutons Polytech sur le premier lot est de "
             "3 %, au-dessus de la cible de 1 %. Decision : controle visuel a 100 %. " * 3)


class FakeVisionLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, json_schema=None, temperature=None):
        self.calls += 1
        parts = messages[0]["content"]
        assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")  # vraie image
        return "Schéma : deux piles AAA alimentent une puce standard reliée à un émetteur IR."


@pytest.fixture
def fake_ocr(monkeypatch):
    texts = {"value": ""}
    monkeypatch.setattr(vision, "ocr_available", lambda: True)
    monkeypatch.setattr(vision, "ocr", lambda image, languages="fra+eng": texts["value"])
    return texts


def test_text_page_is_read_by_ocr_only_no_llm_cost(fake_ocr):
    fake_ocr["value"] = SCAN_TEXT
    llm = FakeVisionLLM()
    segs = vision.image_segments(Image.new("RGB", (80, 60)), "n", 2, 0, llm)
    assert llm.calls == 0 and segs and {s.modality for s in segs} == {"ocr"}
    assert all(s.page == 2 and 2 <= s.start_s < 3 for s in segs)


def test_diagram_with_little_text_is_also_described(fake_ocr):
    fake_ocr["value"] = "Émetteur infrarouge"
    llm = FakeVisionLLM()
    segs = vision.image_segments(Image.new("RGB", (80, 60)), "s", 1, 0, llm)
    assert llm.calls == 1 and [s.modality for s in segs] == ["ocr", "visual"]
    assert "piles AAA" in segs[1].text


def test_standalone_image_is_always_described_unless_disabled(fake_ocr):
    fake_ocr["value"] = SCAN_TEXT
    llm = FakeVisionLLM()
    assert vision.image_segments(Image.new("RGB", (80, 60)), "i", 1, 0, llm,
                                 always_describe=True)[-1].modality == "visual"
    assert all(s.modality == "ocr" for s in vision.image_segments(
        Image.new("RGB", (80, 60)), "i", 1, 0, None, always_describe=True))  # describe=False


def test_scanned_pdf_page_is_read(tmp_path, fake_ocr):
    fake_ocr["value"] = SCAN_TEXT
    pdf = tmp_path / "Note_scan.pdf"
    Image.new("RGB", (400, 560), "white").save(pdf, "PDF")  # PDF image seule : aucun texte
    assert extract_pdf(pdf).segments == []  # sans lecture des scans : rien
    doc = extract_pdf(pdf, llm=None, read_scans=True)
    assert doc.empty_pages == [1] and doc.segments and doc.segments[0].modality == "ocr"
    assert "Polytech" in " ".join(s.text for s in doc.segments)


def test_chunks_never_mix_read_text_and_generated_description(fake_ocr):
    fake_ocr["value"] = "Coût cible total : 12,50 € — forme bonhomme de neige"
    segs = vision.image_segments(Image.new("RGB", (80, 60)), "s", 1, 0, FakeVisionLLM(),
                                 always_describe=True)
    video = Video(video_id="s", title="Schéma v2", source_uri="s.png", duration_s=0, kind="image")
    chunks = chunk_document(segs, video)
    assert sorted(c.modality for c in chunks) == ["ocr", "visual"]
    visual = next(c for c in chunks if c.modality == "visual")
    assert "Description générée de l'image" in visual.context_header
    assert visual.context_header.startswith("Image : Schéma v2 · p. 1")


def test_upload_accepts_images(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import kb.api.app as api
    from kb.config import load_settings

    s = load_settings("free")
    s.data_dir = tmp_path
    monkeypatch.setattr(api, "load_settings", lambda profile=None: s)
    monkeypatch.setattr(api, "run_in_background", lambda *a: None)
    resp = TestClient(api.app).post(
        "/videos", files={"file": ("Schema_v2_seg01.png", b"\x89PNG fake", "image/png")})
    assert resp.status_code == 200 and resp.json()["video_id"] == "schema_v2_seg01"


def test_answer_backed_only_by_generated_descriptions_is_flagged():
    from kb.agent.agent import VISUAL_ONLY_NOTE, only_generated_evidence
    from kb.schemas import Answer, Citation

    def cite(modality):
        return Citation(chunk_id="s__1", video_id="s", start_s=1, quote="deux piles AAA",
                        verified=True, modality=modality)

    assert only_generated_evidence(Answer(answer="x", citations=[cite("visual")]))
    assert not only_generated_evidence(Answer(answer="x", citations=[cite("visual"), cite("ocr")]))
    assert not only_generated_evidence(Answer(not_found=True))
    assert "GÉNÉRÉE" in VISUAL_ONLY_NOTE
