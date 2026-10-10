"""Safety gates: remediation must not change how a document looks or what it says."""
from __future__ import annotations

import difflib
import re
import unicodedata
from pathlib import Path

from PIL import ImageChops

from ..pdf.pdfium import page_texts, render_pages


def visual_diff(original: Path, output: Path, scale: float = 0.6, max_pages: int = 200) -> dict:
    """Compare page renders. Tagging and invisible OCR text must not change appearance."""
    a_pages = list(render_pages(original, scale=scale, max_pages=max_pages))
    b_pages = list(render_pages(output, scale=scale, max_pages=max_pages))
    if len(a_pages) != len(b_pages):
        return {"identical": False, "changed_pages": [], "worst_ratio": 1.0,
                "message": f"Page count changed from {len(a_pages)} to {len(b_pages)}"}
    changed, worst = [], 0.0
    for i, (a, b) in enumerate(zip(a_pages, b_pages)):
        if a.size != b.size:
            changed.append(i + 1)
            worst = 1.0
            continue
        diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
        if diff.getbbox() is None:
            continue
        ratio = diff.point(lambda v: 255 if v > 40 else 0).histogram()[255] / (a.width * a.height)
        worst = max(worst, ratio)
        if ratio > 0.0005:
            changed.append(i + 1)
    return {"identical": not changed, "changed_pages": changed, "worst_ratio": round(worst, 6),
            "pages_compared": len(a_pages)}


def _norm(text: str) -> str:
    # NFKC folds ligature code points (U+FB01) into letters, so a repaired Unicode map
    # is not reported as a change.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def text_diff(baseline: Path, output: Path) -> dict:
    a = [_norm(t) for t in page_texts(baseline)]
    b = [_norm(t) for t in page_texts(output)]
    if a == b:
        return {"identical": True, "similarity": 1.0}
    sa, sb = " ".join(a), " ".join(b)
    ratio = difflib.SequenceMatcher(None, sa[:200000], sb[:200000], autojunk=False).ratio()
    return {"identical": False, "similarity": round(ratio, 4), "chars_before": len(sa), "chars_after": len(sb)}
