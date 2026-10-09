"""Read page-object geometry, text and font facts through PDFium.

PDFium is not thread-safe. Callers must use one document per thread, and the
application runs PDF work in worker processes (see jobs.py).
"""
from __future__ import annotations

import ctypes
import math
from dataclasses import dataclass, field

import pypdfium2 as pdfium
import pypdfium2.raw as R

KIND_BY_TYPE = {
    R.FPDF_PAGEOBJ_TEXT: "text",
    R.FPDF_PAGEOBJ_IMAGE: "image",
    R.FPDF_PAGEOBJ_FORM: "form",
    R.FPDF_PAGEOBJ_PATH: "path",
    R.FPDF_PAGEOBJ_SHADING: "shading",
}

BBox = tuple[float, float, float, float]  # left, bottom, right, top (PDF user space)


@dataclass
class PObj:
    kind: str
    bbox: BBox
    text: str = ""
    size: float = 0.0
    font: str = ""
    bold: bool = False
    embedded: bool = True
    mcid: int = -1
    # Form XObjects only
    form_has_text: bool = False
    form_has_image: bool = False


@dataclass
class PageInfo:
    width: float
    height: float
    objects: list[PObj] = field(default_factory=list)
    full_text: str = ""


def _text_of(obj_raw, textpage_raw) -> str:
    n = R.FPDFTextObj_GetText(obj_raw, textpage_raw, None, 0)
    if n <= 2:
        return ""
    buf = ctypes.create_string_buffer(n)
    R.FPDFTextObj_GetText(obj_raw, textpage_raw, ctypes.cast(buf, ctypes.POINTER(R.FPDF_WCHAR)), n)
    return buf.raw[: n - 2].decode("utf-16-le", errors="replace")


def _font_facts(obj_raw) -> tuple[str, bool, bool]:
    font = R.FPDFTextObj_GetFont(obj_raw)
    if not font:
        return "", False, True
    n = R.FPDFFont_GetBaseFontName(font, None, 0)
    name = ""
    if n > 1:
        buf = ctypes.create_string_buffer(n)
        R.FPDFFont_GetBaseFontName(font, buf, n)
        name = buf.value.decode("latin-1", errors="replace")
    weight = R.FPDFFont_GetWeight(font)
    bold = weight >= 600 or any(k in name.lower() for k in ("bold", "black", "heavy", "semibold"))
    embedded = R.FPDFFont_GetIsEmbedded(font) == 1
    return name, bold, embedded


def _effective_size(obj_raw, mat) -> float:
    size = ctypes.c_float(0)
    if not R.FPDFTextObj_GetFontSize(obj_raw, ctypes.byref(size)):
        return 0.0
    scale = math.sqrt(abs(mat.a * mat.d - mat.b * mat.c)) or 1.0
    return float(size.value) * scale


def _form_contents(form_raw) -> tuple[bool, bool]:
    has_text = has_image = False
    for i in range(R.FPDFFormObj_CountObjects(form_raw)):
        child = R.FPDFFormObj_GetObject(form_raw, i)
        t = R.FPDFPageObj_GetType(child)
        if t == R.FPDF_PAGEOBJ_TEXT:
            has_text = True
        elif t == R.FPDF_PAGEOBJ_IMAGE:
            has_image = True
        elif t == R.FPDF_PAGEOBJ_FORM:
            sub_t, sub_i = _form_contents(child)
            has_text |= sub_t
            has_image |= sub_i
    return has_text, has_image


def read_page(doc: pdfium.PdfDocument, index: int) -> PageInfo:
    page = doc[index]
    width, height = page.get_size()
    textpage = page.get_textpage()
    info = PageInfo(width=width, height=height)
    try:
        info.full_text = textpage.get_text_range()
    except Exception:  # pragma: no cover - damaged text layers
        info.full_text = ""
    for obj in page.get_objects(max_depth=1):
        kind = KIND_BY_TYPE.get(obj.type, "other")
        bbox = tuple(float(v) for v in obj.get_bounds())
        p = PObj(kind=kind, bbox=bbox, mcid=R.FPDFPageObj_GetMarkedContentID(obj.raw))
        if kind == "text":
            p.text = _text_of(obj.raw, textpage.raw)
            p.size = _effective_size(obj.raw, obj.get_matrix())
            p.font, p.bold, p.embedded = _font_facts(obj.raw)
        elif kind == "form":
            p.form_has_text, p.form_has_image = _form_contents(obj.raw)
            if p.form_has_text:
                l, b, r, t = bbox
                p.text = textpage.get_text_bounded(left=l, bottom=b, right=r, top=t)
        info.objects.append(p)
    return info


def render_pages(path, scale: float = 0.75, max_pages: int | None = None):
    """Yield PIL images of each page (used for visual diff and figure crops)."""
    doc = pdfium.PdfDocument(str(path))
    try:
        n = len(doc) if max_pages is None else min(len(doc), max_pages)
        for i in range(n):
            yield doc[i].render(scale=scale).to_pil()
    finally:
        doc.close()


def render_crop(path, page_index: int, bbox: BBox, scale: float = 2.0, pad: float = 4.0):
    """Render a figure region to a PIL image."""
    doc = pdfium.PdfDocument(str(path))
    try:
        page = doc[page_index]
        w, h = page.get_size()
        img = page.render(scale=scale).to_pil()
        l, b, r, t = bbox
        box = (
            max(0, int((l - pad) * scale)),
            max(0, int((h - t - pad) * scale)),
            min(img.width, int((r + pad) * scale)),
            min(img.height, int((h - b + pad) * scale)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            return img
        return img.crop(box)
    finally:
        doc.close()


def page_texts(path) -> list[str]:
    doc = pdfium.PdfDocument(str(path))
    try:
        return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    finally:
        doc.close()
