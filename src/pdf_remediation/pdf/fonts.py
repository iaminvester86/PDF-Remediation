"""Font repair that does not change appearance: add missing ToUnicode maps.

Simple fonts (Type 1, TrueType, Type 3) that re-encode glyphs through an
/Encoding /Differences array, or Type 3 fonts generally, often lack a
/ToUnicode map. PDF/UA-1 requires every used character code to map to Unicode
(7.21.7), and without it screen readers may read ligatures such as "fi" as
nothing or as garbage. When the glyph names are standard (Adobe Glyph List,
"uniXXXX", "f_i"), the map can be rebuilt exactly. Ligatures map to their
component letters, as PDF/UA practice recommends. Codes whose glyph names
carry no meaning (for example TeX's "g12") are left unmapped and still
reported by validation.
"""
from __future__ import annotations

import re
import unicodedata

import pikepdf
from fontTools.agl import toUnicode

SIMPLE = {"/Type1", "/MMType1", "/TrueType", "/Type3"}
BASE_CODECS = {"/WinAnsiEncoding": "cp1252", "/MacRomanEncoding": "mac_roman"}


def _unicode_for(glyph: str) -> str:
    text = toUnicode(glyph)
    if not text or any(0xE000 <= ord(c) <= 0xF8FF for c in text):  # private use: no real meaning
        return ""
    if any(0xFB00 <= ord(c) <= 0xFB06 for c in text):  # ligatures -> component letters
        text = unicodedata.normalize("NFKC", text)
    return text


def _code_map(font: pikepdf.Dictionary) -> dict[int, str]:
    enc = font.get("/Encoding")
    mapping: dict[int, str] = {}
    base = None
    differences = None
    if isinstance(enc, pikepdf.Name):
        base = str(enc)
    elif isinstance(enc, pikepdf.Dictionary):
        base = str(enc.get("/BaseEncoding", "")) or None
        differences = enc.get("/Differences")
    codec = BASE_CODECS.get(base or "")
    if codec:
        for code in range(32, 256):
            ch = bytes([code]).decode(codec, errors="ignore")
            if ch and unicodedata.category(ch)[0] != "C":
                mapping[code] = ch
    if isinstance(differences, pikepdf.Array):
        code = 0
        for item in differences:
            if isinstance(item, int):
                code = item
            elif isinstance(item, pikepdf.Name):
                text = _unicode_for(str(item)[1:])
                if text:
                    mapping[code] = text
                else:
                    mapping.pop(code, None)
                code += 1
    return mapping


def _cmap(mapping: dict[int, str]) -> bytes:
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
             "1 begincodespacerange", "<00> <FF>", "endcodespacerange"]
    items = sorted(mapping.items())
    for start in range(0, len(items), 100):
        chunk = items[start:start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        for code, text in chunk:
            lines.append(f"<{code:02X}> <{text.encode('utf-16-be').hex().upper()}>")
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(lines).encode("ascii")


def _fonts_in(resources, seen: set):
    if not isinstance(resources, pikepdf.Dictionary):
        return
    fonts = resources.get("/Font")
    if isinstance(fonts, pikepdf.Dictionary):
        for _, font in fonts.items():
            if isinstance(font, pikepdf.Dictionary) and font.objgen not in seen:
                seen.add(font.objgen)
                yield font
                if str(font.get("/Subtype")) == "/Type3":
                    yield from _fonts_in(font.get("/Resources"), seen)
    xobjects = resources.get("/XObject")
    if isinstance(xobjects, pikepdf.Dictionary):
        for _, xo in xobjects.items():
            if isinstance(xo, pikepdf.Stream) and str(xo.get("/Subtype")) == "/Form" and xo.objgen not in seen:
                seen.add(xo.objgen)
                yield from _fonts_in(xo.get("/Resources"), seen)


def add_missing_tounicode(pdf: pikepdf.Pdf) -> list[str]:
    """Add ToUnicode maps where they can be derived exactly. Returns the font names fixed."""
    fixed: list[str] = []
    seen: set = set()
    for page in pdf.pages:
        for font in _fonts_in(page.obj.get("/Resources"), seen):
            subtype = str(font.get("/Subtype", ""))
            if subtype not in SIMPLE or "/ToUnicode" in font:
                continue
            enc = font.get("/Encoding")
            has_diffs = isinstance(enc, pikepdf.Dictionary) and "/Differences" in enc
            if not (has_diffs or subtype == "/Type3"):
                continue  # standard encodings are already understood by readers
            mapping = _code_map(font)
            if not mapping:
                continue
            font.ToUnicode = pdf.make_stream(_cmap(mapping))
            fixed.append(str(font.get("/BaseFont", font.get("/Name", "Type3 font"))).lstrip("/"))
    return fixed


_INVALID_DST = {"0000", "FEFF", "FFFE", ""}
_SHOW = {"Tj", "TJ", "'", '"'}


def _show_bytes(operands) -> bytes:
    s = operands[-1] if operands else b""
    if isinstance(s, pikepdf.Array):
        return b"".join(bytes(x) for x in s if isinstance(x, pikepdf.String))
    return bytes(s) if isinstance(s, pikepdf.String) else b""


def _code_len(font) -> int:
    return 2 if str(font.get("/Subtype", "")) == "/Type0" else 1


def repair_tounicode_from_actualtext(pdf: pikepdf.Pdf) -> int:
    """Fix invalid ToUnicode entries (U+0000, U+FEFF, U+FFFE) using the file's own ActualText.

    Generators such as Chrome write ``<F0> <0000>`` for ligature glyphs and put the true text in
    ``/Span <</ActualText (fi)>>`` around each use. When every single-glyph span for a code agrees,
    that text is the correct mapping. Returns the number of (font, code) entries repaired.
    """
    learned: dict[tuple, set[str]] = {}
    fonts_by_key: dict[tuple, pikepdf.Dictionary] = {}
    for page in pdf.pages:
        resources = page.obj.get("/Resources")
        fonts = resources.get("/Font") if isinstance(resources, pikepdf.Dictionary) else None
        if not isinstance(fonts, pikepdf.Dictionary):
            continue
        font_stack, font = [], None
        spans: list[dict | None] = []
        for ins in pikepdf.parse_content_stream(page):
            operands, name = list(ins.operands), str(ins.operator)
            if name == "q":
                font_stack.append(font)
            elif name == "Q":
                font = font_stack.pop() if font_stack else None
            elif name == "Tf" and operands:
                font = fonts.get(operands[0])
            elif name in ("BDC", "BMC"):
                props = operands[1] if name == "BDC" and len(operands) > 1 else None
                if isinstance(props, pikepdf.Dictionary) and "/ActualText" in props:
                    spans.append({"text": str(props.ActualText), "shows": []})
                else:
                    spans.append(None)
            elif name == "EMC":
                span = spans.pop() if spans else None
                if span and len(span["shows"]) == 1:
                    f, data = span["shows"][0]
                    if f is not None and len(data) == _code_len(f) and span["text"]:
                        key = (f.objgen, data.hex().upper())
                        fonts_by_key[key] = f
                        learned.setdefault(key, set()).add(span["text"])
            elif name in _SHOW and font is not None:
                for span in spans:
                    if span is not None:
                        span["shows"].append((font, _show_bytes(operands)))

    by_font: dict = {}
    for key, texts in learned.items():
        if len(texts) == 1:
            by_font.setdefault(key[0], []).append((key[1], texts.pop()))
    repaired = 0
    for objgen, entries in by_font.items():
        font = fonts_by_key[(objgen, entries[0][0])]
        tu = font.get("/ToUnicode")
        if not isinstance(tu, pikepdf.Stream):
            continue
        cmap = tu.read_bytes().decode("latin-1")
        changed = False
        for code, text in entries:
            dst = text.encode("utf-16-be").hex().upper()
            pattern = re.compile(rf"(<{code}>\s*<)([0-9A-Fa-f]*)(>)", re.I)
            m = pattern.search(cmap)
            if m and m.group(2).upper() in _INVALID_DST:
                cmap = cmap[: m.start(2)] + dst + cmap[m.end(2):]
                changed = True
                repaired += 1
        if changed:
            font.ToUnicode = pdf.make_stream(cmap.encode("latin-1"))
    return repaired
