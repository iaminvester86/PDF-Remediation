"""Runtime settings, read from environment variables with safe defaults.

Every field can be overridden with ``PDFREM_<FIELD NAME IN UPPER CASE>``, for
example ``PDFREM_OCR_DPI=300``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("PDFREM_HOME", Path.home() / ".pdfrem"))


@dataclass
class Settings:
    # Storage
    data_dir: Path = Path("pdfrem-data")  # web jobs
    engines_dir: Path = field(default_factory=lambda: _home() / "engines")  # downloaded Java engines
    # Remediation defaults
    default_lang: str = "en-US"
    engine: str = "auto"  # auto (OpenDataLoader when available, else built-in) | basic | odl
    # OCR (pure Python by default)
    ocr_engine: str = "auto"  # auto | rapidocr | tesseract
    ocr_dpi: int = 200
    ocr_min_confidence: float = 0.3  # recognised lines below this are dropped
    # Java engines
    java_cmd: str = "java"
    verapdf_cmd: str = ""  # optional launcher from the official veraPDF installer
    verapdf_timeout: int = 300
    # Limits
    max_file_mb: int = 200
    max_files_per_job: int = 2000
    max_pages: int = 3000
    workers: int = max(1, min(4, (os.cpu_count() or 2) // 2))
    # Links
    allow_private_urls: bool = False
    url_timeout: float = 30.0
    max_discovered_pdfs: int = 50
    # AI (OpenAI-compatible endpoint; a local Ollama server by default)
    ai_enabled: bool = False
    ai_base_url: str = "http://127.0.0.1:11434/v1"
    ai_model: str = "qwen2.5vl:7b"
    ai_api_key: str = ""
    ai_allow_remote: bool = False
    ai_timeout: float = 120.0
    # Web server
    access_token: str = ""

    @property
    def verapdf_lib(self) -> Path:
        return Path(self.engines_dir) / "verapdf"

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        s = cls()
        for f in fields(cls):
            raw = os.environ.get("PDFREM_" + f.name.upper())
            if raw is None:
                continue
            current = getattr(s, f.name)
            if isinstance(current, bool):
                value: object = raw.strip().lower() in {"1", "true", "yes", "on"}
            elif isinstance(current, int):
                value = int(raw)
            elif isinstance(current, float):
                value = float(raw)
            elif isinstance(current, Path):
                value = Path(raw)
            else:
                value = raw
            setattr(s, f.name, value)
        for k, v in overrides.items():
            if v is not None:
                setattr(s, k, v)
        s.data_dir, s.engines_dir = Path(s.data_dir), Path(s.engines_dir)
        return s
