# Spec: catalog recall floor + classifier tests

## Goal
Stop real norns scripts silently dropping out of `catalog.json` (and reappearing) due to
non-deterministic discovery, without admitting non-norns noise. Add the first automated
tests so a recall regression is caught at commit time, not days later by the churn watcher.

## Background (root cause)
The catalog is rebuilt from scratch each run. Only *authors* persist (`known_authors`),
never *repos*. A repo survives a run only if that run re-discovers AND re-fetches-corpus AND
re-passes the gate. Failure modes observed (2026-06-28):
- **No repo floor**: a single-run search/corpus miss = silent drop.
- **Per-owner sweep cap 60**: `list_owner_repos` fetches only top-60-by-push; schollz has
  1150 repos, so older scripts (schollz/ynth) never surface via the sweep.
- **Empty-corpus = reject**: a transient empty GraphQL corpus blob -> richness 0 -> dropped,
  indistinguishable from a genuine non-norns repo.
- **Monorepo guard** `len(top_lua) > 7 -> []`: drops legit multi-script repos (TW_Norns, 9).
- **Dedup by bare name**: collapses distinct repos sharing a name (two `norns-bookworm`).

## Changes
- **A. Repo floor** — `prior_records(catalog_path)` re-feeds every previously-cataloged
  `(owner,name)` into discovery each run; classify_batch re-verifies each against the live
  fingerprint. Drop only on GitHub 404 or genuine gate-fail.
- **B. Carry-forward** — when a *prior* repo exists on GitHub (present in pass-A metadata)
  but this run's corpus blob came back empty (transient), reuse the prior record instead of
  rejecting. `_fetch_meta` gains split-retry so a transient chunk error can't 404-drop 18
  repos at once.
- **C. Dedup by `(owner,name)`** not bare name. Forks are still handled by fork_ahead.
- **D. Tests** — `tests/` with pure-function unit tests + a recorded recall/precision
  fixture (known-good must classify, known-bad must reject) + carry-forward/floor tests.
  CI runs pytest before the ingest.
- **E. Collection facet** — `len(top_lua) >= 8 -> facet "collection"` (still tracked, still
  installable) instead of dropping. `collection` added to `USABLE_FACETS`.

- **F. Same-name fork filter** — a fork that keeps its parent's name is a personal copy/mirror,
  not a distinct script: exclude it. Renamed forks (timber→timberfade) are kept. This restores
  the fork-noise suppression the old bare-name dedup did by accident, which C removed.
- **G. Full sweep pagination** — `list_owner_repos` cursor-paginates every owner's repos, so a
  1150-repo author's older scripts surface (the deterministic recall fix; the floor only keeps
  *already-cataloged* repos). churn re-keyed to owner/name so C can't create phantom drops.

## Out of scope
- Storing `richness` in the catalog to keep a carried repo's rank stable (self-heals next run).

## Acceptance criteria
- [ ] `facets_from_paths` returns `["collection", ...]` for a 9-top-lua repo; `["script"]` for 1.
- [ ] `_record` rejects an empty corpus for a non-native repo, but carries forward a prior one.
- [ ] dedup keeps two installable repos that share a name but differ in owner.
- [ ] recall fixture: ack, mlr256, ynth, 16klangs, andr-ew/ledmap, TW_Norns classify as norns.
- [ ] precision fixture: a non-norns weak-marker-only repo is rejected.
- [ ] `pytest` green; CI invokes it.
