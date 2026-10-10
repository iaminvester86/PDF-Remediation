from __future__ import annotations

import hashlib
import subprocess

import httpx
import pytest

from pdf_remediation import java


@pytest.fixture(autouse=True)
def _clear_cache():
    java.java_version.cache_clear()
    yield
    java.java_version.cache_clear()


@pytest.mark.parametrize("banner, expected", [
    ('openjdk version "21.0.4" 2024-07-16', 21),
    ('openjdk version "17" 2021-09-14', 17),
    ('java version "1.8.0_402"', 8),
    ("no version here", None),
])
def test_java_version_parsing(monkeypatch, banner, expected):
    monkeypatch.setattr(java.shutil, "which", lambda cmd: "/usr/bin/java")
    monkeypatch.setattr(java.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="", stderr=banner))
    assert java.java_version("java") == expected


def test_java_missing(monkeypatch):
    monkeypatch.setattr(java.shutil, "which", lambda cmd: None)
    assert java.java_version("java") is None


def _jars(monkeypatch, payloads: dict[str, bytes]):
    """Pretend the jar list is two small files with known hashes."""
    entries = [("org.example", name, "1.0", hashlib.sha256(data).hexdigest()) for name, data in payloads.items()]
    monkeypatch.setattr(java, "VERAPDF_JARS", entries)
    return entries


def test_install_verifies_checksums_and_is_idempotent(tmp_path, monkeypatch):
    payloads = {"alpha": b"alpha-jar", "beta": b"beta-jar"}
    _jars(monkeypatch, payloads)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        name = request.url.path.rsplit("/", 1)[-1].split("-1.0.jar")[0]
        return httpx.Response(200, content=payloads[name])

    lib = tmp_path / "verapdf"
    java.install_verapdf(lib, log=lambda m: None, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert java.verapdf_installed(lib)
    assert calls == ["/maven2/org/example/alpha/1.0/alpha-1.0.jar", "/maven2/org/example/beta/1.0/beta-1.0.jar"]
    java.install_verapdf(lib, log=lambda m: None, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(calls) == 2  # verified files are not downloaded again


def test_install_rejects_tampered_jar(tmp_path, monkeypatch):
    _jars(monkeypatch, {"alpha": b"alpha-jar"})
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"evil")))
    lib = tmp_path / "verapdf"
    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        java.install_verapdf(lib, log=lambda m: None, client=client)
    assert not list(lib.glob("*.jar"))


def test_install_retries_rate_limit(tmp_path, monkeypatch):
    _jars(monkeypatch, {"alpha": b"alpha-jar"})
    monkeypatch.setattr(java.time, "sleep", lambda s: None)
    responses = iter([httpx.Response(429, headers={"retry-after": "1"}), httpx.Response(503),
                      httpx.Response(200, content=b"alpha-jar")])
    client = httpx.Client(transport=httpx.MockTransport(lambda r: next(responses)))
    java.install_verapdf(tmp_path, log=lambda m: None, client=client)
    assert (tmp_path / "alpha-1.0.jar").read_bytes() == b"alpha-jar"


def test_verapdf_command_prefers_jar_folder(tmp_path, monkeypatch):
    (tmp_path / "core-1.0.jar").write_bytes(b"x")
    monkeypatch.setattr(java, "java_version", lambda cmd: 17)
    monkeypatch.setattr(java.shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd == "java" else None)
    cmd = java.verapdf_command(tmp_path, "java")
    assert cmd[:2] == ["/usr/bin/java", "-cp"] and cmd[-1] == java.VERAPDF_MAIN


def test_verapdf_command_needs_java_11(tmp_path, monkeypatch):
    (tmp_path / "core-1.0.jar").write_bytes(b"x")
    monkeypatch.setattr(java, "java_version", lambda cmd: 8)
    monkeypatch.setattr(java.shutil, "which", lambda cmd: None)
    assert java.verapdf_command(tmp_path, "java") is None
