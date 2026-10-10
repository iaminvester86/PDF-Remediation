"""Local web application: upload files, folders, zips or links; review and download results."""
from __future__ import annotations

import hmac
import io
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import Settings
from ..inputs import InputError, InputFile, extract_zip, looks_like_pdf, safe_relpath
from ..jobs import JobManager
from ..pdf.pdfium import render_crop
from ..report import env
from ..status import capabilities, describe

STATIC = Path(__file__).parent / "static"
LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def create_app(settings: Settings | None = None, manager: JobManager | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    manager = manager or JobManager(settings)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        manager.shutdown()

    app = FastAPI(title="PDF Remediation", version=__version__, docs_url="/api/docs", redoc_url=None,
                  lifespan=lifespan)
    app.state.settings, app.state.manager = settings, manager
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    staging_root = Path(settings.data_dir) / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)

    def render(request: Request, template: str, status: int = 200, **ctx) -> HTMLResponse:
        html = env().get_template(template).render(request=request, version=__version__,
                                                   caps=capabilities(settings), components=describe(settings),
                                                   settings=settings, **ctx)
        return HTMLResponse(html, status_code=status)

    @app.middleware("http")
    async def token_guard(request: Request, call_next):
        token = settings.access_token
        if token and not request.url.path.startswith("/static"):
            supplied = request.cookies.get("pdfrem_token") or request.query_params.get("token") or ""
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                supplied = auth[7:]
            if not hmac.compare_digest(supplied, token):
                return HTMLResponse("<!doctype html><html lang='en'><title>Sign in required</title><main>"
                                    "<h1>Sign in required</h1><p>Open the link that includes the access token "
                                    "printed when the server started.</p></main></html>", status_code=401)
            response = await call_next(request)
            if request.query_params.get("token"):
                response.set_cookie("pdfrem_token", token, httponly=True, samesite="strict")
            return response
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy",
                                    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                                    "frame-ancestors 'none'")
        return response

    # ------------------------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return render(request, "index.html", jobs=manager.list_jobs())

    @app.post("/jobs")
    async def create_job(request: Request,
                         files: list[UploadFile] = File(default=[]),
                         folder: list[UploadFile] = File(default=[]),
                         folder_relpaths: list[str] = Form(default=[]),
                         urls: str = Form(default=""),
                         engine: str = Form(default="auto"),
                         lang: str = Form(default=""),
                         existing_tags: str = Form(default="auto"),
                         ocr: str = Form(default="auto"),
                         ai: str = Form(default=""),
                         accept_ai_alt: str = Form(default="")):
        wants_json = "application/json" in request.headers.get("accept", "")
        errors: list[str] = []
        lang = lang.strip() or settings.default_lang
        if not LANG_RE.match(lang):
            errors.append("Language must be a code such as en-US or es.")
        if engine not in ("auto", "basic", "odl"):
            errors.append("Choose a valid structure engine.")
        if ocr not in ("auto", "off"):
            errors.append("Choose a valid OCR option.")
        if existing_tags not in ("auto", "keep", "retag"):
            errors.append("Choose a valid option for existing tags.")
        url_list = [u.strip() for u in re.split(r"[\r\n]+", urls or "") if u.strip()]
        if len(url_list) > 50:
            errors.append("Enter at most 50 links at a time.")

        staging = staging_root / uuid.uuid4().hex
        staging.mkdir(parents=True)
        inputs: list[InputFile] = []
        messages: list[str] = []
        max_bytes = settings.max_file_mb * 1024 * 1024
        uploads = [(u, u.filename or "", "upload") for u in files]
        for i, u in enumerate(folder):
            rel = folder_relpaths[i] if i < len(folder_relpaths) and folder_relpaths[i] else (u.filename or "")
            uploads.append((u, rel, "upload"))
        try:
            for upload, name, source in uploads:
                if not name:
                    continue
                rel = safe_relpath(name)
                lower = rel.lower()
                if not lower.endswith((".pdf", ".zip")):
                    messages.append(f"{rel}: skipped (not a PDF or zip file)")
                    continue
                target = staging / "u" / uuid.uuid4().hex / Path(rel).name
                target.parent.mkdir(parents=True)
                size = 0
                with open(target, "wb") as out:
                    while chunk := await upload.read(1 << 20):
                        size += len(chunk)
                        if size > max_bytes:
                            break
                        out.write(chunk)
                if size > max_bytes:
                    target.unlink(missing_ok=True)
                    messages.append(f"{rel}: skipped (larger than {settings.max_file_mb} MB)")
                    continue
                if lower.endswith(".zip"):
                    try:
                        found, skipped = extract_zip(target, staging / "z" / uuid.uuid4().hex,
                                                     settings.max_files_per_job, max_bytes)
                    except InputError as exc:
                        messages.append(str(exc))
                        continue
                    inputs.extend(found)
                    messages.extend(skipped)
                elif looks_like_pdf(target):
                    inputs.append(InputFile(target, rel, source))
                else:
                    messages.append(f"{rel}: skipped (the file is not a valid PDF)")
            if not inputs and not url_list and not errors:
                errors.append("Add at least one PDF file, folder, zip archive or link.")
            if errors:
                shutil.rmtree(staging, ignore_errors=True)
                if wants_json:
                    return JSONResponse({"errors": errors, "messages": messages}, status_code=400)
                return render(request, "index.html", status=400, jobs=manager.list_jobs(), errors=errors,
                              messages=messages, form={"urls": urls, "lang": lang, "engine": engine,
                                                       "existing_tags": existing_tags, "ocr": ocr})
            options = {"engine": engine, "lang": lang, "existing_tags": existing_tags, "ocr": ocr,
                       "ai": bool(ai) and settings.ai_enabled, "accept_ai_alt": bool(accept_ai_alt) and bool(ai)}
            job_id = manager.create_job(inputs, url_list, options, messages)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if wants_json:
            return JSONResponse({"job": job_id, "url": f"/jobs/{job_id}"}, status_code=201)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    def _job_or_404(job_id: str) -> dict:
        try:
            return manager.load(job_id)
        except KeyError:
            raise HTTPException(404, "Job not found")

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str):
        return render(request, "job.html", job=_job_or_404(job_id))

    @app.get("/api/jobs/{job_id}")
    def job_api(job_id: str):
        return _job_or_404(job_id)

    @app.get("/api/jobs/{job_id}/files/{fid}")
    def file_api(job_id: str, fid: str):
        _job_or_404(job_id)
        try:
            return manager.result(job_id, fid) or {"status": "processing"}
        except KeyError:
            raise HTTPException(404, "File not found")

    @app.get("/jobs/{job_id}/files/{fid}", response_class=HTMLResponse)
    def file_page(request: Request, job_id: str, fid: str, saved: str = ""):
        job = _job_or_404(job_id)
        try:
            entry = manager.file_entry(job, fid)
        except KeyError:
            raise HTTPException(404, "File not found")
        result = manager.result(job_id, fid)
        return render(request, "file.html", job=job, f=entry, r=result, saved=saved)

    @app.post("/jobs/{job_id}/files/{fid}/figures")
    async def save_figures(request: Request, job_id: str, fid: str):
        _job_or_404(job_id)
        form = await request.form()
        alts: dict[int, str] = {}
        decorative: list[int] = []
        for key, value in form.items():
            m = re.fullmatch(r"alt-(\d+)", key)
            if m and str(value).strip():
                alts[int(m.group(1))] = str(value).strip()[:1000]
            m = re.fullmatch(r"decorative-(\d+)", key)
            if m:
                decorative.append(int(m.group(1)))
        result = manager.apply_review(job_id, fid, alts, decorative)
        n_err = len(result.get("review", {}).get("errors", []))
        return RedirectResponse(f"/jobs/{job_id}/files/{fid}?saved={'partial' if n_err else 'ok'}#review-h",
                                status_code=303)

    @app.get("/jobs/{job_id}/files/{fid}/figures/{index}.png")
    def figure_png(job_id: str, fid: str, index: int):
        _job_or_404(job_id)
        result = manager.result(job_id, fid) or {}
        figs = {f["index"]: f for f in result.get("figures", [])}
        f = figs.get(index)
        if not f or not f.get("bbox"):
            raise HTTPException(404, "Figure not found")
        img = render_crop(manager.paths(job_id, fid)["pdf"], f["page"], tuple(f["bbox"]), scale=1.5)
        img.thumbnail((800, 800))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(buf.getvalue(), media_type="image/png")

    @app.get("/jobs/{job_id}/files/{fid}/download/{kind}")
    def download(job_id: str, fid: str, kind: str):
        _job_or_404(job_id)
        if kind not in ("pdf", "json", "html", "original"):
            raise HTTPException(404)
        path = manager.paths(job_id, fid)[kind]
        if not path.exists():
            raise HTTPException(404, "Not available")
        name = path.name if kind != "original" else "original-" + path.name
        media = {"pdf": "application/pdf", "original": "application/pdf", "json": "application/json",
                 "html": "text/html"}[kind]
        return FileResponse(path, media_type=media, filename=name,
                            content_disposition_type="inline" if kind == "html" else "attachment")

    @app.get("/jobs/{job_id}/download.zip")
    def download_zip(job_id: str):
        _job_or_404(job_id)
        buf = manager.zip_outputs(job_id)
        return StreamingResponse(buf, media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="remediated-{job_id}.zip"'})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "capabilities": capabilities(settings)}

    return app
