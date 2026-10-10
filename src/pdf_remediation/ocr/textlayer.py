"""Write OCR results into a PDF as an invisible, searchable, taggable text layer.

Each recognised line becomes one text-showing operator in rendering mode 3
(invisible), positioned and horizontally scaled to cover the line in the page
image. The font is a "glyphless" CID font: every character code maps to one
box glyph that is never painted (rendering mode 3), so the layer never changes
appearance, while the ToUnicode map
returns the real characters to screen readers, search and copy-paste. The page
image itself is later marked as an artifact by the tagger.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass

import pikepdf
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from pikepdf import Array, Dictionary, Name, String

FONT_KEY = "/PdfRemOcr"
_UNITS = 1000
_ADVANCE = 500  # every glyph is half an em wide; Tz stretches lines to fit
_ASCENT, _DESCENT = 800, -200


@dataclass
class TextLine:
    """One recognised line in PDF user space.

    ``origin`` is the bottom-left corner of the line box; ``along`` and ``up`` are the
    vectors from it to the bottom-right and top-left corners. Using vectors (rather than
    an axis-aligned box) keeps the text aligned with the image on rotated pages.
    """
    text: str
    origin: tuple[float, float]
    along: tuple[float, float]
    up: tuple[float, float]
    confidence: float = 1.0


def _glyphless_truetype() -> bytes:
    fb = FontBuilder(_UNITS, isTTF=True)
    fb.setupGlyphOrder([".notdef", "blank"])
    fb.setupCharacterMap({0x20: "blank"})
    empty = TTGlyphPen(None).glyph()
    # The glyph is a box the size of the em. It is never painted (rendering mode 3), but its
    # outline gives each character real bounds, which readers need to select and extract text
    # on rotated pages.
    pen = TTGlyphPen(None)
    pen.moveTo((0, _DESCENT))
    pen.lineTo((0, _ASCENT))
    pen.lineTo((_ADVANCE, _ASCENT))
    pen.lineTo((_ADVANCE, _DESCENT))
    pen.closePath()
    fb.setupGlyf({".notdef": empty, "blank": pen.glyph()})
    fb.setupHorizontalMetrics({".notdef": (_ADVANCE, 0), "blank": (_ADVANCE, 0)})
    fb.setupHorizontalHeader(ascent=_ASCENT, descent=_DESCENT)
    fb.setupNameTable({"familyName": "PdfRemOcrGlyphless", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=_ASCENT, sTypoDescender=_DESCENT, usWinAscent=_ASCENT, usWinDescent=-_DESCENT)
    fb.setupPost()
    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


def _identity_tounicode() -> bytes:
    """Map every 2-byte code to the same UTF-16 code unit (surrogate block excluded)."""
    ranges = [f"<{hi:02X}00> <{hi:02X}FF> <{hi:02X}00>" for hi in range(256) if not 0xD8 <= hi <= 0xDF]
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
             "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange"]
    for start in range(0, len(ranges), 100):
        chunk = ranges[start:start + 100]
        lines += [f"{len(chunk)} beginbfrange", *chunk, "endbfrange"]
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(lines).encode("ascii")


def glyphless_font(pdf: pikepdf.Pdf) -> pikepdf.Dictionary:
    program = _glyphless_truetype()
    descriptor = pdf.make_indirect(Dictionary(
        Type=Name.FontDescriptor, FontName=Name("/PdfRemOcrGlyphless"), Flags=5,
        FontBBox=Array([0, _DESCENT, _ADVANCE, _ASCENT]), ItalicAngle=0, Ascent=_ASCENT, Descent=_DESCENT,
        CapHeight=700, StemV=80, FontFile2=pdf.make_stream(program, Length1=len(program))))
    cid_font = pdf.make_indirect(Dictionary(
        Type=Name.Font, Subtype=Name.CIDFontType2, BaseFont=Name("/PdfRemOcrGlyphless"),
        CIDSystemInfo=Dictionary(Registry=String("Adobe"), Ordering=String("Identity"), Supplement=0),
        FontDescriptor=descriptor, DW=_ADVANCE,
        CIDToGIDMap=pdf.make_stream(b"\x00\x01" * 65536)))  # every CID -> the blank glyph
    return pdf.make_indirect(Dictionary(
        Type=Name.Font, Subtype=Name.Type0, BaseFont=Name("/PdfRemOcrGlyphless"), Encoding=Name("/Identity-H"),
        DescendantFonts=Array([cid_font]), ToUnicode=pdf.make_stream(_identity_tounicode())))


def _encode(text: str) -> bytes:
    """UTF-16BE, one code unit per character; characters outside the BMP become U+FFFD."""
    return "".join(c if ord(c) <= 0xFFFF and not 0xD800 <= ord(c) <= 0xDFFF else "�"
                   for c in text).encode("utf-16-be")


def _fmt(v: float) -> str:
    out = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if out in ("-0", "") else out


class TextLayerWriter:
    """Adds invisible OCR text to pages of one PDF, sharing a single font object."""

    def __init__(self, pdf: pikepdf.Pdf):
        self.pdf = pdf
        self._font: pikepdf.Dictionary | None = None

    @property
    def font(self) -> pikepdf.Dictionary:
        if self._font is None:
            self._font = glyphless_font(self.pdf)
        return self._font

    def add(self, page: pikepdf.Page, lines: list[TextLine]) -> int:
        parts = []
        for line in lines:
            text = " ".join(line.text.split())
            if not text:
                continue
            width = math.hypot(*line.along)
            height = math.hypot(*line.up)
            if width < 1 or height < 1:
                continue
            ux, uy = line.along[0] / width, line.along[1] / width  # text direction
            vx, vy = line.up[0] / height, line.up[1] / height  # glyph "up" direction
            size = height * 0.8  # approximate type size from the line box
            scale = max(1.0, min(1000.0, 100.0 * width / (len(text) * size * _ADVANCE / _UNITS)))
            ox, oy = line.origin[0] + vx * 0.2 * height, line.origin[1] + vy * 0.2 * height  # baseline
            parts.append(f"BT 3 Tr {FONT_KEY} {_fmt(size)} Tf {_fmt(scale)} Tz "
                         f"{_fmt(ux)} {_fmt(uy)} {_fmt(vx)} {_fmt(vy)} {_fmt(ox)} {_fmt(oy)} Tm "
                         f"<{_encode(text).hex().upper()}> Tj ET")
        if not parts:
            return 0
        # add_resource copes with resources inherited from the page tree.
        page.add_resource(self.font, Name.Font, Name(FONT_KEY), replace_existing=True)
        # Isolate the existing drawing so its graphics state cannot affect the text layer.
        page.contents_add(self.pdf.make_stream(b"q\n"), prepend=True)
        page.contents_add(self.pdf.make_stream(("Q\n" + "\n".join(parts) + "\n").encode("ascii")))
        return len(parts)
