from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from conftest import make_sample
from pdf_remediation.jobs import JobManager
from pdf_remediation.web import create_app


@pytest.fixture
def client(settings):
    manager = JobManager(settings, inline=True)  # process synchronously for tests
    with TestClient(create_app(settings, manager)) as c:
        yield c


def _pdf_bytes(tmp_path, name, pages=1):
    return make_sample(tmp_path / name, pages=pages).read_bytes()


def test_home_page_is_labelled(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    for control in ('for="files"', 'for="folder"', 'for="urls"', "webkitdirectory", 'class="skip-link"'):
        assert control in html


def test_upload_files_folder_and_zip(client, tmp_path):
    a = _pdf_bytes(tmp_path, "a.pdf")
    b = _pdf_bytes(tmp_path, "b.pdf")
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("inner/c.pdf", a)
    files = [
        ("files", ("a.pdf", a, "application/pdf")),
        ("files", ("bundle.zip", z.getvalue(), "application/zip")),
        ("folder", ("b.pdf", b, "application/pdf")),
        ("folder", ("notes.pdf", b"not a pdf", "application/pdf")),
    ]
    data = {"folder_relpaths": ["myfolder/sub/b.pdf", "myfolder/notes.pdf"], "lang": "en-US", "engine": "basic"}
    r = client.post("/jobs", files=files, data=data, headers={"Accept": "application/json"})
    assert r.status_code == 201, r.text
    job_id = r.json()["job"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "complete"
    names = sorted(f["name"] for f in job["files"])
    assert names == ["a.pdf", "bundle/inner/c.pdf", "myfolder/sub/b.pdf"]
    assert any("notes.pdf" in m for m in job["messages"])
    assert all(f["status"] in ("ready-for-review", "needs-attention") for f in job["files"])

    page = client.get(f"/jobs/{job_id}")
    assert page.status_code == 200 and "myfolder/sub/b.pdf" in page.text

    fid = job["files"][0]["id"]
    detail = client.get(f"/jobs/{job_id}/files/{fid}")
    assert detail.status_code == 200 and "Review figures" in detail.text
    png = client.get(f"/jobs/{job_id}/files/{fid}/figures/0.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    pdf = client.get(f"/jobs/{job_id}/files/{fid}/download/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    zr = client.get(f"/jobs/{job_id}/download.zip")
    with zipfile.ZipFile(io.BytesIO(zr.content)) as zf:
        listed = zf.namelist()
    assert "summary.csv" in listed and "myfolder/sub/b.pdf" in listed and "myfolder/sub/b.report.html" in listed


def test_review_alt_text_rechecks(client, tmp_path, need_verapdf):
    a = _pdf_bytes(tmp_path, "a.pdf")
    r = client.post("/jobs", files=[("files", ("a.pdf", a, "application/pdf"))], data={"engine": "basic"},
                    headers={"Accept": "application/json"})
    job_id = r.json()["job"]
    fid = client.get(f"/api/jobs/{job_id}").json()["files"][0]["id"]
    before = client.get(f"/api/jobs/{job_id}/files/{fid}").json()
    assert before["summary"]["machine_validation"] == "fail"
    r = client.post(f"/jobs/{job_id}/files/{fid}/figures", data={"alt-0": "Blue bar chart of budget growth"},
                    follow_redirects=False)
    assert r.status_code == 303
    after = client.get(f"/api/jobs/{job_id}/files/{fid}").json()
    assert after["summary"]["machine_validation"] == "pass", json.dumps(after.get("verapdf"))[:500]
    assert after["figures"][0]["alt"] == "Blue bar chart of budget growth"
    assert after["status"] == "ready-for-review"


def test_validation_errors_are_reported(client):
    r = client.post("/jobs", data={"urls": "", "lang": "not a language!"})
    assert r.status_code == 400
    assert 'role="alert"' in r.text and "Language must be a code" in r.text
    assert "<title>Error:" in r.text


def test_internal_link_rejected_in_job(client):
    r = client.post("/jobs", data={"urls": "http://127.0.0.1:9/x.pdf"}, headers={"Accept": "application/json"})
    job = client.get(f"/api/jobs/{r.json()['job']}").json()
    assert job["status"] == "complete" and not job["files"]
    assert any("internal address" in m for m in job["messages"])


def test_access_token_required_when_configured(settings):
    settings.access_token = "s3cret"
    with TestClient(create_app(settings, JobManager(settings, inline=True))) as c:
        assert c.get("/").status_code == 401
        assert c.get("/?token=s3cret").status_code == 200
        assert c.get("/").status_code == 200  # cookie set
