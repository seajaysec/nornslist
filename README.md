# nornslist

A lean Python tool that discovers **monome norns** scripts from **public GitHub** and
emits a single `catalog.json` feed. Headless — no website.

## Feed URL

`catalog.json` is committed to `main` on every run and also published as a release asset.

**For browser-based consumers** (fetch from a web page — requires CORS):
```
https://raw.githubusercontent.com/seajaysec/nornslist/main/catalog.json
```

**For CLI / non-browser consumers** (curl, wget, scripts):
```
https://github.com/seajaysec/nornslist/releases/latest/download/catalog.json
```

The release asset URL does not send CORS headers and cannot be loaded by browser
`fetch()`. Use the raw URL when adding this as a feed to a norns browser app.

## Discovery

1. **Find** — union of: keyword/topic search, **code search** for norns runtime markers
   in `.lua` (`softcut.` / `engine.` / `params:add` / `function redraw|enc|key`), a
   per-author sweep, and an **author network** (followers/following of known norns
   authors). The code search + network surface untagged, off-the-beaten-path scripts
   that name/topic search never sees.
2. **Classify** — each candidate is gated on the norns runtime fingerprint via **batched
   GraphQL** (file tree + corpus text, many repos per request); no per-repo REST calls.
3. **Rank (hidden-gem)** — `norns-richness + recency + log(stars) + author-cluster`,
   weighted so obscure-but-real scripts surface instead of only the popular ones.
4. **Emit** `catalog.json`. README text and screenshots are **not** stored — consumers
   fetch them live from GitHub.

## Run

```bash
pip install -r requirements.txt
GH_PAT=<public-scope token> python norns_ingest.py --out catalog.json

# debug: classify specific repos and print the verdicts
python norns_ingest.py --classify owner/repo owner/other-repo
```

A **public-scope** token is all that's needed.

## Nightly

`.github/workflows/daily-catalog-refresh.yml` runs discovery once a day, commits
`catalog.json`, and updates the `latest` release asset (the feed URL above).
