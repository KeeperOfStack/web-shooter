"""
docscrape_lib — crawl logic extracted from docscrape.py so it can be reused
by both the CLI and the HTTP service.

crawl(root, max_pages, delay) -> list[Page]
render_single(root, pages) -> str   (one big markdown doc)
render_split(root, pages) -> dict[str, str]   (filename -> content for a folder)
"""
from __future__ import annotations
import base64, re, sys, time, urllib.parse as up
from collections import deque
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

UA = "docscrape/1.0 (+local AI reference builder)"
TIMEOUT = 20

MAIN_SELECTORS = [
    "div[role=main]", "main", "article",
    "div.md-content", "div.document", "div.rst-content",
    "div.theme-doc-markdown", "div#main-content", "div.content", "div.body",
]

STRIP_SELECTORS = [
    "nav", "header", "footer", "aside",
    ".headerlink", ".edit-this-page", ".prev-next-area",
    ".md-sidebar", ".md-header", ".md-footer", ".md-source",
    ".wy-nav-side", ".wy-nav-top", ".rst-versions",
    ".theme-doc-toc-mobile", ".theme-doc-footer",
    "script", "style", "noscript", "form",
]

SKIP_EXT = {".png",".jpg",".jpeg",".gif",".svg",".ico",".pdf",".zip",".gz",".tar",
            ".mp4",".webm",".mp3",".woff",".woff2",".ttf",".css",".js"}

# MediaWiki query params that lead to login-walled junk (edit/history/etc.)
SKIP_ACTIONS = {"edit", "history", "raw", "submit", "preview"}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".gif": "image/gif", ".webp": "image/webp"}


@dataclass
class Page:
    url: str
    title: str
    body: str


def norm(url: str) -> str:
    u = up.urldefrag(url)[0]
    return u.rstrip("/") or u


def same_scope(url: str, root: str) -> bool:
    a, b = up.urlparse(url), up.urlparse(root)
    if a.netloc != b.netloc:
        return False
    root_parts = [s for s in b.path.split("/") if s]
    url_parts = [s for s in a.path.split("/") if s]
    if not root_parts:
        return True
    return url_parts[:len(root_parts)] == root_parts


def fetch(url: str):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        if "html" not in r.headers.get("content-type", "").lower():
            return None
        return (r.url, r.text)
    except Exception as e:
        print(f"  ! fetch failed: {e}", file=sys.stderr)
        return None


def extract_main(soup):
    for sel in MAIN_SELECTORS:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 100:
            return el
    return soup.body


def clean(node):
    for sel in STRIP_SELECTORS:
        for el in node.select(sel):
            el.decompose()
    for a in node.find_all("a"):
        t = a.get_text(strip=True)
        if t in {"¶", "#", ""} and not a.find("img"):
            if a.parent and len(a.parent.get_text(strip=True)) > 3:
                a.decompose()


def page_title(soup, fallback):
    h1 = soup.find("h1")
    if h1:
        return re.sub(r"\s+", " ", h1.get_text(" ", strip=True)).strip(" ¶#")
    if soup.title:
        return soup.title.get_text(strip=True)
    return fallback


def links_from(soup, base):
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "javascript:", "#")):
            continue
        absu = up.urljoin(base, href)
        parsed = up.urlparse(absu)
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in SKIP_EXT):
            continue
        # Skip MediaWiki action URLs (edit, history, etc.) — they're login-walled junk
        qs_params = up.parse_qs(parsed.query, keep_blank_values=False)
        action = qs_params.get("action", [""])[0].lower()
        if action in SKIP_ACTIONS:
            continue
        out.append(norm(absu))
    return out


def fetch_image_as_data_uri(url: str, base_url: str) -> str | None:
    """Fetch an image and return a data URI string, or None on failure."""
    try:
        abs_url = up.urljoin(base_url, url)
        ext = up.urlparse(abs_url).path.lower()
        ext = re.search(r'\.[a-z0-9]+$', ext)
        if not ext:
            return None
        ext = ext.group(0)
        if ext not in IMAGE_EXTS:
            return None
        r = requests.get(abs_url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        mime = IMAGE_MIME.get(ext, r.headers.get("content-type", "image/png").split(";")[0])
        b64 = base64.b64encode(r.content).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        print(f"  ! image fetch failed ({url}): {e}", file=sys.stderr)
        return None


def crawl(root: str, max_pages: int = 200, delay: float = 0.2,
          progress=None) -> list[Page]:
    """progress: optional callable(done:int, total_target:int, url:str)."""
    root = norm(root)
    seen: set[str] = set()
    queue: deque[str] = deque([root])
    pages: list[Page] = []

    while queue and len(pages) < max_pages:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)

        if progress:
            progress(len(pages), max_pages, url)

        fetched = fetch(url)
        if not fetched:
            continue
        final_url, html = fetched
        soup = BeautifulSoup(html, "lxml")

        for link in links_from(soup, final_url):
            if link not in seen and same_scope(link, root):
                queue.append(link)

        main = extract_main(soup)
        if not main:
            continue
        clean(main)
        # Embed images as base64 data URIs so the markdown is self-contained
        for img in main.find_all("img"):
            src = img.get("src", "")
            if src and not src.startswith("data:"):
                data_uri = fetch_image_as_data_uri(src, final_url)
                if data_uri:
                    img["src"] = data_uri
                else:
                    # If we can't fetch it, remove the img tag so markdownify
                    # doesn't emit a broken relative path reference
                    img.decompose()
        title = page_title(soup, url)
        body = md(str(main), heading_style="ATX", strip=["script","style"]).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        if len(body) < 30:
            continue
        pages.append(Page(url=url, title=title, body=body))
        time.sleep(delay)

    return pages


# ----------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------

def _safe_slug(url: str, root: str) -> str:
    """Turn a URL into a safe relative path for a split-output file."""
    pu, ru = up.urlparse(url), up.urlparse(root)
    path = pu.path
    # strip the root's path prefix so files sit relative to the doc root
    root_path = ru.path
    if root_path and path.startswith(root_path):
        path = path[len(root_path):]
    path = path.strip("/")
    if not path:
        path = "index"
    # drop file extensions like .html/.php so we can add .md
    path = re.sub(r"\.(html?|php|aspx?)$", "", path, flags=re.I)
    # For query-param-based wikis (e.g. MediaWiki ?title=Page_Name), the path
    # alone (e.g. "index") is the same for every page.  Append the query params
    # so each page gets a unique, meaningful slug.
    qs = pu.query
    if qs:
        # Use the 'title' param if present, otherwise the full query string
        qs_params = up.parse_qs(qs, keep_blank_values=False)
        if "title" in qs_params:
            qs_part = qs_params["title"][0]
        else:
            qs_part = qs
        qs_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", qs_part).strip("-")
        if qs_slug and qs_slug.lower() != path.lower():
            path = path + "/" + qs_slug
    # sanitize each segment
    parts = [re.sub(r"[^A-Za-z0-9._-]+", "-", p).strip("-") or "_" for p in path.split("/")]
    return "/".join(parts) + ".md"


def render_single(root: str, pages: list[Page]) -> str:
    host = up.urlparse(root).netloc
    out = [
        f"# Documentation: {host}\n",
        f"Source: {root}  ",
        f"Pages: {len(pages)}  ",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "---\n",
        "## Table of Contents\n",
    ]
    for i, p in enumerate(pages, 1):
        out.append(f"{i}. [{p.title}](#page-{i}) — `{p.url}`")
    out.append("\n---\n")
    for i, p in enumerate(pages, 1):
        out.append(f"\n<a id=\"page-{i}\"></a>")
        out.append(f"## {i}. {p.title}\n")
        out.append(f"**Source:** {p.url}\n")
        out.append(p.body)
        out.append("\n\n---\n")
    return "\n".join(out)


def render_split(root: str, pages: list[Page]) -> dict[str, str]:
    """Return {relative_path: content}. Includes an index.md TOC and one .md per page."""
    host = up.urlparse(root).netloc
    files: dict[str, str] = {}
    used: dict[str, int] = {}
    entries = []

    for p in pages:
        slug = _safe_slug(p.url, root)
        # reserve index.md for the TOC — rename a page that lands there
        if slug == "index.md":
            slug = "_root.md"
        # de-dupe collisions
        if slug in files:
            used[slug] = used.get(slug, 1) + 1
            stem, _, ext = slug.rpartition(".")
            slug = f"{stem}-{used[slug]}.{ext}"
        header = f"# {p.title}\n\n**Source:** {p.url}\n\n---\n\n"
        files[slug] = header + p.body + "\n"
        entries.append((slug, p))

    idx = [
        f"# Documentation: {host}\n",
        f"Source: {root}  ",
        f"Pages: {len(pages)}  ",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "---\n",
        "## Pages\n",
    ]
    for slug, p in entries:
        idx.append(f"- [{p.title}](./{slug}) — `{p.url}`")
    files["index.md"] = "\n".join(idx) + "\n"
    return files
