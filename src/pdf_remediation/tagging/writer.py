"""Write a structure tree: annotations, marked content (MCIDs) and StructTreeRoot."""
from __future__ import annotations

import re
from collections import defaultdict

import pikepdf
from pikepdf import Array, Dictionary, Name, String

from ..issues import Issue
from ..pdf.content import SHOW_OPS, Item
from ..pdf.pdfium import BBox
from .model import Node, Objr, TagResult, join_text, overlap_ratio

_STRUCTURE_OPS = {"BT", "ET", "q", "Q", "BDC", "BMC", "EMC"}


def remove_existing_structure(pdf: pikepdf.Pdf) -> None:
    for key in ("/StructTreeRoot", "/MarkInfo"):
        if key in pdf.Root:
            del pdf.Root[key]
    for page in pdf.pages:
        if "/StructParents" in page.obj:
            del page.obj["/StructParents"]
        for annot in page.obj.get("/Annots", []) or []:
            if isinstance(annot, pikepdf.Dictionary) and "/StructParent" in annot:
                del annot["/StructParent"]


# ---------------------------------------------------------------- annotations

def _annot_rect(annot) -> BBox | None:
    try:
        r = [float(v) for v in annot.Rect]
        return (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3]))
    except Exception:
        return None


def _field_with_name(annot) -> tuple[pikepdf.Dictionary | None, str]:
    node = annot
    for _ in range(20):
        if node is None:
            break
        if "/T" in node:
            return node, str(node.T)
        node = node.get("/Parent")
    return None, ""


def _walk(nodes):
    for n in nodes:
        if isinstance(n, Node):
            yield n
            yield from _walk([k for k in n.kids if isinstance(k, Node)])


def attach_annotations(page, idx: int, page_nodes: list[Node], result: TagResult) -> None:
    """Nest links in the text they cover; add Form/Annot elements for other annotations."""
    for annot in page.obj.get("/Annots") or []:
        if not isinstance(annot, pikepdf.Dictionary):
            continue
        subtype = str(annot.get("/Subtype", ""))
        if subtype in ("/Popup", "/PrinterMark", "/TrapNet") or int(annot.get("/F", 0)) & 2:  # 2 = hidden
            continue
        if subtype == "/Link":
            _attach_link(annot, idx, page_nodes)
        elif subtype == "/Widget":
            page_nodes.append(Node("Form", idx, kids=[Objr(annot, idx)]))
            field, name = _field_with_name(annot)
            target = field if field is not None else annot
            if "/TU" not in target or not str(target.TU).strip():
                label = re.sub(r"[_\-.]+", " ", name).strip() or "Form field"
                target.TU = String(label)
                result.issues.append(Issue(
                    "tagger.form-tu-generated", "warning",
                    f"Form field '{name or '(unnamed)'}' had no accessible description; '{label}' was generated "
                    "from its name. Review it.", page=idx + 1, source="tagger", wcag=["3.3.2", "4.1.2"],
                    matterhorn=["28-005"]))
        else:
            contents = str(annot.get("/Contents", "")).strip()
            page_nodes.append(Node("Annot", idx, kids=[Objr(annot, idx)],
                                   alt=contents or subtype.lstrip("/") + " annotation"))


def _attach_link(annot, idx: int, page_nodes: list[Node]) -> None:
    rect = _annot_rect(annot)
    link = Node("Link", idx)
    placed = False
    if rect:
        for node in _walk(page_nodes):
            run: list[int] = []
            for k, kid in enumerate(node.kids):
                if isinstance(kid, Item) and kid.obj and overlap_ratio(kid.obj.bbox, rect) > 0.3:
                    if run and k != run[-1] + 1:
                        break
                    run.append(k)
            if run:
                linked = [node.kids[k] for k in run]
                for it in linked:
                    it.owner = link
                link.kids.extend(linked)
                link.text = join_text(linked).strip()
                node.kids[run[0]:run[-1] + 1] = [link]
                placed = True
                break
    link.kids.append(Objr(annot, idx))
    if not placed:
        page_nodes.append(link)
    if "/Contents" not in annot or not str(annot.Contents).strip():
        action = annot.get("/A")
        uri = str(action.URI) if isinstance(action, pikepdf.Dictionary) and "/URI" in action else ""
        annot.Contents = String(link.text or uri or "Link")


# ------------------------------------------------------------ marked content

def mark_page_content(pdf: pikepdf.Pdf, page, ops: list, items: list[Item]) -> list[Node]:
    """Wrap each content item in marked content and rewrite the page stream.

    Items owned by a structure node get ``BDC <</MCID n>>``; everything else
    (paths, empty text, headers/footers, decorative images) becomes an artifact.
    Returns the owner node of each MCID, in MCID order, for the ParentTree.
    """
    opens: dict[int, list] = defaultdict(list)
    closes: dict[int, list] = defaultdict(list)
    owners: list[Node] = []
    for it in items:
        if it.kind == "clip":
            continue
        if it.kind in ("path", "shading", "text-empty") or it.artifact or it.owner is None:
            if it.kind == "path" and any(str(ops[k][1]) in _STRUCTURE_OPS for k in range(it.start, it.end + 1)):
                continue  # malformed path spanning structure operators: leave untouched
            if it.artifact in ("Header", "Footer"):
                props = Dictionary(Type=Name.Pagination, Subtype=Name("/" + it.artifact))
                opens[it.start].append(([Name.Artifact, props], pikepdf.Operator("BDC")))
            else:
                opens[it.start].append(([Name.Artifact], pikepdf.Operator("BMC")))
            closes[it.end].append(([], pikepdf.Operator("EMC")))
            continue
        it.mcid = len(owners)
        owner: Node = it.owner
        opens[it.start].append(([Name("/" + owner.role), Dictionary(MCID=it.mcid)], pikepdf.Operator("BDC")))
        closes[it.end].append(([], pikepdf.Operator("EMC")))
        owners.append(owner)
    new_ops: list = []
    for i, instr in enumerate(ops):
        new_ops.extend(opens.get(i, []))
        new_ops.append(instr)
        new_ops.extend(closes.get(i, []))
    page.obj.Contents = pdf.make_stream(pikepdf.unparse_content_stream(merge_actualtext_spans(new_ops)))
    return owners


def merge_actualtext_spans(ops: list) -> list:
    """Fold ``/Span <</ActualText ...>>`` around a single tagged item into that item's mark.

    Generators (Chrome, Word) mark ligatures as ``/Span <</ActualText (fi)>> BDC ... EMC``.
    After tagging, the MCID mark sits inside that span, and some readers (PDFium) take only
    the innermost properties and lose the ActualText. One mark holding both is unambiguous.
    """
    out: list = []
    i, n = 0, len(ops)
    painting = {"BDC", "BMC", "EMC", "Do", "INLINE IMAGE", "sh"} | SHOW_OPS
    while i < n:
        operands, op = ops[i]
        props = operands[1] if str(op) == "BDC" and len(operands) == 2 else None
        if isinstance(props, Dictionary) and "/ActualText" in props and "/MCID" not in props:
            j, pre = i + 1, []
            while j < n and str(ops[j][1]) not in painting:
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
                out += [([inner[0], merged], pikepdf.Operator("BDC")), ops[j + 1], ops[j + 2]]
                i = j + 4
                continue
        out.append(ops[i])
        i += 1
    return out


# ------------------------------------------------------------ structure tree

def _attribute_dict(attrs: dict) -> Dictionary:
    return Dictionary({"/" + k: (Name(v) if isinstance(v, str) and v.startswith("/") else v)
                       for k, v in attrs.items()})


def write_structure(pdf: pikepdf.Pdf, doc_node: Node, parent_entries: dict[int, list[Node]]) -> None:
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
        if node.attrs:
            d.A = _attribute_dict(node.attrs)
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
