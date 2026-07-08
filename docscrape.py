#!/usr/bin/env python3
"""docscrape CLI — thin wrapper around docscrape_lib."""
from __future__ import annotations
import argparse, sys, urllib.parse as up, zipfile
from pathlib import Path

from docscrape_lib import crawl, render_single, render_split


def progress(done, total, url):
    print(f"[{done+1}/{total}] {url}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="Root docs URL")
    ap.add_argument("-o", "--out", help="Output file (single mode) or dir (split mode)")
    ap.add_argument("--split", action="store_true",
                    help="Write one .md per page into a folder, plus index.md")
    ap.add_argument("--zip", action="store_true",
                    help="With --split, also produce a .zip of the folder")
    ap.add_argument("--max", type=int, default=500)
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--embed-images", action="store_true", default=False,
                    help="Embed images as base64 data URIs (default: off)")
    args = ap.parse_args()

    pages = crawl(args.root, args.max, args.delay, progress=progress,
                  embed_images=args.embed_images)
    if not pages:
        print("No pages scraped.", file=sys.stderr)
        sys.exit(1)

    host = up.urlparse(args.root).netloc.replace(".", "_")

    if args.split:
        out_dir = Path(args.out) if args.out else Path(host)
        out_dir.mkdir(parents=True, exist_ok=True)
        files = render_split(args.root, pages)
        for rel, content in files.items():
            fp = out_dir / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
        print(f"\n✓ Wrote {len(files)} files to {out_dir}/", file=sys.stderr)
        if args.zip:
            zp = out_dir.with_suffix(".zip")
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
                for rel in files:
                    zf.write(out_dir / rel, arcname=f"{out_dir.name}/{rel}")
            print(f"✓ Zipped → {zp}", file=sys.stderr)
    else:
        out = Path(args.out) if args.out else Path(f"{host}.md")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_single(args.root, pages), encoding="utf-8")
        print(f"\n✓ Wrote {out}  ({len(pages)} pages)", file=sys.stderr)


if __name__ == "__main__":
    main()
