# WEB-SHOOTER — Human Setup Guide

Build the documentation-scraper service from scratch.

---

## 1. What it is

WEB-SHOOTER is a small FastAPI service that crawls a documentation website
and converts it into clean Markdown — either one big `.md` file (good for a
single AI context window) or a folder of one `.md` per page (good for
chunked retrieval / notebook-style LLMs).

Two front doors:

- **HTTP / web UI** — open a browser at the container port, paste a docs
  root URL, pick "single" or "split", click download.
- **CLI** — `python docscrape.py <url> [--split] [--zip] -o out`

The service is **stateless w.r.t. your host filesystem** — it only writes
to its own job-artifacts volume. Nothing touches `~/` on the host.

Stack: Python 3.12, FastAPI + Uvicorn, BeautifulSoup4 + lxml,
markdownify, requests. Frontend is plain HTML/CSS/JS (no build step).

---

## 2. Prerequisites

- Linux/macOS/WSL
- Docker + Docker Compose v2 *(recommended)*, OR Python 3.12 with venv
- Optional: a host folder you want to use as a shared AI context library
  (defaults to `~/context`)

---

## 3. Get the code

```bash
git clone https://github.com/KeeperOfStack/web-shooter.git
cd web-shooter
```

---

## 4. Run it (Docker — the supported path)

```bash
docker compose up -d --build
```

This:

- builds the image as `web-shooter:latest`
- starts the container `web-shooter`
- publishes the API on **host port 8088** → container port 8088
- creates a named volume `web-shooter-jobs` for persistent job artifacts

No host bind-mounts. The container is fully self-contained.

Verify:

```bash
curl http://localhost:8088/healthz   # → {"ok": true}
xdg-open http://localhost:8088/      # open the UI
```

Stop / restart:

```bash
docker compose down
docker compose up -d
```

---

## 5. Run it (bare metal, no Docker)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# web UI on http://localhost:8088
uvicorn server:app --host 0.0.0.0 --port 8088

# or one-shot CLI
python docscrape.py https://docs.example.com/ -o example.md
python docscrape.py https://docs.example.com/ --split --zip -o example_docs
```

Environment variables:

| var                       | default                          | meaning                                              |
|---------------------------|----------------------------------|------------------------------------------------------|
| `DOCSCRAPE_DATA`          | `~/.local/share/docscrape/jobs`  | where job artifacts live                             |
| `DOCSCRAPE_CORS_ORIGINS`  | `*`                              | comma-separated allowed CORS origins (tighten for prod) |

---

## 6. Using the web UI

1. Paste a documentation root URL (e.g. `https://docs.python.org/3/`).
2. Set **MAX PAGES** (default 200, hard cap 2000) and **DELAY** seconds
   between requests (default 0.2 — be polite).
3. Pick one of two web-shots:
   - **① SINGLE → DOWNLOAD .MD** — get one `.md` file back
   - **② SPLIT → DOWNLOAD .ZIP** — get a `.zip` of a per-page folder
4. Click **GO**. Progress bar polls `/jobs/{id}` until done.

---

## 7. HTTP API (for scripting)

```bash
# kick off a job
curl -s -X POST http://localhost:8088/scrape \
  -H 'content-type: application/json' \
  -d '{"url":"https://docs.example.com/","max":300,"delay":0.2,"mode":"single"}'
# → {"job_id":"..."}

# poll
curl -s http://localhost:8088/jobs/<job_id>

# download
curl -OJ http://localhost:8088/jobs/<job_id>/download
```

Full endpoint list is in the docstring at the top of `server.py`.

---

## 8. Repo layout

```
web-shooter/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── docscrape.py         # CLI entry point
├── docscrape_lib.py     # crawl + render (HTML → markdown) — the engine
├── server.py            # FastAPI app: jobs, downloads, context library
├── static/              # zero-build web UI (HTML + CSS + JS)
│   ├── index.html
│   ├── app.js
│   └── style.css
└── developer/
    ├── HUMAN_SETUP.md   # this file
    └── AI_HANDOFF.md    # rebuild-from-scratch notes for another AI
```

---

## 9. Common problems

- **Empty / tiny output** — the site is JS-rendered. `requests` only
  fetches server-side HTML. Workaround: scrape a docs mirror, or extend
  `fetch()` in `docscrape_lib.py` to use Playwright. Not done yet.
- **403 / blocked** — some sites block default UAs. Edit `UA` in
  `docscrape_lib.py`.
- **Garbage in output** — the site uses a layout `MAIN_SELECTORS` / 
  `STRIP_SELECTORS` doesn't know about. Add the right CSS selector to
  the lists at the top of `docscrape_lib.py`.
- **CORS errors when calling the API from a different origin** — set
  `DOCSCRAPE_CORS_ORIGINS=https://your.site` in the compose env.
