"""Semantic QA: checks that a PDF/UA validator cannot make.

Spike 001 showed a file with swapped heading/paragraph roles, reversed reading
order and alt text "image" passing veraPDF. These rules look for exactly that
kind of problem using the structure tree plus PDFium geometry. They produce
review flags, never a pass/fail verdict on their own.
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

import pikepdf
import pypdfium2 as pdfium

from .finisher import existing_title, is_generic_title
from .issues import Issue
from .pdfium_util import PObj, read_page
from .structtree import Elem, figures, read_tree
from .tagger import BULLET_RE

ALT_PLACEHOLDER_RE = re.compile(
    r"^\s*(image|img|picture|pic|photo|graphic|figure|chart|logo|icon|untitled|alt|alt text|"
    r"image\s*\d+|figure\s*\d+|img[_\-\s]?\d+|dsc[_\-]?\d+|\S+\.(png|jpe?g|gif|bmp|tiff?|svg|emf|wmf))\s*$",
    re.I,
)
ALT_REDUNDANT_RE = re.compile(r"^\s*(an?\s+)?(image|picture|photo|graphic)\s+of\b", re.I)
VAGUE_LINK_RE = re.compile(r"^\s*(click here|here|more|read more|learn more|link|this link|click|details)\s*[.!]?\s*$",
                           re.I)
URL_RE = re.compile(r"^\s*(https?://|www\.)\S+\s*$", re.I)


@dataclass
class ElemInfo:
    elem: Elem
    text: str = ""
    size: float = 0.0
    bbox: tuple | None = None
    page: int | None = None
    bold: bool = False


@dataclass
class QAResult:
    issues: list[Issue] = field(default_factory=list)
    figures: list[dict] = field(default_factory=list)
    headings: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _info(e: Elem, objs: dict) -> ElemInfo:
    texts, sizes, boxes, pages = [], [], [], []
    bold_chars = plain_chars = 0
    prev = None
    for page, mcid in e.all_mcids():
        for o in objs.get((page, mcid), []):
            if o.kind == "text" and o.text:
                # Some generators draw one glyph per operator; only add a space at a real gap.
                if prev is not None and texts and not texts[-1].endswith(" ") and not o.text.startswith(" "):
                    gap = o.bbox[0] - prev.bbox[2]
                    new_line = abs(o.bbox[1] - prev.bbox[1]) > 0.5 * max(o.size, prev.size, 1.0)
                    if new_line or gap > 0.15 * max(o.size, 1.0):
                        texts.append(" ")
                prev = o
                texts.append(o.text)
                sizes.append((len(o.text.strip()) or 1, o.size))
                if o.bold:
                    bold_chars += len(o.text.strip())
                else:
                    plain_chars += len(o.text.strip())
            if o.kind in ("text", "image", "form"):
                boxes.append(o.bbox)
            pages.append(page)
    text = re.sub(r"\s+", " ", "".join(texts)).strip()
    size = (sum(w * s for w, s in sizes) / sum(w for w, _ in sizes)) if sizes else 0.0
    bbox = None
    if boxes:
        bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    page = pages[0] if pages else e.page
    return ElemInfo(e, text, size, bbox, page, bold=bold_chars > plain_chars)


def run_qa(path) -> QAResult:
    res = QAResult()
    pdf = pikepdf.open(path)
    doc = pdfium.PdfDocument(str(path))
    try:
        _run(pdf, doc, res)
    finally:
        doc.close()
        pdf.close()
    return res


def _run(pdf: pikepdf.Pdf, doc: pdfium.PdfDocument, res: QAResult) -> None:
    add = res.issues.append
    n_pages = len(pdf.pages)
    objs: dict[tuple[int, int], list[PObj]] = defaultdict(list)
    page_infos = []
    non_embedded: dict[str, int] = {}
    for i in range(n_pages):
        info = read_page(doc, i)
        page_infos.append(info)
        has_text = False
        big_image = False
        for o in info.objects:
            if o.mcid >= 0:
                objs[(i, o.mcid)].append(o)
            if o.kind == "text" and o.text.strip():
                has_text = True
                if not o.embedded:
                    non_embedded.setdefault(o.font or "(unnamed)", i + 1)
            if o.kind == "image":
                b = o.bbox
                if (b[2] - b[0]) * (b[3] - b[1]) > 0.8 * info.width * info.height:
                    big_image = True
        if big_image and not has_text:
            add(Issue("sqa.scanned-page", "error", "Page is an image with no text layer. It needs OCR.",
                      page=i + 1, wcag=["1.1.1", "1.4.5"], matterhorn=["08-001"],
                      fix="Run OCR (install the 'ocr' extra plus Tesseract), then remediate again."))

    for font, page in non_embedded.items():
        add(Issue("sqa.font-not-embedded", "error",
                  f"Font '{font}' is used for visible text but is not embedded. Tagging cannot fix this.",
                  page=page, matterhorn=["31-001"],
                  fix="Re-export the source document with fonts embedded (most Office 'Save as PDF' "
                      "options embed fonts), then remediate again."))

    root = pdf.Root
    title = existing_title(pdf)
    if is_generic_title(title):
        add(Issue("sqa.title-generic", "error", f"Document title is missing or generic ('{title}').",
                  wcag=["2.4.2"], matterhorn=["06-003"]))
    if not str(root.get("/Lang", "")).strip():
        add(Issue("sqa.lang-missing", "error", "Document language (/Lang) is not set.", wcag=["3.1.1"],
                  matterhorn=["11-006"]))

    tree = read_tree(pdf)
    if tree is None or not tree.children:
        add(Issue("sqa.untagged", "error", "The document has no structure tree (it is untagged).",
                  wcag=["1.3.1"], matterhorn=["01-005"]))
        return

    infos: dict[int, ElemInfo] = {}
    for e in tree.walk():
        if e is tree:
            continue
        infos[id(e)] = _info(e, objs)

    # Figures
    for idx, f in enumerate(figures(tree)):
        fi = infos[id(f)]
        alt = (f.alt or "").strip()
        entry = {"index": idx, "page": fi.page if fi.page is not None else 0,
                 "bbox": list(fi.bbox) if fi.bbox else None, "alt": f.alt, "context": _context_for(f, infos)}
        res.figures.append(entry)
        page = (fi.page + 1) if fi.page is not None else None
        if f.alt is None and not f.actual_text:
            add(Issue("sqa.alt-missing", "error", f"Figure {idx + 1} has no alternative text.", page=page,
                      wcag=["1.1.1"], matterhorn=["13-004"],
                      fix="Write alt text in the Figures section, or mark the image as decorative."))
        elif ALT_PLACEHOLDER_RE.match(alt) or not alt:
            add(Issue("sqa.alt-placeholder", "error",
                      f"Figure {idx + 1} alt text '{alt}' is a placeholder, not a description.", page=page,
                      wcag=["1.1.1"], matterhorn=["13-004"]))
        elif ALT_REDUNDANT_RE.match(alt):
            add(Issue("sqa.alt-redundant", "warning",
                      f"Figure {idx + 1} alt text starts with 'image of'; screen readers already announce "
                      "the role.", page=page, wcag=["1.1.1"]))
        elif len(alt) > 300:
            add(Issue("sqa.alt-long", "warning",
                      f"Figure {idx + 1} alt text is {len(alt)} characters. Consider a short alt plus a "
                      "longer description in the text.", page=page, wcag=["1.1.1"]))

    # Headings
    body_sizes = [i.size for i in infos.values() if i.elem.role == "P" and i.size > 0 and len(i.text) > 40]
    body = statistics.median(body_sizes) if body_sizes else 0.0
    heads = [i for i in infos.values() if re.fullmatch(r"H[1-6]?", i.elem.role)]
    ordered_heads = [infos[id(e)] for e in tree.walk() if e is not tree and re.fullmatch(r"H[1-6]", e.role)]
    for h in ordered_heads:
        res.headings.append({"level": int(h.elem.role[1]), "text": h.text, "page": h.page or 0,
                             "top": h.bbox[3] if h.bbox else None})
    if body:
        for h in heads:
            if 0 < h.size < body * 0.95:
                add(Issue("sqa.heading-small", "warning",
                          f"Heading '{h.text[:60]}' is set in smaller type than body text. It may be "
                          "mis-tagged.", page=(h.page or 0) + 1, wcag=["1.3.1", "2.4.6"], matterhorn=["14-001"]))
            elif 0 < h.size <= body * 1.02 and not h.bold and len(h.text) > 120:
                add(Issue("sqa.heading-body-text", "warning",
                          f"Heading '{h.text[:60]}...' looks like body text (long, regular weight, body size). "
                          "It may be a paragraph tagged as a heading.", page=(h.page or 0) + 1,
                          wcag=["1.3.1", "2.4.6"], matterhorn=["14-001"]))
        max_head = max((h.size for h in heads), default=0.0)
        for i in infos.values():
            if i.elem.role == "P" and i.text and len(i.text) <= 100 and i.size >= max(body * 1.3, max_head * 1.05):
                add(Issue("sqa.heading-untagged", "warning",
                          f"Short text in large type ('{i.text[:60]}') is tagged as a paragraph. It may be a "
                          "heading.", page=(i.page or 0) + 1, wcag=["1.3.1", "2.4.6"], matterhorn=["14-001"]))
    n_paras = sum(1 for i in infos.values() if i.elem.role == "P")
    if not heads and (n_pages >= 2 or n_paras >= 8):
        add(Issue("sqa.no-headings", "warning", "The document has no headings, so it cannot be navigated by "
                  "heading.", wcag=["1.3.1", "2.4.6"], matterhorn=["14-002"]))
    prev = 0
    for h in ordered_heads:
        level = int(h.elem.role[1])
        if prev and level > prev + 1:
            add(Issue("sqa.heading-skip", "info",
                      f"Heading level jumps from H{prev} to H{level} at '{h.text[:60]}'.",
                      page=(h.page or 0) + 1, wcag=["1.3.1"], matterhorn=["14-003"]))
        prev = level
    if ordered_heads and int(ordered_heads[0].elem.role[1]) != 1:
        add(Issue("sqa.heading-first-not-h1", "info", "The first heading is not level 1.",
                  wcag=["1.3.1"], matterhorn=["14-002"]))

    # Reading order: content that jumps back up the same column
    seq_by_page: dict[int, list[ElemInfo]] = defaultdict(list)
    for e in tree.walk():
        if e is tree or e.role not in {"P", "H", "H1", "H2", "H3", "H4", "H5", "H6", "LI", "Figure", "Caption"}:
            continue
        i = infos[id(e)]
        if i.bbox and i.page is not None:
            seq_by_page[i.page].append(i)
    for page, seq in seq_by_page.items():
        if len(seq) < 3:
            continue
        back = 0
        for a, b in zip(seq, seq[1:]):
            wa, wb = a.bbox[2] - a.bbox[0], b.bbox[2] - b.bbox[0]
            overlap = min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0])
            same_column = overlap > 0.5 * max(min(wa, wb), 1)
            line = max(a.size, b.size, 8.0)
            if same_column and b.bbox[1] > a.bbox[3] + 1.5 * line:
                back += 1
        if back / (len(seq) - 1) > 0.25:
            add(Issue("sqa.reading-order", "warning",
                      f"Reading order moves back up the page {back} times in {len(seq)} blocks. Check that "
                      "the order is logical.", page=page + 1, wcag=["1.3.2"], matterhorn=["09-001"]))

    # Lists, links, tables
    for i in infos.values():
        if i.elem.role == "P" and BULLET_RE.match(i.text or ""):
            add(Issue("sqa.list-untagged", "warning",
                      f"Paragraph starting with a bullet ('{i.text[:50]}') is not tagged as a list item.",
                      page=(i.page or 0) + 1, wcag=["1.3.1"], matterhorn=["16-001"]))
        if i.elem.role == "Link":
            text = i.text
            if VAGUE_LINK_RE.match(text or ""):
                add(Issue("sqa.link-vague", "warning", f"Link text '{text}' does not describe its destination.",
                          page=(i.page or 0) + 1, wcag=["2.4.4"]))
            elif URL_RE.match(text or ""):
                add(Issue("sqa.link-url", "info", "Link text is a bare URL; screen readers read it character "
                          "by character.", page=(i.page or 0) + 1, wcag=["2.4.4"]))
        if i.elem.role == "Table":
            if not any(c.role == "TH" for c in i.elem.walk()):
                add(Issue("sqa.table-no-headers", "error", "Table has no header cells (TH).",
                          page=(i.page or 0) + 1, wcag=["1.3.1"], matterhorn=["15-003"]))

    res.stats = {"pages": n_pages, "elements": len(infos), "headings": len(heads), "figures": len(res.figures),
                 "body_font_size": round(body, 1)}


def alt_needs_work(alt: str | None) -> bool:
    """True when a figure's alt text is missing, empty or a placeholder."""
    return not (alt or "").strip() or bool(ALT_PLACEHOLDER_RE.match(alt or ""))


def _context_for(fig: Elem, infos: dict) -> str:
    parent = fig.parent
    if parent is None:
        return ""
    sibs = parent.children
    try:
        k = sibs.index(fig)
    except ValueError:
        return ""
    fig_page = infos[id(fig)].page if id(fig) in infos else fig.page
    for j in (k + 1, k - 1, k + 2, k - 2):
        if 0 <= j < len(sibs) and id(sibs[j]) in infos:
            info = infos[id(sibs[j])]
            if info.text and info.page == fig_page:
                return info.text[:400]
    return ""
