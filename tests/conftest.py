from __future__ import annotations

from pathlib import Path

import pytest
import reportlab
from PIL import Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from pdf_remediation.config import Settings
from pdf_remediation.checks.verapdf import command as verapdf_command

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
        pytest.skip("veraPDF not installed (run: pdfrem install-engines)")


def make_ruled_table(path: Path) -> Path:
    """A heading, a paragraph and a 4x3 table drawn with grid lines (one path object)."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    _fonts()
    body = ParagraphStyle("b", fontName="Vera", fontSize=10, leading=13)
    head = ParagraphStyle("h", fontName="VeraBd", fontSize=18, leading=22)
    table = Table([["Program", "FY2025", "FY2026"], ["Remediation", "$1.2M", "$2.0M"],
                   ["Training", "$0.4M", "$0.6M"], ["Audits", "$0.2M", "$0.3M"]],
                  style=TableStyle([("FONT", (0, 0), (-1, -1), "Vera", 10),
                                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(str(path)).build([Paragraph("Budget allocations", head),
                                        Paragraph("Spending by program for two fiscal years.", body), table])
    return path



def make_spanned_table(path: Path) -> Path:
    """A ruled table with a two-row header: cells spanning rows and a group heading over two columns."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    _fonts()
    cell = ParagraphStyle("c", fontName="Vera", fontSize=9, leading=11)
    data = [["Program", "Funding", "", "Notes"],
            ["", "FY2025", "FY2026", ""],
            ["Remediation", "$1.2M", "$2.0M", Paragraph("Vendor contracts and the internal review team.", cell)],
            ["Training", "$0.4M", "$0.6M", Paragraph("Online modules for staff who publish documents.", cell)],
            ["Audits", "$0.2M", "$0.3M", Paragraph("Quarterly sampling.", cell)]]
    table = Table(data, colWidths=[90, 60, 60, 160], style=TableStyle([
        ("FONT", (0, 0), (-1, -1), "Vera", 9), ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (2, 0)), ("SPAN", (3, 0), (3, 1))]))
    SimpleDocTemplate(str(path)).build([Paragraph("Budget", ParagraphStyle("h", fontName="VeraBd", fontSize=16)),
                                        table])
    return path

def make_aligned_table(path: Path) -> Path:
    """A borderless table: columns aligned with spaces only, plus a two-column prose block."""
    _fonts()
    c = canvas.Canvas(str(path))
    c.setFont("VeraBd", 16)
    c.drawString(72, 740, "Enrollment by school")
    rows = [("School", "2024", "2025"), ("Lincoln Elementary", "412", "430"), ("Roosevelt Middle", "655", "640"),
            ("Jefferson High", "1,204", "1,250"), ("Adams Academy", "98", "110")]
    y = 700
    for i, row in enumerate(rows):
        c.setFont("VeraBd" if i == 0 else "Vera", 10)
        c.drawString(72, y, row[0])
        c.drawRightString(300, y, row[1])
        c.drawRightString(380, y, row[2])
        y -= 16
    c.setFont("Vera", 10)
    left = ["Two-column prose must not be mistaken", "for a table even though its lines sit",
            "side by side on the same baselines and", "continue down the page in columns."]
    right = ["The right column continues a separate", "article that happens to align with the",
             "left one, which is common in newsletters", "and annual reports with two columns."]
    y = 560
    for a, b in zip(left, right):
        c.drawString(72, y, a)
        c.drawString(320, y, b)
        y -= 13
    c.save()
    return path


def make_scanned(path: Path, rotate: int = 0) -> Path:
    """An image-only page made by rendering the sample; optionally stored sideways with /Rotate."""
    import pikepdf
    import pypdfium2 as pdfium

    src = make_sample(path.with_name(path.stem + "-src.pdf"), pages=1)
    img = pdfium.PdfDocument(str(src))[0].render(scale=200 / 72).to_pil().convert("L")
    size = (612, 792)
    if rotate == 90:
        img, size = img.rotate(90, expand=True), (792, 612)
    png = path.with_suffix(".png")
    img.save(png)
    c = canvas.Canvas(str(path), pagesize=size)
    c.drawImage(str(png), 0, 0, width=size[0], height=size[1])
    c.save()
    if rotate:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            pdf.pages[0].Rotate = rotate
            pdf.save(path)
    return path
