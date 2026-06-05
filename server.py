"""
docscrape HTTP service — FastAPI.

Endpoints:
  GET  /                          → static UI (static/index.html)
  GET  /healthz                   → {"ok": true}
  POST /scrape                    → start a job, returns {job_id}
       body: {"url": "...", "max": 200, "delay": 0.2, "mode": "single|split"}
  GET  /jobs                      → list jobs
  GET  /jobs/{job_id}             → job status + page count + progress
  GET  /jobs/{job_id}/download    → mode=single: .md  ;  mode=split: .zip
  GET  /jobs/{job_id}/files       → split mode: list relative paths
  GET  /jobs/{job_id}/files/{path:path}  → split mode: serve one file
  DELETE /jobs/{job_id}           → remove a job + artifacts

Artifacts live under DOCSCRAPE_DATA (default ~/.local/share/docscrape/jobs).
This service is stateless w.r.t. the host filesystem outside DATA_DIR — it
does NOT write anywhere else. Safe to ship as a standalone container.
"""
from __future__ import annotations
import os, json, uuid, time, zipfile, threading, traceback, urllib.parse as up
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from docscrape_lib import crawl, render_single, render_split

DATA_DIR = Path(os.environ.get("DOCSCRAPE_DATA",
                               str(Path.home() / ".local/share/docscrape/jobs")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="web-shooter", version="1.1")

# CORS — public-friendly default so anyone running the container can hit the
# API from a different origin (e.g. the GitHub Pages landing page if they
# wire it to a local backend). Override DOCSCRAPE_CORS_ORIGINS to lock down.
_origins = os.environ.get("DOCSCRAPE_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the web UI from ./static
_STATIC_DIR = Path(__file__).resolve().parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# in-memory job registry; status is also mirrored to disk so restarts survive
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _job_dir(job_id: str) -> Path:
    return DATA_DIR / job_id


def _save_status(job_id: str):
    with _jobs_lock:
        info = dict(_jobs.get(job_id, {}))
    if not info:
        return
    (_job_dir(job_id) / "status.json").write_text(json.dumps(info, indent=2))


def _load_existing_jobs():
    if not DATA_DIR.exists():
        return
    for d in DATA_DIR.iterdir():
        sf = d / "status.json"
        if sf.is_file():
            try:
                _jobs[d.name] = json.loads(sf.read_text())
            except Exception:
                pass


_load_existing_jobs()


# ---------------------------------------------------------------- models

class ScrapeRequest(BaseModel):
    url: HttpUrl
    max: int = Field(200, ge=1, le=2000, description="Max pages to crawl")
    delay: float = Field(0.2, ge=0.0, le=5.0, description="Seconds between requests")
    mode: Literal["single", "split"] = "single"


# ---------------------------------------------------------------- worker

def _run_job(job_id: str, req: ScrapeRequest):
    jdir = _job_dir(job_id)
    jdir.mkdir(parents=True, exist_ok=True)

    def progress(done, total, url):
        with _jobs_lock:
            j = _jobs[job_id]
            j["pages_done"] = done
            j["current_url"] = url
        if done % 5 == 0:
            _save_status(job_id)

    try:
        pages = crawl(str(req.url), req.max, req.delay, progress=progress)
        if not pages:
            raise RuntimeError("No pages scraped (site empty or unreachable)")

        host = up.urlparse(str(req.url)).netloc.replace(".", "_")
        if req.mode == "single":
            out = jdir / f"{host}.md"
            out.write_text(render_single(str(req.url), pages), encoding="utf-8")
            artifact = {"kind": "file", "path": str(out), "name": out.name,
                        "size": out.stat().st_size}
        else:
            split_dir = jdir / host
            split_dir.mkdir(exist_ok=True)
            files = render_split(str(req.url), pages)
            for rel, content in files.items():
                fp = split_dir / rel
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content, encoding="utf-8")
            zp = jdir / f"{host}.zip"
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
                for rel in files:
                    zf.write(split_dir / rel, arcname=f"{host}/{rel}")
            artifact = {"kind": "folder", "path": str(split_dir),
                        "zip": str(zp), "name": f"{host}.zip",
                        "size": zp.stat().st_size, "file_count": len(files)}

        with _jobs_lock:
            j = _jobs[job_id]
            j["status"] = "complete"
            j["finished_at"] = time.time()
            j["pages_done"] = len(pages)
            j["artifact"] = artifact
        _save_status(job_id)

    except Exception as e:
        with _jobs_lock:
            j = _jobs[job_id]
            j["status"] = "error"
            j["error"] = f"{type(e).__name__}: {e}"
            j["traceback"] = traceback.format_exc()
            j["finished_at"] = time.time()
        _save_status(job_id)


# ---------------------------------------------------------------- routes

@app.get("/", response_class=HTMLResponse)
def index():
    idx = _STATIC_DIR / "index.html"
    if idx.is_file():
        return HTMLResponse(idx.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>WEB-SHOOTER</h1><p>static/index.html missing</p>")


@app.get("/healthz")
def healthz():
    return {"ok": True, "data_dir": str(DATA_DIR), "jobs": len(_jobs)}


@app.post("/scrape")
def scrape(req: ScrapeRequest, bg: BackgroundTasks):
    job_id = uuid.uuid4().hex[:12]
    _job_dir(job_id).mkdir(parents=True, exist_ok=True)
    now = time.time()
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "url": str(req.url),
            "mode": req.mode,
            "max": req.max,
            "delay": req.delay,
            "started_at": now,
            "pages_done": 0,
            "current_url": None,
        }
    _save_status(job_id)
    bg.add_task(_run_job, job_id, req)
    return {"job_id": job_id, "status": "running"}


@app.get("/jobs")
def list_jobs():
    with _jobs_lock:
        out = list(_jobs.values())
    out.sort(key=lambda j: j.get("started_at", 0), reverse=True)
    return out


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@app.get("/jobs/{job_id}/download")
def download(job_id: str):
    with _jobs_lock:
        j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    if j["status"] != "complete":
        raise HTTPException(409, f"job status is {j['status']}")
    art = j["artifact"]
    if art["kind"] == "file":
        path = Path(art["path"])
        media = "text/markdown"
    else:
        path = Path(art["zip"])
        media = "application/zip"
    if not path.is_file():
        raise HTTPException(410, "artifact missing on disk")
    return FileResponse(path, filename=path.name, media_type=media)


@app.get("/jobs/{job_id}/files")
def list_files(job_id: str):
    with _jobs_lock:
        j = _jobs.get(job_id)
    if not j or j.get("status") != "complete":
        raise HTTPException(404, "job not found or not complete")
    art = j["artifact"]
    if art["kind"] != "folder":
        raise HTTPException(400, "this job is single-file mode; use /download")
    root = Path(art["path"])
    rels = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rels.append(str(p.relative_to(root)))
    return {"root": str(root), "files": rels}


@app.get("/jobs/{job_id}/files/{path:path}")
def get_file(job_id: str, path: str):
    with _jobs_lock:
        j = _jobs.get(job_id)
    if not j or j.get("status") != "complete":
        raise HTTPException(404, "job not found or not complete")
    art = j["artifact"]
    if art["kind"] != "folder":
        raise HTTPException(400, "this job is single-file mode")
    root = Path(art["path"]).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root) + os.sep) and target != root:
        raise HTTPException(400, "invalid path")
    if not target.is_file():
        raise HTTPException(404, "file not found")
    return PlainTextResponse(target.read_text(encoding="utf-8"),
                             media_type="text/markdown")


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    with _jobs_lock:
        j = _jobs.pop(job_id, None)
    if not j:
        raise HTTPException(404, "job not found")
    import shutil
    jd = _job_dir(job_id)
    if jd.exists():
        shutil.rmtree(jd, ignore_errors=True)
    return {"deleted": job_id}
