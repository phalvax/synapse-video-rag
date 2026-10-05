"""L0 Documents : PDF → segments texte PAR PAGE (même format que les transcripts de vidéos).

Un document est traité comme un enregistrement dont l'axe est la page au lieu de la seconde :
page p, unité j → `start_s = p + j/1000`. Tout le reste de la chaîne (chunks, moments, index,
recherche, agent, garde-fous) fonctionne sans changement, et la citation renvoie à la page.

Unité = quelques phrases (≤ ~50 mots) d'une même page : assez fine pour pointer le bon passage,
assez longue pour garder le sens. Une page sans texte extractible (scannée) est signalée ; elle
sera lue par OCR (étape suivante du chantier).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from kb.ingest.sources import slugify
from kb.schemas import Segment

DOCUMENT_EXTENSIONS = {".pdf"}
UNIT_WORDS = 50
MIN_PAGE_CHARS = 25  # en dessous : page sans texte extractible (scan, image seule)
_SENTENCE = re.compile(r"(?<=[.!?;:])\s+")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")

_FR = {"le", "la", "les", "des", "est", "et", "une", "pour", "que", "dans", "du", "sur", "avec",
       "nous"}
_EN = {"the", "and", "is", "of", "to", "for", "that", "with", "we", "are", "on", "this", "it", "in"}


@dataclass
class DocumentText:
    video_id: str
    title: str
    path: Path
    pages: int
    segments: list[Segment] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)  # pages sans texte : OCR nécessaire
    language: str | None = None


def discover_documents(folder: Path) -> list[Path]:
    """PDF et images du dossier (les images sont lues par kb.ingest.vision)."""
    from kb.ingest.vision import IMAGE_EXTENSIONS

    exts = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS
    return [p for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() in exts]


def detect_language(text: str) -> str | None:
    """fr / en par comptage de mots-outils (suffisant pour choisir la langue de recherche)."""
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", text.lower())
    fr, en = sum(w in _FR for w in words), sum(w in _EN for w in words)
    if fr + en < 5:
        return None
    return "fr" if fr >= en else "en"


def page_units(text: str, max_words: int = UNIT_WORDS) -> list[str]:
    """Texte d'une page → unités de quelques phrases (≤ max_words mots, une phrase longue seule)."""
    text = _HYPHEN_BREAK.sub(r"\1\2", text)  # « docu-\nment » → « document »
    flat = " ".join(text.split())
    units, current = [], []
    for sentence in _SENTENCE.split(flat):
        words = sentence.split()
        if current and len(current) + len(words) > max_words:
            units.append(" ".join(current))
            current = []
        current += words
    if current:
        units.append(" ".join(current))
    return [u for u in units if u.strip()]


def pdf_pages(path: Path) -> list[str]:
    from pypdf import PdfReader

    return [(page.extract_text() or "") for page in PdfReader(str(path)).pages]


def extract_pdf(path: Path, llm=None, read_scans: bool = False) -> DocumentText:
    """`read_scans` : les pages sans texte (scans, schémas) sont lues par OCR, et décrites par
    le LLM de vision (`llm`) si l'OCR trouve peu de texte (kb.ingest.vision)."""
    video_id = slugify(path.stem)
    doc = DocumentText(video_id=video_id, title=path.stem.replace("_", " ").strip().capitalize(),
                       path=path, pages=0)
    pages = pdf_pages(path)
    doc.pages = len(pages)
    for p, text in enumerate(pages, start=1):
        if len(text.strip()) < MIN_PAGE_CHARS:
            doc.empty_pages.append(p)
            if read_scans:
                from kb.ingest.vision import image_segments, render_pdf_page

                doc.segments += image_segments(render_pdf_page(path, p), video_id, p,
                                               len(doc.segments), llm)
            continue
        for j, unit in enumerate(page_units(text)):
            doc.segments.append(Segment(
                video_id=video_id, seg_id=len(doc.segments), page=p,
                start_s=p + j / 1000, end_s=p + (j + 1) / 1000, text=unit))
    doc.language = detect_language(" ".join(s.text for s in doc.segments))
    return doc
