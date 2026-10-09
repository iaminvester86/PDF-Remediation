from __future__ import annotations

import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import make_sample
from pdf_remediation.fetch import fetch_inputs
from pdf_remediation.intake import collect_paths, extract_zip, safe_relpath
from pdf_remediation.netguard import BlockedURL, check_public_url


def test_folder_is_scanned_recursively(tmp_path):
    root = tmp_path / "reports"
    (root / "2025" / "q1").mkdir(parents=True)
    make_sample(root / "a.pdf", pages=1)
    make_sample(root / "2025" / "q1" / "b.pdf", pages=1)
    (root / "notes.txt").write_text("not a pdf")
    (root / "fake.pdf").write_text("not really a pdf")
    files, skipped = collect_paths([root])
    assert sorted(f.relpath for f in files) == ["reports/2025/q1/b.pdf", "reports/a.pdf"]
    assert any("fake.pdf" in s for s in skipped)


def test_safe_relpath_blocks_traversal():
    assert safe_relpath("../../etc/passwd.pdf") == "etc/passwd.pdf"
    assert safe_relpath("C:\\Users\\x\\doc.pdf") == "C_/Users/x/doc.pdf"
    assert safe_relpath("folder/sub/../file.pdf") == "folder/sub/file.pdf"


def test_zip_extraction_is_safe(tmp_path):
    pdf = make_sample(tmp_path / "in.pdf", pages=1)
    z = tmp_path / "batch.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(pdf, "docs/one.pdf")
        zf.write(pdf, "../../evil.pdf")
        zf.writestr("readme.txt", "hello")
        zf.writestr("docs/broken.pdf", "not a pdf")
    files, skipped = extract_zip(z, tmp_path / "x", max_files=100, max_bytes=50 * 1024 * 1024)
    rels = sorted(f.relpath for f in files)
    assert rels == ["batch/docs/one.pdf", "batch/evil.pdf"]
    assert all((tmp_path / "x") in f.path.parents for f in files)
    assert any("readme.txt" in s for s in skipped) and any("broken.pdf" in s for s in skipped)


def test_internal_links_blocked_by_default():
    with pytest.raises(BlockedURL):
        check_public_url("http://127.0.0.1:8080/x.pdf", allow_private=False)
    with pytest.raises(BlockedURL):
        check_public_url("file:///etc/passwd", allow_private=True)
    with pytest.raises(BlockedURL):
        check_public_url("http://user:pw@example.com/x.pdf", allow_private=True)


@pytest.fixture
def site(tmp_path):
    www = tmp_path / "www"
    (www / "files").mkdir(parents=True)
    make_sample(www / "files" / "report.pdf", pages=1)
    make_sample(www / "files" / "budget.pdf", pages=1)
    (www / "index.html").write_text(
        '<!doctype html><html><body><a href="files/report.pdf">Report</a> '
        '<a href="/files/budget.pdf#page=2">Budget</a> <a href="https://other.example/x.pdf">Elsewhere</a>'
        '<a href="about.html">About</a></body></html>')
    handler = partial(SimpleHTTPRequestHandler, directory=str(www))
    handler.log_message = lambda *a, **k: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_fetch_pdf_link_and_page_links(site, tmp_path, settings):
    settings.allow_private_urls = True  # the test server is on localhost
    res = fetch_inputs([f"{site}/files/report.pdf", f"{site}/index.html", f"{site}/missing.pdf"],
                       tmp_path / "dl", settings)
    names = sorted(f.relpath for f in res.files)
    # report.pdf is linked from the page too, but is fetched only once
    assert names == ["127.0.0.1/budget.pdf", "report.pdf"]
    assert any("already added" in m for m in res.messages)
    assert any("missing.pdf" in m for m in res.messages)
    assert all(f.source == "url" for f in res.files)


def test_fetch_blocks_localhost_without_opt_in(site, tmp_path, settings):
    res = fetch_inputs([f"{site}/files/report.pdf"], tmp_path / "dl", settings)
    assert not res.files and "internal address" in res.messages[0]
