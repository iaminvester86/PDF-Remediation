"""Regression tests for problems found on real Chrome-generated PDFs."""
from __future__ import annotations

import re

import pikepdf

from pdf_remediation.pdfium_util import page_texts
from pdf_remediation.pipeline import Options, remediate_file


def _break_bullet_glyph(src, dst):
    """Mimic Chrome output: a single-glyph run wrapped in /Span ActualText, with the
    font's ToUnicode mapping that code to the invalid value U+0000."""
    pdf = pikepdf.open(src)
    page = pdf.pages[0]
    ops = [(list(i.operands), i.operator) for i in pikepdf.parse_content_stream(page)]
    font_name, target = None, None
    for k, (operands, op) in enumerate(ops):
        if str(op) == "Tf":
            font_name = operands[0]
        if str(op) == "Tj" and len(bytes(operands[0])) == 1 and target is None:
            target = (k, font_name, bytes(operands[0]))
    k, font_name, code = target
    ops[k:k + 1] = [([pikepdf.Name.Span, pikepdf.Dictionary(ActualText=pikepdf.String("•"))],
                     pikepdf.Operator("BDC")), ops[k], ([], pikepdf.Operator("EMC"))]
    page.obj.Contents = pdf.make_stream(pikepdf.unparse_content_stream(ops))
    font = page.Resources.Font[font_name]
    cmap = font.ToUnicode.read_bytes().decode("latin-1")
    cmap, n = re.subn(rf"(<{code.hex().upper()}>\s*<)[0-9A-Fa-f]+(>)", r"\g<1>0000\g<2>", cmap, flags=re.I)
    assert n, "test setup: code not found in ToUnicode"
    font.ToUnicode = pdf.make_stream(cmap.encode("latin-1"))
    pdf.save(dst)
    return code.hex().upper(), str(font.BaseFont)


def test_actualtext_is_preserved_through_retagging(sample_pdf, tmp_path, settings):
    broken = tmp_path / "chrome-like.pdf"
    _break_bullet_glyph(sample_pdf, broken)
    out = tmp_path / "out.pdf"
    r = remediate_file(broken, out, display_name="c.pdf", settings=settings,
                       options=Options(engine="basic", verapdf=False))
    assert r["text"]["identical"], r["text"]
    with pikepdf.open(out) as pdf:
        marks = [list(i.operands) for i in pikepdf.parse_content_stream(pdf.pages[0]) if str(i.operator) == "BDC"]
    merged = [m for m in marks if isinstance(m[1], pikepdf.Dictionary) and "/ActualText" in m[1]]
    assert merged and "/MCID" in merged[0][1], "ActualText must survive and sit on the tagged mark"


def test_invalid_tounicode_repaired_from_actualtext(sample_pdf, tmp_path, settings, need_verapdf):
    broken = tmp_path / "chrome-like.pdf"
    code, base_font = _break_bullet_glyph(sample_pdf, broken)
    out = tmp_path / "out.pdf"
    r = remediate_file(broken, out, display_name="c.pdf", settings=settings,
                       options=Options(engine="basic", alts={0: "Blue chart"}))
    assert any(i["rule"] == "fonts.tounicode-repaired" for i in r["issues"])
    assert not any(i["rule"].startswith("verapdf.7.21.7") for i in r["issues"])
    with pikepdf.open(out) as pdf:
        font = next(f for _, f in pdf.pages[0].Resources.Font.items() if str(f.BaseFont) == base_font)
        assert f"<{code}> <2022>" in font.ToUnicode.read_bytes().decode("latin-1")
    assert "•" in page_texts(out)[0]
