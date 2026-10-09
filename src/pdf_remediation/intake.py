"""Gather inputs (files, folders, zip archives) and inspect PDFs before processing."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pikepdf
import pypdfium2 as pdfium

PDF_MAGIC = b"%PDF-"


class InputError(ValueError):
    """A problem with an input that should be shown to the user, not a crash."""


@dataclass
class InputFile:
    path: Path
    relpath: str  # display/relative path, POSIX style
    source: str = "file"  # file | folder | zip | url


def safe_relpath(name: str) -> str:
    """Turn an uploaded filename (possibly with folder parts) into a safe relative path."""
    parts = re.split(r"[\\/]+", name or "")
    clean = []
    for p in parts:
        p = p.strip().replace("\x00", "")
        if p in ("", ".", ".."):
            continue
        p = re.sub(r"[<>:\"|?*\x00-\x1f]", "_", p)[:150]
        clean.append(p)
    return str(PurePosixPath(*clean)) if clean else "document.pdf"


def looks_like_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(1024)
        return PDF_MAGIC in head
    except OSError:
        return False


def collect_paths(inputs: list[Path]) -> tuple[list[InputFile], list[str]]:
    """Expand files and folders (recursively) into PDF inputs. Returns (files, skipped messages)."""
    files: list[InputFile] = []
    skipped: list[str] = []
    for p in inputs:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() == ".pdf":
                    if looks_like_pdf(f):
                        files.append(InputFile(f, f.relative_to(p.parent).as_posix(), "folder"))
                    else:
                        skipped.append(f"{f}: not a valid PDF")
        elif p.is_file():
            if p.suffix.lower() == ".zip":
                skipped.append(f"{p}: zip archives are accepted in the web app; extract it for the CLI")
            elif looks_like_pdf(p):
                files.append(InputFile(p, p.name, "file"))
            else:
                skipped.append(f"{p}: not a PDF")
        else:
            skipped.append(f"{p}: not found")
    return files, skipped


def extract_zip(zip_path: Path, dest: Path, max_files: int, max_bytes: int) -> tuple[list[InputFile], list[str]]:
    """Extract PDFs from a zip safely (no path traversal, size and count limits)."""
    files: list[InputFile] = []
    skipped: list[str] = []
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise InputError(f"{zip_path.name} is not a valid zip archive") from exc
    with zf:
        total = 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = safe_relpath(info.filename)
            if not rel.lower().endswith(".pdf") or "__MACOSX" in rel:
                skipped.append(f"{zip_path.name}/{info.filename}: not a PDF")
                continue
            if len(files) >= max_files:
                skipped.append(f"{zip_path.name}: file limit reached")
                break
            total += info.file_size
            if info.file_size > max_bytes or total > max_bytes * 10:
                skipped.append(f"{zip_path.name}/{info.filename}: too large")
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                remaining = max_bytes
                while chunk := src.read(1 << 20):
                    remaining -= len(chunk)
                    if remaining < 0:
                        break
                    out.write(chunk)
            if remaining < 0 or not looks_like_pdf(target):
                target.unlink(missing_ok=True)
                skipped.append(f"{zip_path.name}/{info.filename}: not a valid PDF or too large")
                continue
            files.append(InputFile(target, f"{Path(zip_path.name).stem}/{rel}", "zip"))
    return files, skipped


def inspect_pdf(path: Path) -> dict:
    try:
        pdf = pikepdf.open(path)
    except pikepdf.PasswordError as exc:
        raise InputError("The PDF requires a password to open. Remove the open password and try again.") from exc
    except pikepdf.PdfError as exc:
        raise InputError(f"The file could not be read as a PDF ({exc}).") from exc
    with pdf:
        root = pdf.Root
        acro = root.get("/AcroForm")
        st = root.get("/StructTreeRoot")
        k = st.get("/K") if st is not None else None
        tagged = bool(k is not None and (not isinstance(k, pikepdf.Array) or len(k) > 0))
        signed = False
        if isinstance(acro, pikepdf.Dictionary):
            signed = bool(int(acro.get("/SigFlags", 0)) & 1)
        names = root.get("/Names")
        javascript = bool(isinstance(names, pikepdf.Dictionary) and "/JavaScript" in names)
        facts = {
            "pages": len(pdf.pages),
            "pdf_version": pdf.pdf_version,
            "encrypted": pdf.is_encrypted,
            "tagged": tagged,
            "forms": bool(isinstance(acro, pikepdf.Dictionary) and acro.get("/Fields")),
            "xfa": bool(isinstance(acro, pikepdf.Dictionary) and "/XFA" in acro),
            "signed": signed,
            "javascript": javascript,
            "producer": str(pdf.docinfo.get("/Producer", "")) if pdf.docinfo else "",
            "creator": str(pdf.docinfo.get("/Creator", "")) if pdf.docinfo else "",
        }
    doc = pdfium.PdfDocument(str(path))
    try:
        image_only = []
        for i in range(len(doc)):
            page = doc[i]
            if page.get_textpage().count_chars() > 0:
                continue
            if any(o.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE for o in page.get_objects(max_depth=2)):
                image_only.append(i + 1)
        facts["image_only_pages"] = image_only
    finally:
        doc.close()
    return facts
