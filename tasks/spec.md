# Spec: `feed.json` generator (nornslist → ingenue B7)

**Date:** 2026-06-04

## Goal
Extend the nightly scrape (`norns_scraper_discourse.py`) to precompute, per script,
`{engine, nb, readme, images, tags, upd}` and write a static `feed.json` that the
`ingenue` on-device web app consumes — offloading heavy enrichment (README text,
images, engine names, nb-voice detection, last-updated) off the norns and onto the
nightly run.

## Consumer contract (from `~/gits/ingenue/web/index.html:1041-1052`)
`feed.json` is an **object**. The script map is `feed.scripts` (or the bare top-level
object). **Keys are `project_name.toLowerCase()`** (must match `community.json`).
Each per-script value carries independently-optional fields:

| field | type | semantics |
|---|---|---|
| `engine` | string | SuperCollider engine **class name the script ships** (e.g. `"PolyPerc"`). Drives engine-deconfliction modal. |
| `nb` | truthy flag | script registers an **nb (note-bridge) voice**; ingenue adds synthetic "additional voice" tag. Only truthiness read. |
| `readme` | string | README as **plain text** (HTML-escaped on display). |
| `images` | string[] | absolute, directly-loadable image URLs (carousel; first = cover). |
| `tags` | string[] | merged into catalog tags, deduped, capped at 8 by consumer. |
| `upd` | string | last-updated date, strictly `YYYY-MM-DD`. |

Missing/partial/malformed feed = graceful fallback in ingenue (try/catch). All
correctness guarantees (lowercase keys, ISO date, loadable URLs) are the scraper's
responsibility.

## Inputs
- The merged per-script rows produced inside `save_to_excel()` (Excel-column dicts:
  `Name`, `Tags`, `Last Updated`, `Project URL`, ...).
- GitHub repo (from `Project URL`) for engine/nb/readme/images.
- A feed-enrichment cache sidecar (for efficiency).

## Outputs
- `feed.json` (default: alongside the xlsx; `--feed-output` to override, e.g. point at
  `../ingenue/web/feed.json`). Envelope: `{file_info:{version,kind:"script_feed"}, date, scripts:{...}}`.
- `*.feed_cache.json` sidecar: per-repo `{engine, nb, readme, images, source_upd, fetched_at}`.

## Field derivation
- `tags` — split the merged `Tags` string. Free.
- `upd` — the merged `Last Updated`. Free.
- `engine` — fetch repo tree; `Engine_<Name>.sc` → `<Name>`. Definitive: matches the
  "registers a SuperCollider engine named X" deconfliction semantics (a shipped engine,
  not one merely *used*).
- `images` — README markdown images + repo screenshot files, relative→
  `raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}`, badges/shields filtered,
  capped 6.
- `readme` — README markdown stripped to ~1200-char plain-text prose prefix.
- `nb` — **best-effort** heuristic (README/tree nb-voice signal). ingenue's live
  `/api/deps` remains authoritative; feed flag is a hint. Conservative to avoid
  polluting the "additional voice" facet with false positives.

## Efficiency (core requirement)
- Per-repo enrichment cached keyed by `owner/repo`, invalidated only when the repo's
  `upd` changed vs `source_upd`, the entry is missing, or it's older than a 30-day TTL.
  → nightly runs re-fetch GitHub **only for repos that actually changed**.
- Only GitHub-hosted `Project URL`s get engine/nb/readme/images; others get tags+upd.
- Parallel fetch via `ThreadPoolExecutor` reusing `self.github_session`; 403/rate-limit
  degrades to empty (same pattern as `_github_latest_non_readme_date`).
- Stdlib only (`base64`, `re`, `json`) — no new dependencies.

## CLI
- default: feed written at end of full nightly run (`save_to_excel`).
- `--no-feed`: skip feed generation.
- `--feed-only`: regenerate `feed.json` from the existing xlsx + cache, no re-scrape.
- `--feed-output PATH`: output location (default `feed.json` next to the xlsx).

## Edge cases
- No GitHub token → enrichment still attempted (lower rate limit), degrades to
  tags+upd on 403. Run never fails because of feed.
- Non-GitHub / missing Project URL → tags+upd only.
- README absent (404) → no readme/images, engine still from tree.
- Empty `images`/`readme`/`engine` → key omitted (consumer guards on truthiness).
- Feed write failure → logged warning, never aborts the run (xlsx already saved).

## Out of scope
- Deploying `feed.json` onto the norns device (ingenue's nightly refresh mechanism).
- Regenerating `enriched.json` (demo/links) — separate file, unchanged.
- Precise nb detection (left to ingenue live deps).

## Acceptance criteria
- [ ] `feed.json` validates: object with `scripts` keyed by lowercase name; every `upd`
      matches `^\d{4}-\d{2}-\d{2}$`; `images` entries are absolute URLs; `engine` a string.
- [ ] Pure helpers (markdown→text, image extraction, engine-from-tree, cache-freshness)
      unit-tested without network.
- [ ] Live smoke test on ≥1 real repo produces a well-formed entry.
- [ ] Second run with unchanged cache makes **zero** GitHub enrichment calls (efficiency).
- [ ] `--no-feed` and `--feed-only` behave as specified; full run still writes the xlsx.
