# Task: feed.json generator (ingenue B7)

See `tasks/spec.md` for the contract. Status: **DONE & verified.**

## Completed
- [x] `feed.json` generator on `NornsScraper` (`norns_scraper_discourse.py`):
      engine / nb / readme / images / tags / upd, consumer-keyed by lowercase name.
- [x] Per-repo enrichment cache (`*.feed_cache.json`), invalidated on repo change,
      30-day TTL, transient-failure retry, and `FEED_LOGIC_VERSION` stamp.
- [x] Hooked into `save_to_excel` (runs on full nightly run; `--no-feed` to skip).
- [x] CLI: `--no-feed`, `--feed-only`, `--feed-output`.
- [x] Stdlib only — no new dependencies.
- [x] Offline unit tests (`tasks/test_feed.py`, 38 checks) — all pass.
- [x] Live smoke test (engine=oooooo→SimpleDelay, nb=sixolet/nb→True, 404 graceful).
- [x] Full real run: 344 scripts → 117 engine / 15 nb / 315 readme / 194 images.
      0 contract violations. Warm second run = 0 GitHub calls.
- [x] README + .gitignore documented.

## Verification commands
```bash
~/.virtualenvs/nornslist-ddno/bin/python tasks/test_feed.py          # offline helpers
~/.virtualenvs/nornslist-ddno/bin/python norns_scraper_discourse.py --feed-only  # real feed
```

## Deferred / not done (by design)
- Deploying feed.json onto the device / into the ingenue repo — left to the user
  (`--feed-output ../ingenue/web/feed.json` writes it in place when wanted).
- Sharing the `GET /repos/{owner}/{repo}` call between Last-Updated and feed
  enrichment (minor optimization; cache already makes feed cheap).
- Precise nb detection (intentionally best-effort; ingenue `/api/deps` is authoritative).
