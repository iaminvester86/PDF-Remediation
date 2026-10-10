"""OCR for scanned pages, called automatically when a page needs it.

A page needs OCR when it has (almost) no extractable text but images cover a
substantial part of it. Pages that already carry a text layer (including an
earlier OCR layer) are left alone. Recognised text is written as an invisible
layer (textlayer.py) and then tagged like any other text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium

from ..pdf.pdfium import device_to_page
from .engines import available_engines, get_engine
from .textlayer import TextLayerWriter, TextLine

MIN_TEXT_CHARS = 20  # fewer extractable characters than this counts as "no text"
MIN_IMAGE_COVERAGE = 0.25  # share of the page covered by images


@dataclass
class OcrResult:
    engine: str
    pages: list[int] = field(default_factory=list)  # 0-based pages that were processed
    lines: int = 0
    confidence: dict[int, float] = field(default_factory=dict)  # page -> mean line confidence
    dropped: int = 0  # lines below the confidence floor

    def low_confidence_pages(self, threshold: float = 0.85) -> list[int]:
        return [p for p, c in self.confidence.items() if c < threshold]


def pages_needing_ocr(path: Path) -> list[int]:
    doc = pdfium.PdfDocument(str(path))
    try:
        result = []
        for i in range(len(doc)):
            page = doc[i]
            if page.get_textpage().count_chars() >= MIN_TEXT_CHARS:
                continue
            w, h = page.get_size()
            covered = 0.0
            for obj in page.get_objects(max_depth=2):
                if obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                    l, b, r, t = obj.get_bounds()
                    covered += max(r - l, 0) * max(t - b, 0)
            if covered >= MIN_IMAGE_COVERAGE * w * h:
                result.append(i)
        return result
    finally:
        doc.close()


def run_ocr(src: Path, dst: Path, pages: list[int], *, engine_name: str = "auto", lang: str = "en",
            dpi: int = 200, min_confidence: float = 0.3) -> OcrResult:
    """OCR the given pages of ``src`` and write the result with a text layer to ``dst``."""
    engine = get_engine(engine_name)
    if engine is None:
        raise RuntimeError("No OCR engine is installed")
    result = OcrResult(engine=engine.name)
    doc = pdfium.PdfDocument(str(src))
    pdf = pikepdf.open(src)
    try:
        writer = TextLayerWriter(pdf)
        for i in pages:
            page = doc[i]
            image = page.render(scale=dpi / 72).to_pil()
            recognised = [pl for pl in engine.recognize(image, lang) if pl.text.strip()]
            kept = [pl for pl in recognised if pl.confidence >= min_confidence]
            result.dropped += len(recognised) - len(kept)
            # Content order = reading order on the displayed page: top to bottom, then left to right.
            kept.sort(key=lambda pl: (round(pl.box[1] / (8 * dpi / 72)), pl.box[0]))
            lines: list[TextLine] = []
            for pl in kept:
                l, t, r, b = pl.box
                bl = device_to_page(page, image.size, l, b)
                br = device_to_page(page, image.size, r, b)
                tl = device_to_page(page, image.size, l, t)
                lines.append(TextLine(pl.text, bl, (br[0] - bl[0], br[1] - bl[1]), (tl[0] - bl[0], tl[1] - bl[1]),
                                      pl.confidence))
            scores = [ln.confidence for ln in lines]
            result.lines += writer.add(pdf.pages[i], lines)
            result.pages.append(i)
            result.confidence[i] = round(sum(scores) / len(scores), 3) if scores else 0.0
        pdf.save(dst)
    finally:
        pdf.close()
        doc.close()
    return result


__all__ = ["OcrResult", "available_engines", "get_engine", "pages_needing_ocr", "run_ocr"]
