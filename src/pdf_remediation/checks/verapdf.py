"""veraPDF: the reference PDF/UA validator, run as a separate Java process."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..config import Settings
from ..issues import Issue
from ..java import verapdf_command

# Approximate mapping from PDF/UA-1 clauses (as reported by veraPDF) to Matterhorn
# checkpoints and WCAG success criteria. Used to group report entries only.
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
    for prefix, checkpoints, wcag in CLAUSE_MAP:
        if clause == prefix or clause.startswith(prefix + "."):
            return [f"CP{c}" for c in checkpoints], wcag
    return [], []


def command(settings: Settings) -> list[str] | None:
    return verapdf_command(settings.verapdf_lib, settings.java_cmd, settings.verapdf_cmd)


def not_run(message: str) -> dict:
    return {"available": False, "compliant": None, "failed_rules": [], "message": message}


def run_verapdf(path: Path, settings: Settings, flavour: str = "ua1") -> dict:
    cmd = command(settings)
    if cmd is None:
        return not_run("veraPDF is not installed. Run: pdfrem install-engines")
    try:
        proc = subprocess.run(cmd + ["-f", flavour, "--format", "json", str(path)], capture_output=True,
                              text=True, timeout=settings.verapdf_timeout)
    except subprocess.TimeoutExpired:
        return {**not_run("veraPDF timed out"), "available": True}
    start = proc.stdout.find("{")
    try:
        data = json.loads(proc.stdout[start:]) if start >= 0 else {}
    except json.JSONDecodeError:
        data = {}
    jobs = data.get("report", {}).get("jobs", [])
    if not jobs or not jobs[0].get("validationResult"):
        err = (proc.stderr or "").strip().splitlines()
        return {**not_run("veraPDF could not validate the file: " + (err[-1] if err else "no report")),
                "available": True}
    result = jobs[0]["validationResult"][0]
    details = result.get("details", {})
    rules = [{
        "clause": r.get("clause", ""),
        "test": r.get("testNumber"),
        "description": r.get("description", ""),
        "failed_checks": r.get("failedChecks", 0),
        "contexts": [c.get("context", "") for c in r.get("checks", [])[:3]],
    } for r in details.get("ruleSummaries", [])]
    return {"available": True, "compliant": bool(result.get("compliant")), "profile": result.get("profileName", ""),
            "passed_rules": details.get("passedRules"), "failed_rules": rules, "message": result.get("statement", "")}


def verapdf_issues(report: dict) -> list[Issue]:
    issues = []
    for r in report.get("failed_rules", []):
        checkpoints, wcag = _map_clause(r["clause"])
        issues.append(Issue(f"verapdf.{r['clause']}-{r['test']}", "error",
                            f"PDF/UA-1 {r['clause']} (test {r['test']}): {r['description']} "
                            f"[{r['failed_checks']} failed check(s)]",
                            source="verapdf", wcag=wcag, matterhorn=checkpoints))
    return issues
