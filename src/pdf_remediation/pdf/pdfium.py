"""Read page-object geometry, text, fonts and vector lines through PDFium.

PDFium is not thread-safe: use one document per thread. The application runs
all PDF work in worker processes (see jobs.py).
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
INVISIBLE_RENDER_MODES = {3, 7}  # text drawn without fill or stroke (OCR text layers)

BBox = tuple[float, float, float, float]  # left, bottom, right, top in PDF user space
Segment = tuple[float, float, float, float]  # x0, y0, x1, y1 of a straight path segment


@dataclass
class PObj:
    """One top-level page object as PDFium sees it."""
    kind: str
    bbox: BBox
    text: str = ""
    size: float = 0.0
    font: str = ""
    bold: bool = False
    embedded: bool = True
    invisible: bool = False
    mcid: int = -1
    form_has_text: bool = False  # form XObjects only
    form_has_image: bool = False


@dataclass
class PageInfo:
    width: float
    height: float
    objects: list[PObj] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)  # straight lines from path objects
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
    name = ""
    n = R.FPDFFont_GetBaseFontName(font, None, 0)
    if n > 1:
        buf = ctypes.create_string_buffer(n)
        R.FPDFFont_GetBaseFontName(font, buf, n)
        name = buf.value.decode("latin-1", errors="replace")
    bold = R.FPDFFont_GetWeight(font) >= 600 or any(k in name.lower() for k in ("bold", "black", "heavy", "semibold"))
    return name, bold, R.FPDFFont_GetIsEmbedded(font) == 1


def _effective_size(obj_raw, mat) -> float:
    size = ctypes.c_float(0)
    if not R.FPDFTextObj_GetFontSize(obj_raw, ctypes.byref(size)):
        return 0.0
    return float(size.value) * (math.sqrt(abs(mat.a * mat.d - mat.b * mat.c)) or 1.0)


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
            sub_text, sub_image = _form_contents(child)
            has_text, has_image = has_text or sub_text, has_image or sub_image
    return has_text, has_image


def _path_segments(obj) -> list[Segment]:
    """Straight segments of a path object, in page coordinates."""
    m = obj.get_matrix()

    def tx(x: float, y: float) -> tuple[float, float]:
        return m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f

    out: list[Segment] = []
    x, y = ctypes.c_float(), ctypes.c_float()
    start = prev = None
    for i in range(R.FPDFPath_CountSegments(obj.raw)):
        seg = R.FPDFPath_GetPathSegment(obj.raw, i)
        R.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
        pt = tx(x.value, y.value)
        kind = R.FPDFPathSegment_GetType(seg)
        if kind == R.FPDF_SEGMENT_MOVETO:
            start = prev = pt
            continue
        if kind == R.FPDF_SEGMENT_LINETO and prev is not None:
            out.append((prev[0], prev[1], pt[0], pt[1]))
        prev = pt
        if R.FPDFPathSegment_GetClose(seg) and start is not None and prev != start:
            out.append((prev[0], prev[1], start[0], start[1]))
            prev = start
    return out


def read_page(doc: pdfium.PdfDocument, index: int) -> PageInfo:
    page = doc[index]
    width, height = page.get_size()
    textpage = page.get_textpage()
    info = PageInfo(width=width, height=height)
    try:
        info.full_text = textpage.get_text_range()
    except Exception:  # damaged text layers should not stop analysis
        info.full_text = ""
    for obj in page.get_objects(max_depth=1):
        kind = KIND_BY_TYPE.get(obj.type, "other")
        p = PObj(kind=kind, bbox=tuple(float(v) for v in obj.get_bounds()),
                 mcid=R.FPDFPageObj_GetMarkedContentID(obj.raw))
        if kind == "text":
            p.text = _text_of(obj.raw, textpage.raw)
            p.size = _effective_size(obj.raw, obj.get_matrix())
            p.font, p.bold, p.embedded = _font_facts(obj.raw)
            p.invisible = R.FPDFTextObj_GetTextRenderMode(obj.raw) in INVISIBLE_RENDER_MODES
            l, b, r, t = p.bbox
            if p.invisible and t - b < 0.5 and p.size > 0:
                # OCR layers use empty glyphs, so PDFium reports a zero-height box on the baseline.
                # Give it the line's typographic height so layout analysis works as for normal text.
                p.bbox = (l, b - 0.2 * p.size, r, b + 0.8 * p.size)
        elif kind == "form":
            p.form_has_text, p.form_has_image = _form_contents(obj.raw)
            if p.form_has_text:
                l, b, r, t = p.bbox
                p.text = textpage.get_text_bounded(left=l, bottom=b, right=r, top=t)
        elif kind == "path":
            info.segments.extend(_path_segments(obj))
        info.objects.append(p)
    return info


def device_to_page(page: pdfium.PdfPage, size: tuple[int, int], x: float, y: float) -> tuple[float, float]:
    """Convert a pixel position in a rendered page image to PDF user space (handles /Rotate)."""
    px, py = ctypes.c_double(), ctypes.c_double()
    R.FPDF_DeviceToPage(page.raw, 0, 0, size[0], size[1], 0, int(round(x)), int(round(y)),
                        ctypes.byref(px), ctypes.byref(py))
    return px.value, py.value


def render_pages(path, scale: float = 0.75, max_pages: int | None = None):
    """Yield PIL images of each page (visual diff, thumbnails)."""
    doc = pdfium.PdfDocument(str(path))
    try:
        n = len(doc) if max_pages is None else min(len(doc), max_pages)
        for i in range(n):
            yield doc[i].render(scale=scale).to_pil()
    finally:
        doc.close()


def render_crop(path, page_index: int, bbox: BBox, scale: float = 2.0, pad: float = 4.0):
    """Render one region of a page (figure review, AI alt text)."""
    doc = pdfium.PdfDocument(str(path))
    try:
        page = doc[page_index]
        _, h = page.get_size()
        img = page.render(scale=scale).to_pil()
        l, b, r, t = bbox
        box = (max(0, int((l - pad) * scale)), max(0, int((h - t - pad) * scale)),
               min(img.width, int((r + pad) * scale)), min(img.height, int((h - b + pad) * scale)))
        return img if box[2] <= box[0] or box[3] <= box[1] else img.crop(box)
    finally:
        doc.close()


def page_texts(path) -> list[str]:
    doc = pdfium.PdfDocument(str(path))
    try:
        return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    finally:
        doc.close()
