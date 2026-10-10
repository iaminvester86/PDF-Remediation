"""Java engines: runtime detection and veraPDF installation.

Two optional engines run on Java 11+:

* **veraPDF** (PDF/UA validator, GPLv3+ or MPLv2+, run as a separate process).
  ``install_verapdf`` downloads the exact jars listed below from Maven Central
  and checks each SHA-256, so no Maven or manual download is needed.
* **OpenDataLoader** (structure engine, Apache-2.0). It ships its own jar inside
  the ``opendataloader-pdf`` Python package (``pip install -e ".[odl]"``).
"""
from __future__ import annotations

import functools
import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx

MAVEN = "https://repo1.maven.org/maven2"
VERAPDF_VERSION = "1.28.2"
VERAPDF_MAIN = "org.verapdf.apps.GreenfieldCliWrapper"

# group, artifact, version, sha256 (resolved from org.verapdf.apps:greenfield-apps:1.28.2)
VERAPDF_JARS = [
    ("org.verapdf.apps", "greenfield-apps", "1.28.2", "687d4d8bcfec48c9f7e931cf78ed061f1eeccfba55d4cdc000ba9b4d8aa46ce6"),
    ("org.verapdf.apps", "gui", "1.28.2", "b3382c806dfc11f780cdc51d398bdacc7cc23c0ba1899d687ad26dbef533c114"),
    ("org.verapdf", "core", "1.28.2", "847b0d5ac9effa76d310db92dfb8e11a67c94f70271f54971fcbc75a358abf01"),
    ("org.verapdf", "feature-reporting", "1.28.2", "b11601c1644fc06ac09190632b7fc172946a707b55e976acbe804a25ab8500be"),
    ("org.verapdf", "metadata-fixer", "1.28.2", "7a005db32a5781ea34502c0c4d99aeb0f97a742c7d6fd80756fd10e8a987862f"),
    ("org.verapdf", "parser", "1.28.2", "b51d39394b2d24f1e0303a0cffbaffc238604d4bb6010ea90a85150b4a2659f6"),
    ("org.verapdf", "pdf-model", "1.28.2", "7f4695701faefaa9efd3a39265f0020dc622edbc66d528e96118c392c03ec4d2"),
    ("org.verapdf", "validation-model", "1.28.2", "8d5891939a8302a9b5b1b4791fb63328ad5edb51728866e935bf89b3c6f469df"),
    ("org.verapdf", "verapdf-xmp-core", "1.28.2", "e7b827185f0480cc1a4347522eaea51a826e0177689d623b39646a02edfab421"),
    ("com.beust", "jcommander", "1.81", "9d8b42979c99f3daa99102fe9ba1fb25f52226cb48cf58bc18acb93132e41a05"),
    ("com.fasterxml.jackson.core", "jackson-annotations", "2.15.0", "91adcd3dcf5fd9a16499934e7536a23d456692a0093e3d4fd52f138c3936348c"),
    ("com.fasterxml.jackson.core", "jackson-core", "2.15.0", "5b483f68fa9dd6aa37da37d1f79dd5c4b9464238f4f0660a242cb6b5c724950c"),
    ("com.fasterxml.jackson.core", "jackson-databind", "2.15.0", "00c5a5d5ae71ac8e8d5b8da606841e2251c806355939cb5d51c4cdc6b644a0dc"),
    ("com.sun.xml.bind", "jaxb-core", "2.3.0.1", "d2ecba63615f317a11fb55c6468f6a9480f6411c10951d9881bafd9a9a8d0467"),
    ("com.sun.xml.bind", "jaxb-impl", "2.3.2", "b3a3d3aeaa5503cadc24dca9539b87efcd7bc3bd8c48018887a1489f2a77bdc0"),
    ("javax.activation", "javax.activation-api", "1.2.0", "43fdef0b5b6ceb31b0424b208b930c74ab58fac2ceeb7b3f6fd3aeb8b5ca4393"),
    ("javax.xml.bind", "jaxb-api", "2.3.1", "88b955a0df57880a26a74708bc34f74dcaf8ebf4e78843a28b50eae945732b06"),
    ("net.java.dev.stax-utils", "stax-utils", "20070216", "7c7fd0892cb3362ed2e43ce2f76c8f18f2d7ff1d371ed7490775b7368f3fee9a"),
    ("org.mozilla", "rhino", "1.7.13", "931dda33789d8e004ff5b5478ee3d6d224305de330c48266df7c3e49d52fc606"),
]


@functools.lru_cache(maxsize=8)
def java_version(java_cmd: str = "java") -> int | None:
    """Major Java version (8, 11, 17, 21...) or None when Java is not available."""
    exe = shutil.which(java_cmd)
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r'version "(\d+)(?:\.(\d+))?', proc.stderr + proc.stdout)
    if not m:
        return None
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major  # "1.8.0" means Java 8


def _jar_name(artifact: str, version: str) -> str:
    return f"{artifact}-{version}.jar"


def verapdf_installed(lib: Path) -> bool:
    return all((lib / _jar_name(a, v)).exists() for _, a, v, _ in VERAPDF_JARS)


def install_verapdf(lib: Path, log=print, timeout: float = 120.0, client: httpx.Client | None = None) -> Path:
    """Download and verify the veraPDF jars into ``lib``. Safe to run again."""
    lib.mkdir(parents=True, exist_ok=True)
    with client or httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for group, artifact, version, sha256 in VERAPDF_JARS:
            target = lib / _jar_name(artifact, version)
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == sha256:
                continue
            url = f"{MAVEN}/{group.replace('.', '/')}/{artifact}/{version}/{target.name}"
            log(f"  downloading {target.name}")
            data = _get_with_retry(client, url)
            digest = hashlib.sha256(data).hexdigest()
            if digest != sha256:
                raise RuntimeError(f"Checksum mismatch for {target.name}: expected {sha256}, got {digest}")
            tmp = target.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(target)
    return lib


def _get_with_retry(client: httpx.Client, url: str, attempts: int = 5) -> bytes:
    """GET with exponential backoff on rate limits (429) and server errors."""
    delay = 2.0
    for attempt in range(attempts):
        r = client.get(url)
        if r.status_code == 200:
            return r.content
        if r.status_code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
            r.raise_for_status()
        retry_after = r.headers.get("retry-after", "")
        time.sleep(min(float(retry_after), 60.0) if retry_after.isdigit() else delay)
        delay *= 2
    raise RuntimeError(f"Could not download {url}")


def verapdf_command(lib: Path, java_cmd: str = "java", launcher: str = "") -> list[str] | None:
    """Command prefix that runs veraPDF, or None when it is not installed.

    Order: an explicit launcher script, the jar folder (needs Java 11+), a
    ``verapdf`` launcher on PATH (from the official installer).
    """
    if launcher:
        exe = shutil.which(launcher) or launcher
        if Path(exe).exists():
            return [exe]
    version = java_version(java_cmd)
    if lib.is_dir() and any(lib.glob("*.jar")) and version and version >= 11:
        return [shutil.which(java_cmd) or java_cmd, "-cp", str(lib / "*"), VERAPDF_MAIN]
    found = shutil.which("verapdf")
    return [found] if found else None
