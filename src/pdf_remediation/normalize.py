"""Content normalisation that must happen before tagging.

Spike 001 found generators that emit ``BT ... ET`` blocks which set fonts but
draw nothing. Validators can count those fonts as "used", which fails PDF/UA
when the font is not embedded. Text-state operators persist across text
objects, so such a block cannot simply be deleted. It is replaced by its
text-state operators, which are legal outside a text object. Its ``Tf`` is
dropped only when a lookahead proves the font is replaced (another ``Tf``) or
scoped out (a ``Q`` closing the enclosing state) before any glyph is drawn.
The rendering gate in the pipeline verifies the result.
"""
from __future__ import annotations

import pikepdf

from .contentscan import SHOW_OPS

TEXT_STATE_OPS = {"Tc", "Tw", "Tz", "TL", "Ts", "Tr", "Tf"}


def _font_overridden_before_use(instrs, start: int) -> bool:
    depth = 0
    for operands, op in instrs[start:]:
        name = str(op)
        if name == "q":
            depth += 1
        elif name == "Q":
            if depth == 0:
                return True
            depth -= 1
        elif name == "Tf" and depth == 0:
            return True
        elif name in SHOW_OPS:
            return False
        elif name == "Do":
            # A form XObject inherits the current font; be conservative.
            return False
    return True


def collapse_empty_text_blocks(pdf: pikepdf.Pdf) -> int:
    changed = 0
    for page in pdf.pages:
        instrs = [(list(i.operands), i.operator) for i in pikepdf.parse_content_stream(page)]
        out: list = []
        i = 0
        page_changed = False
        while i < len(instrs):
            operands, op = instrs[i]
            if str(op) != "BT":
                out.append((operands, op))
                i += 1
                continue
            j = i + 1
            while j < len(instrs) and str(instrs[j][1]) != "ET":
                j += 1
            block = instrs[i:j + 1]
            if j >= len(instrs) or any(str(o) in SHOW_OPS for _, o in block):
                out.extend(block)
                i = j + 1
                continue
            drop_tf = _font_overridden_before_use(instrs, j + 1)
            for ops_, o in block:
                name = str(o)
                if name in TEXT_STATE_OPS and not (name == "Tf" and drop_tf):
                    out.append((ops_, o))
            changed += 1
            page_changed = True
            i = j + 1
        if page_changed:
            page.obj.Contents = pdf.make_stream(pikepdf.unparse_content_stream(out))
    return changed
