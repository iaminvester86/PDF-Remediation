"""Command line interface.

    pdfrem remediate <files|folders|links...> -o out/   remediate in batch
    pdfrem validate <files|folders...>                   check without changing
    pdfrem serve                                         run the web app
    pdfrem doctor                                        show installed components
    pdfrem install-engines                               download the veraPDF validator
"""
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
from .checks import run_qa, run_verapdf
from .config import Settings
from .inputs import InputFile, collect_paths, fetch_inputs
from .java import install_verapdf, java_version
from .pipeline import Options, remediate_file
from .report import STATUS_LABELS
from .status import describe

URL_RE = re.compile(r"^https?://", re.I)


def _settings(args) -> Settings:
    return Settings.from_env(
        data_dir=getattr(args, "data_dir", None),
        allow_private_urls=True if getattr(args, "allow_private_urls", False) else None,
        ai_enabled=True if getattr(args, "ai", False) else None)


def _output_paths(files: list[InputFile], out_root: Path) -> list[tuple[InputFile, Path]]:
    """Mirror input folder structure; never let two inputs write the same file."""
    pairs, used = [], set()
    for f in files:
        rel = Path(f.relpath)
        target, n = out_root / rel, 1
        while str(target).lower() in used:
            n += 1
            target = out_root / rel.with_name(f"{rel.stem}-{n}{rel.suffix}")
        used.add(str(target).lower())
        pairs.append((f, target))
    return pairs


def cmd_remediate(args) -> int:
    settings = _settings(args)
    urls = [a for a in args.inputs if URL_RE.match(a)]
    files, skipped = collect_paths([Path(a) for a in args.inputs if not URL_RE.match(a)])
    for s in skipped:
        print(f"skipped: {s}", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="pdfrem-fetch-") as tmp:
        if urls:
            fetched = fetch_inputs(urls, Path(tmp), settings)
            files.extend(fetched.files)
            for m in fetched.messages:
                print(f"link: {m}", file=sys.stderr)
        if not files:
            print("No PDFs to process.", file=sys.stderr)
            return 2
        options = Options(engine=args.engine or "", lang=args.lang or "", existing_tags=args.existing_tags, ocr=args.ocr,
                          ai=args.ai, accept_ai_alt=args.accept_ai_alt, verapdf=not args.no_verapdf)
        out_root = Path(args.output)
        jobs = _output_paths(files, out_root)
        workers = max(1, args.workers or 1)
        print(f"Processing {len(jobs)} file(s) with {workers} worker(s)...", file=sys.stderr)
        results = []
        if workers == 1:
            for f, target in jobs:
                results.append((f, target, _run_one(f, target, settings, options)))
        else:
            with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
                futures = {pool.submit(remediate_file, f.path, target, display_name=f.relpath, settings=settings,
                                       options=options, source=f.source): (f, target) for f, target in jobs}
                for fut in as_completed(futures):
                    f, target = futures[fut]
                    results.append((f, target, fut.result()))
                    _print_line(f, results[-1][2])
    _write_summary(out_root, results)
    counts = {k: sum(1 for *_, r in results if r["status"] == k) for k in STATUS_LABELS}
    print(f"\nDone. {counts['ready-for-review']} ready for review, {counts['needs-attention']} need attention, "
          f"{counts['failed']} failed. Summary: {out_root / 'summary.csv'}", file=sys.stderr)
    if counts["failed"]:
        return 3
    return 1 if counts["needs-attention"] else 0


def _run_one(f: InputFile, target: Path, settings: Settings, options: Options) -> dict:
    result = remediate_file(f.path, target, display_name=f.relpath, settings=settings, options=options,
                            source=f.source)
    _print_line(f, result)
    return result


def _print_line(f: InputFile, r: dict) -> None:
    s = r.get("summary") or {}
    detail = r.get("error") or (f"PDF/UA-1 {s.get('machine_validation', '?')}, {s.get('errors', 0)} error(s), "
                                f"{s.get('warnings', 0)} warning(s)" + (", OCR applied" if r.get("ocr") else ""))
    print(f"[{STATUS_LABELS.get(r['status'], r['status'])}] {f.relpath}: {detail}")


def _write_summary(out_root: Path, results: list) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    with open(out_root / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "output", "status", "machine_validation", "errors", "warnings", "ocr_pages", "error"])
        for f, target, r in results:
            s = r.get("summary") or {}
            w.writerow([f.relpath, str(target), r["status"], s.get("machine_validation", ""), s.get("errors", ""),
                        s.get("warnings", ""), " ".join(map(str, (r.get("ocr") or {}).get("pages", []))),
                        r.get("error", "")])


def cmd_validate(args) -> int:
    settings = _settings(args)
    files, _ = collect_paths([Path(p) for p in args.inputs])
    worst = 0
    for f in files:
        vera = run_verapdf(f.path, settings)
        qa = run_qa(f.path)
        verdict = {True: "PASS", False: "FAIL"}.get(vera.get("compliant"), "NOT RUN")
        print(f"{f.relpath}: veraPDF PDF/UA-1 {verdict}; {len(qa.issues)} semantic issue(s)")
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
    for name, ready, detail in describe(settings):
        print(f"  [{'x' if ready else ' '}] {name}: {detail}")
    print(f"  Jobs folder:    {Path(settings.data_dir).resolve()}")
    print(f"  Engines folder: {Path(settings.engines_dir).resolve()}")
    return 0


def cmd_install_engines(args) -> int:
    settings = _settings(args)
    version = java_version(settings.java_cmd)
    if not version or version < 11:
        print("Java 11 or newer is required for the Java engines (veraPDF, OpenDataLoader).\n"
              "Install Java 17 or 21, for example Eclipse Temurin from https://adoptium.net, then run this again.",
              file=sys.stderr)
        return 2
    print(f"Java {version} found. Installing veraPDF into {settings.verapdf_lib} ...")
    install_verapdf(settings.verapdf_lib)
    print("veraPDF installed (checksums verified).")
    from .tagging import odl_installed
    if not odl_installed():
        print('OpenDataLoader is not installed. For the stronger layout and table engine run: pip install -e ".[odl]"')
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .web import create_app

    settings = _settings(args)
    host = args.host
    loopback = host == "localhost" or (_is_ip(host) and ipaddress.ip_address(host).is_loopback)
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
    r.add_argument("--engine", choices=["auto", "basic", "odl"], help="Structure engine (default: PDFREM_ENGINE, else auto)")
    r.add_argument("--lang", help="Document language when not declared, e.g. en-US")
    r.add_argument("--existing-tags", choices=["auto", "keep", "retag"], default="auto")
    r.add_argument("--ocr", choices=["auto", "off"], default="auto", help="OCR pages that have no text (default)")
    r.add_argument("--no-verapdf", action="store_true", help="Skip veraPDF validation")
    r.add_argument("--ai", action="store_true", help="Request AI alt-text suggestions (see README)")
    r.add_argument("--accept-ai-alt", action="store_true", help="Write AI alt text without human review")
    r.add_argument("--allow-private-urls", action="store_true", help="Allow links to internal network hosts")
    r.add_argument("--workers", type=int, default=1, help="Parallel worker processes")
    r.set_defaults(func=cmd_remediate)

    v = sub.add_parser("validate", help="Check PDFs (veraPDF + semantic checks) without changing them")
    v.add_argument("inputs", nargs="+")
    v.set_defaults(func=cmd_validate)

    s = sub.add_parser("serve", help="Run the local web application")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--data-dir", help="Where jobs are stored (default ./pdfrem-data)")
    s.add_argument("--allow-private-urls", action="store_true")
    s.set_defaults(func=cmd_serve)

    sub.add_parser("doctor", help="Show which optional components are installed").set_defaults(func=cmd_doctor)
    sub.add_parser("install-engines", help="Download the veraPDF validator (needs Java 11+)").set_defaults(
        func=cmd_install_engines)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
