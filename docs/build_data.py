#!/usr/bin/env python3
"""Build docs/data.json — the self-contained data product for the nornslist
GitHub Pages site (https://seajaysec.github.io/nornslist/).

The site is a static snapshot of the *latest scrape*. This script merges the two
artifacts the nightly scrape already commits:

  * norns_scripts_discourse.xlsx  — the full per-script catalog rows
        (Name, Author, Tags, Description, Demo, Discussion/Project/Doc/Community
         URLs, Last Updated). This is the parity layer with norns.community.
  * feed.json                     — the enrichment layer emitted for ingenue (B7):
        readme plaintext, screenshot image URLs, SuperCollider engine class, and
        the nb (note-bridge) voice flag, keyed by project_name.lower().

It writes one self-contained `docs/data.json` so the page has zero runtime
dependency on any external service — it simply renders the latest committed run.

Deliberately standalone (does NOT import the 205 KB scraper) so the Pages build
stays fast and the feed.json contract consumed by ingenue is never perturbed.
Stdlib + openpyxl only (openpyxl is already in requirements.txt).

Usage:
    python docs/build_data.py
    python docs/build_data.py --xlsx norns_scripts_discourse.xlsx \
                              --feed feed.json --out docs/data.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

import openpyxl

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Excel column header -> output field. Headers are matched case-insensitively
# against the first row so a column reorder in the scraper doesn't break us.
COLS = {
    "name": "Name",
    "author": "Author",
    "tags": "Tags",
    "desc": "Description",
    "demo": "Demo",
    "disc": "Discussion URL",
    "proj": "Project URL",
    "doc": "Documentation URL",
    "comm": "Community URL",
    "upd": "Last Updated",
}


def _clean(value) -> str:
    """Normalize a cell value to a trimmed string, treating None/'None' as empty."""
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() == "none" else s


def _split_tags(raw: str) -> list[str]:
    seen: dict[str, None] = {}  # preserve order, dedupe case-insensitively
    for part in raw.split(","):
        t = part.strip()
        if t and t.lower() not in {k.lower() for k in seen}:
            seen[t] = None
    return list(seen)


def load_feed(feed_path: str) -> tuple[dict, str]:
    """Return (scripts_by_lowercase_name, feed_date)."""
    if not os.path.exists(feed_path):
        print(f"[build_data] WARN: {feed_path} missing — no enrichment", file=sys.stderr)
        return {}, ""
    with open(feed_path, encoding="utf-8") as fh:
        feed = json.load(fh)
    scripts = feed.get("scripts", feed if isinstance(feed, dict) else {})
    return scripts, str(feed.get("date", ""))


def load_catalog(xlsx_path: str) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    # case-insensitive header -> index
    idx = {str(h).strip().lower(): i for i, h in enumerate(header) if h is not None}
    missing = [c for c in COLS.values() if c.lower() not in idx]
    if missing:
        raise SystemExit(f"[build_data] xlsx missing expected columns: {missing}")

    out: list[dict] = []
    for row in rows:
        get = lambda key: _clean(row[idx[COLS[key].lower()]])  # noqa: E731
        name = get("name")
        if not name:
            continue
        out.append({
            "name": name,
            "author": get("author"),
            "desc": get("desc"),
            "tags": _split_tags(get("tags")),
            "demo": get("demo"),
            "disc": get("disc"),
            "proj": get("proj"),
            "doc": get("doc"),
            "comm": get("comm"),
            "upd": get("upd"),
        })
    wb.close()
    return out


def merge(catalog: list[dict], feed: dict) -> list[dict]:
    """Fold feed enrichment into each catalog row; derive filter facets."""
    for s in catalog:
        enr = feed.get(s["name"].lower(), {})

        engine = _clean(enr.get("engine"))
        readme = enr.get("readme") or ""
        images = [u for u in (enr.get("images") or []) if isinstance(u, str) and u.strip()]
        nb = bool(enr.get("nb"))

        # Merge feed tags into catalog tags (catalog order wins, deduped).
        feed_tags = enr.get("tags") or []
        if feed_tags:
            existing = {t.lower() for t in s["tags"]}
            for t in feed_tags:
                if isinstance(t, str) and t.strip() and t.lower() not in existing:
                    s["tags"].append(t.strip())
                    existing.add(t.lower())

        if engine:
            s["engine"] = engine
        if nb:
            s["nb"] = True
        if readme:
            s["readme"] = readme
        if images:
            s["images"] = images

        # Boolean facets the UI filters on (kept out of `tags` to avoid clutter).
        s["facets"] = {
            "engine": bool(engine),
            "nb": nb,
            "demo": bool(s["demo"]),
            "images": bool(images),
            "readme": bool(readme),
            "doc": bool(s["doc"]),
        }
    return catalog


def build(xlsx_path: str, feed_path: str, out_path: str) -> None:
    feed, feed_date = load_feed(feed_path)
    catalog = load_catalog(xlsx_path)
    scripts = merge(catalog, feed)
    scripts.sort(key=lambda s: s["name"].lower())

    generated = feed_date or _dt.date.today().isoformat()
    payload = {
        "generated": generated,
        "source": "norns.community + nornslist enrichment",
        "count": len(scripts),
        "scripts": scripts,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))

    enriched = sum(1 for s in scripts if "readme" in s)
    withimg = sum(1 for s in scripts if "images" in s)
    withdemo = sum(1 for s in scripts if s["demo"])
    print(
        f"[build_data] wrote {out_path}: {len(scripts)} scripts "
        f"(generated {generated}; {withdemo} demos, {withimg} images, "
        f"{enriched} readmes)"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build docs/data.json for the Pages site")
    ap.add_argument("--xlsx", default=os.path.join(REPO_ROOT, "norns_scripts_discourse.xlsx"))
    ap.add_argument("--feed", default=os.path.join(REPO_ROOT, "feed.json"))
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "docs", "data.json"))
    args = ap.parse_args()
    build(args.xlsx, args.feed, args.out)


if __name__ == "__main__":
    main()
