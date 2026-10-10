from __future__ import annotations

from collections import defaultdict

import pikepdf
import pypdfium2 as pdfium
import pytest

from pdf_remediation.pdf.pdfium import read_page
from pdf_remediation.pdf.structure import read_tree
from pdf_remediation.pipeline import Options, remediate_file

from conftest import make_aligned_table, make_ruled_table, make_spanned_table


def _rows(path):
    """Table rows as lists of (role, text) from the structure tree."""
    doc = pdfium.PdfDocument(str(path))
    text = defaultdict(str)
    for i in range(len(doc)):
        for o in read_page(doc, i).objects:
            if o.kind == "text" and o.mcid >= 0:
                text[(i, o.mcid)] += o.text
    doc.close()

    def cell_text(e):
        return " ".join("".join(text[m] for m in e.all_mcids()).split())

    with pikepdf.open(path) as pdf:
        tables = [e for e in read_tree(pdf).walk() if e.role == "Table"]
        return [[[(c.role, cell_text(c)) for c in tr.children if c.role in ("TH", "TD")]
                 for tr in table.walk() if tr.role == "TR"] for table in tables]


def _run(src, tmp_path, settings):
    out = tmp_path / "out" / src.name
    r = remediate_file(src, out, display_name=src.name, settings=settings,
                       options=Options(engine="basic", verapdf=False))
    assert r["status"] != "failed", r.get("error")
    return r, out


def test_ruled_table(tmp_path, settings):
    r, out = _run(make_ruled_table(tmp_path / "ruled.pdf"), tmp_path, settings)
    tables = _rows(out)
    assert len(tables) == 1
    rows = tables[0]
    assert rows[0] == [("TH", "Program"), ("TH", "FY2025"), ("TH", "FY2026")]
    assert rows[1] == [("TD", "Remediation"), ("TD", "$1.2M"), ("TD", "$2.0M")]
    assert len(rows) == 4
    assert r["visual"]["identical"] and r["text"]["identical"]
    assert "tagger.table-headers-assumed" in {i["rule"] for i in r["issues"]}


def test_spanned_header_cells(tmp_path, settings):
    r, out = _run(make_spanned_table(tmp_path / "spanned.pdf"), tmp_path, settings)
    (rows,) = _rows(out)
    assert rows[0] == [("TH", "Program"), ("TH", "Funding"), ("TH", "Notes")]
    assert rows[1] == [("TH", "FY2025"), ("TH", "FY2026")]  # cells under the spans are not repeated
    assert rows[2][:3] == [("TD", "Remediation"), ("TD", "$1.2M"), ("TD", "$2.0M")]
    with pikepdf.open(out) as pdf:
        spans = [(e.role, int(e.raw.A.get("/RowSpan", 1)), int(e.raw.A.get("/ColSpan", 1)))
                 for e in read_tree(pdf).walk() if e.role == "TH"]
    assert spans[:3] == [("TH", 2, 1), ("TH", 1, 2), ("TH", 2, 1)]
    assert r["visual"]["identical"] and r["text"]["identical"]


def test_aligned_table_and_prose(tmp_path, settings):
    r, out = _run(make_aligned_table(tmp_path / "aligned.pdf"), tmp_path, settings)
    tables = _rows(out)
    assert len(tables) == 1, "the two-column prose block must not become a table"
    rows = tables[0]
    assert len(rows) == 5
    assert rows[0][0] == ("TH", "School")
    assert ("TD", "Jefferson High") in rows[3] and ("TD", "1,204") in rows[3]
    assert "tagger.possible-table" not in {i["rule"] for i in r["issues"]}
    assert r["visual"]["identical"] and r["text"]["identical"]


@pytest.mark.parametrize("make", [make_ruled_table, make_spanned_table, make_aligned_table])
def test_tables_pass_verapdf(tmp_path, settings, need_verapdf, make):
    src = make(tmp_path / "table.pdf")
    r = remediate_file(src, tmp_path / "out" / "table.pdf", display_name="table.pdf", settings=settings,
                       options=Options(engine="basic"))
    assert r["summary"]["machine_validation"] == "pass", r["verapdf"]


def test_sparse_columns_are_flagged_not_tagged(tmp_path, settings):
    """Aligned short values that do not fill a grid are left as text with a warning for review."""
    from conftest import _fonts
    from reportlab.pdfgen import canvas

    _fonts()
    path = tmp_path / "sparse.pdf"
    c = canvas.Canvas(str(path))
    c.setFont("Vera", 10)
    xs = (72, 200, 330, 460)
    for r, cols in enumerate([(0, 1), (2, 3), (0, 2), (1, 3)]):
        for col in cols:
            c.drawString(xs[col], 700 - 16 * r, f"Item {r}{col}")
    c.save()
    r, out = _run(path, tmp_path, settings)
    assert _rows(out) == []
    assert "tagger.possible-table" in {i["rule"] for i in r["issues"]}
