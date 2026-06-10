# Voice detection & installability classification — design

Date: 2026-06-10
Status: Approved

Confirmed decisions (2026-06-10): replace `nb`/`nb_role` outright with **no
transition shim** — `voices` is the only voice schema in feed.json. The ingenue
repo (`~/gits/ingenue`) is updated **in lockstep** in the same effort (it is the
sole consumer and the user's own project); correctness is guaranteed by testing
before going live, not by feed back-compat.
Scope: `norns_scraper_discourse.py`, `docs/build_data.py`, `tasks/`, `feed.json`/`catalog.json` schema. Dependent subtask in the **ingenue** repo.

## Problem

Two related accuracy problems in the nornslist scraper:

1. **Voice detection is too basic.** The catalog tags scripts that participate in
   the norns "voice" ecosystem (instruments other scripts can load/play). Today's
   detector (`_nb_from_keyfile` + `_detect_nb`) reads **exactly one file** per repo
   and only knows **nb**. It misses voice registrations buried in `lib/` files, has
   no knowledge of non-nb voice systems (mx.samples / mx.synths, playable SC
   engines), and grossly under-detects voice *consumers*.

2. **Non-community sources surface a lot of non-installable junk.** GitHub discovery
   yields 715 entries vs 348 curated. Many are forks, tutorials, study/boilerplate
   repos, test probes, or dev tooling — not "things you'd install on your norns."
   The current gate (`NORNS_FP` regex + structural facets + `GH_BLOCK`) doesn't
   distinguish these.

## Validation against the curated set (the design evidence)

The 348 monome/norns-community entries are hand-vetted, known-good, installable
scripts — ground truth. Running candidate signals against them:

| Signal | Result on curated | Verdict |
|---|---|---|
| Current `nb=provides` | 18 caught (incl. all four `nb_*` packs) | Providers already mostly work |
| Current `nb_role=uses` | **1** caught across 348 | **Consumer detection is broken** |
| Current `engine` name | 118 caught | Works |
| Dependency-only (no `script` facet) | 15 curated hit — all **installable** mods/voice packs (`nb_mxsynths`, `cybermidi`, `oilcan`, …) | "no script facet → not installable" is **WRONG**; drop from gate |
| High-precision red-flags (`tutorial\|study\|boilerplate\|template\|exercise\|wip`) | **0** curated hit | Safe to gate on |
| Low-precision red-flags (`test\|playground\|example\|sandbox`) | **5** curated hit (`acid-test`, `grid-test`, `cheat_codes_2`, `twins`, `passthrough`) | **Too noisy to gate**; tag-only at most |
| `fork` flag | Not currently captured at all | Biggest missing structural signal |

Conclusion: the win is **accuracy from reading real code** + reusing ingenue's
battle-tested detector, not new guesswork. Installability must gate on **structural**
signals (fork, blocklist, truly-empty), not string-matching or dependency status.

## Prior art: ingenue's `analyze_dir` (`web/server.py`)

ingenue's live `/api/deps` already does accurate detection and has absorbed the
hard-won edge cases. The scraper should mirror it:

- Concatenates **all** `.lua/.sc/.sh` into one corpus.
- **Excludes bundled `lib/<X>/` copies** from the corpus so a script that vendors
  its own nb (e.g. dreamsequence bundling `lib/nb/lib/nb.lua`) is **not** false-flagged
  as needing nb. nornslist's single-keyfile reader has no equivalent and this is the
  key precision fix.
- Extracts: `require "X/lib"` with **dotted names** (`mx.samples`, `mx.synths`),
  `engine.name = "Foo"` targets vs shipped `Engine_*.sc` (`self_engines`),
  `nb_referenced` (= `require "nb/" | /nb/lib | nb_voice | nb:add`) minus bundled,
  `*_scsynth.so` SC extensions, download URLs, `norns.version.required` pin,
  `params:bang()`-in-`add_params` footgun.

## Design

### Foundation — corpus-based enrichment

In `_github_fetch_feed_enrichment`, replace the single `_nb_key_file` read with a
bounded multi-blob fetch built from the recursive tree already fetched:

- Candidate files: all top-level `*.lua`, `lib/**/*.lua` (cap ~12), `Engine_*.sc`.
- Detect bundled libs (`lib/<X>/` dirs containing code) from the tree and **exclude
  them from the corpus**, mirroring `analyze_dir`.
- Fetch raw blobs in the existing `ThreadPoolExecutor` pass.
- Cost control: bump `FEED_LOGIC_VERSION` (forces one re-enrichment of all repos),
  thereafter only SHA-changed repos re-fetch. Per-repo file cap bounds API calls.

This corpus feeds **both** Job 1 and Job 2.

### Job 1 — `voices` object (replaces `nb` / `nb_role`)

Per script, emit:

```json
"voices": { "provides": ["nb"], "uses": ["nb", "mx.samples"], "systems": ["nb","mx.samples"] }
```

- **provides** — voices other scripts can load. Triggers the umbrella "additional
  voices" tag. Signals: `nb:add_player`, `nb_*` mod packs, a shipped `Engine_*.sc`
  that is a playable instrument (exposes a note interface — `noteOn`/`gate`/`hz`/`note`;
  effect-only engines excluded). Note: mx.samples/mx.synths are treated as a
  **`uses`** signal only — they are libraries scripts consume; detecting a script
  that *publishes a new* mx instrument pack is out of initial scope (rare, no clean
  signal) and can be added later if a reliable marker emerges.
- **uses** — consumed voice systems (subtype tags only, never the umbrella). Signals:
  `require "X/lib"` (mx.samples, mx.synths, …), `nb_referenced` minus bundled,
  `engine.name` targets not shipped by the repo.
- **systems** — union of detected systems, for subtype tagging (`nb`, `mx.samples`,
  `mx.synths`, `sc-engine`, …). Each detected system gets its own subtype tag in
  addition to the umbrella tag.

**Umbrella rule:** "additional voices" tag fires **iff `provides` is non-empty** —
the user's criterion, "another script can load this voice."

### Job 2 — installability classification (tag, don't hide)

Capture richer raw signals (cheap; mostly already in API responses):

- `fork` — GitHub `fork: bool` (currently discarded). Captured at discovery time.
- `has_init` (`function init(`), `has_params` (`params:add`) — from the corpus;
  prove a runnable script vs. a fragment.
- High-precision red-flag match on name/desc (`tutorial|study|boilerplate|template|exercise|wip`).
- `dependency` — engine/library/mod facet but no `script` facet (informational only).
- `unverified` — 0 stars AND no README AND no init/params.

**Derived `installable` boolean (the default-on filter):** `false` iff
`fork` OR high-precision red-flag OR no usable facet at all (not script/mod/engine/library)
OR in `GH_BLOCK`. Otherwise `true`. Mods and voice packs are installable.

Everything stays in `catalog.json` and on the site. `installable` drives a
**default-on** "installable only" filter (one-click off). Classification tags
(`fork`, `study`, `template`, `dependency`, `unverified`) are additive, never
exclusionary.

### Schema changes

- **feed.json**: add `voices` object; **remove** `nb` and `nb_role` (note 2 —
  ingenue is the only consumer and is updated in the dependent subtask). Keep
  `engine`, `facets`.
- **catalog.json**: add `fork` (bool) and classification tags on GitHub rows.
- **build_data.py `merge()`**: consume `voices` instead of `nb`/`nb_role`; derive
  `facets.voices` (= `provides` non-empty) and `facets.installable`; emit subtype
  chips; derive `installable` for community rows too (their facets resolve at
  build time).

### Coupling — mirror + parity test (decided)

Reimplement ingenue's detection in the scraper against the GitHub API (ingenue's
`analyze_dir` walks a local clone; the scraper has no clone). Keep the **same regex
vocabulary**, pinned by a parity test, so precomputed feed signals match ingenue's
live `/api/deps`. No shared package; the two repos stay independently deployable.
(Rejected: shared module — packaging coupling between independently-deployed repos.
Rejected: nornslist-authoritative-with-ingenue-calling-it — biggest change, deferred.)

### Dependent subtask — ingenue

Separate ingenue PR (`web/server.py`, `web/index.html`):
1. Update feed.json reads from `nb`/`nb_role` to the `voices` schema (the
   "additional voice" tag + DEP_OVERLAY paths).
2. Bonus (provider-goal aligned): for cataloged repos, consume nornslist's
   precomputed deps from feed.json instead of recomputing live; live fallback for
   un-cataloged repos. Exact edits scoped when that PR is taken up.

## Verification

- Bump `FEED_LOGIC_VERSION`.
- Extend `tasks/test_feed.py`: provides vs uses; mx.samples via `require`;
  bundled-nb excluded (dreamsequence shape); effect-engine excluded from voices;
  fork / high-precision-red-flag / dependency installability cases; the 5
  low-precision false-positive names must stay `installable=true`.
- New `tasks/voice_census.py` — voice classification breakdown over curated +
  GitHub sets.
- Extend `tasks/discovery_census.py` — print the installability reclassification so
  it can be eyeballed before shipping.
- **Parity test** — scraper detection regexes match ingenue's `analyze_dir` vocabulary.
- Re-run against the 348 curated set: every curated entry must remain
  `installable=true` (zero false-positive exclusions).

## Non-goals

- No exclusion/dropping of entries from catalog.json (tag-only, per decision).
- No live device analysis in the scraper (`/api/deps` stays ingenue's live path).
- No redesign of the discovery sources/queries themselves.
