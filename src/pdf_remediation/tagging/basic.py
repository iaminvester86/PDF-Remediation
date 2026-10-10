"""The built-in tagging engine. Needs only pikepdf and PDFium.

Stages, all on the original drawing operators so appearance never changes:

  A. scan        pair content-stream operators with PDFium objects (pdf/content.py)
  B. layout      lines, running headers/footers, body size (layout.py)
  C. blocks      tables (tables.py), paragraphs, figures, headings, lists
  D. structure   nodes, annotations, marked content, StructTreeRoot (writer.py)

Works best on born-digital documents and OCR'd scans. Limits (raised as review
issues rather than guessed): nested lists, row-spanning cells, multi-column
reading order beyond content order.
"""
from __future__ import annotations

import pikepdf
import pypdfium2 as pdfium
from pikepdf import Dictionary

from ..issues import Issue
from ..pdf.content import Item, scan, strip_structure_marks
from ..pdf.pdfium import PageInfo, read_page
from . import layout
from .model import Block, Line, Node, Table, TagResult
from .tables import detect_tables
from .writer import attach_annotations, mark_page_content, remove_existing_structure, write_structure


def tag_document(pdf: pikepdf.Pdf, pdfium_doc: pdfium.PdfDocument) -> TagResult:
    result = TagResult(pages_total=len(pdf.pages))
    remove_existing_structure(pdf)

    # A. scan every page
    pages: list[_Page] = []
    for idx, page in enumerate(pdf.pages):
        raw = [(list(ins.operands), ins.operator) for ins in pikepdf.parse_content_stream(page)]
        ops, _ = strip_structure_marks(raw)
        info = read_page(pdfium_doc, idx)
        items, matched = scan(ops, page.obj.get("/Resources", Dictionary()), info.objects)
        mb = [float(v) for v in page.mediabox]
        box = (min(mb[0], mb[2]), min(mb[1], mb[3]), max(mb[0], mb[2]), max(mb[1], mb[3]))
        p = _Page(idx, ops, items, matched, box, info)
        if matched:
            result.pages_matched += 1
            text_items = [it for it in items if it.kind == "text" and it.obj and it.obj.text.strip()]
            p.lines = layout.group_lines(idx, text_items)
        else:
            result.issues.append(Issue(
                "tagger.page-unmapped", "warning",
                "Page content could not be matched to layout objects, so it was tagged in content order "
                "without heading, list or table detection. Review this page's structure.",
                page=idx + 1, source="tagger", wcag=["1.3.1", "1.3.2"]))
        pages.append(p)

    # B. document-wide layout facts
    layout.mark_running_artifacts([p.lines for p in pages], [p.box for p in pages])
    body, body_styles = layout.body_style([p.lines for p in pages])

    # C. blocks per page, then headings and lists across the document
    for p in pages:
        p.blocks = _blocks(p, result) if p.matched else _unmapped_blocks(p)
    layout.assign_headings([p.blocks for p in pages], body, body_styles)
    layout.assign_lists([p.blocks for p in pages])

    # D. structure
    doc_node = Node("Document")
    open_list: Node | None = None
    for p in pages:
        page_nodes: list[Node] = []
        for b in p.blocks:
            if b.role == "LI":
                if open_list is None:
                    open_list = Node("L", p.idx, attrs={"O": "/List",
                                                        "ListNumbering": "/Disc" if b.marker == "bullet" else "/Decimal"})
                    page_nodes.append(open_list)
                open_list.kids.append(_list_item(b))
                continue
            open_list = None
            page_nodes.append(_node_for(b, result))
        for f in result.figures:
            if f["page"] == p.idx and not f["context"]:
                f["context"] = layout.figure_context(p.blocks, f["bbox"])
        attach_annotations(pdf.pages[p.idx], p.idx, page_nodes, result)
        doc_node.kids.extend(page_nodes)

    parent_entries: dict[int, list[Node]] = {}
    for p in pages:
        owners = mark_page_content(pdf, pdf.pages[p.idx], p.ops, p.items)
        if owners:
            parent_entries[p.idx] = owners
    write_structure(pdf, doc_node, parent_entries)

    result.title_candidate = next((h["text"].strip() for h in result.headings
                                   if h["level"] == 1 and h["text"].strip()), "")
    return result


class _Page:
    def __init__(self, idx: int, ops: list, items: list[Item], matched: bool, box: tuple, info: PageInfo):
        self.idx, self.ops, self.items, self.matched, self.box, self.info = idx, ops, items, matched, box, info
        self.lines: list[Line] = []
        self.blocks: list[Block] = []


def _blocks(p: _Page, result: TagResult) -> list[Block]:
    """Blocks of a mapped page in content (reading) order."""
    x0, y0, x1, y1 = p.box
    page_area = max((x1 - x0) * (y1 - y0), 1.0)
    content_lines = [ln for ln in p.lines if not ln.items[0].artifact]

    tables, content_lines, rejected = detect_tables(p.idx, content_lines, p.info.segments)
    ordered: list[tuple[int, Block]] = [(t.start, Block(p.idx, "table", table=t)) for t in tables]
    if tables:
        result.tables += len(tables)
        result.issues.append(Issue(
            "tagger.table-headers-assumed", "warning",
            f"{len(tables)} table(s) tagged on this page with the top row(s) as column headers. Check the "
            "headers and any merged cells.", page=p.idx + 1, source="tagger", wcag=["1.3.1"], matterhorn=["15-003"]))
    if rejected:
        result.issues.append(Issue(
            "tagger.possible-table", "warning",
            "Text is laid out in aligned columns that may be a table, but it did not meet the rules for "
            "automatic table tagging. Check whether it should be a table.",
            page=p.idx + 1, source="tagger", wcag=["1.3.1"], matterhorn=["15-003"]))

    ordered += [(b.lines[0].items[0].start, b) for b in layout.group_blocks(p.idx, content_lines)]

    invisible_text = [it for it in p.items if it.kind == "text" and it.obj and it.obj.invisible]
    has_visible_text = any(not ln.items[0].obj.invisible for ln in content_lines)
    for it in p.items:
        if it.kind not in ("image", "inline", "form") or it.obj is None:
            continue
        b = it.obj.bbox
        area = max((b[2] - b[0]) * (b[3] - b[1]), 0.0)
        if it.kind == "form" and it.obj.form_has_text:
            ordered.append((it.start, Block(p.idx, "form-text", item=it)))
        elif it.kind == "form" and not it.obj.form_has_image:
            it.artifact = "Layout"
        elif area / page_area < 0.0025 or min(b[2] - b[0], b[3] - b[1]) < 8:
            it.artifact = "Layout"
        elif area / page_area > 0.5 and _covers_text_layer(b, invisible_text):
            it.artifact = "Layout"  # a scanned page image under its OCR text: the text is the content
        else:
            ordered.append((it.start, Block(p.idx, "figure", item=it, role="Figure")))
            if area / page_area > 0.8 and not has_visible_text and not invisible_text:
                result.issues.append(Issue(
                    "tagger.scanned-page", "error",
                    "This page is a scanned image with no text layer. Enable OCR, then remediate again.",
                    page=p.idx + 1, source="tagger", wcag=["1.1.1", "1.4.5"], matterhorn=["08-001"]))
    ordered.sort(key=lambda t: t[0])
    return [b for _, b in ordered]


def _covers_text_layer(bbox, invisible_items: list[Item]) -> bool:
    inside = 0
    for it in invisible_items:
        cx = (it.obj.bbox[0] + it.obj.bbox[2]) / 2
        cy = (it.obj.bbox[1] + it.obj.bbox[3]) / 2
        if bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]:
            inside += 1
    return inside >= 2


def _unmapped_blocks(p: _Page) -> list[Block]:
    """Fallback when PDFium objects could not be paired with operators: content order only."""
    by_bt: dict[int, Block] = {}
    ordered: list[Block] = []
    for it in p.items:
        if it.kind == "text":
            blk = by_bt.get(it.bt_index)
            if blk is None:
                blk = by_bt[it.bt_index] = Block(p.idx, "unmapped-text")
                ordered.append(blk)
            blk.lines.append(Line(p.idx, [it]))
        elif it.kind in ("image", "inline"):
            ordered.append(Block(p.idx, "figure", item=it, role="Figure"))
        elif it.kind == "form":
            ordered.append(Block(p.idx, "form-text", item=it))
    return ordered


def _own(node: Node, items: list[Item]) -> Node:
    for it in items:
        it.owner = node
        node.kids.append(it)
    return node


def _list_item(b: Block) -> Node:
    li = Node("LI", b.page)
    items = b.items
    first = items[0].obj.text if items and items[0].obj else ""
    if len(items) > 1 and layout.MARKER_ONLY_RE.match(first or ""):
        li.kids.append(_own(Node("Lbl", b.page), items[:1]))
        items = items[1:]
    li.kids.append(_own(Node("LBody", b.page, text=b.text), items))
    return li


def _table_node(t: Table) -> Node:
    table = Node("Table", t.page)
    for r in range(t.n_rows):
        row = Node("TR", t.page)
        for cell in sorted((c for c in t.cells if c.row == r), key=lambda c: c.col):
            attrs = {"O": "/Table"}
            if cell.header:
                attrs["Scope"] = "/Column"
            if cell.colspan > 1:
                attrs["ColSpan"] = cell.colspan
            if cell.rowspan > 1:
                attrs["RowSpan"] = cell.rowspan
            row.kids.append(_own(Node("TH" if cell.header else "TD", t.page, attrs=attrs), cell.items))
        table.kids.append(row)
    return table


def _node_for(b: Block, result: TagResult) -> Node:
    if b.kind == "table":
        return _table_node(b.table)
    if b.kind == "figure":
        result.figures.append({"index": len(result.figures), "page": b.page, "bbox": list(b.bbox), "context": ""})
        return _own(Node("Figure", b.page), b.items)
    if b.kind == "text":
        node = _own(Node(b.role, b.page, text=b.text), b.items)
        if b.role.startswith("H"):
            result.headings.append({"level": int(b.role[1]), "text": b.text, "page": b.page, "top": b.bbox[3]})
        return node
    return _own(Node("P", b.page), b.items)
