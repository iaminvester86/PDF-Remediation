"""Feasibility spike: retro-tag an untagged PDF with pikepdf only, then validate with veraPDF.

Usage: python spike.py OUTDIR {embed|noembed} [--wrong-semantics]

--wrong-semantics deliberately swaps the H1/P roles, reverses reading order and
uses "image" as alt text. It exists to show what a validator cannot detect.

Steps:
 1. Build an untagged PDF with reportlab (heading, paragraph, image, footer).
 2. Rewrite the page content stream: wrap each BT..ET text block and each image
    draw in BDC/EMC with an MCID; mark the footer as /Artifact.
 3. Build StructTreeRoot -> Document -> H1/P/Figure(+Alt)/P, ParentTree, RoleMap-free.
 4. Set /MarkInfo, /Lang, /Title, DisplayDocTitle, /Tabs /S, XMP pdfuaid:part=1.
"""
import sys
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, Operator, String
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

out = Path(sys.argv[1])
embed = sys.argv[2] == "embed"
wrong = "--wrong-semantics" in sys.argv[3:]
out.mkdir(parents=True, exist_ok=True)
src = out / f"untagged_{sys.argv[2]}.pdf"
dst = out / f"{'wrong' if wrong else 'tagged'}_{sys.argv[2]}.pdf"

# ---- 1. untagged source --------------------------------------------------
c = canvas.Canvas(str(src), pageCompression=0)
if embed:
    pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
    reg, bold = "DV", "DVB"
else:
    reg, bold = "Helvetica", "Helvetica-Bold"
c.setFont(bold, 20); c.drawString(72, 720, "Annual Accessibility Report")
c.setFont(reg, 11); c.drawString(72, 690, "This paragraph explains the purpose of the report.")
from PIL import Image  # noqa: E402  (reportlab dependency)
img = Image.new("RGB", (60, 40), (30, 90, 160))
c.drawImage(ImageReader(img), 72, 600, width=120, height=80)
c.setFont(reg, 8); c.drawString(72, 40, "Page 1")  # footer -> artifact
c.save()

# ---- 2. rewrite content stream with marked content -----------------------
pdf = pikepdf.open(src)
page = pdf.pages[0]
ops = pikepdf.parse_content_stream(page)

# Plan: text blocks in order -> H1, P, (footer=artifact); image Do -> Figure
roles = iter(["P", "H1", "ARTIFACT"] if wrong else ["H1", "P", "ARTIFACT"])
new_ops, mcid_roles, mcid = [], [], 0
in_bt = False
# Lesson from first run: generators emit BT..ET blocks that paint nothing
# (font/leading setup only). Only blocks with text-showing operators get roles.
SHOW = {"Tj", "TJ", "'", '"'}
bt_paints, cur = [], None
for _, op in ops:
    if str(op) == "BT": cur = False
    elif str(op) in SHOW and cur is not None: cur = True
    elif str(op) == "ET": bt_paints.append(cur); cur = None
bt_iter = iter(bt_paints)
for operands, op in ops:
    name = str(op)
    if name == "BT" and not next(bt_iter):
        new_ops.append((operands, op)); in_bt = "empty"; continue
    if name == "ET" and in_bt == "empty":
        new_ops.append((operands, op)); in_bt = False; continue
    if name == "BT":
        role = next(roles)
        if role == "ARTIFACT":
            new_ops.append(([Name.Artifact, Dictionary(Type=Name.Pagination, Subtype=Name.Footer)], Operator("BDC")))
        else:
            new_ops.append(([Name("/" + role), Dictionary(MCID=mcid)], Operator("BDC")))
            mcid_roles.append((role, mcid)); mcid += 1
        new_ops.append((operands, op)); in_bt = True; continue
    if name == "ET":
        new_ops.append((operands, op)); new_ops.append(([], Operator("EMC"))); in_bt = False; continue
    if name == "Do" and not in_bt:
        new_ops.append(([Name.Figure, Dictionary(MCID=mcid)], Operator("BDC")))
        new_ops.append((operands, op)); new_ops.append(([], Operator("EMC")))
        mcid_roles.append(("Figure", mcid)); mcid += 1; continue
    new_ops.append((operands, op))
page.obj.Contents = pdf.make_stream(pikepdf.unparse_content_stream(new_ops))

# ---- 3. structure tree ----------------------------------------------------
root = pdf.make_indirect(Dictionary(Type=Name.StructTreeRoot))
doc = pdf.make_indirect(Dictionary(Type=Name.StructElem, S=Name.Document, P=root, K=Array()))
root.K = doc
parent_array = Array([None] * mcid)
# Reading order = H1, P, Figure (sorted by mcid here; a real tool sorts by layout)
for role, m in sorted(mcid_roles, key=lambda t: -t[1] if wrong else t[1]):
    el = Dictionary(Type=Name.StructElem, S=Name("/" + role), P=doc, Pg=page.obj, K=m)
    if role == "Figure":
        el.Alt = String("image" if wrong else "Blue rectangle used as a sample chart placeholder")
    el = pdf.make_indirect(el)
    doc.K.append(el)
    parent_array[m] = el
root.ParentTree = pdf.make_indirect(Dictionary(Nums=Array([0, pdf.make_indirect(parent_array)])))
root.ParentTreeNextKey = 1
page.obj.StructParents = 0
page.obj.Tabs = Name.S
pdf.Root.StructTreeRoot = root

# ---- 4. document-level requirements --------------------------------------
pdf.Root.MarkInfo = Dictionary(Marked=True)
pdf.Root.Lang = String("en-US")
pdf.Root.ViewerPreferences = Dictionary(DisplayDocTitle=True)
with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
    meta["dc:title"] = "Annual Accessibility Report"
    meta.register_xml_namespace("http://www.aiim.org/pdfua/ns/id/", "pdfuaid")
    meta["pdfuaid:part"] = "1"
pdf.docinfo["/Title"] = "Annual Accessibility Report"
pdf.save(dst)
print("wrote", dst)
