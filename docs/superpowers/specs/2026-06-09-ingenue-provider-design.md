# nornslist as ingenue's data provider — 3 phases

**Goal:** offload ingenue's two slow areas (per-installed-script update checks, GitHub
discovery search) onto nornslist's nightly scrape, and broaden the catalog with
forum-surfaced, demo-enriched discoveries. All three phases extend the existing
scraper (`norns_scraper_discourse.py`) and the `feed.json` / `catalog.json` contracts.

Build order ①→②→③, each independently shippable.

---

## Phase ① — Per-repo commit SHA + date (update detection)

ingenue compares an installed script's commit against nornslist's feed and knows
instantly if an update exists — no per-script GitHub call.

- Persist default-branch HEAD `sha` (full 40-char) in `*.lastupd_cache.json` alongside
  the `last_updated` / `pushed_at` already cached. SHA changes only when `pushed_at`
  changes — the existing commits-refetch trigger — so steady-state cost is **zero extra
  calls**.
- **One-time backfill:** unchanged repos with no cached SHA → fetch once
  (`GET /repos/{o}/{r}/commits/{default_branch}`, ~1158 calls first run, free after).
- Emit `sha` into `feed.json` per script; bump `file_info.version` 1→2. Keep `upd` (date)
  for display. ingenue must treat a missing `sha` gracefully.
- **Scope:** all repos (community + discovered).
- **Site:** no change (ingenue-feed-only).

## Phase ② — Aggressive daily discovery + A/V enrichment

- Wire `--discover` (aggressive) into the 2:30am nightly
  (`.github/workflows/daily-scrape-discourse.yml`).
- **Token:** scraper prefers `GH_PAT` (the user's 5000/hr key, now set as a repo secret),
  falls back to the Actions `GITHUB_TOKEN` if absent. Nothing breaks without it; discovery
  just runs slower.
- **Author-sweep cap:** default `--discover-max-authors` ≈ 100 to keep a run inside ~one
  rate-limit hour; tunable. (Aggressive daily is a heavier CI job — accepted.)
- **A/V from README** — new `_extract_readme_media()`: pull YouTube / Vimeo / SoundCloud /
  Bandcamp / Instagram links (matching the site's `demoEmbed` support), video>audio
  precedence (per the demo-preference policy). Lands in the repo's `Demo` field.
- **Linked-thread demo:** if a discovered repo's README links a lines thread, run the
  existing `discover_demo_via_discourse_api` on it for a richer demo.
- **Feeds:** discovered repos gain `demo` in `feed.json` + `catalog.json`.

## Phase ③ — Forum-driven discovery (repo-linked threads only)

- Search Discourse's `norns` tag (`/tag/norns.json`, paginated) for recent topics.
- For each topic: extract a GitHub repo URL from the OP. If that repo isn't already in the
  catalog, classify it (`_classify_norns_repo`); if norns, add it **with** its discussion
  URL + a demo mined from the thread.
- Dedup by `owner/repo` against the catalog (reuses the resolution cache).
- **Representation:** no new entity type — merges into the `source:"github"` discovered
  pool, enriched with discussion link + demo. Add a lightweight `lines` tag/facet so
  forum-surfaced repos are filterable.

## Cross-cutting contract

- `feed.json`: `+sha` per script (version→2); discovered repos `+demo`.
- `catalog.json`: discovered rows gain `Demo` + `Discussion URL` (existing columns).
- `docs/` site: auto-benefits (already renders demo / disc / source chip for any source);
  only optional add is surfacing the `lines` facet.
- **Manual (done):** `GH_PAT` Actions secret created.

## Verification

- ①: diff a known repo's feed `sha` vs `git ls-remote`.
- ②: `--discover` dry-run — discovered repos gain demos; run stays in budget.
- ③: a recent norns-tagged thread's repo lands with its discussion URL + demo.

## Non-goals

No code-less WIP threads as entities (repo-linked only). No new `source` value. ① stays
ingenue-feed-only (no "update available" UI on the public site).
