# todo: catalog recall floor + tests

Branch: `fix/catalog-recall-floor` (nornslist) + `fix/churn-owner-name-keys` (nornslist-churn)

## Done
- [x] **E** collection facet — `facets_from_paths` labels 8+ top-lua repos `collection`
      (was dropped wholesale); added to `USABLE_FACETS`. `COLLECTION_MIN = 8`.
- [x] **C** dedup by `(owner, name)` — extracted `dedup_installable()`; two same-named repos
      under different owners both kept (was: bare-name collapse dropped the loser).
- [x] **A** floor — `prior_records()` re-feeds every cataloged repo into classify each run;
      `discover()` unions it into `cand`. A repo drops only on 404 or genuine gate-fail.
- [x] **B** carry-forward — `classify_batch(prior=...)` reuses the prior verdict when a repo
      exists but its corpus blob is empty (transient). `_fetch_meta()` split-retry so a flaky
      chunk can't 404-drop 18 repos.
- [x] **D** tests — `tests/test_classifier.py` (recall fixtures + precision + facets),
      `tests/test_floor.py` (floor/carry/404 + dedup + parse). 31 pass. CI runs pytest first.
- [x] churn: key ledger by `owner/name` (`_repo_key`, `_migrate_keys`) so C can't create
      phantom drops. 14 churn tests pass (incl. 3 new). Dry-run migration: 1194/1194 overlap,
      0 phantom adds.

## Verified
- `pytest tests/` (nornslist) → 31 passed.
- `tests/test_churn.py` → 14 passed; `tests/test_leaderboard.py` → 4 passed.
- Live: floor re-confirms `schollz/ynth`; a 404 repo is dropped; `TW_Norns` → `collection`.
- Live migration dry-run: bare-name roster → owner/name maps cleanly onto the catalog.

## Measured on a full run (rule F applied)
- OLD 1194 -> FINAL 1277 (net +83): 90 added, 7 dropped.
- adds = 83 new independent scripts (full pagination) + 7 renamed divergent forks.
- 164 same-name personal forks filtered as noise (rule F).
- 18 collections restored (TW_Norns, monome/crow-studies, schollz/gatherum, …).
- caveat: first scratch run had empty prior (--out to a fresh file) so the floor/carry
  were untested; re-running with real prior to confirm the ~1 flake-drop (quintessence)
  is protected. Drops should settle to the 6 fork->original swaps.

## Not deferred (done)
- F same-name fork filter; G full sweep pagination; churn owner/name keying.

## Still open
- Store `richness` in the catalog so a carried repo's rank doesn't dip for one run (minor).

## Deploy note
First nornslist run after merge re-admits the flapped repos (ynth, TW_Norns, …); churn will
log them as re-added/discovered, and the migration message prints once.
