"""OpenDataLoader PDF engine (Apache-2.0, Java 11+).

OpenDataLoader's layout analysis is stronger than the built-in engine on
multi-column pages and complex or borderless tables. Its free tier produces a
Tagged PDF; this application then applies its own finishing, font repair and
checks, which the free tier does not include.
"""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path

from ..java import java_version


def odl_installed() -> bool:
    return importlib.util.find_spec("opendataloader_pdf") is not None


def odl_available(java_cmd: str = "java") -> bool:
    version = java_version(java_cmd)
    return odl_installed() and version is not None and version >= 11


def odl_autotag(src: Path, dst: Path) -> Path:
    """Run OpenDataLoader auto-tagging; the tagged PDF is written to ``dst``."""
    import opendataloader_pdf

    with tempfile.TemporaryDirectory(prefix="pdfrem-odl-") as tmp:
        opendataloader_pdf.convert(input_path=str(src), output_dir=tmp, format="tagged-pdf", quiet=True)
        produced = sorted(Path(tmp).glob("*_tagged.pdf"))
        if not produced:
            raise RuntimeError("OpenDataLoader did not produce a tagged PDF")
        shutil.copyfile(produced[0], dst)
    return dst
