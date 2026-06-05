"""
docscrape HTTP service — FastAPI.

Endpoints:
  GET  /                          → health + tiny HTML help page
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
"""
from __future__ import annotations
import os, json, uuid, time, zipfile, threading, traceback, urllib.parse as up
from pathlib import Path
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from docscrape_lib import crawl, render_single, render_split

DATA_DIR = Path(os.environ.get("DOCSCRAPE_DATA",
                               str(Path.home() / ".local/share/docscrape/jobs")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# AI-reference context library — finished scrapes can be deposited here
# directly (single mode -> one .md file, split mode -> a folder per site).
CONTEXT_DIR = Path(os.environ.get("DOCSCRAPE_CONTEXT",
                                  str(Path.home() / "context")))
CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="docscrape", version="1.0")

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
    deliver_to_context: bool = Field(
        False,
        description=("Also copy the finished artifact straight into the context "
                     "library (DOCSCRAPE_CONTEXT, default ~/context). "
                     "Single mode → ~/context/<host>.md. "
                     "Split mode → ~/context/<host>/ folder.")
    )
    overwrite: bool = Field(
        True,
        description="If a context entry for this site already exists, replace it."
    )


# ---------------------------------------------------------------- worker

def _run_job(job_id: str, req: ScrapeRequest):
    jdir = _job_dir(job_id)
    jdir.mkdir(parents=True, exist_ok=True)

    def progress(done, total, url):
        with _jobs_lock:
            j = _jobs[job_id]
            j["pages_done"] = done
            j["current_url"] = url
        # don't fsync every tick — write every 5 pages
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
            # also build a .zip for one-click download
            zp = jdir / f"{host}.zip"
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
                for rel in files:
                    zf.write(split_dir / rel, arcname=f"{host}/{rel}")
            artifact = {"kind": "folder", "path": str(split_dir),
                        "zip": str(zp), "name": f"{host}.zip",
                        "size": zp.stat().st_size, "file_count": len(files)}

        # Optionally deliver straight into the context library so the user
        # doesn't have to download + extract before AI tooling can read it.
        if req.deliver_to_context:
            import shutil
            if req.mode == "single":
                dest = CONTEXT_DIR / f"{host}.md"
                if dest.exists() and not req.overwrite:
                    artifact["context_skipped"] = str(dest)
                else:
                    if dest.exists():
                        dest.unlink()
                    shutil.copy2(out, dest)
                    artifact["context_path"] = str(dest)
            else:
                dest = CONTEXT_DIR / host
                if dest.exists() and not req.overwrite:
                    artifact["context_skipped"] = str(dest)
                else:
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(split_dir, dest)
                    artifact["context_path"] = str(dest)

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
    return {"ok": True, "data_dir": str(DATA_DIR),
            "context_dir": str(CONTEXT_DIR), "jobs": len(_jobs)}


@app.get("/context")
def context_list():
    """List everything currently in the context library."""
    entries = []
    for p in sorted(CONTEXT_DIR.iterdir()) if CONTEXT_DIR.exists() else []:
        if p.is_file() and p.suffix == ".md":
            entries.append({"name": p.name, "kind": "single",
                            "size": p.stat().st_size,
                            "mtime": p.stat().st_mtime})
        elif p.is_dir():
            file_count = sum(1 for _ in p.rglob("*.md"))
            total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            entries.append({"name": p.name, "kind": "split",
                            "file_count": file_count, "size": total,
                            "mtime": p.stat().st_mtime})
    return {"context_dir": str(CONTEXT_DIR), "entries": entries}


@app.delete("/context/{name}")
def context_delete(name: str):
    """Remove a single entry from the context library (file or folder)."""
    if "/" in name or name.startswith("."):
        raise HTTPException(400, "invalid name")
    target = (CONTEXT_DIR / name).resolve()
    if not str(target).startswith(str(CONTEXT_DIR.resolve())):
        raise HTTPException(400, "invalid path")
    if not target.exists():
        raise HTTPException(404, "not found")
    import shutil
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"deleted": str(target)}


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
    # path traversal guard
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
