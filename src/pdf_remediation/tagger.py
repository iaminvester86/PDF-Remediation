"""Built-in heuristic tagger (the "basic" engine).

It needs nothing beyond pikepdf and PDFium. It works best on born-digital
documents exported from word processors. It does not detect tables, nested
lists or multi-column reading order beyond the content-stream order; those
cases raise review issues instead of being guessed. The OpenDataLoader engine
(odl.py) is preferred for complex layouts when it is installed.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pikepdf
import pypdfium2 as pdfium
from pikepdf import Array, Dictionary, Name, String

from .contentscan import SHOW_OPS, Item, scan, strip_structure_marks
from .issues import Issue
from .pdfium_util import BBox, read_page

_BULLET_CHARS = re.escape(
    "\u2022\u2023\u25CF\u25CB\u25E6\u25AA\u25AB\u25A0\u2043\u2219\u00B7\u2013\u2014"
    "\u27A2\u2713\u2714\u2756*-\uF0B7\uF0A7\uF076\uF0D8\uF0FC\uF06E"
)
BULLET_RE = re.compile(rf"^\s*[{_BULLET_CHARS}](\s+|$)")
ENUM_RE = re.compile(r"^\s*(\(?\d{1,3}[.)]|\(?[a-z][.)]|\(?[ivx]{1,4}[.)])(\s+|$)")
MARKER_ONLY_RE = re.compile(rf"^\s*([{_BULLET_CHARS}]|\(?\d{{1,3}}[.)]|\(?[a-z][.)]|\(?[ivx]{{1,4}}[.)])\s*$")
PAGE_NUM_RE = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.I)
_DIGITS = re.compile(r"\d+")


@dataclass
class Objr:
    annot: pikepdf.Object
    page: int


@dataclass
class Node:
    role: str
    page: int | None = None
    kids: list = field(default_factory=list)  # Item | Node | Objr
    alt: str | None = None
    attrs: dict = field(default_factory=dict)
    text: str = ""
    bbox: BBox | None = None
    size: float = 0.0
    obj: pikepdf.Dictionary | None = None  # filled when written


@dataclass
class Line:
    page: int
    items: list[Item]

    @property
    def bbox(self) -> BBox:
        bs = [it.obj.bbox for it in self.items]
        return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))

    @property
    def size(self) -> float:
        weights = [(max(len(it.obj.text.strip()), 1), _size(it)) for it in self.items]
        total = sum(w for w, _ in weights)
        return sum(w * s for w, s in weights) / total

    @property
    def bold(self) -> bool:
        chars = Counter()
        for it in self.items:
            chars[it.obj.bold] += max(len(it.obj.text.strip()), 1)
        return chars[True] > chars[False]

    @property
    def text(self) -> str:
        out = ""
        prev = None
        for it in self.items:
            t = it.obj.text
            if prev is not None and out and not out.endswith(" ") and not t.startswith(" "):
                gap = it.obj.bbox[0] - prev.obj.bbox[2]
                if gap > 0.15 * max(_size(it), 1):
                    out += " "
            out += t
            prev = it
        return out


@dataclass
class Block:
    page: int
    kind: str  # text | figure | form-text
    lines: list[Line] = field(default_factory=list)
    item: Item | None = None
    role: str = "P"
    marker: str = ""  # "bullet" | "enum" | ""

    @property
    def text(self) -> str:
        if self.kind != "text":
            return self.item.obj.text if self.item and self.item.obj else ""
        return " ".join(line.text.strip() for line in self.lines).strip()

    @property
    def size(self) -> float:
        if not self.lines:
            return 0.0
        return max(line.size for line in self.lines)

    @property
    def bold(self) -> bool:
        return all(line.bold for line in self.lines) if self.lines else False

    @property
    def bbox(self) -> BBox:
        if self.kind != "text":
            return self.item.obj.bbox if self.item and self.item.obj else (0, 0, 0, 0)
        bs = [line.bbox for line in self.lines]
        return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))

    @property
    def items(self) -> list[Item]:
        if self.kind == "unmapped-text":
            return [it for line in self.lines for it in line.items]
        if self.kind != "text":
            return [self.item]
        return [it for line in self.lines for it in line.items]


@dataclass
class TagResult:
    headings: list[dict] = field(default_factory=list)  # {level, text, page, top}
    figures: list[dict] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    title_candidate: str = ""
    pages_matched: int = 0
    pages_total: int = 0


def _size(it: Item) -> float:
    o = it.obj
    if o is None:
        return 0.0
    if o.size > 0.5:
        return o.size
    return max(o.bbox[3] - o.bbox[1], 1.0)


def _overlap_ratio(a: BBox, b: BBox) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    area = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return (w * h) / area


def remove_existing_structure(pdf: pikepdf.Pdf) -> None:
    root = pdf.Root
    for key in ("/StructTreeRoot", "/MarkInfo"):
        if key in root:
            del root[key]
    for page in pdf.pages:
        if "/StructParents" in page.obj:
            del page.obj["/StructParents"]
        for annot in page.obj.get("/Annots", []) or []:
            if isinstance(annot, pikepdf.Dictionary) and "/StructParent" in annot:
                del annot["/StructParent"]


# ---------------------------------------------------------------------------
# grouping


def _group_lines(page: int, items: list[Item]) -> list[Line]:
    lines: list[Line] = []
    cur: Line | None = None
    for it in items:
        if cur is not None:
            last = cur.items[-1]
            s = max(_size(it), _size(last), 1.0)
            # PDFium bounds are tight glyph boxes, so small glyphs (bullets, punctuation) do not
            # share the text's bottom edge. Vertical overlap identifies them as the same line.
            a, b = it.obj.bbox, last.obj.bbox
            v_overlap = min(a[3], b[3]) - max(a[1], b[1])
            min_h = max(min(a[3] - a[1], b[3] - b[1]), 0.1)
            same_baseline = abs(a[1] - b[1]) <= 0.35 * s or v_overlap >= 0.5 * min_h
            moving_right = it.obj.bbox[0] >= last.obj.bbox[0] - 1.0
            gap = it.obj.bbox[0] - last.obj.bbox[2]
            if same_baseline and moving_right and gap < 2.5 * s:
                cur.items.append(it)
                continue
        cur = Line(page, [it])
        lines.append(cur)
    return lines


def _marker_of(text: str) -> str:
    if BULLET_RE.match(text):
        return "bullet"
    if ENUM_RE.match(text):
        return "enum"
    return ""


def _group_blocks(page: int, lines: list[Line]) -> list[Block]:
    blocks: list[Block] = []
    cur: Block | None = None
    for line in lines:
        marker = _marker_of(line.text)
        if cur is not None and not marker:
            prev = cur.lines[-1]
            ps, ls = prev.size, line.size
            pb, lb = prev.bbox, line.bbox
            similar_size = abs(ls - ps) <= 0.12 * max(ps, 1.0)
            same_weight = prev.bold == line.bold
            gap = pb[1] - lb[3]  # previous line bottom minus this line top (y grows upwards)
            close = -0.4 * ps <= gap <= 0.9 * ps
            overlap = lb[0] < pb[2] and lb[2] > pb[0]
            if similar_size and same_weight and close and overlap:
                cur.lines.append(line)
                continue
        cur = Block(page, "text", lines=[line], marker=marker)
        blocks.append(cur)
    return blocks


def _hf_key(text: str) -> str:
    return _DIGITS.sub("#", text.strip().lower())


def _cluster_positions(values: list[float], default_gap: float = 18.0) -> list[list[float]]:
    if not values:
        return []
    ordered = sorted(values)
    clusters: list[list[float]] = [[ordered[0]]]
    span = max(ordered[-1] - ordered[0], 1.0)
    for value in ordered[1:]:
        gap = value - clusters[-1][-1]
        if gap <= max(default_gap, 0.12 * span):
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return clusters


def _read_order_sort(blocks: list[Block]) -> list[Block]:
    if len(blocks) < 2:
        return blocks
    text_blocks = [b for b in blocks if b.kind == "text" and b.text.strip()]
    if not text_blocks:
        return blocks
    tops = [b.bbox[3] for b in text_blocks]
    row_clusters = _cluster_positions(tops, default_gap=18.0)
    row_index: dict[int, int] = {}
    for idx, cluster in enumerate(row_clusters):
        lo, hi = min(cluster), max(cluster)
        for b in text_blocks:
            top = b.bbox[3]
            if lo <= top <= hi:
                row_index[id(b)] = len(row_clusters) - 1 - idx
    def key(block: Block):
        if block.kind != "text":
            return (1_000_000, 1_000_000, 0)
        row = row_index.get(id(block), 0)
        return (row, block.bbox[0], block.bbox[1])
    return sorted(blocks, key=key)


def _detect_table_layout(blocks: list[Block]) -> dict | None:
    text_blocks = [b for b in blocks if b.kind == "text" and b.text.strip() and len(b.text) < 200]
    if len(text_blocks) < 4:
        return None
    x_centers = [(b.bbox[0] + b.bbox[2]) / 2 for b in text_blocks]
    x_clusters = _cluster_positions(x_centers, default_gap=22.0)
    if len(x_clusters) < 2:
        return None
    rows: list[dict] = []
    for b in text_blocks:
        cy = (b.bbox[1] + b.bbox[3]) / 2
        row = next((r for r in rows if abs(cy - r["mid"]) <= max(8.0, b.size * 0.8)), None)
        if row is None:
            rows.append({"mid": cy, "blocks": [b]})
        else:
            row["blocks"].append(b)
    rows = sorted(rows, key=lambda r: r["mid"], reverse=True)
    valid_rows: list[list[list[Block]]] = []
    for row in rows:
        by_col: dict[int, list[Block]] = {}
        for b in row["blocks"]:
            cx = (b.bbox[0] + b.bbox[2]) / 2
            col = next((i for i, cluster in enumerate(x_clusters) if min(cluster) <= cx <= max(cluster)), 0)
            by_col.setdefault(col, []).append(b)
        if len(by_col) >= 2:
            valid_rows.append([by_col[i] for i in sorted(by_col)])
    if len(valid_rows) < 3:
        return None
    flat = [b for row in valid_rows for col in row for b in col]
    if len(flat) < 6:
        return None
    unique: list[Block] = []
    seen: set[int] = set()
    for block in flat:
        key = id(block)
        if key in seen:
            continue
        seen.add(key)
        unique.append(block)
    return {"rows": valid_rows, "blocks": unique}


def _build_table_nodes(page: int, rows: list[list[list[Block]]]) -> list[Node]:
    nodes: list[Node] = []
    table = Node("Table", page)
    for row_index, row in enumerate(rows):
        tr = Node("TR", page)
        for col_index, cells in enumerate(row):
            block_text = " ".join(block.text for block in cells if block.text).strip()
            header = row_index == 0 or all(block.bold for block in cells if block.kind == "text")
            cell = Node("TH" if header else "TD", page, text=block_text)
            cell.bbox = (min(b.bbox[0] for b in cells), min(b.bbox[1] for b in cells),
                         max(b.bbox[2] for b in cells), max(b.bbox[3] for b in cells))
            for block in cells:
                for it in block.items:
                    it.owner = cell
                    cell.kids.append(it)
            tr.kids.append(cell)
        table.kids.append(tr)
    nodes.append(table)
    return nodes


# ---------------------------------------------------------------------------
# main entry


def tag_document(pdf: pikepdf.Pdf, pdfium_doc: pdfium.PdfDocument) -> TagResult:
    result = TagResult(pages_total=len(pdf.pages))
    remove_existing_structure(pdf)

    page_ops: list[list] = []
    page_items: list[list[Item]] = []
    page_lines: list[list[Line]] = []
    page_matched: list[bool] = []
    page_boxes: list[tuple[float, float, float, float]] = []

    # Pass A: scan pages
    for idx, page in enumerate(pdf.pages):
        raw = [(list(ins.operands), ins.operator) for ins in pikepdf.parse_content_stream(page)]
        ops, _ = strip_structure_marks(raw)
        info = read_page(pdfium_doc, idx)
        resources = page.obj.get("/Resources", Dictionary())
        items, matched = scan(ops, resources, info.objects)
        mb = [float(v) for v in page.mediabox]
        page_boxes.append((min(mb[0], mb[2]), min(mb[1], mb[3]), max(mb[0], mb[2]), max(mb[1], mb[3])))
        page_ops.append(ops)
        page_items.append(items)
        page_matched.append(matched)
        if matched:
            result.pages_matched += 1
            text_items = [it for it in items if it.kind == "text" and it.obj and it.obj.text.strip()]
            page_lines.append(_group_lines(idx, text_items))
        else:
            page_lines.append([])
            result.issues.append(Issue(
                "tagger.page-unmapped", "warning",
                "Page content could not be matched to layout objects, so it was tagged in stream order "
                "without heading or list detection. Review this page's structure.",
                page=idx + 1, source="tagger", wcag=["1.3.1", "1.3.2"]))

    # Pass B: header/footer detection and body size
    hf_counts: Counter = Counter()
    for idx, lines in enumerate(page_lines):
        x0, y0, x1, y1 = page_boxes[idx]
        h = max(y1 - y0, 1.0)
        for line in lines:
            b = line.bbox
            if (b[1] - y0) / h > 0.92 or (b[3] - y0) / h < 0.08:
                hf_counts[_hf_key(line.text)] += 1
    n_pages = len(pdf.pages)
    for idx, lines in enumerate(page_lines):
        x0, y0, x1, y1 = page_boxes[idx]
        h = max(y1 - y0, 1.0)
        for line in lines:
            b = line.bbox
            top_zone = (b[1] - y0) / h > 0.92
            bottom_zone = (b[3] - y0) / h < 0.08
            if not (top_zone or bottom_zone):
                continue
            repeated = n_pages > 1 and hf_counts[_hf_key(line.text)] >= 2
            if repeated or PAGE_NUM_RE.match(line.text):
                for it in line.items:
                    it.artifact = "Header" if top_zone else "Footer"

    size_chars: Counter = Counter()
    for lines in page_lines:
        for line in lines:
            if line.items[0].artifact:
                continue
            size_chars[round(line.size * 2) / 2] += len(line.text)
    body = size_chars.most_common(1)[0][0] if size_chars else 10.0
    total_chars = sum(size_chars.values()) or 1
    # A size that carries a large share of all text is a body style (for example main text in a
    # document whose long reference list is set smaller), never a heading level.
    body_styles = {k for k, v in size_chars.items() if v / total_chars > 0.2}

    # Pass C: blocks and roles per page
    page_blocks: list[list[Block]] = []
    for idx, items in enumerate(page_items):
        x0, y0, x1, y1 = page_boxes[idx]
        page_area = max((x1 - x0) * (y1 - y0), 1.0)
        blocks: list[Block] = []
        if page_matched[idx]:
            content_lines = [ln for ln in page_lines[idx] if not ln.items[0].artifact]
            text_blocks = _group_blocks(idx, content_lines)
            first_index = {id(b): b.lines[0].items[0].start for b in text_blocks}
            ordered: list[tuple[int, Block]] = [(first_index[id(b)], b) for b in text_blocks]
            text_area = 0.0
            for it in items:
                if it.kind in ("image", "inline", "form") and it.obj is not None:
                    b = it.obj.bbox
                    area = max((b[2] - b[0]) * (b[3] - b[1]), 0.0)
                    if it.kind == "form" and it.obj.form_has_text:
                        ordered.append((it.start, Block(idx, "form-text", item=it)))
                    elif it.kind == "form" and not it.obj.form_has_image:
                        it.artifact = "Layout"
                    elif area / page_area < 0.0025 or min(b[2] - b[0], b[3] - b[1]) < 8:
                        it.artifact = "Layout"
                    else:
                        ordered.append((it.start, Block(idx, "figure", item=it, role="Figure")))
                        if area / page_area > 0.8:
                            text_area = -1.0
            ordered.sort(key=lambda t: t[0])
            blocks = _read_order_sort([b for _, b in ordered])
            if text_area < 0 and not content_lines:
                result.issues.append(Issue(
                    "tagger.scanned-page", "error",
                    "This page appears to be a scanned image with no text layer. Run OCR, then re-tag.",
                    page=idx + 1, source="tagger", wcag=["1.1.1", "1.4.5"], matterhorn=["08-001"]))
        else:
            by_bt: dict[int, Block] = {}
            ordered = []
            for it in items:
                if it.kind == "text":
                    blk = by_bt.get(it.bt_index)
                    if blk is None:
                        blk = Block(idx, "unmapped-text")
                        blk.item = it
                        by_bt[it.bt_index] = blk
                        ordered.append(blk)
                    blk.lines.append(Line(idx, [it]))
                elif it.kind in ("image", "inline"):
                    ordered.append(Block(idx, "figure", item=it, role="Figure"))
                elif it.kind == "form":
                    ordered.append(Block(idx, "form-text", item=it))
            blocks = _read_order_sort(ordered)
        page_blocks.append(blocks)

    # Heading levels (global)
    heading_keys: set[float] = set()
    for blocks in page_blocks:
        for b in blocks:
            if b.role == "TableCell" or b.kind != "text" or b.marker:
                continue
            text = b.text
            size = b.size
            max_lines = 5 if size >= body * 1.4 else 3  # large titles often wrap
            if not re.search(r"[A-Za-z0-9]", text) or len(text) > 200 or len(b.lines) > max_lines:
                continue
            if round(size * 2) / 2 in body_styles:
                continue
            if size >= body * 1.15:
                b.role = "H"
                heading_keys.add(round(size * 2) / 2)
            elif b.bold and size >= body * 0.95 and len(b.lines) == 1 and len(text) <= 120 and not text.endswith("."):
                b.role = "H"
                heading_keys.add(round(body * 2) / 2 - 0.01)
    ranked = sorted(heading_keys, reverse=True)
    level_of = {k: min(i + 1, 6) for i, k in enumerate(ranked)}
    prev_level = 0
    for blocks in page_blocks:
        for b in blocks:
            if b.role == "H":
                size = b.size
                key = round(size * 2) / 2 if size >= body * 1.15 else round(body * 2) / 2 - 0.01
                # Keep levels well nested (PDF/UA-1 7.4.2): start at H1 and never skip a level.
                level = min(level_of.get(key, 6), prev_level + 1)
                b.role = f"H{level}"
                prev_level = level

    # Lists: bullets always; enumerations only when two or more appear in a row
    flat = [b for blocks in page_blocks for b in blocks]
    i = 0
    while i < len(flat):
        b = flat[i]
        if b.role == "TableCell":
            i += 1
            continue
        if b.kind == "text" and b.marker:
            j = i
            while j < len(flat) and flat[j].kind == "text" and flat[j].marker == b.marker:
                j += 1
            if b.marker == "bullet" or j - i >= 2:
                for k in range(i, j):
                    flat[k].role = "LI"
            i = j
        else:
            i += 1

    # Pass D: nodes, annotations, MCIDs, content rewrite
    doc_node = Node("Document")
    possible_tables = 0
    open_list: Node | None = None
    for idx, page in enumerate(pdf.pages):
        page_nodes: list[Node] = []
        table_plan = _detect_table_layout(page_blocks[idx])
        if table_plan:
            for b in table_plan["blocks"]:
                b.role = "TableCell"
            page_nodes.extend(_build_table_nodes(idx, table_plan["rows"]))
        for b in page_blocks[idx]:
            if b.role == "TableCell":
                continue
            if b.role == "LI":
                if open_list is None:
                    numbering = "/Disc" if b.marker == "bullet" else "/Decimal"
                    open_list = Node("L", idx, attrs={"ListNumbering": numbering})
                    page_nodes.append(open_list)
                li = Node("LI", idx)
                body_node = Node("LBody", idx, text=b.text)
                its = b.items
                if its and its[0].obj and MARKER_ONLY_RE.match(its[0].obj.text or "") and len(its) > 1:
                    lbl = Node("Lbl", idx)
                    lbl.kids.append(its[0])
                    its[0].owner = lbl
                    li.kids.append(lbl)
                    its = its[1:]
                for it in its:
                    it.owner = body_node
                    body_node.kids.append(it)
                li.kids.append(body_node)
                open_list.kids.append(li)
                continue
            open_list = None
            if b.kind == "figure":
                node = Node("Figure", idx, bbox=b.bbox)
                result.figures.append({"index": len(result.figures), "page": idx, "bbox": list(b.bbox),
                                       "context": ""})
            else:
                mapped = b.kind == "text"
                node = Node(b.role if mapped else "P", idx, text=b.text if mapped else "",
                            bbox=b.bbox if mapped else None, size=b.size if mapped else 0.0)
            for it in b.items:
                it.owner = node
                node.kids.append(it)
            page_nodes.append(node)
            if node.role.startswith("H"):
                result.headings.append({"level": int(node.role[1]), "text": b.text, "page": idx,
                                        "top": b.bbox[3]})
        # Figure context (nearest text block after or before) for alt text help
        for fi, f in enumerate(result.figures):
            if f["page"] == idx and not f["context"]:
                f["context"] = _figure_context(page_blocks[idx], f["bbox"])

        # Possible tables: several rows with 2+ text blocks sharing a baseline
        if page_matched[idx] and not table_plan:
            rows: dict[int, int] = defaultdict(int)
            for b in page_blocks[idx]:
                if b.kind == "text" and len(b.lines) == 1:
                    rows[round(b.lines[0].bbox[1] / 3)] += 1
            if sum(1 for c in rows.values() if c >= 2) >= 3:
                possible_tables += 1
                result.issues.append(Issue(
                    "tagger.possible-table", "warning",
                    "Text is laid out in aligned columns, which may be a table. The basic engine tags it as "
                    "paragraphs; use the OpenDataLoader engine or tag the table manually.",
                    page=idx + 1, source="tagger", wcag=["1.3.1"], matterhorn=["15-003"]))

        _attach_annotations(pdf, page, idx, page_nodes, result)
        doc_node.kids.extend(page_nodes)

    # Assign MCIDs per page and rewrite content
    parent_entries: dict[int, list[Node]] = {}
    for idx, page in enumerate(pdf.pages):
        ops = page_ops[idx]
        opens: dict[int, list] = defaultdict(list)
        closes: dict[int, list] = defaultdict(list)
        mcid = 0
        owners: list[Node] = []
        for it in page_items[idx]:
            if it.kind == "clip":
                continue
            if it.kind in ("path", "shading", "text-empty") or it.artifact or it.owner is None:
                if it.kind == "path" and _range_has_structure(ops, it.start, it.end):
                    continue
                if it.artifact in ("Header", "Footer"):
                    props = Dictionary(Type=Name.Pagination, Subtype=Name("/" + it.artifact))
                    opens[it.start].append(([Name.Artifact, props], pikepdf.Operator("BDC")))
                else:
                    opens[it.start].append(([Name.Artifact], pikepdf.Operator("BMC")))
                closes[it.end].append(([], pikepdf.Operator("EMC")))
                continue
            it.mcid = mcid
            owner: Node = it.owner  # type: ignore[assignment]
            tag = Name("/" + (owner.role if owner.role[0].isalpha() else "Span"))
            opens[it.start].append(([tag, Dictionary(MCID=mcid)], pikepdf.Operator("BDC")))
            closes[it.end].append(([], pikepdf.Operator("EMC")))
            owners.append(owner)
            mcid += 1
        new_ops = []
        for i, instr in enumerate(ops):
            new_ops.extend(opens.get(i, []))
            new_ops.append(instr)
            new_ops.extend(closes.get(i, []))
        new_ops = merge_actualtext_spans(new_ops)
        page.obj.Contents = pdf.make_stream(pikepdf.unparse_content_stream(new_ops))
        if owners:
            parent_entries[idx] = owners

    _write_structure(pdf, doc_node, parent_entries)

    for h in result.headings:
        if h["level"] == 1 and h["text"].strip():
            result.title_candidate = h["text"].strip()
            break
    return result


def merge_actualtext_spans(ops: list) -> list:
    """Fold ``/Span <</ActualText ...>>`` around a single tagged item into that item's MCID mark.

    Source files (Chrome, Word) mark ligatures as ``/Span <</ActualText (fi)>> BDC ... EMC``. After
    tagging, our ``BDC <</MCID n>>`` sits inside that span, and some readers (PDFium) then take the
    innermost properties and lose the ActualText. One mark holding both keys is unambiguous.
    """
    out: list = []
    i, n = 0, len(ops)
    while i < n:
        operands, op = ops[i]
        props = operands[1] if str(op) == "BDC" and len(operands) == 2 else None
        if isinstance(props, Dictionary) and "/ActualText" in props and "/MCID" not in props:
            j, pre = i + 1, []
            while j < n and str(ops[j][1]) not in {"BDC", "BMC", "EMC", "Do", "INLINE IMAGE", "sh"} | SHOW_OPS:
                pre.append(ops[j])
                j += 1
            inner = ops[j][0] if j < n and str(ops[j][1]) == "BDC" else None
            inner_props = inner[1] if inner and len(inner) == 2 else None
            if (isinstance(inner_props, Dictionary) and "/MCID" in inner_props and j + 3 < n
                    and str(ops[j + 2][1]) == "EMC" and str(ops[j + 3][1]) == "EMC"):
                merged = Dictionary({k: v for k, v in inner_props.items()})
                for k, v in props.items():
                    merged[k] = v
                out.extend(pre)
                out.append(([inner[0], merged], pikepdf.Operator("BDC")))
                out.append(ops[j + 1])
                out.append(ops[j + 2])
                i = j + 4
                continue
        out.append(ops[i])
        i += 1
    return out


def _figure_context(blocks: list[Block], bbox) -> str:
    best, best_d = "", 1e9
    for b in blocks:
        if b.kind != "text":
            continue
        bb = b.bbox
        d = min(abs(bb[3] - bbox[1]), abs(bbox[3] - bb[1]))
        if d < best_d and d < 72:
            best, best_d = b.text, d
    return best[:400]


def _range_has_structure(ops, start: int, end: int) -> bool:
    return any(str(ops[k][1]) in {"BT", "ET", "q", "Q", "BDC", "BMC", "EMC"} for k in range(start, end + 1))


def _annot_rect(annot) -> BBox | None:
    try:
        r = [float(v) for v in annot.Rect]
        return (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3]))
    except Exception:
        return None


def _field_name(annot) -> tuple[pikepdf.Dictionary | None, str]:
    node = annot
    for _ in range(20):
        if node is None:
            break
        if "/T" in node:
            return node, str(node.T)
        node = node.get("/Parent")
    return None, ""


def _attach_annotations(pdf, page, idx: int, page_nodes: list[Node], result: TagResult) -> None:
    annots = page.obj.get("/Annots")
    if not annots:
        return
    for annot in annots:
        if not isinstance(annot, pikepdf.Dictionary):
            continue
        subtype = str(annot.get("/Subtype", ""))
        flags = int(annot.get("/F", 0))
        if subtype in ("/Popup", "/PrinterMark", "/TrapNet") or flags & 2:
            continue
        if subtype == "/Link":
            rect = _annot_rect(annot)
            link = Node("Link", idx)
            placed = False
            if rect:
                for node in _walk_nodes(page_nodes):
                    run: list[int] = []
                    for k, kid in enumerate(node.kids):
                        if isinstance(kid, Item) and kid.obj and _overlap_ratio(kid.obj.bbox, rect) > 0.3:
                            if run and k != run[-1] + 1:
                                break
                            run.append(k)
                    if run:
                        linked = [node.kids[k] for k in run]
                        for it in linked:
                            it.owner = link
                        link.kids.extend(linked)
                        link.text = " ".join((it.obj.text or "").strip() for it in linked).strip()
                        node.kids[run[0]:run[-1] + 1] = [link]
                        placed = True
                        break
            link.kids.append(Objr(annot, idx))
            if not placed:
                page_nodes.append(link)
            if "/Contents" not in annot or not str(annot.Contents).strip():
                uri = ""
                action = annot.get("/A")
                if isinstance(action, pikepdf.Dictionary) and "/URI" in action:
                    uri = str(action.URI)
                annot.Contents = String(link.text or uri or "Link")
        elif subtype == "/Widget":
            form = Node("Form", idx)
            form.kids.append(Objr(annot, idx))
            page_nodes.append(form)
            field_dict, name = _field_name(annot)
            target = field_dict if field_dict is not None else annot
            if "/TU" not in target or not str(target.TU).strip():
                label = re.sub(r"[_\-.]+", " ", name).strip() or "Form field"
                target.TU = String(label)
                result.issues.append(Issue(
                    "tagger.form-tu-generated", "warning",
                    f"Form field '{name or '(unnamed)'}' had no accessible description; '{label}' was generated "
                    "from its name. Review it.", page=idx + 1, source="tagger", wcag=["3.3.2", "4.1.2"],
                    matterhorn=["28-005"]))
        else:
            node = Node("Annot", idx)
            node.kids.append(Objr(annot, idx))
            contents = str(annot.get("/Contents", "")).strip()
            node.alt = contents or subtype.lstrip("/") + " annotation"
            page_nodes.append(node)


def _walk_nodes(nodes):
    for n in nodes:
        if isinstance(n, Node):
            yield n
            yield from _walk_nodes([k for k in n.kids if isinstance(k, Node)])


def _write_structure(pdf: pikepdf.Pdf, doc_node: Node, parent_entries: dict[int, list[Node]]) -> None:
    pages = list(pdf.pages)
    root = pdf.make_indirect(Dictionary(Type=Name.StructTreeRoot))
    annot_parents: list[tuple[pikepdf.Object, Node]] = []

    def build(node: Node, parent) -> pikepdf.Dictionary:
        d = pdf.make_indirect(Dictionary(Type=Name.StructElem, S=Name("/" + node.role), P=parent))
        node.obj = d
        if node.page is not None:
            d.Pg = pages[node.page].obj
        if node.alt:
            d.Alt = String(node.alt)
        if node.role == "L" and node.attrs.get("ListNumbering"):
            d.A = Dictionary(O=Name.List, ListNumbering=Name(node.attrs["ListNumbering"]))
        kids = Array()
        for kid in node.kids:
            if isinstance(kid, Item):
                if kid.mcid < 0:
                    continue
                kid_page = kid.owner.page if isinstance(kid.owner, Node) else node.page
                if kid_page == node.page:
                    kids.append(kid.mcid)
                else:
                    kids.append(Dictionary(Type=Name.MCR, MCID=kid.mcid, Pg=pages[kid_page].obj))
            elif isinstance(kid, Node):
                kids.append(build(kid, d))
            elif isinstance(kid, Objr):
                kids.append(Dictionary(Type=Name.OBJR, Obj=kid.annot, Pg=pages[kid.page].obj))
                annot_parents.append((kid.annot, node))
        d.K = kids
        return d

    root.K = build(doc_node, root)
    nums = Array()
    for idx in sorted(parent_entries):
        pages[idx].obj.StructParents = idx
        nums.append(idx)
        nums.append(pdf.make_indirect(Array([n.obj for n in parent_entries[idx]])))
    next_key = len(pages)
    for annot, node in annot_parents:
        annot.StructParent = next_key
        nums.append(next_key)
        nums.append(node.obj)
        next_key += 1
    root.ParentTree = pdf.make_indirect(Dictionary(Nums=nums))
    root.ParentTreeNextKey = next_key
    pdf.Root.StructTreeRoot = root
