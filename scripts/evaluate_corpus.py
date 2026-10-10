"""Run reproducible remediation regressions over a licensed local PDF corpus."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pikepdf

from pdf_remediation.config import Settings
from pdf_remediation.pipeline import Options, remediate_file
from pdf_remediation.pdf.structure import read_tree

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_MACHINE_STATES = {"pass", "fail", "not run"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(corpus_dir: Path, manifest_path: Path | None = None) -> tuple[dict, list[dict]]:
    root = corpus_dir.resolve()
    path = (manifest_path or root / "manifest.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("The manifest must be inside the corpus directory.") from exc
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read corpus manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("The corpus manifest must be an object with version: 1.")
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("The corpus manifest must contain at least one document.")

    seen_ids: set[str] = set()
    seen_files: set[Path] = set()
    validated: list[dict] = []
    for index, entry in enumerate(documents):
        label = f"documents[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{label} must be an object.")
        case_id, rel_file = entry.get("id"), entry.get("file")
        if not isinstance(case_id, str) or not _ID_RE.fullmatch(case_id):
            raise ValueError(f"{label}.id must contain only letters, digits, dot, underscore, or hyphen.")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate corpus case id: {case_id}")
        seen_ids.add(case_id)
        if not isinstance(rel_file, str) or not rel_file.strip():
            raise ValueError(f"{label}.file must be a relative PDF path.")
        pdf_path = (root / rel_file).resolve()
        try:
            pdf_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"{label}.file must resolve inside the corpus directory.") from exc
        if pdf_path.suffix.lower() != ".pdf" or not pdf_path.is_file():
            raise ValueError(f"{label}.file is not an existing PDF: {rel_file}")
        if pdf_path in seen_files:
            raise ValueError(f"Duplicate corpus PDF: {rel_file}")
        seen_files.add(pdf_path)
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
            raise ValueError(f"{label}.sha256 must be the PDF's 64-character SHA-256 digest.")
        actual_hash = _sha256(pdf_path)
        if actual_hash.lower() != expected_hash.lower():
            raise ValueError(f"{label}.sha256 does not match {rel_file}.")
        for metadata in ("category", "source", "license"):
            if not isinstance(entry.get(metadata), str) or not entry[metadata].strip():
                raise ValueError(f"{label}.{metadata} must be a non-empty string.")
        expected = entry.get("expected", {})
        if not isinstance(expected, dict):
            raise ValueError(f"{label}.expected must be an object.")
        required_roles = expected.get("required_roles", {})
        if not isinstance(required_roles, dict) or any(
            not isinstance(role, str) or not role or type(count) is not int or count < 0
            for role, count in required_roles.items()
        ):
            raise ValueError(f"{label}.expected.required_roles must map role names to non-negative integers.")
        for rules_key in ("required_issue_rules", "forbidden_issue_rules"):
            rules = expected.get(rules_key, [])
            if not isinstance(rules, list) or any(not isinstance(rule, str) or not rule for rule in rules):
                raise ValueError(f"{label}.expected.{rules_key} must be a list of rule IDs.")
        machine = expected.get("machine_validation")
        if machine is not None and (not isinstance(machine, str) or machine not in _MACHINE_STATES):
            raise ValueError(f"{label}.expected.machine_validation must be one of {sorted(_MACHINE_STATES)}.")
        validated.append({**entry, "_path": pdf_path, "_sha256": actual_hash})
    return manifest, validated


def _check_case(entry: dict, result: dict, output_pdf: Path) -> dict:
    expected = entry.get("expected", {})
    failures: list[str] = []
    if result.get("status") == "failed":
        failures.append(f"remediation failed: {result.get('error', 'unknown error')}")
    for gate in ("visual", "text"):
        gate_result = result.get(gate)
        if not isinstance(gate_result, dict) or gate_result.get("identical") is not True:
            failures.append(f"{gate} preservation gate did not pass")

    role_counts: Counter[str] = Counter()
    if output_pdf.is_file():
        try:
            with pikepdf.open(output_pdf) as pdf:
                role_counts.update(elem.role for elem in read_tree(pdf).walk())
        except (OSError, pikepdf.PdfError) as exc:
            failures.append(f"could not inspect output PDF structure: {type(exc).__name__}: {exc}")
    elif result.get("status") != "failed":
        failures.append("remediation reported success but produced no output PDF")
    for role, minimum in expected.get("required_roles", {}).items():
        if role_counts[role] < minimum:
            failures.append(f"expected at least {minimum} {role} structure element(s), found {role_counts[role]}")

    issue_rules = {issue.get("rule") for issue in result.get("issues", [])}
    for rule in expected.get("required_issue_rules", []):
        if rule not in issue_rules:
            failures.append(f"expected issue rule was not reported: {rule}")
    for rule in expected.get("forbidden_issue_rules", []):
        if rule in issue_rules:
            failures.append(f"unexpected issue rule was reported: {rule}")
    machine_expected = expected.get("machine_validation")
    machine_actual = result.get("summary", {}).get("machine_validation", "not run")
    if machine_expected is not None and machine_actual != machine_expected:
        failures.append(f"expected machine validation {machine_expected!r}, got {machine_actual!r}")

    return {
        "id": entry["id"],
        "file": entry["file"],
        "sha256": entry["_sha256"],
        "category": entry["category"],
        "source": entry["source"],
        "license": entry["license"],
        "status": result.get("status", "failed"),
        "engine": result.get("engine"),
        "machine_validation": machine_actual,
        "visual_identical": bool(result.get("visual", {}).get("identical", False)),
        "text_identical": bool(result.get("text", {}).get("identical", False)),
        "roles": dict(sorted(role_counts.items())),
        "issues": sorted(issue_rules),
        "failures": failures,
        "output": str(output_pdf),
        "seconds": result.get("seconds"),
    }


def run_corpus(corpus_dir: Path, output_dir: Path, *, manifest_path: Path | None = None,
               engine: str = "auto", verapdf: bool = True, settings: Settings | None = None) -> dict:
    """Remediate each manifest entry and check preservation and declared regressions."""
    root = corpus_dir.resolve()
    _, documents = _load_manifest(root, manifest_path)
    destination = output_dir.resolve()
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("The output directory must be outside the corpus directory.")
    destination.mkdir(parents=True, exist_ok=True)
    settings = settings or Settings.from_env()
    cases = []
    for entry in documents:
        output_pdf = destination / f"{entry['id']}.pdf"
        result = remediate_file(
            entry["_path"],
            output_pdf,
            display_name=entry["file"],
            settings=settings,
            options=Options(engine=engine, verapdf=verapdf),
            source="corpus",
        )
        cases.append(_check_case(entry, result, output_pdf))

    report = {
        "version": 1,
        "corpus_dir": str(root),
        "engine": engine,
        "verapdf_requested": verapdf,
        "total": len(cases),
        "passed": sum(not case["failures"] for case in cases),
        "failed": sum(bool(case["failures"]) for case in cases),
        "cases": cases,
    }
    (destination / "corpus-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (destination / "corpus-results.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ("id", "file", "sha256", "category", "status", "engine", "machine_validation",
                  "visual_identical", "text_identical", "seconds", "failures")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            writer.writerow({key: case[key] for key in fields if key != "failures"} |
                            {"failures": "; ".join(case["failures"])})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True,
                        help="Directory containing manifest.json and the licensed PDFs")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for remediated PDFs and reports")
    parser.add_argument("--engine", choices=("auto", "basic", "odl"), default="auto")
    parser.add_argument("--no-verapdf", action="store_true", help="Skip veraPDF machine validation")
    args = parser.parse_args(argv)
    try:
        report = run_corpus(args.corpus_dir, args.output_dir, engine=args.engine, verapdf=not args.no_verapdf)
    except ValueError as exc:
        print(f"Corpus configuration error: {exc}", file=sys.stderr)
        return 2
    print(f"Corpus regression: {report['passed']}/{report['total']} passed; results: "
          f"{args.output_dir / 'corpus-results.json'}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
