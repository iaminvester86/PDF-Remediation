"""Table detection for the built-in engine.

Two detectors, tried in order:

1. **Ruled tables**: a grid of horizontal and vertical vector lines (cell
   borders). Cells come from the grid; a missing internal border merges cells
   (ColSpan across, RowSpan down). Text is assigned to the cell containing its
   centre.
2. **Aligned tables**: no borders, but three or more consecutive rows whose
   text segments fall into the same column bands. Guarded against
   multi-column prose: cells must be short and at least one column must hold
   short values (numbers, codes, labels).

Header cells are assumed to be the first row, extended down when a first-row
cell spans several rows or groups sub-headings (a ColSpan cell with headings
under it). That is the most common layout, but it is an assumption, so every
detected table raises a review warning. Row headers (a first column of TH)
and nested tables are not detected.
"""
from __future__ import annotations

import statistics

from ..pdf.content import Item
from ..pdf.pdfium import BBox, Segment
from .model import Cell, Line, Table, union

TOL = 2.0  # points: how close two rules must be to count as the same line


# ---------------------------------------------------------------- ruled tables

def _axis_lines(segments: list[Segment]) -> tuple[list[list[float]], list[list[float]]]:
    """Split segments into merged horizontal [x0, x1, y] and vertical [y0, y1, x] rules."""
    h, v = [], []
    for x0, y0, x1, y1 in segments:
        if abs(y1 - y0) <= 1.0 and abs(x1 - x0) >= 6:
            h.append([min(x0, x1), max(x0, x1), (y0 + y1) / 2])
        elif abs(x1 - x0) <= 1.0 and abs(y1 - y0) >= 6:
            v.append([min(y0, y1), max(y0, y1), (x0 + x1) / 2])
    return _merge(h), _merge(v)


def _merge(lines: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for lo, hi, pos in sorted(lines, key=lambda r: (round(r[2] / TOL), r[0])):
        last = out[-1] if out else None
        if last and abs(pos - last[2]) <= TOL and lo <= last[1] + TOL:
            last[1] = max(last[1], hi)
        else:
            out.append([lo, hi, pos])
    return out


def _cluster(values: list[float]) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if out and v - out[-1] <= TOL:
            continue
        out.append(v)
    return out


def _components(h: list[list[float]], v: list[list[float]]) -> list[tuple[list, list]]:
    """Groups of horizontal and vertical rules that touch each other."""
    parent = list(range(len(h) + len(v)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (hx0, hx1, hy) in enumerate(h):
        for j, (vy0, vy1, vx) in enumerate(v):
            if hx0 - TOL <= vx <= hx1 + TOL and vy0 - TOL <= hy <= vy1 + TOL:
                parent[find(i)] = find(len(h) + j)
    groups: dict[int, tuple[list, list]] = {}
    for i, line in enumerate(h):
        groups.setdefault(find(i), ([], []))[0].append(line)
    for j, line in enumerate(v):
        groups.setdefault(find(len(h) + j), ([], []))[1].append(line)
    return [g for g in groups.values() if len(g[0]) >= 2 and len(g[1]) >= 2]


def _has_border(rules: list[list[float]], pos: float, lo: float, hi: float) -> bool:
    """Is there a rule at ``pos`` covering most of the span [lo, hi]? Works for both axes."""
    for r0, r1, rp in rules:
        if abs(rp - pos) <= TOL and min(r1, hi) - max(r0, lo) >= 0.6 * (hi - lo):
            return True
    return False


def _grid_cells(h: list[list[float]], v: list[list[float]], xs: list[float],
                ys: list[float]) -> list[tuple[Cell, BBox]]:
    """Cells of a ruled grid (ys top to bottom), merging slots where an internal border is missing."""
    n_rows, n_cols = len(ys) - 1, len(xs) - 1
    covered = [[False] * n_cols for _ in range(n_rows)]
    out: list[tuple[Cell, BBox]] = []
    for r in range(n_rows):
        for c in range(n_cols):
            if covered[r][c]:
                continue
            top, bottom = ys[r], ys[r + 1]
            span = 1
            while c + span < n_cols and not covered[r][c + span] and not _has_border(v, xs[c + span], bottom, top):
                span += 1
            rows = 1
            while r + rows < n_rows and not _has_border(h, ys[r + rows], xs[c], xs[c + span]):
                rows += 1
            for rr in range(r, r + rows):
                for cc in range(c, c + span):
                    covered[rr][cc] = True
            out.append((Cell(row=r, col=c, colspan=span, rowspan=rows), (xs[c], ys[r + rows], xs[c + span], top)))
    return out


def _mark_headers(cells: list[Cell], n_rows: int) -> None:
    """First row is the header; extend it down over row spans and grouped sub-headings."""
    first = [c for c in cells if c.row == 0]
    depth = max((c.rowspan for c in first), default=1)
    if any(c.colspan > 1 for c in first):
        depth = max(depth, 2)
    depth = min(depth, n_rows - 1)  # keep at least one data row
    for c in cells:
        c.header = c.row < depth


def _centre(it: Item) -> tuple[float, float]:
    b = it.obj.bbox
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def detect_ruled(page: int, items: list[Item], segments: list[Segment]) -> list[Table]:
    h_all, v_all = _axis_lines(segments)
    tables: list[Table] = []
    for h, v in _components(h_all, v_all):
        xs = _cluster([line[2] for line in v])
        ys = sorted(_cluster([line[2] for line in h]), reverse=True)
        ys = [y for k, y in enumerate(ys) if k == 0 or ys[k - 1] - y >= 3]  # ignore double rules
        if len(xs) < 3 or len(ys) < 3:  # need at least 2 columns and 2 rows
            continue
        rects = _grid_cells(h, v, xs, ys)
        cells = [cell for cell, _ in rects]
        for it in items:
            cx, cy = _centre(it)
            for cell, (x0, y0, x1, y1) in rects:
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    cell.items.append(it)
                    break
        filled = [c for c in cells if c.items]
        filled_cols = {c.col for c in filled}
        filled_rows = {c.row for c in filled}
        chars = [sum(len(it.obj.text.strip()) for it in c.items) for c in filled]
        # Reject boxes that merely frame prose (sidebars, two-column page frames).
        if len(filled) < 3 or len(filled_cols) < 2 or len(filled_rows) < 2 or statistics.mean(chars) > 250:
            continue
        for c in cells:
            c.items.sort(key=lambda it: it.start)
        _mark_headers(cells, len(ys) - 1)
        tables.append(Table(page, (xs[0], ys[-1], xs[-1], ys[0]), len(ys) - 1, len(xs) - 1, cells, "ruled"))
    return tables


# -------------------------------------------------------------- aligned tables

def _rows_of(lines: list[Line]) -> list[list[Line]]:
    """Group lines that share a baseline into rows, top to bottom."""
    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda ln: -ln.bbox[1]):
        if rows and abs(rows[-1][0].bbox[1] - line.bbox[1]) <= 0.4 * max(line.size, 1.0):
            rows[-1].append(line)
        else:
            rows.append([line])
    for row in rows:
        row.sort(key=lambda ln: ln.bbox[0])
    return rows


def _bands(rows: list[list[Line]], size: float) -> list[tuple[float, float]]:
    """Column bands: the union of all segments' horizontal extents."""
    spans = sorted((ln.bbox[0], ln.bbox[2]) for row in rows for ln in row)
    bands: list[list[float]] = []
    for x0, x1 in spans:
        if bands and x0 <= bands[-1][1] + 0.5 * size:
            bands[-1][1] = max(bands[-1][1], x1)
        else:
            bands.append([x0, x1])
    return [(b[0], b[1]) for b in bands]


def _aligned_table(page: int, rows: list[list[Line]]) -> Table | None:
    size = statistics.median(ln.size for row in rows for ln in row)
    bands = _bands(rows, size)
    if len(bands) < 2:
        return None
    cells: list[Cell] = []
    for r, row in enumerate(rows):
        for c, (b0, b1) in enumerate(bands):
            members = [ln for ln in row if ln.bbox[0] >= b0 - 0.1 and ln.bbox[2] <= b1 + 0.1]
            cells.append(Cell(row=r, col=c, header=(r == 0),
                              items=sorted((it for ln in members for it in ln.items), key=lambda it: it.start)))
    filled = [c for c in cells if c.items]
    lengths = [len(" ".join(it.obj.text for it in c.items).strip()) for c in filled]
    if not filled or len(filled) / len(cells) < 0.6 or statistics.mean(lengths) > 30 or max(lengths) > 80:
        return None
    # Real tables have at least one column of short values (numbers, codes, labels).
    short_column = False
    for c in range(len(bands)):
        col = [len(" ".join(it.obj.text for it in cell.items).strip()) for cell in cells if cell.col == c and cell.items]
        if col and statistics.median(col) <= 15:
            short_column = True
    if not short_column:
        return None
    bbox = union(ln.bbox for row in rows for ln in row)
    return Table(page, bbox, len(rows), len(bands), cells, "aligned")


def detect_aligned(page: int, lines: list[Line]) -> tuple[list[Table], int]:
    """Return (tables, number of aligned runs rejected as tables)."""
    rows = _rows_of(lines)
    runs: list[list[list[Line]]] = []
    run: list[list[Line]] = []
    for row in rows:
        size = max(ln.size for ln in row)
        multi = len(row) >= 2
        close = bool(run) and run[-1][0].bbox[1] - row[0].bbox[3] <= 2.2 * size
        if multi and (not run or close):
            run.append(row)
            continue
        if len(run) >= 3:
            runs.append(run)
        run = [row] if multi else []
    if len(run) >= 3:
        runs.append(run)
    tables, rejected = [], 0
    for r in runs:
        table = _aligned_table(page, r)
        if table is not None:
            tables.append(table)
        elif statistics.mean(len(ln.text.split()) for row in r for ln in row) <= 4:
            rejected += 1  # short phrases: plausibly a table worth a human look (prose lines run 6+ words)
    return tables, rejected


# --------------------------------------------------------------------- entry

def detect_tables(page: int, lines: list[Line], segments: list[Segment]) -> tuple[list[Table], list[Line], int]:
    """Find tables on a page.

    Returns (tables, remaining lines not inside a table, rejected aligned runs).
    """
    items = [it for ln in lines for it in ln.items]
    tables = detect_ruled(page, items, segments)
    used = {id(it) for t in tables for it in t.items}
    remaining = [Line(ln.page, [it for it in ln.items if id(it) not in used]) for ln in lines]
    remaining = [ln for ln in remaining if ln.items]
    aligned, rejected = detect_aligned(page, remaining)
    if aligned:
        used = {id(it) for t in aligned for it in t.items}
        remaining = [ln for ln in remaining if not any(id(it) in used for it in ln.items)]
    return tables + aligned, remaining, rejected

