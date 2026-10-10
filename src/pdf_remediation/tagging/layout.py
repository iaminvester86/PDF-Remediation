"""Layout analysis for the built-in engine: lines, paragraphs, running
headers/footers, heading levels and lists. Pure functions over the model."""
from __future__ import annotations

import re
from collections import Counter

from ..pdf.content import Item
from .model import Block, Line, item_size

_BULLET_CHARS = re.escape(
    "•‣●○◦▪▫■⁃∙·–—"
    "➢✓✔❖*-"
)
BULLET_RE = re.compile(rf"^\s*[{_BULLET_CHARS}](\s+|$)")
ENUM_RE = re.compile(r"^\s*(\(?\d{1,3}[.)]|\(?[a-z][.)]|\(?[ivx]{1,4}[.)])(\s+|$)")
MARKER_ONLY_RE = re.compile(rf"^\s*([{_BULLET_CHARS}]|\(?\d{{1,3}}[.)]|\(?[a-z][.)]|\(?[ivx]{{1,4}}[.)])\s*$")
PAGE_NUM_RE = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.I)
_DIGITS = re.compile(r"\d+")

HEADER_ZONE = 0.92  # top 8% of the page
FOOTER_ZONE = 0.08  # bottom 8%


def group_lines(page: int, items: list[Item]) -> list[Line]:
    """Group text items (in content order) into lines."""
    lines: list[Line] = []
    cur: Line | None = None
    for it in items:
        if cur is not None:
            last = cur.items[-1]
            s = max(item_size(it), item_size(last), 1.0)
            # PDFium bounds are tight glyph boxes, so small glyphs (bullets, punctuation) do not
            # share the text's bottom edge; vertical overlap identifies them as the same line.
            a, b = it.obj.bbox, last.obj.bbox
            v_overlap = min(a[3], b[3]) - max(a[1], b[1])
            min_h = max(min(a[3] - a[1], b[3] - b[1]), 0.1)
            same_baseline = abs(a[1] - b[1]) <= 0.35 * s or v_overlap >= 0.5 * min_h
            moving_right = a[0] >= b[0] - 1.0
            gap = a[0] - b[2]
            if same_baseline and moving_right and gap < 2.5 * s:
                cur.items.append(it)
                continue
        cur = Line(page, [it])
        lines.append(cur)
    return lines


def marker_of(text: str) -> str:
    if BULLET_RE.match(text):
        return "bullet"
    if ENUM_RE.match(text):
        return "enum"
    return ""


def group_blocks(page: int, lines: list[Line]) -> list[Block]:
    """Group consecutive lines with similar style and spacing into paragraphs."""
    blocks: list[Block] = []
    cur: Block | None = None
    for line in lines:
        marker = marker_of(line.text)
        if cur is not None and not marker:
            prev = cur.lines[-1]
            ps, ls = prev.size, line.size
            pb, lb = prev.bbox, line.bbox
            similar_size = abs(ls - ps) <= 0.12 * max(ps, 1.0)
            same_weight = prev.bold == line.bold
            gap = pb[1] - lb[3]  # previous bottom minus this top (PDF y grows upwards)
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


def mark_running_artifacts(page_lines: list[list[Line]], page_boxes: list[tuple]) -> None:
    """Mark repeated headers/footers and page numbers as pagination artifacts."""
    def zone(line: Line, box) -> str:
        y0, h = box[1], max(box[3] - box[1], 1.0)
        b = line.bbox
        if (b[1] - y0) / h > HEADER_ZONE:
            return "Header"
        if (b[3] - y0) / h < FOOTER_ZONE:
            return "Footer"
        return ""

    counts: Counter = Counter()
    for idx, lines in enumerate(page_lines):
        for line in lines:
            if zone(line, page_boxes[idx]):
                counts[_hf_key(line.text)] += 1
    multi_page = len(page_lines) > 1
    for idx, lines in enumerate(page_lines):
        for line in lines:
            z = zone(line, page_boxes[idx])
            if z and ((multi_page and counts[_hf_key(line.text)] >= 2) or PAGE_NUM_RE.match(line.text)):
                for it in line.items:
                    it.artifact = z


def body_style(page_lines: list[list[Line]]) -> tuple[float, set[float]]:
    """Return the body font size and the set of sizes used for body text.

    A size carrying more than 20% of all text is a body style (for example main
    text in a document whose long reference list is set smaller) and can never be
    a heading level.
    """
    size_chars: Counter = Counter()
    for lines in page_lines:
        for line in lines:
            if not line.items[0].artifact:
                size_chars[round(line.size * 2) / 2] += len(line.text)
    if not size_chars:
        return 10.0, set()
    total = sum(size_chars.values())
    return size_chars.most_common(1)[0][0], {k for k, v in size_chars.items() if v / total > 0.2}


def assign_headings(page_blocks: list[list[Block]], body: float, body_styles: set[float]) -> None:
    """Promote large or bold short blocks to headings with well-nested levels (PDF/UA-1 7.4.2)."""
    bold_key = round(body * 2) / 2 - 0.01  # bold body-size headings rank below larger ones
    keys: dict[int, float] = {}
    for blocks in page_blocks:
        for b in blocks:
            if b.kind != "text" or b.marker:
                continue
            text, size = b.text, b.size
            max_lines = 5 if size >= body * 1.4 else 3  # large titles often wrap
            if not re.search(r"[A-Za-z0-9]", text) or len(text) > 200 or len(b.lines) > max_lines:
                continue
            if round(size * 2) / 2 in body_styles:
                continue
            if size >= body * 1.15:
                keys[id(b)] = round(size * 2) / 2
            elif b.bold and size >= body * 0.95 and len(b.lines) == 1 and len(text) <= 120 \
                    and not text.endswith("."):
                keys[id(b)] = bold_key
    level_of = {k: min(i + 1, 6) for i, k in enumerate(sorted(set(keys.values()), reverse=True))}
    prev = 0
    for blocks in page_blocks:
        for b in blocks:
            if id(b) in keys:
                level = min(level_of[keys[id(b)]], prev + 1)  # start at H1, never skip a level
                b.role = f"H{level}"
                prev = level


def assign_lists(page_blocks: list[list[Block]]) -> None:
    """Bulleted paragraphs become list items; enumerations need two or more in a row."""
    flat = [b for blocks in page_blocks for b in blocks]
    i = 0
    while i < len(flat):
        b = flat[i]
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


def figure_context(blocks: list[Block], bbox) -> str:
    """Nearest text block above or below a figure, to help write alt text."""
    best, best_d = "", 1e9
    for b in blocks:
        if b.kind != "text":
            continue
        bb = b.bbox
        d = min(abs(bb[3] - bbox[1]), abs(bbox[3] - bb[1]))
        if d < best_d and d < 72:
            best, best_d = b.text, d
    return best[:400]
