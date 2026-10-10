"""Decide what to do with a PDF that is already tagged, and carry alt text across a re-tag."""
from __future__ import annotations

from pathlib import Path

from ..checks.semantic import run_qa
from ..checks.verapdf import run_verapdf
from ..config import Settings

# veraPDF clauses the finisher or a reviewer fixes anyway; failures elsewhere mean the
# existing structure itself is broken.
_DOC_LEVEL_CLAUSES = ("5", "6.2", "7.1-8", "7.1-9", "7.1-10", "7.2", "7.3", "7.21")
_STRUCTURAL_QA = {"sqa.heading-untagged", "sqa.heading-small", "sqa.reading-order", "sqa.list-untagged",
                  "sqa.no-headings", "sqa.untagged", "sqa.table-no-headers"}


def needs_retag(path: Path, settings: Settings, use_verapdf: bool = True) -> tuple[bool, str]:
    """Keep good existing tags; replace them when they are structurally broken."""
    structural = sorted({i.rule for i in run_qa(path).issues if i.rule in _STRUCTURAL_QA})
    if structural:
        return True, "existing tags have structural problems (" + ", ".join(structural) + ")"
    if use_verapdf:
        bad = []
        for r in run_verapdf(path, settings).get("failed_rules", []):
            key = f"{r['clause']}-{r['test']}"
            if not any(r["clause"] == c or r["clause"].startswith(c + ".") or key == c for c in _DOC_LEVEL_CLAUSES):
                bad.append(key)
        if bad:
            return True, "existing tags fail PDF/UA structure checks (" + ", ".join(sorted(set(bad))) + ")"
    return False, "existing tags kept (no structural problems found)"


def figures_with_alt(path: Path) -> list[dict]:
    return [f for f in run_qa(path).figures if (f.get("alt") or "").strip() and f.get("bbox")]


def match_alts(old: list[dict], new: list[dict]) -> dict[int, str]:
    """Map alt text from original figures onto re-tagged figures by page and overlap."""
    out: dict[int, str] = {}
    for f in new:
        if not f.get("bbox"):
            continue
        for o in old:
            if o["page"] != f["page"]:
                continue
            a, b = o["bbox"], f["bbox"]
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            if w > 0 and h > 0 and (w * h) / max((b[2] - b[0]) * (b[3] - b[1]), 1e-6) > 0.5:
                out[f["index"]] = o["alt"]
                break
    return out
