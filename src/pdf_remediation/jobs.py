"""Batch jobs: a set of files (uploaded, from folders/zips, or fetched from links)
processed in worker processes, with status persisted as JSON on disk."""
from __future__ import annotations

import csv
import io
import json
import multiprocessing
import re
import secrets
import shutil
import threading
import time
import zipfile
from concurrent.futures import Executor, Future, ProcessPoolExecutor
from pathlib import Path

from .config import Settings
from .edit import apply_figure_decisions
from .fetch import fetch_inputs
from .intake import InputFile
from .pipeline import Options, remediate_file, reverify
from .qa import alt_needs_work

ID_RE = re.compile(r"^[a-f0-9]{12}$")


def new_id() -> str:
    return secrets.token_hex(6)


def _process_one(src: str, out: str, display: str, settings: Settings, options: dict, source: str,
                 marker: str) -> dict:
    Path(marker).parent.mkdir(parents=True, exist_ok=True)
    Path(marker).write_text(str(time.time()))
    try:
        return remediate_file(Path(src), Path(out), display_name=display, settings=settings,
                              options=Options.from_dict(options), source=source)
    finally:
        Path(marker).unlink(missing_ok=True)


def _apply_review(src: str, out: str, settings: Settings, previous: dict, alts: dict, decorative: list) -> dict:
    info = apply_figure_decisions(Path(out), Path(out), {int(k): v for k, v in alts.items()},
                                  {int(i) for i in decorative})
    result = reverify(Path(src), Path(out), settings, previous)
    result["review"] = info
    return result


class _InlineExecutor(Executor):
    """Runs work immediately in the calling thread (tests, CLI)."""

    def submit(self, fn, /, *args, **kwargs):
        f: Future = Future()
        try:
            f.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - surfaced through the future
            f.set_exception(exc)
        return f


class JobManager:
    def __init__(self, settings: Settings, inline: bool = False):
        self.settings = settings
        self.root = Path(settings.data_dir) / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if inline:
            self.pool: Executor = _InlineExecutor()
        else:
            self.pool = ProcessPoolExecutor(max_workers=settings.workers,
                                            mp_context=multiprocessing.get_context("spawn"))
        self.inline = inline

    # ------------------------------------------------------------------ storage
    def job_dir(self, job_id: str) -> Path:
        if not ID_RE.match(job_id or ""):
            raise KeyError(job_id)
        return self.root / job_id

    def load(self, job_id: str) -> dict:
        path = self.job_dir(job_id) / "job.json"
        if not path.exists():
            raise KeyError(job_id)
        with self._lock:
            job = json.loads(path.read_text(encoding="utf-8"))
        for f in job["files"]:
            if f["status"] == "queued" and (self.job_dir(job_id) / "outputs" / f["id"] / ".processing").exists():
                f["status"] = "processing"
        return job

    def _save(self, job: dict) -> None:
        path = self.job_dir(job["id"]) / "job.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    def _update(self, job_id: str, fn) -> dict:
        with self._lock:
            job = json.loads((self.job_dir(job_id) / "job.json").read_text(encoding="utf-8"))
            fn(job)
            done = [f for f in job["files"] if f["status"] in ("ready-for-review", "needs-attention", "failed")]
            job["progress"] = {"done": len(done), "total": len(job["files"])}
            if not job.get("pending_urls") and len(done) == len(job["files"]) and job["status"] != "fetching":
                job["status"] = "complete"
            self._save(job)
            return job

    def list_jobs(self, limit: int = 20) -> list[dict]:
        jobs = []
        for d in sorted(self.root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if (d / "job.json").exists():
                try:
                    jobs.append(self.load(d.name))
                except (KeyError, json.JSONDecodeError):
                    continue
            if len(jobs) >= limit:
                break
        return jobs

    # ------------------------------------------------------------------ create/run
    def create_job(self, inputs: list[InputFile], urls: list[str], options: dict,
                   messages: list[str] | None = None) -> str:
        job_id = new_id()
        jdir = self.job_dir(job_id)
        (jdir / "inputs").mkdir(parents=True)
        (jdir / "outputs").mkdir()
        files = []
        for inp in inputs[: self.settings.max_files_per_job]:
            files.append(self._register(jdir, inp))
        job = {
            "id": job_id,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "options": options,
            "status": "fetching" if urls else "processing",
            "files": files,
            "pending_urls": [u for u in urls if u.strip()],
            "messages": list(messages or []),
            "progress": {"done": 0, "total": len(files)},
        }
        if len(inputs) > self.settings.max_files_per_job:
            job["messages"].append(f"Only the first {self.settings.max_files_per_job} files were accepted.")
        self._save(job)
        t = threading.Thread(target=self._run, args=(job_id,), daemon=True)
        t.start()
        if self.inline:
            t.join()
        return job_id

    def _register(self, jdir: Path, inp: InputFile) -> dict:
        fid = new_id()
        target = jdir / "inputs" / fid / Path(inp.relpath).name
        target.parent.mkdir(parents=True, exist_ok=True)
        if inp.path.resolve() != target.resolve():
            if inp.source in ("upload", "url", "zip"):  # temporary copies we own
                shutil.move(str(inp.path), target)
            else:  # the user's own files: never move them
                shutil.copyfile(inp.path, target)
        return {"id": fid, "name": inp.relpath, "source": inp.source, "input": str(target.relative_to(jdir)),
                "status": "queued"}

    def _run(self, job_id: str) -> None:
        jdir = self.job_dir(job_id)
        job = self.load(job_id)
        if job["pending_urls"]:
            res = fetch_inputs(job["pending_urls"], jdir / "fetched", self.settings)
            new_entries = [self._register(jdir, f) for f in res.files]

            def add(j):
                room = self.settings.max_files_per_job - len(j["files"])
                j["files"].extend(new_entries[:max(room, 0)])
                j["messages"].extend(res.messages)
                j["pending_urls"] = []
                j["status"] = "processing"
            job = self._update(job_id, add)
        if not job["files"]:
            self._update(job_id, lambda j: j.update(status="complete"))
            return
        for f in job["files"]:
            if f["status"] != "queued":
                continue
            src = jdir / f["input"]
            out = jdir / "outputs" / f["id"] / Path(f["input"]).name
            marker = jdir / "outputs" / f["id"] / ".processing"
            fut = self.pool.submit(_process_one, str(src), str(out), f["name"], self.settings, job["options"],
                                   f["source"], str(marker))
            fut.add_done_callback(lambda fu, fid=f["id"], o=out: self._done(job_id, fid, o, fu))

    def _done(self, job_id: str, fid: str, out: Path, fut: Future) -> None:
        try:
            result = fut.result()
        except Exception as exc:  # worker crashed
            result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

        def upd(job):
            for f in job["files"]:
                if f["id"] == fid:
                    f["status"] = result.get("status", "failed")
                    f["error"] = result.get("error")
                    f["summary"] = result.get("summary")
                    f["output"] = str(out.relative_to(self.job_dir(job_id))) if out.exists() else None
                    f["figures_without_alt"] = sum(1 for x in result.get("figures", []) if alt_needs_work(x.get("alt")))
        self._update(job_id, upd)

    # ------------------------------------------------------------------ files
    def file_entry(self, job: dict, fid: str) -> dict:
        for f in job["files"]:
            if f["id"] == fid:
                return f
        raise KeyError(fid)

    def result(self, job_id: str, fid: str) -> dict | None:
        job = self.load(job_id)
        f = self.file_entry(job, fid)
        out_dir = self.job_dir(job_id) / "outputs" / fid
        for p in out_dir.glob("*.report.json"):
            return json.loads(p.read_text(encoding="utf-8"))
        return None if f["status"] in ("queued", "processing") else {"status": f["status"], "error": f.get("error")}

    def paths(self, job_id: str, fid: str) -> dict[str, Path]:
        job = self.load(job_id)
        f = self.file_entry(job, fid)
        jdir = self.job_dir(job_id)
        src = jdir / f["input"]
        out = jdir / "outputs" / fid / Path(f["input"]).name
        stem = out.stem
        return {"original": src, "pdf": out, "json": out.with_name(stem + ".report.json"),
                "html": out.with_name(stem + ".report.html")}

    def apply_review(self, job_id: str, fid: str, alts: dict[int, str], decorative: list[int]) -> dict:
        p = self.paths(job_id, fid)
        previous = json.loads(p["json"].read_text(encoding="utf-8"))
        result = self.pool.submit(_apply_review, str(p["original"]), str(p["pdf"]), self.settings, previous,
                                  alts, decorative).result(timeout=600)

        def upd(job):
            f = self.file_entry(job, fid)
            f["status"], f["summary"] = result["status"], result.get("summary")
            f["figures_without_alt"] = sum(1 for x in result.get("figures", []) if alt_needs_work(x.get("alt")))
        self._update(job_id, upd)
        return result

    def zip_outputs(self, job_id: str) -> io.BytesIO:
        job = self.load(job_id)
        jdir = self.job_dir(job_id)
        buf = io.BytesIO()
        rows = []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in job["files"]:
                out_dir = jdir / "outputs" / f["id"]
                rel = Path(f["name"])
                for p in sorted(out_dir.glob("*")):
                    if p.name.startswith("."):
                        continue
                    suffix = p.name[len(Path(f["input"]).stem):]
                    zf.write(p, str(rel.parent / (rel.stem + suffix)))
                s = f.get("summary") or {}
                rows.append([f["name"], f["status"], s.get("machine_validation", ""), s.get("errors", ""),
                             s.get("warnings", ""), f.get("figures_without_alt", ""), f.get("error") or ""])
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["file", "status", "machine_validation", "errors", "warnings", "figures_without_alt", "error"])
            w.writerows(rows)
            zf.writestr("summary.csv", out.getvalue())
        buf.seek(0)
        return buf

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
