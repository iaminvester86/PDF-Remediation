"""Verification: veraPDF (PDF/UA machine checks), rendering gate, text gate."""
from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from PIL import ImageChops

from .config import Settings
from .issues import Issue
from .pdfium_util import page_texts, render_pages

# Approximate mapping from PDF/UA-1 clause prefixes (as reported by veraPDF) to
# Matterhorn checkpoints and WCAG success criteria. Used for report grouping only.
CLAUSE_MAP = [
    ("7.1", ["01", "02", "06"], ["1.3.1"]),
    ("7.2", ["11"], ["3.1.1", "3.1.2"]),
    ("7.3", ["13"], ["1.1.1"]),
    ("7.4", ["14"], ["1.3.1", "2.4.6"]),
    ("7.5", ["15"], ["1.3.1"]),
    ("7.6", ["16"], ["1.3.1"]),
    ("7.7", ["17"], ["1.1.1"]),
    ("7.9", ["19"], ["1.3.1"]),
    ("7.10", ["20"], []),
    ("7.11", ["21"], []),
    ("7.15", ["25"], ["4.1.2"]),
    ("7.16", ["26"], []),
    ("7.18", ["28"], ["2.4.4", "4.1.2"]),
    ("7.20", ["30"], []),
    ("7.21", ["31"], []),
    ("6", ["01"], ["1.3.1"]),
    ("5", ["06"], []),
]


def _map_clause(clause: str) -> tuple[list[str], list[str]]:
    for prefix, mh, wcag in CLAUSE_MAP:
        if clause == prefix or clause.startswith(prefix + "."):
            return [f"CP{m}" for m in mh], wcag
    return [], []


def verapdf_command(settings: Settings) -> list[str] | None:
    if settings.verapdf_cmd:
        exe = shutil.which(settings.verapdf_cmd) or settings.verapdf_cmd
        if Path(exe).exists():
            return [exe]
    lib = settings.verapdf_lib
    if lib.is_dir() and any(lib.glob("*.jar")) and shutil.which(settings.java_cmd):
        return [settings.java_cmd, "-cp", str(lib / "*"), "org.verapdf.apps.GreenfieldCliWrapper"]
    found = shutil.which("verapdf")
    return [found] if found else None


def run_verapdf(path: Path, settings: Settings, flavour: str = "ua1") -> dict:
    cmd = verapdf_command(settings)
    if cmd is None:
        return {"available": False, "compliant": None, "failed_rules": [],
                "message": "veraPDF is not installed. Run scripts/fetch-verapdf.sh or set PDFREM_VERAPDF_CMD."}
    try:
        proc = subprocess.run(cmd + ["-f", flavour, "--format", "json", str(path)], capture_output=True,
                              text=True, timeout=settings.verapdf_timeout)
    except subprocess.TimeoutExpired:
        return {"available": True, "compliant": None, "failed_rules": [], "message": "veraPDF timed out"}
    out = proc.stdout
    start = out.find("{")
    try:
        data = json.loads(out[start:]) if start >= 0 else {}
    except json.JSONDecodeError:
        data = {}
    jobs = data.get("report", {}).get("jobs", [])
    if not jobs or not jobs[0].get("validationResult"):
        err = (proc.stderr or "").strip().splitlines()
        return {"available": True, "compliant": None, "failed_rules": [],
                "message": "veraPDF could not validate the file: " + (err[-1] if err else "no report")}
    vr = jobs[0]["validationResult"][0]
    details = vr.get("details", {})
    rules = []
    for r in details.get("ruleSummaries", []):
        contexts = [c.get("context", "") for c in r.get("checks", [])[:3]]
        rules.append({
            "clause": r.get("clause", ""),
            "test": r.get("testNumber"),
            "description": r.get("description", ""),
            "failed_checks": r.get("failedChecks", 0),
            "contexts": contexts,
        })
    return {"available": True, "compliant": bool(vr.get("compliant")), "profile": vr.get("profileName", ""),
            "passed_rules": details.get("passedRules"), "failed_rules": rules, "message": vr.get("statement", "")}


def verapdf_issues(report: dict) -> list[Issue]:
    issues = []
    for r in report.get("failed_rules", []):
        mh, wcag = _map_clause(r["clause"])
        issues.append(Issue(f"verapdf.{r['clause']}-{r['test']}", "error",
                            f"PDF/UA-1 {r['clause']} (test {r['test']}): {r['description']} "
                            f"[{r['failed_checks']} failed check(s)]",
                            source="verapdf", wcag=wcag, matterhorn=mh))
    return issues


def visual_diff(original: Path, output: Path, scale: float = 0.6, max_pages: int = 200) -> dict:
    """Compare renders page by page. Tagging must not change appearance."""
    changed_pages = []
    worst = 0.0
    a_pages = list(render_pages(original, scale=scale, max_pages=max_pages))
    b_pages = list(render_pages(output, scale=scale, max_pages=max_pages))
    if len(a_pages) != len(b_pages):
        return {"identical": False, "changed_pages": [], "worst_ratio": 1.0,
                "message": f"Page count changed from {len(a_pages)} to {len(b_pages)}"}
    for i, (a, b) in enumerate(zip(a_pages, b_pages)):
        if a.size != b.size:
            changed_pages.append(i + 1)
            worst = 1.0
            continue
        diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
        if diff.getbbox() is None:
            continue
        hist = diff.point(lambda v: 255 if v > 40 else 0).histogram()
        ratio = hist[255] / (a.width * a.height)
        worst = max(worst, ratio)
        if ratio > 0.0005:
            changed_pages.append(i + 1)
    return {"identical": not changed_pages, "changed_pages": changed_pages, "worst_ratio": round(worst, 6),
            "pages_compared": len(a_pages)}


def _norm(t: str) -> str:
    # NFKC folds ligature code points (U+FB01) into letters so a repaired Unicode map
    # is not reported as a text change.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", t)).strip()


def text_diff(original: Path, output: Path) -> dict:
    a = [_norm(t) for t in page_texts(original)]
    b = [_norm(t) for t in page_texts(output)]
    if a == b:
        return {"identical": True, "similarity": 1.0}
    sa, sb = " ".join(a), " ".join(b)
    ratio = difflib.SequenceMatcher(None, sa[:200000], sb[:200000], autojunk=False).ratio()
    return {"identical": False, "similarity": round(ratio, 4),
            "chars_before": len(sa), "chars_after": len(sb)}
