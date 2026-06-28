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

## Deferred (noted in spec)
- Paginate `list_owner_repos` past 60 to *discover* brand-new old scripts by 1000-repo
  authors (the floor already protects already-known ones).
- Store `richness` in the catalog so a carried repo's rank doesn't dip for one run.

## Deploy note
First nornslist run after merge re-admits the flapped repos (ynth, TW_Norns, …); churn will
log them as re-added/discovered, and the migration message prints once.
