"""Command line interface: ``pdfrem remediate|validate|serve|doctor``."""
from __future__ import annotations

import argparse
import csv
import ipaddress
import multiprocessing
import re
import secrets
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import __version__
from .config import Settings
from .engines import ocr_available, odl_available
from .fetch import fetch_inputs
from .intake import InputFile, collect_paths
from .pipeline import Options, remediate_file
from .qa import run_qa
from .report import STATUS_LABELS
from .verify import run_verapdf, verapdf_command

URL_RE = re.compile(r"^https?://", re.I)


def _settings(args) -> Settings:
    return Settings.from_env(data_dir=getattr(args, "data_dir", None),
                             allow_private_urls=True if getattr(args, "allow_private_urls", False) else None,
                             ai_enabled=True if getattr(args, "ai", False) else None)


def cmd_remediate(args) -> int:
    settings = _settings(args)
    urls = [a for a in args.inputs if URL_RE.match(a)]
    paths = [Path(a) for a in args.inputs if not URL_RE.match(a)]
    files, skipped = collect_paths(paths)
    for s in skipped:
        print(f"skipped: {s}", file=sys.stderr)
    tmp = tempfile.TemporaryDirectory(prefix="pdfrem-fetch-")
    if urls:
        res = fetch_inputs(urls, Path(tmp.name), settings)
        files.extend(res.files)
        for m in res.messages:
            print(f"link: {m}", file=sys.stderr)
    if not files:
        print("No PDFs to process.", file=sys.stderr)
        return 2
    out_root = Path(args.output)
    options = Options(engine=args.engine, lang=args.lang or "", existing_tags=args.existing_tags,
                      ocr="off" if args.no_ocr else "auto", ai=args.ai, accept_ai_alt=args.accept_ai_alt,
                      verapdf=not args.no_verapdf)
    jobs: list[tuple[InputFile, Path]] = []
    used: set[str] = set()
    for f in files:
        rel = Path(f.relpath)
        target = out_root / rel
        n = 1
        while str(target).lower() in used:
            n += 1
            target = out_root / rel.with_name(f"{rel.stem}-{n}{rel.suffix}")
        used.add(str(target).lower())
        jobs.append((f, target))

    results = []
    workers = max(1, args.workers or 1)
    print(f"Processing {len(jobs)} file(s) with {workers} worker(s)...", file=sys.stderr)
    if workers == 1:
        for f, target in jobs:
            r = remediate_file(f.path, target, display_name=f.relpath, settings=settings, options=options,
                               source=f.source)
            results.append((f, target, r))
            _print_line(f, r)
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            futs = {pool.submit(remediate_file, f.path, target, display_name=f.relpath, settings=settings,
                                options=options, source=f.source): (f, target) for f, target in jobs}
            for fut in as_completed(futs):
                f, target = futs[fut]
                r = fut.result()
                results.append((f, target, r))
                _print_line(f, r)
    tmp.cleanup()

    out_root.mkdir(parents=True, exist_ok=True)
    with open(out_root / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "output", "status", "machine_validation", "errors", "warnings", "error"])
        for f, target, r in results:
            s = r.get("summary") or {}
            w.writerow([f.relpath, str(target), r["status"], s.get("machine_validation", ""), s.get("errors", ""),
                        s.get("warnings", ""), r.get("error", "")])
    counts = {k: sum(1 for *_, r in results if r["status"] == k) for k in STATUS_LABELS}
    print(f"\nDone. {counts['ready-for-review']} ready for review, {counts['needs-attention']} need attention, "
          f"{counts['failed']} failed. Summary: {out_root / 'summary.csv'}", file=sys.stderr)
    if counts["failed"]:
        return 3
    return 1 if counts["needs-attention"] else 0


def _print_line(f: InputFile, r: dict) -> None:
    s = r.get("summary") or {}
    detail = r.get("error") or f"PDF/UA-1 {s.get('machine_validation', '?')}, {s.get('errors', 0)} error(s), " \
                               f"{s.get('warnings', 0)} warning(s)"
    print(f"[{STATUS_LABELS.get(r['status'], r['status'])}] {f.relpath}: {detail}")


def cmd_validate(args) -> int:
    settings = _settings(args)
    files, skipped = collect_paths([Path(p) for p in args.inputs])
    worst = 0
    for f in files:
        vera = run_verapdf(f.path, settings)
        qa = run_qa(f.path)
        verdict = "PASS" if vera.get("compliant") else ("FAIL" if vera.get("compliant") is False else "NOT RUN")
        print(f"{f.relpath}: veraPDF PDF/UA-1 {verdict}; {len(qa.issues)} semantic QA issue(s)")
        for r in vera.get("failed_rules", []):
            print(f"  verapdf {r['clause']}-{r['test']}: {r['description'][:110]}")
        for i in qa.issues:
            print(f"  {i.severity:7} {i.rule} (p{i.page or '-'}): {i.message[:110]}")
        if verdict != "PASS" or any(i.severity == "error" for i in qa.issues):
            worst = 1
    return worst


def cmd_doctor(args) -> int:
    settings = _settings(args)
    print(f"pdf-remediation {__version__}")
    print(f"  veraPDF validator: {'yes' if verapdf_command(settings) else 'NO  (run scripts/fetch-verapdf.sh)'}")
    print(f"  OpenDataLoader:    {'yes' if odl_available(settings.java_cmd) else 'no  (pip install -e .[odl]; needs Java 11+)'}")
    print(f"  OCR:               {'yes' if ocr_available() else 'no  (pip install -e .[ocr]; needs Tesseract + Ghostscript)'}")
    print(f"  AI suggestions:    {'enabled, ' + settings.ai_model + ' at ' + settings.ai_base_url if settings.ai_enabled else 'disabled (PDFREM_AI_ENABLED=1)'}")
    print(f"  Data directory:    {Path(settings.data_dir).resolve()}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .web import create_app

    settings = _settings(args)
    host = args.host
    loopback = host in ("localhost",) or (_is_ip(host) and ipaddress.ip_address(host).is_loopback)
    if not loopback and not settings.access_token:
        settings.access_token = secrets.token_urlsafe(24)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{args.port}/"
    if settings.access_token:
        url += f"?token={settings.access_token}"
        print("Access token required. Open:", url)
    else:
        print("Open:", url)
    uvicorn.run(create_app(settings), host=host, port=args.port, log_level="info")
    return 0


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdfrem", description="Local-first PDF accessibility remediation (PDF/UA-1).")
    p.add_argument("--version", action="version", version=f"pdf-remediation {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("remediate", help="Remediate PDFs from files, folders (recursive) and links")
    r.add_argument("inputs", nargs="+", help="PDF files, folders, or http(s) links to PDFs or web pages")
    r.add_argument("-o", "--output", default="remediated", help="Output folder (default: ./remediated)")
    r.add_argument("--engine", choices=["auto", "basic", "odl"], default="auto")
    r.add_argument("--lang", help="Document language when not declared, e.g. en-US")
    r.add_argument("--existing-tags", choices=["auto", "keep", "retag"], default="auto")
    r.add_argument("--no-ocr", action="store_true", help="Do not OCR image-only pages")
    r.add_argument("--no-verapdf", action="store_true", help="Skip veraPDF validation")
    r.add_argument("--ai", action="store_true", help="Request AI alt-text suggestions (see README for policy)")
    r.add_argument("--accept-ai-alt", action="store_true", help="Write AI alt text without human review")
    r.add_argument("--allow-private-urls", action="store_true", help="Allow links to internal network hosts")
    r.add_argument("--workers", type=int, default=1, help="Parallel worker processes")
    r.set_defaults(func=cmd_remediate)

    v = sub.add_parser("validate", help="Check PDFs (veraPDF + semantic QA) without changing them")
    v.add_argument("inputs", nargs="+")
    v.set_defaults(func=cmd_validate)

    s = sub.add_parser("serve", help="Run the local web application")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--data-dir", help="Where jobs are stored (default ./pdfrem-data)")
    s.add_argument("--allow-private-urls", action="store_true")
    s.set_defaults(func=cmd_serve)

    d = sub.add_parser("doctor", help="Show which optional components are installed")
    d.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
