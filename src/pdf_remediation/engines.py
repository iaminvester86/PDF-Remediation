"""Optional external engines: OpenDataLoader (structure) and OCRmyPDF (OCR).

Both are optional. ``available_*`` functions report whether they can run so the
pipeline and the ``pdfrem doctor`` command can explain what is missing.
"""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path


def java_available(java_cmd: str = "java") -> bool:
    return shutil.which(java_cmd) is not None


def odl_available(java_cmd: str = "java") -> bool:
    return importlib.util.find_spec("opendataloader_pdf") is not None and java_available(java_cmd)


def odl_autotag(src: Path, dst: Path) -> Path:
    """Run OpenDataLoader auto-tagging. Returns the tagged PDF path (copied to dst)."""
    import opendataloader_pdf  # Apache-2.0, needs Java 11+

    with tempfile.TemporaryDirectory(prefix="pdfrem-odl-") as tmp:
        opendataloader_pdf.convert(input_path=str(src), output_dir=tmp, format="tagged-pdf", quiet=True)
        produced = list(Path(tmp).glob("*_tagged.pdf"))
        if not produced:
            raise RuntimeError("OpenDataLoader did not produce a tagged PDF")
        shutil.copyfile(produced[0], dst)
    return dst


def ocr_available() -> bool:
    return (importlib.util.find_spec("ocrmypdf") is not None and shutil.which("tesseract") is not None
            and (shutil.which("gs") is not None or shutil.which("gswin64c") is not None))


def ocr(src: Path, dst: Path, language: str = "eng") -> Path:
    """Add a text layer to image-only pages. Pages that already have text are skipped."""
    import ocrmypdf  # MPL-2.0; needs Tesseract and Ghostscript

    ocrmypdf.ocr(str(src), str(dst), language=language, skip_text=True, output_type="pdf",
                 progress_bar=False)
    return dst


def tesseract_lang(bcp47: str) -> str:
    """Map a BCP 47 tag (en-US) to a Tesseract language code (eng)."""
    table = {"en": "eng", "es": "spa", "fr": "fra", "de": "deu", "it": "ita", "pt": "por", "nl": "nld",
             "zh": "chi_sim", "ja": "jpn", "ko": "kor", "ar": "ara", "ru": "rus", "vi": "vie", "hi": "hin"}
    return table.get(bcp47.split("-")[0].lower(), "eng")
