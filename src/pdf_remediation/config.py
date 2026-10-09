"""Runtime settings, read from environment variables with safe defaults.

Every setting can be overridden with an environment variable named
``PDFREM_<FIELD NAME IN UPPER CASE>``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path


def _repo_vendor_dir() -> Path:
    # src/pdf_remediation/config.py -> repo root / vendor
    return Path(__file__).resolve().parents[2] / "vendor"


@dataclass
class Settings:
    data_dir: Path = Path("pdfrem-data")
    # Default document language written to /Lang when none is known.
    default_lang: str = "en-US"
    # Structure engine: "auto" (OpenDataLoader when installed, else basic), "basic", "odl".
    engine: str = "auto"
    # veraPDF: either a launcher script ("verapdf") or a directory of jars.
    verapdf_cmd: str = ""
    verapdf_lib: Path = field(default_factory=lambda: _repo_vendor_dir() / "verapdf" / "lib")
    java_cmd: str = "java"
    verapdf_timeout: int = 300
    # Limits
    max_file_mb: int = 200
    max_files_per_job: int = 2000
    max_pages: int = 3000
    workers: int = max(1, min(4, (os.cpu_count() or 2) // 2))
    # URL fetching
    allow_private_urls: bool = False
    url_timeout: float = 30.0
    max_discovered_pdfs: int = 50
    # AI (OpenAI-compatible chat completions endpoint; Ollama by default)
    ai_enabled: bool = False
    ai_base_url: str = "http://127.0.0.1:11434/v1"
    ai_model: str = "qwen2.5vl:7b"
    ai_api_key: str = ""
    ai_allow_remote: bool = False
    ai_timeout: float = 120.0
    # Web server
    access_token: str = ""

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        s = cls()
        for f in fields(cls):
            env = os.environ.get("PDFREM_" + f.name.upper())
            if env is None:
                continue
            current = getattr(s, f.name)
            if isinstance(current, bool):
                value: object = env.strip().lower() in {"1", "true", "yes", "on"}
            elif isinstance(current, int):
                value = int(env)
            elif isinstance(current, float):
                value = float(env)
            elif isinstance(current, Path):
                value = Path(env)
            else:
                value = env
            setattr(s, f.name, value)
        for k, v in overrides.items():
            if v is not None:
                setattr(s, k, v)
        s.data_dir = Path(s.data_dir)
        s.verapdf_lib = Path(s.verapdf_lib)
        return s
