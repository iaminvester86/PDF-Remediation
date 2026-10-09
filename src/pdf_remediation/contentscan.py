"""Split a page content stream into paintable items and pair them with PDFium objects.

An *item* is the smallest unit the tagger can wrap in marked content without
editing the drawing itself: one text-showing operator, one ``Do``, one inline
image, one ``sh``, or one path (construction operators through the painting
operator). PDFium's top-level page objects appear in the same order as these
operators, which lets us attach text, geometry and font facts to each item.
Spike-era probes on LibreOffice and reportlab output matched one-to-one; when a
page does not match, the caller falls back to geometry-free tagging.
"""
from __future__ import annotations

from dataclasses import dataclass

import pikepdf

from .pdfium_util import PObj

SHOW_OPS = {"Tj", "TJ", "'", '"'}
PATH_CONSTRUCT = {"m", "l", "c", "v", "y", "h", "re"}
PATH_PAINT = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"}
CLIP_OPS = {"W", "W*"}
MARK_OPS = {"BDC", "BMC"}

Op = tuple[list, pikepdf.Operator]


@dataclass
class Item:
    kind: str  # text | text-empty | image | form | inline | path | clip | shading
    start: int
    end: int
    obj: PObj | None = None
    bt_index: int = -1  # which BT..ET block a text item belongs to
    # Filled in by the tagger
    owner: object = None  # structure node that will own this item's MCID
    artifact: str | None = None  # "Header", "Footer", "Layout", ... when not real content
    mcid: int = -1


def _string_empty(s) -> bool:
    if isinstance(s, pikepdf.String):
        return len(bytes(s)) == 0
    if isinstance(s, pikepdf.Array):
        return all(not isinstance(x, pikepdf.String) or len(bytes(x)) == 0 for x in s)
    return False


def is_empty_show(operands, op_name: str) -> bool:
    if not operands:
        return True
    return _string_empty(operands[-1])


MEANINGFUL_PROPS = ("/ActualText", "/Alt", "/E", "/Lang")


def _keep_mark(operands, op_name: str):
    """Decide what to do with an existing BMC/BDC when re-tagging.

    Returns the operands to keep, or None to drop the mark. Old structure (MCID)
    and /Artifact marks are dropped so new tags do not nest inside stale ones.
    Marks that carry meaning are kept: optional content (/OC) and spans with
    ActualText, Alt, E or Lang (for example Chrome and Word write
    ``/Span <</ActualText (fi)>>`` around ligatures; dropping it loses text).
    """
    if op_name == "BMC" or not operands:
        return None
    tag = str(operands[0])
    if tag == "/Artifact":
        return None
    if tag == "/OC":
        return operands
    props = operands[1] if len(operands) > 1 else None
    if isinstance(props, pikepdf.Name):  # named resource in /Properties: keep as is
        return operands
    if isinstance(props, pikepdf.Dictionary) and any(k in props for k in MEANINGFUL_PROPS):
        kept = pikepdf.Dictionary({k: v for k, v in props.items() if k != "/MCID"})
        return [pikepdf.Name.Span, kept]
    return None


def strip_structure_marks(ops: list[Op]) -> tuple[list[Op], int]:
    """Remove old structure marks before re-tagging; keep marks that carry meaning."""
    out: list[Op] = []
    stack: list[bool] = []
    removed = 0
    for operands, op in ops:
        name = str(op)
        if name in MARK_OPS:
            kept = _keep_mark(operands, name)
            stack.append(kept is not None)
            if kept is not None:
                out.append((kept, pikepdf.Operator("BDC")))
            else:
                removed += 1
            continue
        if name == "EMC":
            keep = stack.pop() if stack else False
            if keep:
                out.append((operands, op))
            continue
        out.append((operands, op))
    return out, removed


def _xobject_subtype(resources, name) -> str:
    try:
        xobj = resources["/XObject"][name]
        return str(xobj.get("/Subtype", "/Form"))
    except Exception:
        return "/Form"


def scan(ops: list[Op], resources, pobjs: list[PObj] | None) -> tuple[list[Item], bool]:
    """Return items in stream order and whether PDFium objects were matched."""
    items: list[Item] = []
    path_start: int | None = None
    bt_index = -1
    for i, (operands, op) in enumerate(ops):
        name = str(op)
        if name == "BT":
            bt_index += 1
        elif name in SHOW_OPS:
            kind = "text-empty" if is_empty_show(operands, name) else "text"
            items.append(Item(kind, i, i, bt_index=bt_index))
        elif name == "Do":
            sub = _xobject_subtype(resources, operands[0]) if operands else "/Form"
            items.append(Item("image" if sub == "/Image" else "form", i, i))
        elif name == "INLINE IMAGE":
            items.append(Item("inline", i, i))
        elif name == "sh":
            items.append(Item("shading", i, i))
        elif name in PATH_CONSTRUCT:
            if path_start is None:
                path_start = i
        elif name in CLIP_OPS:
            if path_start is None:
                path_start = i
        elif name in PATH_PAINT:
            start = path_start if path_start is not None else i
            items.append(Item("clip" if name == "n" else "path", start, i))
            path_start = None
    if pobjs is None:
        return items, False

    want = [it for it in items if it.kind in ("text", "image", "form", "inline")]
    have = [o for o in pobjs if o.kind in ("text", "image", "form")]
    compatible = {"text": {"text"}, "image": {"image", "form"}, "form": {"form", "image"}, "inline": {"image"}}
    if len(want) != len(have) or any(o.kind not in compatible[it.kind] for it, o in zip(want, have)):
        return items, False
    for it, o in zip(want, have):
        it.obj = o
        if it.kind in ("image", "form") and o.kind != it.kind:
            it.kind = o.kind
    return items, True
