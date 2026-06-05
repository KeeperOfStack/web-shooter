# WEB-SHOOTER — AI Handoff

Everything another AI agent needs to rebuild this project from scratch,
including the choices we made, what we tried, and what we abandoned.
Read this before changing the crawler.

---

## 1. Mission

Take a documentation website (Sphinx / MkDocs / Docusaurus / Read-the-Docs
/ generic) and produce clean Markdown suitable for:

- pasting into a single LLM context window, OR
- ingesting page-by-page into a RAG / notebook LLM.

Non-goals: JS-rendered single-page apps, paywalled content, full-site
mirroring, image archiving.

---

## 2. Architecture in one breath

```
                 ┌──────────────┐    POST /scrape
   browser ──►   │  static/     │  ──────────────►  ┌─────────────────┐
                 │  index.html  │                   │   server.py     │
                 │  app.js      │   GET /jobs/{id}  │  (FastAPI)      │
                 └──────────────┘  ◄─────────────── └────────┬────────┘
                                                            │ threading.Thread
                                                            ▼
                                                   ┌─────────────────┐
                                                   │ docscrape_lib   │
                                                   │  crawl()        │
                                                   │  render_single  │
                                                   │  render_split   │
                                                   └────────┬────────┘
                                                            │ writes
                                                            ▼
                                          DOCSCRAPE_DATA   +   DOCSCRAPE_CONTEXT
                                          (jobs/<id>/...)      (~/context, optional)
```

`docscrape_lib.py` is the only file that knows HTML. `server.py` is
transport + job bookkeeping. `docscrape.py` is the CLI shim. Keep this
seam clean — do not import `requests` or `bs4` in `server.py`.

---

## 3. The crawl algorithm

`crawl(root, max_pages, delay, progress=...)` in `docscrape_lib.py`:

1. **Seed** a BFS queue with the normalized `root` URL.
2. For each URL pop:
   1. Skip if already visited or extension in `SKIP_EXT`.
   2. `requests.get` with `User-Agent: docscrape/1.0` and 20s timeout.
      Discard non-200 / non-HTML responses (we never want PDFs etc.).
   3. Parse with `BeautifulSoup(..., "lxml")`.
   4. Pick a **main content node** by trying `MAIN_SELECTORS` in order
      and accepting the first match with > 100 chars of text. Fall back
      to `<body>`.
   5. **Strip noise** — every selector in `STRIP_SELECTORS` is
      `decompose()`d (nav, footer, edit-this-page, theme chrome).
      Also drop dangling `<a>¶</a>` heading-anchor links.
   6. `markdownify(node)` → Markdown body.
   7. Record `Page(url, title, body)`.
   8. Enqueue every same-scope link found in the soup.
      `same_scope`: same netloc AND url path starts with root path
      segments — this is what stops a crawl of `/docs/` from wandering
      into `/blog/`.
   9. Sleep `delay` seconds.

`render_single` concatenates all pages into one Markdown doc with a
TOC. `render_split` returns `{relative_path: content}` keyed by the
page's URL path, plus an `index.md` table of contents.

---

## 4. The HTTP service

`server.py` — FastAPI. Key contract points:

- Jobs are kicked off via `BackgroundTasks`. Each job spawns a worker
  thread that calls `crawl(...)`, then renders, then writes artifacts
  under `DATA_DIR/<job_id>/`.
- Status is mirrored to `<job_id>/status.json` so a container restart
  re-loads the registry (see `_load_existing_jobs`).
- `deliver_to_context: true` copies the finished artifact into
  `CONTEXT_DIR` for downstream AI tools. Single mode → `<host>.md`.
  Split mode → `<host>/` directory.
- Endpoints documented in the file's top docstring; keep it in sync if
  you add routes.
- Static UI is mounted at `/static`; root `/` serves `static/index.html`.

---

## 5. What we tried and threw away

- **Playwright / headless Chromium for JS-rendered sites.** Worked but
  added ~700 MB to the image and tripled scrape time on plain HTML
  sites. Decided to stay `requests`-only and document the limitation.
  If you re-add it, gate it behind an opt-in flag, not the default.
- **Trafilatura for content extraction.** Gave better text on news
  sites but stripped code blocks and tables from docs sites — exactly
  the things we need to keep. BeautifulSoup + a curated
  `MAIN_SELECTORS` / `STRIP_SELECTORS` pair beat it for docs.
- **html2text** instead of markdownify. html2text mangles fenced code
  blocks and tables. markdownify preserves them.
- **Recursive depth limit** as the stop signal. Replaced with
  `max_pages` because doc sites vary wildly in shape; a page budget is
  more predictable for users.
- **`asyncio` + `httpx` crawl.** Hit politeness/rate-limit problems
  quickly and didn't actually speed us up because the bottleneck is the
  target server. Stuck with threaded blocking `requests` + `delay`.
- **Writing every page to disk during crawl.** Switched to building a
  list in memory then writing once because the split-mode artifact is
  always small (< 50 MB typical) and on-disk during crawl made
  artifact cleanup messy.

---

## 6. Sharp edges (read before changing things)

- **`same_scope` is path-prefix, not domain.** A user passing
  `https://docs.foo.com/v2/` should NOT pull `/v1/` pages. Don't
  loosen this without a flag.
- **Headings get `¶` anchor links from Sphinx.** We strip them in
  `clean()`. If a site uses `#` or `🔗` instead, add to the set in
  `clean()`.
- **`user: "1000:1000"`** in compose. Required so the bind-mounted
  `/context` is writable by the host user. Will break on hosts with a
  different UID — call it out in HUMAN_SETUP.
- **In-memory job registry + disk mirror.** If you add concurrency
  features, hold `_jobs_lock` for any read-modify-write on `_jobs`.
- **Port 8088, not 8080.** The compose file, Dockerfile EXPOSE, and
  uvicorn command all agree on 8088. Don't change one without changing
  all three.
- **No tests.** This project ships without a test suite. If you start
  modifying `docscrape_lib.py` non-trivially, snapshot a small known
  docs site first (e.g. `https://docs.python.org/3/library/json.html`)
  and diff Markdown output before/after your change.

---

## 7. To rebuild from scratch

1. `pip install fastapi uvicorn[standard] pydantic requests beautifulsoup4 markdownify lxml`
2. Write `docscrape_lib.py` with: `Page` dataclass, `crawl()`,
   `render_single()`, `render_split()`. Match the selector lists in
   §3 — they took the most tuning.
3. Write `docscrape.py` — argparse over `crawl` + render, with
   `--split` / `--zip` / `--out`.
4. Write `server.py` — FastAPI, `BackgroundTasks`-driven jobs, a disk
   mirror, `/scrape` `/jobs` `/jobs/{id}/download` `/jobs/{id}/files`
   `/context` `/context/{name}` endpoints. Mount `/static`.
5. Frontend in `static/` — three files, no build step. The aesthetic
   ("1967 Spider-Man cartoon") is a deliberate brand and uses inline
   SVG for the spider so we never depend on an external asset.
6. Containerize. Base: `python:3.12-slim`. Install `libxml2 libxslt1.1
   ca-certificates curl`. Copy code, `pip install -r requirements.txt`,
   `EXPOSE 8088`, `HEALTHCHECK` against `/healthz`,
   `CMD uvicorn server:app --host 0.0.0.0 --port 8088`.
7. Compose: bind-mount the context dir, named volume for jobs, run as
   UID 1000. Image tag `web-shooter:latest`, container name
   `web-shooter`.

---

## 8. Open follow-ups (not done, candidate work)

- Optional Playwright backend gated by `?render=js` on `/scrape`.
- Per-job log file streamed via Server-Sent Events on
  `/jobs/{id}/events`.
- `robots.txt` honoring (currently we ignore it — fine for our use
  cases, not okay for a public service).
- Auth on the API — currently anyone on the LAN can scrape.
- Dedup near-identical pages (Sphinx generates `genindex` etc. that
  could be skipped by URL pattern).
