"""Documents (PDF) SANS réseau ni modèle : extraction par page, chunks, moments, citations."""

from pathlib import Path

import pytest

from kb.agent.agent import merge_results
from kb.index.build import build_moments
from kb.index.chunking import chunk_document
from kb.index.search import Hit, SearchResult
from kb.ingest.documents import detect_language, extract_pdf, page_units
from kb.schemas import Chunk, Segment, Video

PAGE1 = ("Compte rendu technique. Le fournisseur retenu pour les boutons est Polytech. "
         "Le cout unitaire est de 1,20 euro par piece.")
PAGE2 = ("Decision du comite : la batterie cinetique est abandonnee pour des raisons de cout. "
         "Nous passons a une pile standard AAA.")


def make_pdf(pages: list[str]) -> bytes:
    """PDF minimal valide (Helvetica), une ligne de texte par page ; "" = page vide (scan)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", ""]
    kids, font_id = [], 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        page_id, content_id = 3 + 2 * i, 4 + 2 * i
        kids.append(f"{page_id} 0 R")
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 9 Tf 20 750 Td ({safe}) Tj ET" if text else ""
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return out


@pytest.fixture
def pdf(tmp_path) -> Path:
    path = tmp_path / "Compte_rendu_ES2002.pdf"
    path.write_bytes(make_pdf([PAGE1, PAGE2, ""]))
    return path


def test_pdf_text_is_extracted_page_by_page(pdf):
    doc = extract_pdf(pdf)
    assert (doc.video_id, doc.pages, doc.empty_pages) == ("compte_rendu_es2002", 3, [3])
    assert {s.page for s in doc.segments} == {1, 2}
    assert "Polytech" in " ".join(s.text for s in doc.segments if s.page == 1)
    assert all(s.page <= s.start_s < s.page + 1 for s in doc.segments)  # axe : page + rang/1000
    assert doc.language == "fr"


def test_page_units_keep_sentences_and_size():
    text = "Une phrase courte. " * 30 + "Fin-\nale."
    units = page_units(text, max_words=20)
    assert all(len(u.split()) <= 20 for u in units) and units[-1].endswith("Finale.")


def test_language_detection():
    fr = "Le projet est en retard et nous devons revoir le budget pour la suite"
    assert detect_language(fr) == "fr"
    assert detect_language("The project is late and we need to review the budget for this") == "en"
    assert detect_language("Polytech AAA 1,20") is None


def _doc_segments() -> list[Segment]:
    segs = []
    for page in (1, 2):
        for j in range(4):
            segs.append(Segment(video_id="d", seg_id=len(segs), page=page,
                                start_s=page + j / 1000, end_s=page + (j + 1) / 1000,
                                text=f"page {page} unité {j} " + "mot " * 60))
    return segs


def test_document_chunks_never_span_two_pages():
    video = Video(video_id="d", title="Compte rendu", source_uri="d.pdf", duration_s=0,
                  kind="document", mission="ES2002")
    chunks = chunk_document(_doc_segments(), video, target_tokens=100)
    assert {c.page for c in chunks} == {1, 2} and len({c.chunk_id for c in chunks}) == len(chunks)
    for c in chunks:
        assert f"p. {c.page}" in c.context_header and "Mission : ES2002" in c.context_header
        assert f"page {c.page} " in c.text and f"page {3 - c.page} " not in c.text


def test_document_moments_stay_on_their_page():
    moments = build_moments(_doc_segments())
    assert all(m.text.count("page ") == m.text.count(f"page {m.page} ") for m in moments)


def test_merge_keeps_the_best_score_per_passage():
    def hit(cid, score):
        return Hit(chunk=Chunk(chunk_id=cid, video_id="v", start_s=0, end_s=1, text=cid),
                   score=score, rerank_score=score)

    translated = SearchResult(hits=[hit("a", 0.2), hit("b", 0.05)], best_score=0.2)
    original = SearchResult(hits=[hit("b", 0.9)], best_score=0.9)
    merged = merge_results(translated, original, k=5, threshold=0.1)
    assert [h.chunk.chunk_id for h in merged.hits] == ["b", "a"]
    assert merged.best_score == 0.9 and not merged.abstain


def test_citation_of_a_document_carries_its_page():
    from kb.agent.agent import Agent
    from kb.config import load_settings

    chunk = Chunk(chunk_id="d__001", video_id="d", start_s=2.0, end_s=2.004, page=2,
                  text=PAGE2, context_header="Document : CR · p. 2")

    class Searcher:
        def search(self, query, mode="hybrid_rerank", k=5, filters=None):
            h = Hit(chunk=chunk, score=0.9, rerank_score=0.9, moment_s=2.0, moment_text=PAGE2)
            return SearchResult(hits=[h], best_score=0.9)

    class LLM:
        def complete(self, messages, json_schema=None, temperature=None):
            return ('{"answer": "La batterie cinétique est abandonnée [S1].", "not_found": false,'
                    ' "citations": [{"source_id": "S1", "quote": "la batterie cinetique est '
                    'abandonnee pour des raisons de cout"}]}')

    s = load_settings("free")
    s.retrieval.query_language = None
    res = Agent(s, Searcher(), LLM()).ask("Pourquoi abandonner la batterie cinétique ?")
    assert not res.answer.not_found and res.answer.citations[0].page == 2


def test_upload_accepts_pdf(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import kb.api.app as api

    s = load_settings_tmp(tmp_path, monkeypatch, api)
    resp = TestClient(api.app).post(
        "/videos", files={"file": ("Rapport_part2.pdf", make_pdf([PAGE1]), "application/pdf")})
    assert resp.status_code == 200 and resp.json()["video_id"] == "rapport_part2"
    assert (s.data_dir / "videos" / "Rapport_part2.pdf").exists()


def load_settings_tmp(tmp_path, monkeypatch, api):
    from kb.config import load_settings

    s = load_settings("free")
    s.data_dir = tmp_path
    monkeypatch.setattr(api, "load_settings", lambda profile=None: s)
    monkeypatch.setattr(api, "run_in_background", lambda *a: None)
    return s


def test_bilingual_corpus_searches_in_each_language_and_keeps_the_best():
    from kb.agent.agent import Agent
    from kb.config import load_settings

    fr_chunk = Chunk(chunk_id="d__002", video_id="d", start_s=3.0, end_s=3.001, page=3,
                     text="Prototype v2 : 15 octobre 2026, responsable Laura Martin.")
    searched: list[str] = []

    class Searcher:
        def search(self, query, mode="hybrid_rerank", k=5, filters=None):
            searched.append(query)
            score = 0.9 if "responsable" in query else 0.05  # le passage FR ne matche qu'en FR
            h = Hit(chunk=fr_chunk, score=score, rerank_score=score, moment_s=3.0,
                    moment_text=fr_chunk.text)
            return SearchResult(hits=[h], best_score=score, abstain=score < 0.1)

    replies = iter([
        "Who is responsible for prototype v2?",           # traduction → en
        "Qui est responsable du prototype v2 ?",          # traduction → fr
        '{"answer": "Laura Martin [S1].", "not_found": false, "citations": [{"source_id": '
        '"S1", "quote": "responsable Laura Martin"}]}',
    ])

    class LLM:
        def complete(self, messages, json_schema=None, temperature=None):
            return next(replies)

    s = load_settings("free")
    s.retrieval.query_language = "en"
    agent = Agent(s, Searcher(), LLM(), languages={"en", "fr"})
    res = agent.ask("Who is responsible for prototype v2?")
    assert searched == ["Who is responsible for prototype v2?",
                        "Qui est responsable du prototype v2 ?"]
    assert not res.answer.not_found and res.retrieval_score == 0.9
    assert res.answer.citations[0].page == 3


def test_one_extract_proving_two_numbers_is_added_once():
    from kb.agent.agent import _back_numbers
    from kb.schemas import Answer

    chunk = Chunk(chunk_id="d__001", video_id="d", start_s=2.0, end_s=2.1, page=2,
                  text="Nous passons a deux piles AAA, pour tenir le cout de 12,50 euros.")
    hit = Hit(chunk=chunk, score=0.9, rerank_score=0.9, moment_s=2.0, moment_text=chunk.text)
    ans = Answer(answer="Pour tenir un coût de 12,50 euros [S1].", citations=[])
    out, missing = _back_numbers(ans, [hit], {"d__001": 2.0})
    assert missing == set() and len(out.citations) == 1 and out.citations[0].page == 2
