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

Source resolution (most-canonical first, each step degrading gracefully):
  1. `catalog.json` at the repo root, if present — the forward-looking canonical
     JSON catalog (diffable, PR-able). Preferred so the site can eventually stop
     depending on the binary xlsx entirely.
  2. `norns_scripts_discourse.xlsx` — tolerant of column renames/removals (a
     missing column degrades that field to empty; it never aborts the build).
  3. feed.json names alone — last-resort so the site still renders something.
If NONE is readable, an existing data.json is preserved (last-good), so a
transient source failure can never take the live site down.

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


def _normalize_row(d: dict) -> dict:
    """Coerce any source row dict into the canonical website shape, tolerating
    missing/extra keys. Accepts either our short keys (name/desc/disc/proj/…) or
    the long Excel-style headers (Name/Description/Discussion URL/…)."""
    def pick(*keys):
        for k in keys:
            for variant in (k, k.lower(), k.title()):
                if variant in d and d[variant] not in (None, ""):
                    return _clean(d[variant])
        return ""
    return {
        "name": pick("name", "Name"),
        "author": pick("author", "Author"),
        "desc": pick("desc", "description", "Description"),
        "tags": _split_tags(pick("tags", "Tags")) if not isinstance(d.get("tags"), list) else d["tags"],
        "demo": pick("demo", "Demo"),
        "disc": pick("disc", "discussion url", "Discussion URL"),
        "proj": pick("proj", "project url", "Project URL"),
        "doc": pick("doc", "documentation url", "Documentation URL"),
        "comm": pick("comm", "community url", "Community URL"),
        "upd": pick("upd", "last updated", "Last Updated"),
    }


def load_catalog_json(path: str) -> list[dict]:
    """Load a JSON catalog (forward-looking canonical source). Accepts a bare
    list, {scripts:[...]}, or {entries:[...]}. Each item is normalized."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    rows = data if isinstance(data, list) else (data.get("scripts") or data.get("entries") or [])
    out = [_normalize_row(r) for r in rows if isinstance(r, dict)]
    return [r for r in out if r["name"]]


def load_catalog_xlsx(xlsx_path: str) -> list[dict]:
    """Read the catalog from the xlsx. Tolerant of column renames/removals:
    a missing column degrades that field to empty rather than aborting the build."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    idx = {str(h).strip().lower(): i for i, h in enumerate(header) if h is not None}
    missing = [c for c in COLS.values() if c.lower() not in idx]
    if missing:
        print(f"[build_data] NOTE: xlsx missing columns {missing} — those fields "
              f"will be empty (site still builds)", file=sys.stderr)

    def cell(row, key):
        col = COLS[key].lower()
        i = idx.get(col)
        return _clean(row[i]) if i is not None and i < len(row) else ""

    out: list[dict] = []
    for row in rows:
        name = cell(row, "name")
        if not name:
            continue
        out.append({k: (cell(row, k) if k != "tags" else _split_tags(cell(row, "tags")))
                    for k in COLS})
    wb.close()
    return out


def derive_catalog_from_feed(feed: dict) -> list[dict]:
    """Last-resort catalog when neither a JSON catalog nor the xlsx is readable:
    synthesize names + tags/upd straight from feed.json so the site still renders."""
    out = []
    for key, enr in feed.items():
        out.append(_normalize_row({
            "name": key,
            "tags": enr.get("tags") or [],
            "upd": enr.get("upd", ""),
        }))
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


def load_catalog(json_path: str, xlsx_path: str) -> tuple[list[dict], str]:
    """Resolve the catalog source, most-canonical first, degrading gracefully.
    Returns (rows, source_label). Never raises for data reasons — an empty list
    signals 'no usable source' so build() can preserve the last-good data.json."""
    if json_path and os.path.exists(json_path):
        try:
            rows = load_catalog_json(json_path)
            if rows:
                return rows, f"catalog.json ({len(rows)})"
            print(f"[build_data] NOTE: {json_path} held no rows — trying xlsx", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 — any malformed JSON degrades, never aborts
            print(f"[build_data] WARN: failed reading {json_path}: {e} — trying xlsx", file=sys.stderr)
    if xlsx_path and os.path.exists(xlsx_path):
        try:
            rows = load_catalog_xlsx(xlsx_path)
            if rows:
                return rows, f"xlsx ({len(rows)})"
        except Exception as e:  # noqa: BLE001
            print(f"[build_data] WARN: failed reading {xlsx_path}: {e}", file=sys.stderr)
    return [], "none"


def build(xlsx_path: str, feed_path: str, out_path: str, json_path: str = "") -> int:
    feed, feed_date = load_feed(feed_path)
    catalog, source = load_catalog(json_path, xlsx_path)

    if not catalog and feed:
        catalog = derive_catalog_from_feed(feed)
        source = f"feed-only fallback ({len(catalog)})"
        print(f"[build_data] WARN: no catalog source readable — derived a minimal "
              f"catalog from feed.json ({len(catalog)} scripts)", file=sys.stderr)

    # If we still have nothing, never clobber a previously-good data.json: a
    # transient source failure should leave the live site on its last-good data.
    if not catalog:
        if os.path.exists(out_path):
            print(f"[build_data] ERROR: no usable data source — KEEPING existing "
                  f"{out_path} (last-good)", file=sys.stderr)
            return 0
        print("[build_data] ERROR: no usable data source and no existing data.json", file=sys.stderr)
        return 0  # still exit 0 so the Pages deploy proceeds (serves whatever is staged)

    scripts = merge(catalog, feed)
    scripts.sort(key=lambda s: s["name"].lower())

    generated = feed_date or _dt.date.today().isoformat()
    payload = {
        "generated": generated,
        "source": "norns.community + nornslist enrichment",
        "count": len(scripts),
        "scripts": scripts,
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))

    enriched = sum(1 for s in scripts if "readme" in s)
    withimg = sum(1 for s in scripts if "images" in s)
    withdemo = sum(1 for s in scripts if s["demo"])
    print(
        f"[build_data] wrote {out_path}: {len(scripts)} scripts via {source} "
        f"(generated {generated}; {withdemo} demos, {withimg} images, "
        f"{enriched} readmes)"
    )
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Build docs/data.json for the Pages site")
    ap.add_argument("--xlsx", default=os.path.join(REPO_ROOT, "norns_scripts_discourse.xlsx"))
    ap.add_argument("--feed", default=os.path.join(REPO_ROOT, "feed.json"))
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "docs", "data.json"))
    ap.add_argument("--catalog-json", default=os.path.join(REPO_ROOT, "catalog.json"),
                    help="canonical JSON catalog; preferred over the xlsx when present")
    args = ap.parse_args()
    sys.exit(build(args.xlsx, args.feed, args.out, args.catalog_json))


if __name__ == "__main__":
    main()
