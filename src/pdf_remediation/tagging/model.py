"""Data model shared by the built-in tagging engine's stages.

    content items (pdf/content.py)
        -> Line (text items on one baseline)
        -> Block (paragraph, heading, list item, figure, table)
        -> Node (structure element to be written)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import pikepdf

from ..issues import Issue
from ..pdf.content import Item
from ..pdf.pdfium import BBox


def item_size(it: Item) -> float:
    """Effective font size of a text item, falling back to its box height."""
    o = it.obj
    if o is None:
        return 0.0
    if o.size > 0.5:
        return o.size
    return max(o.bbox[3] - o.bbox[1], 1.0)


def union(boxes) -> BBox:
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def overlap_ratio(a: BBox, b: BBox) -> float:
    """Share of box ``a`` covered by box ``b``."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return (w * h) / max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)


@dataclass
class Line:
    """Text items that sit on one baseline with no large horizontal gap."""
    page: int
    items: list[Item]

    @property
    def bbox(self) -> BBox:
        return union(it.obj.bbox for it in self.items)

    @property
    def size(self) -> float:
        weights = [(max(len(it.obj.text.strip()), 1), item_size(it)) for it in self.items]
        return sum(w * s for w, s in weights) / sum(w for w, _ in weights)

    @property
    def bold(self) -> bool:
        chars: Counter = Counter()
        for it in self.items:
            chars[it.obj.bold] += max(len(it.obj.text.strip()), 1)
        return chars[True] > chars[False]

    @property
    def text(self) -> str:
        return join_text(self.items)


def join_text(items: list[Item]) -> str:
    """Join item texts, adding a space only where the glyphs leave a real gap.

    Some generators (Chrome) draw one glyph per operator, so naive joining with
    spaces would produce "t e x t".
    """
    out = ""
    prev = None
    for it in items:
        t = it.obj.text if it.obj else ""
        if prev is not None and out and not out.endswith(" ") and not t.startswith(" "):
            gap = it.obj.bbox[0] - prev.obj.bbox[2]
            new_line = abs(it.obj.bbox[1] - prev.obj.bbox[1]) > 0.5 * max(item_size(it), 1.0)
            if new_line or gap > 0.15 * max(item_size(it), 1.0):
                out += " "
        out += t
        prev = it
    return out


@dataclass
class Cell:
    row: int
    col: int
    items: list[Item] = field(default_factory=list)
    colspan: int = 1
    rowspan: int = 1
    header: bool = False


@dataclass
class Table:
    page: int
    bbox: BBox
    n_rows: int
    n_cols: int
    cells: list[Cell]
    method: str  # "ruled" (vector grid lines) | "aligned" (columns of text)

    @property
    def items(self) -> list[Item]:
        return [it for c in self.cells for it in c.items]

    @property
    def start(self) -> int:
        """Content-stream position of the table's first item (for reading order)."""
        return min((it.start for it in self.items), default=0)


@dataclass
class Block:
    """A unit of page content in reading order."""
    page: int
    kind: str  # text | figure | form-text | table | unmapped-text
    lines: list[Line] = field(default_factory=list)
    item: Item | None = None
    table: Table | None = None
    role: str = "P"
    marker: str = ""  # "bullet" | "enum" | ""

    @property
    def text(self) -> str:
        if self.kind == "text":
            return " ".join(line.text.strip() for line in self.lines).strip()
        if self.item is not None and self.item.obj is not None:
            return self.item.obj.text
        return ""

    @property
    def size(self) -> float:
        return max((line.size for line in self.lines), default=0.0) if self.kind == "text" else 0.0

    @property
    def bold(self) -> bool:
        return bool(self.lines) and all(line.bold for line in self.lines)

    @property
    def bbox(self) -> BBox:
        if self.kind == "text":
            return union(line.bbox for line in self.lines)
        if self.kind == "table" and self.table is not None:
            return self.table.bbox
        if self.item is not None and self.item.obj is not None:
            return self.item.obj.bbox
        return (0.0, 0.0, 0.0, 0.0)

    @property
    def items(self) -> list[Item]:
        if self.kind in ("text", "unmapped-text"):
            return [it for line in self.lines for it in line.items]
        if self.kind == "table" and self.table is not None:
            return self.table.items
        return [self.item] if self.item is not None else []


@dataclass
class Objr:
    """Reference from a structure element to an annotation (link, form field...)."""
    annot: pikepdf.Object
    page: int


@dataclass
class Node:
    """A structure element to be written into the StructTreeRoot."""
    role: str
    page: int | None = None
    kids: list = field(default_factory=list)  # Item | Node | Objr
    alt: str | None = None
    # PDF attribute values: strings starting with "/" are written as names.
    attrs: dict = field(default_factory=dict)
    text: str = ""
    obj: pikepdf.Dictionary | None = None  # set when written


@dataclass
class TagResult:
    headings: list[dict] = field(default_factory=list)  # {level, text, page, top}
    figures: list[dict] = field(default_factory=list)
    tables: int = 0
    issues: list[Issue] = field(default_factory=list)
    title_candidate: str = ""
    pages_matched: int = 0
    pages_total: int = 0
