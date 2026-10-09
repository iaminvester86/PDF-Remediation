"""Read an existing structure tree (from any engine) into a simple Python model."""
from __future__ import annotations

from dataclasses import dataclass, field

import pikepdf

STANDARD_ROLES = {
    "Document", "Part", "Art", "Sect", "Div", "BlockQuote", "Caption", "TOC", "TOCI", "Index", "NonStruct",
    "Private", "P", "H", "H1", "H2", "H3", "H4", "H5", "H6", "L", "LI", "Lbl", "LBody", "Table", "TR", "TH",
    "TD", "THead", "TBody", "TFoot", "Span", "Quote", "Note", "Reference", "BibEntry", "Code", "Link",
    "Annot", "Ruby", "RB", "RT", "RP", "Warichu", "WT", "WP", "Figure", "Formula", "Form",
    # PDF 2.0 additions
    "DocumentFragment", "Aside", "Title", "FENote", "Sub", "Em", "Strong", "Artifact",
}


@dataclass
class Elem:
    raw: pikepdf.Dictionary
    role: str  # resolved through RoleMap
    raw_role: str
    page: int | None
    parent: "Elem | None" = None
    children: list["Elem"] = field(default_factory=list)
    mcids: list[tuple[int, int]] = field(default_factory=list)  # (page, mcid) direct children
    objrs: list[pikepdf.Object] = field(default_factory=list)
    alt: str | None = None
    actual_text: str | None = None

    def all_mcids(self) -> list[tuple[int, int]]:
        out = list(self.mcids)
        for c in self.children:
            out.extend(c.all_mcids())
        return out

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def _resolve_role(name: str, rolemap) -> str:
    seen = set()
    while name not in STANDARD_ROLES and rolemap is not None and ("/" + name) in rolemap and name not in seen:
        seen.add(name)
        name = str(rolemap["/" + name]).lstrip("/")
    return name


def read_tree(pdf: pikepdf.Pdf) -> Elem | None:
    root = pdf.Root.get("/StructTreeRoot")
    if root is None:
        return None
    rolemap = root.get("/RoleMap")
    page_index = {pg.obj.objgen: i for i, pg in enumerate(pdf.pages)}
    seen: set = set()

    def page_of(d, inherited):
        pg = d.get("/Pg") if isinstance(d, pikepdf.Dictionary) else None
        if pg is not None:
            return page_index.get(pg.objgen, inherited)
        return inherited

    def build(d: pikepdf.Dictionary, parent: Elem | None, inherited_page):
        key = d.objgen if d.is_indirect else id(d)
        if key in seen:
            return None
        seen.add(key)
        raw_role = str(d.get("/S", "/NonStruct")).lstrip("/")
        e = Elem(raw=d, role=_resolve_role(raw_role, rolemap), raw_role=raw_role,
                 page=page_of(d, inherited_page), parent=parent)
        if "/Alt" in d:
            e.alt = str(d.Alt)
        if "/ActualText" in d:
            e.actual_text = str(d.ActualText)
        k = d.get("/K")
        kids = list(k) if isinstance(k, pikepdf.Array) else ([k] if k is not None else [])
        for kid in kids:
            if isinstance(kid, int):  # pikepdf returns PDF integers as Python ints
                if e.page is not None:
                    e.mcids.append((e.page, int(kid)))
            elif isinstance(kid, pikepdf.Dictionary):
                t = str(kid.get("/Type", ""))
                if t == "/MCR":
                    pg = page_of(kid, e.page)
                    if pg is not None and "/MCID" in kid:
                        e.mcids.append((pg, int(kid.MCID)))
                elif t == "/OBJR":
                    e.objrs.append(kid.get("/Obj"))
                elif "/S" in kid:
                    child = build(kid, e, e.page)
                    if child is not None:
                        e.children.append(child)
        return e

    k = root.get("/K")
    top = Elem(raw=root, role="StructTreeRoot", raw_role="StructTreeRoot", page=None)
    kids = list(k) if isinstance(k, pikepdf.Array) else ([k] if k is not None else [])
    for kid in kids:
        if isinstance(kid, pikepdf.Dictionary):
            child = build(kid, top, None)
            if child is not None:
                top.children.append(child)
    return top


def figures(tree: Elem | None) -> list[Elem]:
    if tree is None:
        return []
    return [e for e in tree.walk() if e.role == "Figure"]
