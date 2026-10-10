"""Which optional components are installed. Shown by `pdfrem doctor` and the web app."""
from __future__ import annotations

from .checks.verapdf import command as verapdf_command
from .config import Settings
from .java import java_version
from .ocr import available_engines
from .tagging import odl_available, odl_installed


def capabilities(settings: Settings) -> dict:
    java = java_version(settings.java_cmd)
    ocr = available_engines()
    return {
        "java": java,
        "verapdf": verapdf_command(settings) is not None,
        "odl": odl_available(settings.java_cmd),
        "odl_installed": odl_installed(),
        "ocr": bool(ocr),
        "ocr_engines": ocr,
        "ai": settings.ai_enabled,
        "ai_model": settings.ai_model,
        "ai_url": settings.ai_base_url,
    }


def describe(settings: Settings) -> list[tuple[str, bool, str]]:
    """Human-readable component list: (name, ready, detail)."""
    c = capabilities(settings)
    java = f"Java {c['java']}" if c["java"] else "Java not found"
    return [
        ("Java runtime (11+)", bool(c["java"] and c["java"] >= 11),
         java if c["java"] and c["java"] >= 11 else f"{java}. Install Java 17 or 21 (for example Eclipse Temurin)"),
        ("veraPDF validator (Java)", c["verapdf"],
         "installed" if c["verapdf"] else "run: pdfrem install-engines"),
        ("OpenDataLoader structure engine (Java)", c["odl"],
         "installed" if c["odl"] else ("needs Java 11+" if c["odl_installed"] else 'run: pip install -e ".[odl]"')),
        ("OCR for scanned pages (Python)", c["ocr"],
         "engine: " + ", ".join(c["ocr_engines"]) if c["ocr"] else 'run: pip install -e ".[ocr]"'),
        ("AI alt-text suggestions", c["ai"],
         f"model {c['ai_model']} at {c['ai_url']}" if c["ai"] else "turned off; set PDFREM_AI_ENABLED=1 to use it"),
    ]
