"""Write per-file JSON and HTML reports next to the remediated PDF."""
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

_env: Environment | None = None

STATUS_LABELS = {
    "ready-for-review": "Ready for human review",
    "needs-attention": "Needs attention",
    "failed": "Failed",
    "queued": "Queued",
    "processing": "Processing",
    "fetching": "Fetching",
}


def env() -> Environment:
    global _env
    if _env is None:
        _env = Environment(loader=PackageLoader("pdf_remediation", "templates"),
                           autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
        _env.globals["status_label"] = lambda s: STATUS_LABELS.get(s, s)
    return _env


def report_paths(out_pdf: Path) -> tuple[Path, Path]:
    return (out_pdf.with_name(out_pdf.stem + ".report.json"), out_pdf.with_name(out_pdf.stem + ".report.html"))


def write_reports(result: dict, out_pdf: Path) -> None:
    jpath, hpath = report_paths(out_pdf)
    if out_pdf.exists():
        result["outputs"]["pdf"] = out_pdf.name
    result["outputs"]["report_json"] = jpath.name
    result["outputs"]["report_html"] = hpath.name
    jpath.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    css = (Path(__file__).parent / "static" / "app.css").read_text(encoding="utf-8")
    html = env().get_template("report_standalone.html").render(r=result, css=css)
    hpath.write_text(html, encoding="utf-8")
