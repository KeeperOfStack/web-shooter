<div align="center">

# 🕷️ WEB-SHOOTER

**Turn any documentation site into clean Markdown for AI context windows, RAG, or NotebookLM.**

[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Container](https://img.shields.io/badge/ghcr.io-web--shooter-c8102e?logo=docker&logoColor=white)](https://github.com/KeeperOfStack/web-shooter/pkgs/container/web-shooter)
[![Built with FastAPI](https://img.shields.io/badge/built%20with-FastAPI-1d3fb8?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python 3.12](https://img.shields.io/badge/python-3.12-1d3fb8?logo=python&logoColor=white)](https://www.python.org)

*A web you actually want to crawl into.*

</div>

---

## ⚡ One-line deploy (no clone needed)

```bash
curl -fsSL https://raw.githubusercontent.com/KeeperOfStack/web-shooter/main/docker-compose.ghcr.yml \
  -o web-shooter.yml && docker compose -f web-shooter.yml up -d
```

Then open **http://localhost:8088/**.

The image is published on the GitHub Container Registry:

> **`ghcr.io/keeperofstack/web-shooter:latest`**

`linux/amd64` and `linux/arm64`. Anyone can `docker pull` it — no auth, no login.

---

## 🎯 What it does

Paste a documentation root URL (Sphinx, MkDocs, Docusaurus, Read-the-Docs, generic HTML) and pick a web-shot:

| # | Mode                      | Output                                    | Best for                          |
|---|---------------------------|-------------------------------------------|-----------------------------------|
| ① | **Single → Download**     | one `.md` with TOC                        | one LLM context window            |
| ② | **Single → `~/context`**  | one `.md` dropped on the host             | your local AI context library     |
| ③ | **Split → Download .zip** | one `.md` per page + `index.md`           | RAG / per-topic retrieval         |
| ④ | **Split → `~/context`**   | a folder dropped on the host              | NotebookLM, Hermes, Obsidian      |

Three front doors: **Web UI** · **HTTP / JSON API** · **CLI**.

---

## 🐳 Deploy options

### Option A — Pull the published image (recommended for users)

`docker-compose.ghcr.yml` is hosted right in the repo. Either grab just that file:

```bash
curl -fsSL https://raw.githubusercontent.com/KeeperOfStack/web-shooter/main/docker-compose.ghcr.yml -o web-shooter.yml
docker compose -f web-shooter.yml up -d
```

…or pull and run by hand:

```bash
docker run -d --name web-shooter \
  -p 8088:8088 \
  -v ~/context:/context \
  -v web-shooter-jobs:/data/jobs \
  --restart unless-stopped \
  ghcr.io/keeperofstack/web-shooter:latest
```

Pick your own host directory for the context library:

```bash
CONTEXT_DIR=/srv/ai-context docker compose -f web-shooter.yml up -d
```

### Option B — Build locally (for development)

```bash
git clone https://github.com/KeeperOfStack/web-shooter.git
cd web-shooter
docker compose up -d --build
```

### Option C — Bare metal (no Docker)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8088
```

---

## 🖥️ Web UI

Open `http://localhost:8088/`. Paste a docs root URL, pick one of the four web-shots, click **SHOOT WEB!**. Progress bar streams live. Context library entries can be browsed and removed straight from the UI.

---

## 🤖 HTTP API

```bash
# kick off a job
curl -s -X POST http://localhost:8088/scrape \
  -H 'content-type: application/json' \
  -d '{"url":"https://docs.python.org/3/","max":300,"mode":"single","deliver_to_context":true}'
# → {"job_id":"abc123..."}

# poll
curl -s http://localhost:8088/jobs/abc123...

# download (only if deliver_to_context was false)
curl -OJ http://localhost:8088/jobs/abc123.../download

# inspect / clean the context library
curl -s http://localhost:8088/context
curl -X DELETE http://localhost:8088/context/docs_python_org
```

Full OpenAPI at **http://localhost:8088/docs** on any running instance.

---

## 🧪 CLI

```bash
# one big .md
python docscrape.py https://docs.example.com/ -o example.md

# one file per page, plus a .zip
python docscrape.py https://docs.example.com/ --split --zip -o example_docs
```

---

## ⚙️ Configuration

| env var                   | default                            | meaning                              |
|---------------------------|------------------------------------|--------------------------------------|
| `DOCSCRAPE_DATA`          | `/data/jobs` (container)           | persistent job artifacts             |
| `DOCSCRAPE_CONTEXT`       | `/context` (container) / `~/context` (host) | "deliver to context" target dir |

Crawl politeness:

- Default 0.2 s delay between requests (`delay` in the request body — be polite)
- Hard cap of 2000 pages per job (`max`)
- Same-path-scope only — a crawl of `/docs/` won't wander into `/blog/`

---

## 📁 Repo layout

```
web-shooter/
├── Dockerfile
├── docker-compose.yml          # local build (development)
├── docker-compose.ghcr.yml     # pull prebuilt image (deploy)
├── requirements.txt
├── docscrape.py                # CLI
├── docscrape_lib.py            # crawler + HTML→Markdown
├── server.py                   # FastAPI service
├── static/                     # zero-build web UI
├── developer/
│   ├── HUMAN_SETUP.md          # build-from-scratch guide for humans
│   └── AI_HANDOFF.md           # build-from-scratch guide for AI agents
└── .github/workflows/publish.yml  # builds + pushes to ghcr.io on every push to main
```

---

## 🛠️ Stack

Python 3.12 · FastAPI · BeautifulSoup4 + lxml · markdownify · requests.
About 300 lines of crawler code. MIT licensed.

---

<div align="center">

**Be a good citizen.** Respect `robots.txt`, throttle your crawls, and don't redistribute scraped content beyond what its license allows.

🕸️ *with great scraping comes great responsibility* 🕸️

</div>
