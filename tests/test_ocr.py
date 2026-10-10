from __future__ import annotations

import pikepdf
import pypdfium2 as pdfium
import pytest

from pdf_remediation.ocr import get_engine, pages_needing_ocr
from pdf_remediation.ocr.textlayer import TextLayerWriter, TextLine
from pdf_remediation.pipeline import Options, remediate_file
from pdf_remediation.pdf.structure import read_tree

from conftest import make_sample, make_scanned

needs_ocr_engine = pytest.mark.skipif(get_engine("auto") is None, reason='no OCR engine (pip install -e ".[ocr]")')


def _text(path, page=0):
    doc = pdfium.PdfDocument(str(path))
    try:
        return doc[page].get_textpage().get_text_range()
    finally:
        doc.close()


def _roles(path):
    with pikepdf.open(path) as pdf:
        return [e.role for e in read_tree(pdf).walk()]


def _mixed(tmp_path):
    """Page 1 born digital, page 2 a scan."""
    digital = make_sample(tmp_path / "digital.pdf", pages=1)
    scan = make_scanned(tmp_path / "scan.pdf")
    with pikepdf.open(digital) as pdf, pikepdf.open(scan) as other:
        pdf.pages.extend(other.pages)
        pdf.save(tmp_path / "mixed.pdf")
    return tmp_path / "mixed.pdf"


def test_detects_only_image_pages(tmp_path):
    assert pages_needing_ocr(make_sample(tmp_path / "s.pdf")) == []
    assert pages_needing_ocr(make_scanned(tmp_path / "scan.pdf")) == [0]
    assert pages_needing_ocr(_mixed(tmp_path)) == [1]


def test_text_layer_is_invisible_and_extractable(tmp_path):
    """The writer alone, without an OCR engine: text is extractable and rendering is unchanged."""
    src = make_scanned(tmp_path / "scan.pdf")
    before = pdfium.PdfDocument(str(src))[0].render(scale=1).to_pil().tobytes()
    with pikepdf.open(src) as pdf:
        n = TextLayerWriter(pdf).add(pdf.pages[0], [
            TextLine("Hello scanned world", (72, 700), (200, 0), (0, 14)),
            TextLine("Second line", (72, 680), (90, 0), (0, 14)),
        ])
        pdf.save(tmp_path / "layer.pdf")
    assert n == 2
    text = _text(tmp_path / "layer.pdf")
    assert "Hello scanned world" in text and "Second line" in text
    assert text.index("Hello") < text.index("Second")
    after = pdfium.PdfDocument(str(tmp_path / "layer.pdf"))[0].render(scale=1).to_pil().tobytes()
    assert before == after


def test_ocr_off_reports_error(tmp_path, settings):
    out = tmp_path / "out" / "scan.pdf"
    r = remediate_file(make_scanned(tmp_path / "scan.pdf"), out, display_name="scan.pdf", settings=settings,
                       options=Options(engine="basic", verapdf=False, ocr="off"))
    rules = {i["rule"]: i["severity"] for i in r["issues"]}
    assert rules.get("ocr.skipped") == "error"
    assert "ocr" not in r


@needs_ocr_engine
def test_scanned_page_is_ocred_and_tagged(tmp_path, settings, need_verapdf):
    settings.engine = "auto"
    out = tmp_path / "out" / "scan.pdf"
    r = remediate_file(make_scanned(tmp_path / "scan.pdf"), out, display_name="scan.pdf", settings=settings,
                       options=Options())
    assert r["status"] != "failed", r.get("error")
    assert r["ocr"]["pages"] == [1] and r["ocr"]["lines"] >= 5
    assert r["engine"] == "basic"  # OCR output is always tagged by the built-in engine
    assert "Annual Accessibility Report" in _text(out)
    assert any(h["level"] == 1 and "Annual Accessibility Report" in h["text"] for h in r["headings"])
    assert "Figure" not in _roles(out)  # the scan image is background, not a figure
    assert r["visual"]["identical"], r["visual"]
    assert r["summary"]["machine_validation"] == "pass", r["verapdf"]
    assert "ocr.applied" in {i["rule"] for i in r["issues"]}


@needs_ocr_engine
def test_mixed_document_ocrs_only_the_scan(tmp_path, settings):
    out = tmp_path / "out" / "mixed.pdf"
    r = remediate_file(_mixed(tmp_path), out, display_name="mixed.pdf", settings=settings,
                       options=Options(engine="basic", verapdf=False))
    assert r["facts"]["pages_needing_ocr"] == [2]
    assert r["ocr"]["pages"] == [2]
    assert "Annual Accessibility Report" in _text(out, 1)


@needs_ocr_engine
def test_rotated_scan_text_is_extractable(tmp_path, settings):
    out = tmp_path / "out" / "rot.pdf"
    r = remediate_file(make_scanned(tmp_path / "rot.pdf", rotate=90), out, display_name="rot.pdf",
                       settings=settings, options=Options(engine="basic", verapdf=False))
    assert r["ocr"]["pages"] == [1]
    assert "Annual Accessibility Report" in _text(out)
    assert r["visual"]["identical"], r["visual"]
