"""Document-level PDF/UA-1 requirements, applied after any structure engine.

These are the steps OpenDataLoader's free tier leaves out (spike 001) and the
basic engine needs too: MarkInfo, Lang, title, DisplayDocTitle, tab order,
XMP with the PDF/UA identifier, and bookmarks built from headings.
"""
from __future__ import annotations

import re
from pathlib import Path

import pikepdf
from pikepdf import Dictionary, Name, String

from ..issues import Issue

GENERIC_TITLE_RE = re.compile(
    r"^\s*$|^(untitled|document\d*|microsoft (word|powerpoint|excel)\b.*|.*\.(docx?|pptx?|xlsx?|pdf|indd|tmp))$",
    re.I,
)
LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def is_generic_title(title: str) -> bool:
    return bool(GENERIC_TITLE_RE.match(title or ""))


def existing_title(pdf: pikepdf.Pdf) -> str:
    try:
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            t = meta.get("dc:title")
            if t:
                return str(t)
    except Exception:
        pass
    try:
        return str(pdf.docinfo.get("/Title", "") or "")
    except Exception:
        return ""


def title_from_filename(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem[:1].upper() + stem[1:] if stem else "Document"


def finish(pdf: pikepdf.Pdf, *, filename: str, lang: str, title_candidate: str = "",
           headings: list[dict] | None = None, add_bookmarks: bool = True) -> tuple[list[Issue], dict]:
    issues: list[Issue] = []
    facts: dict = {}
    root = pdf.Root
    root.MarkInfo = Dictionary(Marked=True)

    current_lang = str(root.get("/Lang", "")).strip()
    if current_lang and LANG_RE.match(current_lang):
        facts["lang"] = current_lang
    else:
        root.Lang = String(lang)
        facts["lang"] = lang
        issues.append(Issue("doc.lang-set", "info", f"Document language set to '{lang}'. Confirm it is correct.",
                            source="pipeline", wcag=["3.1.1"], matterhorn=["11-006"]))

    title = existing_title(pdf).strip()
    title_source = "existing"
    if is_generic_title(title):
        if title_candidate and not is_generic_title(title_candidate):
            title, title_source = title_candidate.strip()[:200], "first heading"
        else:
            title, title_source = title_from_filename(filename), "file name"
        issues.append(Issue("doc.title-generated", "warning",
                            f"Document title set to '{title}' (from the {title_source}). Review it.",
                            source="pipeline", wcag=["2.4.2"], matterhorn=["06-003"]))
    facts["title"], facts["title_source"] = title, title_source

    prefs = root.get("/ViewerPreferences")
    if not isinstance(prefs, pikepdf.Dictionary):
        prefs = Dictionary()
    prefs.DisplayDocTitle = True
    root.ViewerPreferences = prefs
    for page in pdf.pages:
        page.obj.Tabs = Name.S

    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
        meta["dc:title"] = title
        meta.register_xml_namespace("http://www.aiim.org/pdfua/ns/id/", "pdfuaid")
        meta["pdfuaid:part"] = "1"
    pdf.docinfo["/Title"] = String(title)

    headings = headings or []
    facts["bookmarks_added"] = 0
    if add_bookmarks and len(pdf.pages) > 1 and len(headings) >= 2 and "/Outlines" not in root:
        _add_bookmarks(pdf, headings)
        facts["bookmarks_added"] = len(headings)
    return issues, facts


def _add_bookmarks(pdf: pikepdf.Pdf, headings: list[dict]) -> None:
    with pdf.open_outline() as outline:
        stack: list[tuple[int, pikepdf.OutlineItem]] = []
        for h in headings[:500]:
            text = re.sub(r"\s+", " ", h["text"]).strip()[:200] or "Section"
            item = pikepdf.OutlineItem(text, h["page"], "XYZ", top=h.get("top"))
            while stack and stack[-1][0] >= h["level"]:
                stack.pop()
            if stack:
                stack[-1][1].children.append(item)
            else:
                outline.root.append(item)
            stack.append((h["level"], item))
