"""L0 Vision : ce que MONTRE une image (image seule, page scannée ; bientôt images de vidéo).

Deux lectures complémentaires, mesurées le 27/09 sur un schéma et une note scannée (CPU) :
- **OCR (Tesseract, fra+eng)** : le texte écrit, recopié tel quel (1 à 1,5 s). Quasi parfait
  sur une page scannée ; rate l'écriture manuscrite d'un schéma (« 2 piles AAA »).
- **Description par le LLM de vision (gemma3)** : composants, liens, annotations (≈ 60 s).
  C'est du texte GÉNÉRÉ : il est marqué `modality="visual"` et le front l'affiche comme
  « description générée — à vérifier sur l'image », jamais comme une preuve exacte.

Règle de coût : la description n'est lancée que pour une image seule, ou quand l'OCR trouve
peu de texte (schéma, photo). Une page de texte scannée se contente de l'OCR.
"""

from __future__ import annotations

import base64
import io
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from kb.config import MODELS_DIR
from kb.ingest.documents import page_units
from kb.schemas import Segment

if TYPE_CHECKING:
    from PIL.Image import Image

    from kb.adapters.base import LLM

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DESCRIBE_IF_OCR_BELOW = 200  # caractères : en dessous, l'image n'est pas « du texte » → description
MAX_SIDE = 1280  # px envoyés au LLM de vision (au-delà : plus lent, pas plus précis)
_WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

DESCRIBE_PROMPT = (
    "Décris cette image en français, en 3 à 6 phrases factuelles : de quoi il s'agit, les "
    "éléments visibles, les liens entre eux, les chiffres et annotations. Recopie les textes "
    "visibles tels quels. N'invente rien ; si un élément est illisible, dis-le. Commence "
    "directement par la description, sans phrase d'introduction."
)


def _tesseract():
    """pytesseract configuré : binaire (PATH, TESSERACT_CMD, ou chemin Windows par défaut) et
    langues (data/models/tessdata, qui contient fra + eng, s'il existe)."""
    import pytesseract

    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not cmd and _WINDOWS_TESSERACT.exists():
        cmd = str(_WINDOWS_TESSERACT)
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    local = MODELS_DIR / "tessdata"
    if (local / "fra.traineddata").exists():
        os.environ.setdefault("TESSDATA_PREFIX", str(local))
    return pytesseract


def ocr_available() -> bool:
    try:
        _tesseract().get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001 — binaire absent : l'OCR est simplement sauté
        return False


def ocr(image: Image, languages: str = "fra+eng") -> str:
    pt = _tesseract()
    try:
        langs = set(pt.get_languages())
    except Exception:  # noqa: BLE001
        langs = {"eng"}
    lang = "+".join(x for x in languages.split("+") if x in langs) or "eng"
    return " ".join(pt.image_to_string(image, lang=lang).split())


def describe(llm: LLM, image: Image, prompt: str = DESCRIBE_PROMPT) -> str:
    """Description par un LLM de vision (format OpenAI : image en base64 dans le message)."""
    img = image.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": url}},
    ]}]
    return " ".join(llm.complete(messages, temperature=0).split())


def image_segments(image: Image, video_id: str, page: int, first_seg_id: int,
                   llm: LLM | None, always_describe: bool = False) -> list[Segment]:
    """Segments d'une image (page p) : texte lu (ocr) puis, si utile, description (visual)."""
    segs: list[Segment] = []

    def add(text: str, modality: str) -> None:
        for unit in page_units(text):
            j = len(segs)
            segs.append(Segment(video_id=video_id, seg_id=first_seg_id + j, page=page,
                                start_s=page + j / 1000, end_s=page + (j + 1) / 1000,
                                text=unit, modality=modality))

    text = ocr(image) if ocr_available() else ""
    if text:
        add(text, "ocr")
    if llm is not None and (always_describe or len(text) < DESCRIBE_IF_OCR_BELOW):
        add(describe(llm, image), "visual")
    return segs


def render_pdf_page(path: Path, page: int, scale: float = 2.0) -> Image:
    import pypdfium2

    return pypdfium2.PdfDocument(str(path))[page - 1].render(scale=scale).to_pil()
