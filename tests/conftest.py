from __future__ import annotations

import os
from pathlib import Path

import pytest
import reportlab
from PIL import Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from pdf_remediation.config import Settings
from pdf_remediation.verify import verapdf_command

FONT_DIR = Path(reportlab.__file__).parent / "fonts"


def _fonts():
    if "Vera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("Vera", str(FONT_DIR / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("VeraBd", str(FONT_DIR / "VeraBd.ttf")))


def make_sample(path: Path, pages: int = 2, with_link: bool = True, with_image: bool = True) -> Path:
    """Untagged, born-digital sample: title, headings, paragraphs, bullets, image, link, page numbers.
    All fonts embedded, so a correct remediation can pass PDF/UA-1 once alt text is supplied."""
    _fonts()
    c = canvas.Canvas(str(path))
    for p in range(pages):
        y = 760
        if p == 0:
            c.setFont("VeraBd", 22)
            c.drawString(72, y, "Annual Accessibility Report")
            y -= 40
        c.setFont("VeraBd", 15)
        c.drawString(72, y, f"Section {p + 1} overview")
        y -= 24
        c.setFont("Vera", 10)
        for line in ("This paragraph explains the purpose of the section and continues on a",
                     "second line so that line grouping into paragraphs is exercised by the tests."):
            c.drawString(72, y, line)
            y -= 13
        y -= 10
        for item in ("First priority item", "Second priority item"):
            c.drawString(80, y, "•")
            c.drawString(92, y, item)
            y -= 14
        y -= 10
        if with_link and p == 0:
            c.drawString(72, y, "Read the full policy online.")
            c.linkURL("https://example.gov/policy", (72, y - 2, 220, y + 10), relative=0)
            y -= 24
        if with_image and p == 0:
            img = Image.new("RGB", (120, 80), (30, 90, 160))
            c.drawInlineImage(img, 72, y - 120, width=180, height=120)
            y -= 140
        c.setFont("Vera", 8)
        c.drawString(290, 30, f"Page {p + 1}")
        c.showPage()
    c.save()
    return path


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    return make_sample(tmp_path / "sample.pdf")


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings.from_env(data_dir=tmp_path / "data")
    s.engine = "basic"
    return s


@pytest.fixture
def need_verapdf(settings):
    if verapdf_command(settings) is None:
        pytest.skip("veraPDF not installed (scripts/fetch-verapdf.sh)")
