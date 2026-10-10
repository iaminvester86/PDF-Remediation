"""Apply reviewer decisions to a tagged PDF: figure alt text and decorative marking."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pikepdf
from pikepdf import Array, Name, String

from .structure import figures, read_tree


def _number_tree_get(node, key: int):
    if node is None:
        return None
    if "/Nums" in node:
        nums = node.Nums
        for i in range(0, len(nums) - 1, 2):
            if int(nums[i]) == key:
                return nums[i + 1]
    for kid in node.get("/Kids", []) or []:
        lim = kid.get("/Limits")
        if lim is not None and not (int(lim[0]) <= key <= int(lim[1])):
            continue
        found = _number_tree_get(kid, key)
        if found is not None:
            return found
    return None


def apply_figure_decisions(src: Path, dst: Path, alts: dict[int, str], decorative: set[int]) -> dict:
    """Set /Alt on figures (by index) and convert decorative figures to artifacts.

    Figure indices follow structure.figures() order, the same order the checks report.
    """
    pdf = pikepdf.open(src, allow_overwriting_input=True)
    tree = read_tree(pdf)
    figs = figures(tree)
    applied, decorated, errors = 0, 0, []
    for idx, text in alts.items():
        if 0 <= idx < len(figs) and idx not in decorative:
            figs[idx].raw.Alt = String(text.strip())
            applied += 1

    by_page: dict[int, set[int]] = defaultdict(set)
    to_remove = []
    for idx in sorted(decorative):
        if not 0 <= idx < len(figs):
            continue
        fig = figs[idx]
        mcids = fig.all_mcids()
        if not mcids or fig.objrs or not fig.raw.is_indirect:
            errors.append(f"Figure {idx + 1} cannot be marked decorative automatically.")
            continue
        for page, mcid in mcids:
            by_page[page].add(mcid)
        to_remove.append(fig)

    pages = list(pdf.pages)
    for page_idx, mcids in by_page.items():
        page = pages[page_idx]
        out, found = [], set()
        for ins in pikepdf.parse_content_stream(page):
            operands, op = list(ins.operands), ins.operator
            if str(op) == "BDC" and len(operands) == 2 and isinstance(operands[1], pikepdf.Dictionary):
                mcid = operands[1].get("/MCID")
                if mcid is not None and int(mcid) in mcids:
                    found.add(int(mcid))
                    out.append(([Name.Artifact], pikepdf.Operator("BMC")))
                    continue
            out.append((operands, op))
        page.obj.Contents = pdf.make_stream(pikepdf.unparse_content_stream(out))
        if "/StructParents" in page.obj:
            arr = _number_tree_get(pdf.Root.StructTreeRoot.get("/ParentTree"), int(page.obj.StructParents))
            if isinstance(arr, pikepdf.Array):
                for m in found:
                    if m < len(arr):
                        arr[m] = None
        missing = mcids - found
        if missing:
            errors.append(f"Marked content {sorted(missing)} on page {page_idx + 1} was not found in the page "
                          "content (it may be inside a form XObject).")

    for fig in to_remove:
        parent = fig.raw.get("/P")
        if parent is None:
            continue
        k = parent.get("/K")
        if isinstance(k, pikepdf.Array):
            parent.K = Array([kid for kid in k if not (isinstance(kid, pikepdf.Dictionary) and kid.is_indirect
                                                       and kid.objgen == fig.raw.objgen)])
        elif isinstance(k, pikepdf.Dictionary) and k.objgen == fig.raw.objgen:
            parent.K = Array()
        decorated += 1

    pdf.save(dst)
    pdf.close()
    return {"alt_applied": applied, "decorative": decorated, "errors": errors}
