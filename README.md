# web-shooter

> Self-hosted documentation scraper. Crawls any docs site and converts it to
> clean Markdown for AI context windows, RAG pipelines, or NotebookLM.

**🌐 Landing page:** https://keeperofstack.github.io/web-shooter/
**📖 Setup:** [`developer/HUMAN_SETUP.md`](developer/HUMAN_SETUP.md) · [`developer/AI_HANDOFF.md`](developer/AI_HANDOFF.md)

---

## Quick start

```bash
git clone https://github.com/KeeperOfStack/web-shooter.git
cd web-shooter
docker compose up -d --build
```

Open http://localhost:8088/ — paste a docs URL, get Markdown back.

Two output modes:

- **Single** — one `.md` file with TOC (great for one LLM context window)
- **Split** — one `.md` per page + `index.md` (great for RAG)

Also available as a CLI: `python docscrape.py <url> [--split] [--zip] -o out`

## Why self-host?

This repo intentionally does **not** ship a public hosted instance. The
scraper makes outbound HTTP requests and writes files — that has to run on
*your* machine, not a free public endpoint where any user could abuse it.
The GitHub Pages landing page above is a static showcase; it does not
proxy crawls.

## Stack

Python 3.12 · FastAPI · BeautifulSoup4 + lxml · markdownify · requests.
~300 LOC of crawler. MIT licensed.

## Repo layout

```
web-shooter/
├── Dockerfile, docker-compose.yml, requirements.txt
├── docscrape.py          # CLI
├── docscrape_lib.py      # crawler + HTML→Markdown
├── server.py             # FastAPI app (jobs, downloads)
├── static/               # zero-build web UI
├── docs/                 # GitHub Pages landing page
└── developer/
    ├── HUMAN_SETUP.md    # rebuild guide for humans
    └── AI_HANDOFF.md     # rebuild guide for AI agents
```
