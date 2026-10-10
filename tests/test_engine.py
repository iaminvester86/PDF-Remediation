from __future__ import annotations

import pikepdf
from reportlab.pdfgen import canvas

from pdf_remediation.edit import apply_figure_decisions
from pdf_remediation.pipeline import Options, remediate_file
from pdf_remediation.qa import run_qa
from pdf_remediation.structtree import read_tree


def roles(path):
    with pikepdf.open(path) as pdf:
        tree = read_tree(pdf)
        return [e.role for e in tree.walk()]


def test_basic_engine_structure(sample_pdf, tmp_path, settings):
    out = tmp_path / "out" / "sample.pdf"
    r = remediate_file(sample_pdf, out, display_name="sample.pdf", settings=settings,
                       options=Options(engine="basic", verapdf=False))
    assert r["status"] != "failed", r.get("error")
    rs = roles(out)
    assert "H1" in rs and "H2" in rs
    assert rs.count("LI") == 4 and "Lbl" in rs and "LBody" in rs
    assert "Figure" in rs and "Link" in rs
    # rendering and text must be unchanged by tagging
    assert r["visual"]["identical"], r["visual"]
    assert r["text"]["identical"], r["text"]
    # title from first heading, page numbers as artifacts (not in structure)
    assert r["document"]["title"] == "Annual Accessibility Report"
    assert all("Page 1" != h["text"] for h in r["headings"])
    with pikepdf.open(out) as pdf:
        assert pdf.Root.MarkInfo.Marked
        assert str(pdf.Root.Lang) == "en-US"
        assert "/Outlines" in pdf.Root  # bookmarks from headings on multi-page documents
        annot = pdf.pages[0].Annots[0]
        assert "/StructParent" in annot and str(annot.Contents)


def test_basic_engine_detects_simple_table_layout(tmp_path, settings):
    src = tmp_path / "table.pdf"
    c = canvas.Canvas(str(src))
    header = ("Name", "Score", "Status")
    rows = (("Alice", "91", "Pass"), ("Bob", "78", "Review"), ("Cara", "94", "Pass"))
    c.setFont("Times-Bold", 12)
    for col_index, text in enumerate(header):
        c.drawString(72 + col_index * 140, 760, text)
    for row_index, row in enumerate(rows, start=1):
        c.setFont("Times-Roman", 11)
        for col_index, text in enumerate(row):
            c.drawString(72 + col_index * 140, 760 - row_index * 36, text)
    c.save()

    out = tmp_path / "out" / "table.pdf"
    r = remediate_file(src, out, display_name="table.pdf", settings=settings,
                       options=Options(engine="basic", verapdf=False))
    assert r["status"] != "failed", r.get("error")
    roles_out = roles(out)
    assert "Table" in roles_out and "TR" in roles_out and "TH" in roles_out and "TD" in roles_out


def test_missing_alt_is_reported_then_fixed(sample_pdf, tmp_path, settings, need_verapdf):
    out = tmp_path / "out" / "sample.pdf"
    r = remediate_file(sample_pdf, out, display_name="sample.pdf", settings=settings,
                       options=Options(engine="basic"))
    rules = {i["rule"] for i in r["issues"]}
    assert "sqa.alt-missing" in rules
    assert r["summary"]["machine_validation"] == "fail"  # 7.3: figure without alt
    apply_figure_decisions(out, out, {0: "Blue bar chart of yearly budget growth"}, set())
    r2 = remediate_file(sample_pdf, tmp_path / "out2" / "sample.pdf", display_name="sample.pdf",
                        settings=settings, options=Options(engine="basic", alts={0: "Blue bar chart of growth"}))
    assert r2["summary"]["machine_validation"] == "pass", r2["verapdf"]
    assert r2["status"] == "ready-for-review"
    assert r2["summary"]["human_verification"] == "not done"


def test_decorative_figure_becomes_artifact(sample_pdf, tmp_path, settings, need_verapdf):
    out = tmp_path / "out" / "sample.pdf"
    remediate_file(sample_pdf, out, display_name="sample.pdf", settings=settings, options=Options(engine="basic"))
    info = apply_figure_decisions(out, out, {}, {0})
    assert info["decorative"] == 1 and not info["errors"]
    assert "Figure" not in roles(out)
    from pdf_remediation.verify import run_verapdf
    assert run_verapdf(out, settings)["compliant"] is True


def test_qa_catches_semantics_validators_miss(sample_pdf, tmp_path, settings):
    """The spike-001 lesson: swap heading/paragraph roles and use placeholder alt text."""
    out = tmp_path / "out" / "sample.pdf"
    remediate_file(sample_pdf, out, display_name="sample.pdf", settings=settings,
                   options=Options(engine="basic", verapdf=False))
    with pikepdf.open(out, allow_overwriting_input=True) as pdf:
        tree = read_tree(pdf)
        h1 = next(e for e in tree.walk() if e.role == "H1")
        p = next(e for e in tree.walk() if e.role == "P")
        h1.raw.S, p.raw.S = pikepdf.Name.P, pikepdf.Name.H1
        fig = next(e for e in tree.walk() if e.role == "Figure")
        fig.raw.Alt = pikepdf.String("image")
        pdf.save(out)
    rules = {i.rule for i in run_qa(out).issues}
    assert "sqa.alt-placeholder" in rules
    assert "sqa.heading-body-text" in rules
    assert "sqa.heading-untagged" in rules


def test_retag_existing_bad_tags_and_keep_alt(sample_pdf, tmp_path, settings):
    first = tmp_path / "first.pdf"
    remediate_file(sample_pdf, first, display_name="first.pdf", settings=settings,
                   options=Options(engine="basic", verapdf=False, alts={0: "Budget chart"}))
    with pikepdf.open(first, allow_overwriting_input=True) as pdf:  # break the headings
        for e in read_tree(pdf).walk():
            if e.role in ("H1", "H2"):
                e.raw.S = pikepdf.Name.P
        pdf.save(first)
    second = tmp_path / "second.pdf"
    r = remediate_file(first, second, display_name="second.pdf", settings=settings,
                       options=Options(engine="basic", verapdf=False))
    steps = {s["step"]: s["detail"] for s in r["steps"]}
    assert steps["existing-tags"].startswith("replaced"), steps
    assert "H1" in roles(second)
    assert r["figures"][0]["alt"] == "Budget chart"  # carried over by position


def test_unreadable_file_fails_gracefully(tmp_path, settings):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7\nthis is not really a pdf")
    r = remediate_file(bad, tmp_path / "out" / "bad.pdf", display_name="bad.pdf", settings=settings,
                       options=Options(verapdf=False))
    assert r["status"] == "failed" and r["error"]


def test_placeholder_alt_is_removed_so_validation_is_honest(sample_pdf, tmp_path, settings, need_verapdf):
    first = tmp_path / "first.pdf"
    remediate_file(sample_pdf, first, display_name="first.pdf", settings=settings,
                   options=Options(engine="basic", verapdf=False, alts={0: "image 1"}))
    out = tmp_path / "out.pdf"
    r = remediate_file(first, out, display_name="first.pdf", settings=settings,
                       options=Options(existing_tags="keep"))
    assert any("placeholder" in s["detail"] for s in r["steps"])
    assert r["figures"][0]["alt"] is None
    assert r["summary"]["machine_validation"] == "fail"  # no longer a misleading pass
