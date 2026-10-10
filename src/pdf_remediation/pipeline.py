"""Remediate one PDF.

    inspect -> OCR (only pages that need it) -> normalise -> tag -> finish
    -> reviewer/AI alt text -> verify (veraPDF, semantic QA, gates) -> report

Each stage records a step in the result so the report shows exactly what was
done. Failures become a "failed" result with a reason; they never stop a batch.
"""
from __future__ import annotations

import shutil
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium

from . import __version__
from .checks import ALT_PLACEHOLDER_RE, QAResult, run_qa, run_verapdf, text_diff, verapdf_issues, visual_diff
from .config import Settings
from .inputs import InputError, inspect_pdf
from .issues import Issue, sort_issues
from .ocr import get_engine, pages_needing_ocr, run_ocr
from .pdf.edit import apply_figure_decisions
from .pdf.finisher import finish
from .pdf.fonts import add_missing_tounicode, repair_tounicode_from_actualtext
from .pdf.normalize import collapse_empty_text_blocks
from .pdf.structure import figures, read_tree
from .report import write_reports
from .tagging import odl_autotag, odl_available, tag_document
from .tagging.existing import figures_with_alt, match_alts, needs_retag


@dataclass
class Options:
    """Per-job choices (the web form and CLI flags map onto these)."""
    engine: str = ""  # "" = settings default | auto | basic | odl
    lang: str = ""  # default document language; "" = settings default
    existing_tags: str = "auto"  # auto (keep good, replace broken) | keep | retag
    ocr: str = "auto"  # auto (pages without text) | off
    ai: bool = False
    accept_ai_alt: bool = False
    verapdf: bool = True
    alts: dict[int, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Options":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        if "alts" in known:
            known["alts"] = {int(k): v for k, v in known["alts"].items()}
        return cls(**known)


class _Run:
    """Result and issue log for one file."""

    def __init__(self, display_name: str, source: str, options: Options):
        self.t0 = time.monotonic()
        self.issues: list[Issue] = []
        self.result: dict = {
            "tool": f"pdf-remediation {__version__}", "file": display_name, "source": source,
            "status": "failed", "engine": None, "steps": [], "issues": [], "figures": [], "headings": [],
            "outputs": {}, "options": {k: v for k, v in options.__dict__.items() if k != "alts"},
        }

    def step(self, name: str, detail: str = "") -> None:
        self.result["steps"].append({"step": name, "detail": detail, "t": round(time.monotonic() - self.t0, 2)})

    def issue(self, rule: str, severity: str, message: str, **kw) -> None:
        self.issues.append(Issue(rule, severity, message, source=kw.pop("source", "pipeline"), **kw))


def remediate_file(src: Path, out_pdf: Path, *, display_name: str, settings: Settings,
                   options: Options | None = None, source: str = "file") -> dict:
    options = options or Options()
    run = _Run(display_name, source, options)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        facts = _inspect(run, src, settings)
        lang = options.lang or settings.default_lang
        with tempfile.TemporaryDirectory(prefix="pdfrem-") as tmp:
            work = Path(tmp)
            current = work / "input.pdf"
            shutil.copyfile(src, current)
            current = _ocr(run, current, work, settings, options, lang)
            norm = _normalize(run, current, work)
            tagged, headings, title, carried = _tag(run, norm, work, facts, settings, options)
            _finish(run, tagged, out_pdf, display_name, lang, headings, title)
            if carried:
                matched = match_alts(carried, run_qa(out_pdf).figures)
                if matched:
                    apply_figure_decisions(out_pdf, out_pdf, matched, set())
                    run.step("alt-text", f"{len(matched)} alt text(s) carried over from the original tags")
            if options.alts:
                apply_figure_decisions(out_pdf, out_pdf, options.alts, set())
                run.step("alt-text", f"{len(options.alts)} alt text(s) applied")
            qa = run_qa(out_pdf)
            if options.ai:
                qa = _ai(run, out_pdf, qa, settings, options)
            verify_and_report(run, src_original=src, text_baseline=norm, out_pdf=out_pdf, settings=settings,
                              options=options, qa=qa)
    except InputError as exc:
        run.result["error"] = str(exc)
    except Exception as exc:  # report, never crash the batch
        run.result["error"] = f"{type(exc).__name__}: {exc}"
        run.result["traceback"] = traceback.format_exc(limit=6)
    run.result["seconds"] = round(time.monotonic() - run.t0, 2)
    if run.result["status"] == "failed":
        run.result["issues"] = [i.to_dict() for i in sort_issues(run.issues)]
        write_reports(run.result, out_pdf)
    return run.result


# ------------------------------------------------------------------ stages

def _inspect(run: _Run, src: Path, settings: Settings) -> dict:
    facts = inspect_pdf(src)
    run.result["facts"] = facts
    run.step("inspect", f"{facts['pages']} page(s), tagged={facts['tagged']}")
    if facts["pages"] > settings.max_pages:
        raise InputError(f"The PDF has {facts['pages']} pages; the limit is {settings.max_pages}.")
    if facts["xfa"]:
        run.issue("intake.xfa", "error", "The file contains an XFA form, which cannot conform to PDF/UA. Recreate "
                  "the form as a standard (AcroForm) PDF form at the source.", matterhorn=["25-001"])
    if facts["signed"]:
        run.issue("intake.signed", "warning", "The file is digitally signed. Remediation changes the file, so the "
                  "existing signature will no longer validate. Re-sign the remediated copy if needed.")
    if facts["encrypted"]:
        run.issue("intake.encrypted", "info", "The file had security restrictions. The remediated copy is saved "
                  "without encryption so assistive technology can read it.", matterhorn=["26-001"])
    return facts


def _ocr(run: _Run, current: Path, work: Path, settings: Settings, options: Options, lang: str) -> Path:
    """OCR pages that are images without text. Other pages are not touched."""
    pages = pages_needing_ocr(current)
    run.result["facts"]["pages_needing_ocr"] = [p + 1 for p in pages]
    if not pages:
        return current
    listed = ", ".join(str(p + 1) for p in pages[:20]) + ("..." if len(pages) > 20 else "")
    if options.ocr == "off":
        run.issue("ocr.skipped", "error", f"Page(s) {listed} are scanned images without text, and OCR was turned "
                  "off.", wcag=["1.1.1"], matterhorn=["08-001"])
        return current
    if get_engine(settings.ocr_engine) is None:
        run.issue("ocr.unavailable", "error", f"Page(s) {listed} are scanned images without text, but no OCR "
                  "engine is installed. Run: pip install -e \".[ocr]\"", wcag=["1.1.1"], matterhorn=["08-001"])
        return current
    out = work / "ocr.pdf"
    res = run_ocr(current, out, pages, engine_name=settings.ocr_engine, lang=lang, dpi=settings.ocr_dpi,
                  min_confidence=settings.ocr_min_confidence)
    run.result["ocr"] = {"engine": res.engine, "pages": [p + 1 for p in res.pages], "lines": res.lines,
                         "dropped_lines": res.dropped,
                         "confidence": {str(p + 1): c for p, c in res.confidence.items()}}
    run.step("ocr", f"{res.engine}: {len(res.pages)} page(s), {res.lines} line(s) recognised")
    run.issue("ocr.applied", "info", f"Page(s) {listed} were scanned images. Text was recognised with "
              f"{res.engine} and added as an invisible, searchable layer. Proofread it.", matterhorn=["08-001"])
    low = res.low_confidence_pages()
    if low:
        run.issue("ocr.low-confidence", "warning", "OCR confidence is low on page(s) "
                  f"{', '.join(str(p + 1) for p in low)}. Proofread the recognised text against the image.",
                  matterhorn=["08-001"])
    return out


def _normalize(run: _Run, current: Path, work: Path) -> Path:
    pdf = pikepdf.open(current)
    collapsed = collapse_empty_text_blocks(pdf)
    fonts_fixed = add_missing_tounicode(pdf)
    codes_fixed = repair_tounicode_from_actualtext(pdf)
    norm = work / "normalized.pdf"
    pdf.save(norm)
    pdf.close()
    run.step("normalize", f"{collapsed} empty text block(s) collapsed; Unicode map added to {len(fonts_fixed)} "
                          f"font(s); {codes_fixed} invalid mapping(s) repaired")
    if fonts_fixed:
        run.issue("fonts.tounicode-added", "info", f"Added a Unicode map to {len(fonts_fixed)} font(s) "
                  f"({', '.join(fonts_fixed[:5])}) from their glyph names, so text such as ligatures reads "
                  "correctly.", matterhorn=["10-001"])
    if codes_fixed:
        run.issue("fonts.tounicode-repaired", "info", f"Repaired {codes_fixed} invalid Unicode mapping(s) (for "
                  "example ligatures mapped to U+0000) using the document's own ActualText.", matterhorn=["10-001"])
    return norm


def _tag(run: _Run, norm: Path, work: Path, facts: dict, settings: Settings,
         options: Options) -> tuple[Path, list[dict], str, list[dict]]:
    """Choose an engine and tag. Returns (tagged file, headings, title candidate, alts to carry over)."""
    engine = (options.engine or settings.engine or "auto").lower()
    if engine == "auto":
        if "ocr" in run.result:
            # Measured: OpenDataLoader tags the scan image as a figure and alters the OCR text layer,
            # while the built-in engine marks the image as background and tags the recognised text.
            engine = "basic"
            run.step("engine", "built-in engine chosen because OCR was applied")
        else:
            engine = "odl" if odl_available(settings.java_cmd) else "basic"
    carried: list[dict] = []
    if facts["tagged"] and options.existing_tags != "retag":
        retag, reason = (False, "kept as requested") if options.existing_tags == "keep" else \
            needs_retag(norm, settings, options.verapdf)
        if retag:
            carried = figures_with_alt(norm)
            run.step("existing-tags", f"replaced: {reason}")
        else:
            engine = "existing-tags"
            run.step("existing-tags", reason)

    tagged = work / "tagged.pdf"
    if engine == "odl":
        try:
            odl_autotag(norm, tagged)
            run.step("tag", "OpenDataLoader auto-tagging")
        except Exception as exc:  # fall back rather than fail the file
            run.issue("tag.odl-failed", "warning", f"OpenDataLoader failed ({exc}); the built-in engine was used.")
            engine = "basic"
    if engine == "existing-tags":
        shutil.copyfile(norm, tagged)
        run.step("tag", "kept existing tags (choose 're-tag' to replace them)")
    run.result["engine"] = engine

    if engine == "basic":
        pdf = pikepdf.open(norm)
        doc = pdfium.PdfDocument(str(norm))
        try:
            tr = tag_document(pdf, doc)
        finally:
            doc.close()
        pdf.save(tagged)
        pdf.close()
        run.issues.extend(tr.issues)
        run.step("tag", f"built-in engine: {tr.pages_matched}/{tr.pages_total} page(s) mapped, "
                        f"{len(tr.headings)} heading(s), {tr.tables} table(s), {len(tr.figures)} figure(s)")
        return tagged, tr.headings, tr.title_candidate, carried

    headings = run_qa(tagged).headings
    title = next((h["text"] for h in headings if h["level"] == 1 and h["text"]), "")
    return tagged, headings, title, carried


def _finish(run: _Run, tagged: Path, out_pdf: Path, display_name: str, lang: str, headings: list[dict],
            title: str) -> None:
    pdf = pikepdf.open(tagged)
    removed = _strip_placeholder_alts(pdf)
    if removed:
        run.step("alt-text", f"removed {removed} placeholder alt text(s) such as 'image 1'; real descriptions "
                             "are needed")
    issues, facts = finish(pdf, filename=display_name, lang=lang, title_candidate=title, headings=headings)
    pdf.save(out_pdf)
    pdf.close()
    run.issues.extend(issues)
    run.result["document"] = facts
    run.step("finish", f"title '{facts['title']}', lang {facts['lang']}")


def _strip_placeholder_alts(pdf: pikepdf.Pdf) -> int:
    """Remove placeholder alt text ("image 1", file names) written by engines or authoring tools.

    A placeholder satisfies the PDF/UA machine check while telling a screen reader user
    nothing, so leaving it would make the validation result misleading.
    """
    removed = 0
    for fig in figures(read_tree(pdf)):
        if fig.alt is not None and ALT_PLACEHOLDER_RE.match(fig.alt):
            del fig.raw["/Alt"]
            removed += 1
    return removed


def _ai(run: _Run, out_pdf: Path, qa: QAResult, settings: Settings, options: Options) -> QAResult:
    """Ask the AI provider for alt text. Suggestions are stored for review unless accepted."""
    from .ai import AIUnavailable, suggest_alt
    from .pdf.pdfium import render_crop

    done = 0
    for f in qa.figures:
        if (f.get("alt") or "").strip() or not f.get("bbox"):
            continue
        try:
            f["ai"] = suggest_alt(settings, render_crop(out_pdf, f["page"], tuple(f["bbox"])), f.get("context", ""))
            done += 1
        except AIUnavailable as exc:
            run.issue("ai.unavailable", "info", str(exc))
            break
    run.step("ai", f"{done} alt text suggestion(s)")
    if not options.accept_ai_alt:
        return qa
    alts = {f["index"]: f["ai"]["alt"] for f in qa.figures
            if f.get("ai") and not f["ai"].get("decorative") and f["ai"].get("alt")}
    decorative = {f["index"] for f in qa.figures if f.get("ai") and f["ai"].get("decorative")}
    if not (alts or decorative):
        return qa
    apply_figure_decisions(out_pdf, out_pdf, alts, decorative)
    run.issue("ai.accepted-unreviewed", "warning", f"{len(alts)} AI alt text(s) and {len(decorative)} decorative "
              "decision(s) were written without human review.", wcag=["1.1.1"])
    suggestions = {f["index"]: f.get("ai") for f in qa.figures}
    qa = run_qa(out_pdf)
    for f in qa.figures:
        f["ai"] = suggestions.get(f["index"])
    return qa


# --------------------------------------------------------------- verification

def verify_and_report(run: _Run, *, src_original: Path, text_baseline: Path | None, out_pdf: Path,
                      settings: Settings, options: Options, qa: QAResult) -> dict:
    result = run.result
    vera = run_verapdf(out_pdf, settings) if options.verapdf else {
        "available": False, "compliant": None, "failed_rules": [], "message": "Skipped"}
    result["verapdf"] = vera
    run.step("verapdf", {True: "pass", False: "fail"}.get(vera.get("compliant"), vera.get("message", "")))
    vis = visual_diff(src_original, out_pdf)
    # Reviewer edits cannot change text, so re-verification reuses the earlier text gate.
    txt = text_diff(text_baseline, out_pdf) if text_baseline else result.get("text", {"identical": True})
    result["visual"], result["text"] = vis, txt
    run.step("gates", f"rendering identical={vis['identical']}, text identical={txt['identical']}")
    if not vis["identical"]:
        run.issue("gate.rendering-changed", "error", "The remediated file renders differently on page(s) "
                  f"{vis.get('changed_pages')}. Compare the two files before publishing.")
    if not txt["identical"] and txt.get("similarity", 0) < 0.999:
        run.issue("gate.text-changed", "warning",
                  f"Extracted text differs from the original (similarity {txt.get('similarity')}).")

    all_issues = sort_issues(_dedupe(run.issues + qa.issues + verapdf_issues(vera)))
    errors = sum(1 for i in all_issues if i.severity == "error")
    machine = {True: "pass", False: "fail"}.get(vera.get("compliant"), "not run")
    result.update({
        "issues": [i.to_dict() for i in all_issues],
        "figures": qa.figures,
        "headings": qa.headings,
        "qa_stats": qa.stats,
        "summary": {"machine_validation": machine, "errors": errors,
                    "warnings": sum(1 for i in all_issues if i.severity == "warning"),
                    "human_verification": "not done"},
        "status": "needs-attention" if (errors or machine == "fail") else "ready-for-review",
    })
    write_reports(result, out_pdf)
    return result


def _dedupe(issues: list[Issue]) -> list[Issue]:
    seen, out = set(), []
    for i in issues:
        key = (i.rule, i.page, i.message)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def reverify(src_original: Path, out_pdf: Path, settings: Settings, previous: dict) -> dict:
    """Re-run verification after a reviewer edit (alt text or decorative decisions)."""
    options = Options.from_dict(previous.get("options", {}))
    run = _Run(previous.get("file", out_pdf.name), previous.get("source", "file"), options)
    run.result.update({k: v for k, v in previous.items()
                       if k not in ("issues", "figures", "summary", "verapdf", "visual", "steps")})
    run.result["steps"] = list(previous.get("steps", []))
    run.issues = [Issue(**i) for i in previous.get("issues", [])
                  if i["source"] in ("tagger", "pipeline") and not i["rule"].startswith("gate.")]
    qa = run_qa(out_pdf)
    suggestions = {f["index"]: f.get("ai") for f in previous.get("figures", [])}
    for f in qa.figures:
        f["ai"] = suggestions.get(f["index"])
    return verify_and_report(run, src_original=src_original, text_baseline=None, out_pdf=out_pdf,
                             settings=settings, options=options, qa=qa)
