# nornslist ↔ ingenue "Available" tab parity

**Goal:** bring the public nornslist catalog (`docs/`) to visual + tagging parity with
ingenue's Available tab. All needed data already exists in `data.json`/`feed.json`;
this is almost entirely a rendering change.

## Changes

1. **`docs/build_data.py`** — propagate `nb_role` (provides/uses) from `feed.json`
   into each script row. Only new data field.

2. **Type taxonomy chips (`docs/index.html`)** — render structural `kind` as
   ingenue-style `.facets` chips on each card, using ingenue's `FACET_META` palette:
   - `▶ script` #7ee787 · `◆ mod` #c678dd · `❏ library` #56b6c2 · `♪ engine` #e5c07b
   - nb split: `♪ nb voices` (role=provides) vs `♪ nb-ready` (role=uses), replacing
     the flat `nb` badge.
   - **Engine rule:** keep the richer named-engine badge (`PolyPerc`); show the generic
     `♪ engine` kind chip *only* when `kind` includes `engine` but no name was extracted
     (GitHub-discovered rows). No double-up.

3. **Type filter row (`docs/index.html`)** — add `script / mod / library` toggles to the
   facetbar, wired into existing `state.facets` machinery. Engine stays out of this row
   (the facetbar already has a `⚙ engine` capability filter).

4. **Source chips (`docs/index.html`)** — replace the github-only badge with color-coded
   source chips (`community` #DEB887 / `github` #7ee787) + ingenue's `.card.gh` left border.

5. **Sort by stars (`docs/index.html`)** — add "most stars" to the sort dropdown.

6. **README + A/V** — audit only. Already implemented and at/above parity; verify expanded
   layout ordering/styling, change only if needed.

## Verification

`python3 docs/build_data.py`, open `docs/index.html` — check a mod, a library, an
nb-voices script, and a github card's source chip + border. Filter by type=mod.

## Non-goals

No scraper changes, no nightly-job impact. `data.json` stays backward-compatible.
