"""Per-file remediation pipeline.

intake -> (OCR) -> normalise -> tag (OpenDataLoader | basic | keep existing)
-> finish document-level properties -> AI alt-text suggestions (optional)
-> verify (veraPDF, semantic QA, rendering and text gates) -> report
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
from .config import Settings
from .edit import apply_figure_decisions
from .engines import ocr, ocr_available, odl_autotag, odl_available, tesseract_lang
from .finisher import finish
from .fonts import add_missing_tounicode, repair_tounicode_from_actualtext
from .intake import InputError, inspect_pdf
from .issues import Issue, sort_issues
from .normalize import collapse_empty_text_blocks
from .qa import run_qa
from .report import write_reports
from .tagger import tag_document
from .verify import run_verapdf, text_diff, verapdf_issues, visual_diff


@dataclass
class Options:
    engine: str = ""  # "" = settings default; auto | basic | odl
    lang: str = ""
    existing_tags: str = "auto"  # auto | keep | retag
    ocr: str = "auto"  # auto | off
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


def remediate_file(src: Path, out_pdf: Path, *, display_name: str, settings: Settings,
                   options: Options | None = None, source: str = "file") -> dict:
    options = options or Options()
    t0 = time.monotonic()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "tool": f"pdf-remediation {__version__}",
        "file": display_name,
        "source": source,
        "status": "failed",
        "engine": None,
        "steps": [],
        "issues": [],
        "figures": [],
        "headings": [],
        "outputs": {},
        "options": {k: v for k, v in options.__dict__.items() if k != "alts"},
    }
    issues: list[Issue] = []

    def step(name: str, detail: str = "") -> None:
        result["steps"].append({"step": name, "detail": detail, "t": round(time.monotonic() - t0, 2)})

    try:
        facts = inspect_pdf(src)
        result["facts"] = facts
        step("inspect", f"{facts['pages']} page(s), tagged={facts['tagged']}")
        if facts["pages"] > settings.max_pages:
            raise InputError(f"The PDF has {facts['pages']} pages; the limit is {settings.max_pages}.")
        if facts["xfa"]:
            issues.append(Issue("intake.xfa", "error",
                                "The file contains an XFA form, which cannot conform to PDF/UA. Recreate the "
                                "form as a standard (AcroForm) PDF form at the source.", source="pipeline",
                                matterhorn=["25-001"]))
        if facts["signed"]:
            issues.append(Issue("intake.signed", "warning",
                                "The file is digitally signed. Remediation changes the file, so the existing "
                                "signature will no longer validate. Re-sign the remediated copy if needed.",
                                source="pipeline"))
        if facts["encrypted"]:
            issues.append(Issue("intake.encrypted", "info",
                                "The file had security restrictions. The remediated copy is saved without "
                                "encryption so assistive technology can read it.", source="pipeline",
                                matterhorn=["26-001"]))

        lang = options.lang or settings.default_lang
        with tempfile.TemporaryDirectory(prefix="pdfrem-") as tmpdir:
            work = Path(tmpdir)
            current = work / "input.pdf"
            shutil.copyfile(src, current)

            if facts.get("image_only_pages") and options.ocr != "off":
                if ocr_available():
                    ocr_out = work / "ocr.pdf"
                    ocr(current, ocr_out, language=tesseract_lang(lang))
                    current = ocr_out
                    step("ocr", f"pages {facts['image_only_pages']}")
                else:
                    issues.append(Issue("intake.ocr-unavailable", "error",
                                        f"Pages {facts['image_only_pages']} are images without text. OCR is not "
                                        "installed (pip install 'pdf-remediation[ocr]' plus Tesseract and "
                                        "Ghostscript).", source="pipeline", wcag=["1.1.1"], matterhorn=["08-001"]))

            pdf = pikepdf.open(current)
            collapsed = collapse_empty_text_blocks(pdf)
            unicode_fixed = add_missing_tounicode(pdf)
            codes_fixed = repair_tounicode_from_actualtext(pdf)
            if codes_fixed:
                issues.append(Issue("fonts.tounicode-repaired", "info",
                                    f"Repaired {codes_fixed} invalid Unicode mapping(s) (for example ligatures "
                                    "mapped to U+0000) using the document's own ActualText.",
                                    source="pipeline", matterhorn=["10-001"]))
            norm = work / "normalized.pdf"
            pdf.save(norm)
            pdf.close()
            step("normalize", f"{collapsed} empty text block(s) collapsed; Unicode map added to "
                              f"{len(unicode_fixed)} font(s)")
            if unicode_fixed:
                issues.append(Issue("fonts.tounicode-added", "info",
                                    f"Added a Unicode map to {len(unicode_fixed)} font(s) "
                                    f"({', '.join(unicode_fixed[:5])}) from their glyph names, so text "
                                    "such as ligatures reads correctly.", source="pipeline", matterhorn=["10-001"]))
            text_baseline = work / "text-baseline.pdf"
            shutil.copyfile(norm, text_baseline)

            engine = (options.engine or settings.engine or "auto").lower()
            if engine == "auto":
                engine = "odl" if odl_available(settings.java_cmd) else "basic"
            carried_alts: list[dict] = []
            if facts["tagged"] and options.existing_tags != "retag":
                retag, reason = (False, "kept as requested") if options.existing_tags == "keep" else \
                    _existing_tags_need_retag(norm, settings, options)
                if retag:
                    carried_alts = [f for f in run_qa(norm).figures if (f.get("alt") or "").strip() and f.get("bbox")]
                    step("existing-tags", f"replaced: {reason}")
                else:
                    engine = "existing-tags"
                    step("existing-tags", reason)

            tagged = work / "tagged.pdf"
            headings: list[dict] = []
            title_candidate = ""
            if engine == "odl":
                try:
                    odl_autotag(norm, tagged)
                    step("tag", "OpenDataLoader auto-tagging")
                except Exception as exc:  # fall back rather than fail the file
                    issues.append(Issue("tag.odl-failed", "warning",
                                        f"OpenDataLoader failed ({exc}); the basic engine was used instead.",
                                        source="pipeline"))
                    engine = "basic"
            if engine == "basic":
                pdf = pikepdf.open(norm)
                doc = pdfium.PdfDocument(str(norm))
                try:
                    tr = tag_document(pdf, doc)
                finally:
                    doc.close()
                pdf.save(tagged)
                pdf.close()
                issues.extend(tr.issues)
                headings, title_candidate = tr.headings, tr.title_candidate
                step("tag", f"basic engine: {tr.pages_matched}/{tr.pages_total} page(s) mapped, "
                            f"{len(tr.headings)} heading(s), {len(tr.figures)} figure(s)")
            elif engine == "existing-tags":
                shutil.copyfile(norm, tagged)
                step("tag", "kept existing tags (choose 're-tag' to replace them)")
            result["engine"] = engine

            if engine != "basic":
                pre = run_qa(tagged)
                headings = pre.headings
                title_candidate = next((h["text"] for h in headings if h["level"] == 1 and h["text"]), "")

            pdf = pikepdf.open(tagged)
            removed = _strip_placeholder_alts(pdf)
            if removed:
                step("alt-text", f"removed {removed} placeholder alt text(s) such as 'image 1'; real "
                                 "descriptions are needed")
            fin_issues, fin_facts = finish(pdf, filename=display_name, lang=lang, title_candidate=title_candidate,
                                           headings=headings)
            pdf.save(out_pdf)
            pdf.close()
            issues.extend(fin_issues)
            result["document"] = fin_facts
            step("finish", f"title '{fin_facts['title']}', lang {fin_facts['lang']}")

            if carried_alts:
                carried = _match_alts(carried_alts, run_qa(out_pdf).figures)
                if carried:
                    apply_figure_decisions(out_pdf, out_pdf, carried, set())
                    step("alt-text", f"{len(carried)} alt text(s) carried over from the original tags")
            if options.alts:
                apply_figure_decisions(out_pdf, out_pdf, options.alts, set())
                step("alt-text", f"{len(options.alts)} alt text(s) applied")

            qa = run_qa(out_pdf)
            figures = qa.figures
            if options.ai:
                _ai_suggestions(out_pdf, figures, settings, issues, step)
                if options.accept_ai_alt:
                    alts = {f["index"]: f["ai"]["alt"] for f in figures
                            if f.get("ai") and not f["ai"].get("decorative") and f["ai"].get("alt")}
                    decorative = {f["index"] for f in figures if f.get("ai") and f["ai"].get("decorative")}
                    if alts or decorative:
                        apply_figure_decisions(out_pdf, out_pdf, alts, decorative)
                        issues.append(Issue("ai.accepted-unreviewed", "warning",
                                            f"{len(alts)} AI alt text(s) and {len(decorative)} decorative "
                                            "decision(s) were written without human review.", source="pipeline",
                                            wcag=["1.1.1"]))
                        ai_by_index = {f["index"]: f.get("ai") for f in figures}
                        qa = run_qa(out_pdf)
                        figures = qa.figures
                        for f in figures:
                            f["ai"] = ai_by_index.get(f["index"])

            verify_and_report(src_original=src, text_baseline=text_baseline, out_pdf=out_pdf, settings=settings,
                              options=options, result=result, issues=issues, qa=qa, figures=figures, step=step)
    except InputError as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
    except Exception as exc:  # report, never crash the batch
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc(limit=6)
    result["seconds"] = round(time.monotonic() - t0, 2)
    if result["status"] == "failed":
        result["issues"] = [i.to_dict() for i in sort_issues(issues)]
        write_reports(result, out_pdf)
    return result


def _strip_placeholder_alts(pdf: pikepdf.Pdf) -> int:
    """Remove placeholder alt text ("image 1", file names) written by engines or authoring tools.

    A placeholder satisfies the PDF/UA machine check while telling a screen reader user nothing,
    so leaving it in place would make the validation result misleading.
    """
    from .qa import ALT_PLACEHOLDER_RE
    from .structtree import figures, read_tree

    removed = 0
    for fig in figures(read_tree(pdf)):
        if fig.alt is not None and ALT_PLACEHOLDER_RE.match(fig.alt):
            del fig.raw["/Alt"]
            removed += 1
    return removed


# veraPDF clauses the finisher or a reviewer fixes anyway; failures elsewhere mean
# the existing structure itself is broken.
_DOC_LEVEL_CLAUSES = ("5", "6.2", "7.1-8", "7.1-9", "7.1-10", "7.2", "7.3", "7.21")
_STRUCTURAL_QA = {"sqa.heading-untagged", "sqa.heading-small", "sqa.reading-order", "sqa.list-untagged",
                  "sqa.no-headings", "sqa.untagged", "sqa.table-no-headers"}


def _existing_tags_need_retag(norm: Path, settings: Settings, options: Options) -> tuple[bool, str]:
    qa = run_qa(norm)
    structural = sorted({i.rule for i in qa.issues if i.rule in _STRUCTURAL_QA})
    if structural:
        return True, "existing tags have structural problems (" + ", ".join(structural) + ")"
    if options.verapdf:
        vera = run_verapdf(norm, settings)
        bad = []
        for r in vera.get("failed_rules", []):
            key = f"{r['clause']}-{r['test']}"
            if not any(r["clause"] == c or r["clause"].startswith(c + ".") or key == c for c in _DOC_LEVEL_CLAUSES):
                bad.append(key)
        if bad:
            return True, "existing tags fail PDF/UA structure checks (" + ", ".join(sorted(set(bad))) + ")"
    return False, "existing tags kept (no structural problems found)"


def _match_alts(old: list[dict], new: list[dict]) -> dict[int, str]:
    """Map alt text from the original figures onto re-tagged figures by page and overlap."""
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
            area = max((b[2] - b[0]) * (b[3] - b[1]), 1e-6)
            if w > 0 and h > 0 and (w * h) / area > 0.5:
                out[f["index"]] = o["alt"]
                break
    return out


def _ai_suggestions(out_pdf: Path, figures: list[dict], settings: Settings, issues: list[Issue], step) -> None:
    from .ai import AIUnavailable, suggest_alt
    from .pdfium_util import render_crop

    todo = [f for f in figures if not (f.get("alt") or "").strip() and f.get("bbox")]
    done = 0
    for f in todo:
        try:
            img = render_crop(out_pdf, f["page"], tuple(f["bbox"]))
            f["ai"] = suggest_alt(settings, img, f.get("context", ""))
            done += 1
        except AIUnavailable as exc:
            issues.append(Issue("ai.unavailable", "info", str(exc), source="pipeline"))
            break
    step("ai", f"{done} alt text suggestion(s)")


def verify_and_report(*, src_original: Path, text_baseline: Path | None, out_pdf: Path, settings: Settings,
                      options: Options, result: dict, issues: list[Issue], qa, figures: list[dict], step) -> dict:
    vera = run_verapdf(out_pdf, settings) if options.verapdf else {
        "available": False, "compliant": None, "failed_rules": [], "message": "Skipped"}
    result["verapdf"] = vera
    step("verapdf", "pass" if vera.get("compliant") else ("fail" if vera.get("compliant") is False else
                                                           vera.get("message", "")))
    vis = visual_diff(src_original, out_pdf)
    # Reviewer edits cannot change text, so re-verification reuses the earlier text gate.
    txt = text_diff(text_baseline, out_pdf) if text_baseline else result.get("text", {"identical": True})
    result["visual"], result["text"] = vis, txt
    step("gates", f"rendering identical={vis['identical']}, text identical={txt['identical']}")
    if not vis["identical"]:
        issues.append(Issue("gate.rendering-changed", "error",
                            f"The remediated file renders differently on page(s) {vis.get('changed_pages')}. "
                            "Compare the two files before publishing.", source="pipeline"))
    if not txt["identical"] and txt.get("similarity", 0) < 0.999:
        issues.append(Issue("gate.text-changed", "warning",
                            f"Extracted text differs from the original (similarity {txt.get('similarity')}).",
                            source="pipeline"))
    all_issues = sort_issues(_dedupe(issues + qa.issues + verapdf_issues(vera)))
    result["issues"] = [i.to_dict() for i in all_issues]
    result["figures"] = figures
    result["headings"] = qa.headings
    result["qa_stats"] = qa.stats
    errors = sum(1 for i in all_issues if i.severity == "error")
    warnings = sum(1 for i in all_issues if i.severity == "warning")
    machine = "pass" if vera.get("compliant") else ("fail" if vera.get("compliant") is False else "not run")
    result["summary"] = {
        "machine_validation": machine,
        "errors": errors,
        "warnings": warnings,
        "human_verification": "not done",
    }
    result["status"] = "needs-attention" if (errors or machine == "fail") else "ready-for-review"
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
    t0 = time.monotonic()
    result = {k: v for k, v in previous.items() if k not in ("issues", "figures", "summary", "verapdf",
                                                               "visual")}
    result["steps"] = list(previous.get("steps", []))
    issues = [Issue(**i) for i in previous.get("issues", [])
              if i["source"] in ("tagger", "pipeline") and not i["rule"].startswith("gate.")]

    def step(name: str, detail: str = "") -> None:
        result["steps"].append({"step": name, "detail": detail, "t": round(time.monotonic() - t0, 2)})

    qa = run_qa(out_pdf)
    prev_ai = {f["index"]: f.get("ai") for f in previous.get("figures", [])}
    for f in qa.figures:
        f["ai"] = prev_ai.get(f["index"])
    opts = Options.from_dict(previous.get("options", {}))
    return verify_and_report(src_original=src_original, text_baseline=None, out_pdf=out_pdf,
                             settings=settings, options=opts, result=result, issues=issues, qa=qa,
                             figures=qa.figures, step=step)
