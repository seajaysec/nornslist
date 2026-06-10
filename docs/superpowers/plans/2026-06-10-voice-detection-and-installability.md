# Voice Detection & Installability Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scraper's single-keyfile nb check with a corpus-based voice classifier (mirroring ingenue's `analyze_dir`), emit a `voices` object in feed.json, capture GitHub's `fork` flag, derive an `installable` filter — all validated to keep every curated script installable — and update ingenue to consume the new schema in lockstep.

**Architecture:** The scraper fetches a bounded multi-file corpus per repo (all top-level `*.lua`, `lib/**/*.lua` minus bundled `lib/<X>/` copies, `Engine_*.sc`), runs pure static classifiers over it, and emits `voices` + `has_init`/`has_params` in feed.json and `fork` in catalog.json. `docs/build_data.py` derives the UI booleans (`facets.voices`, `facets.installable`) and class tags. ingenue (`web/server.py`, `web/index.html`) is updated to read `voices` instead of `nb`/`nb_role`. Pure helpers are unit-tested offline in `tasks/`; cross-repo regex parity is pinned by a shared-fixture test.

**Tech Stack:** Python 3.11 (scraper, build_data, tests — no network in unit tests), vanilla JS (ingenue web UI), GitHub REST API (git/trees + contents raw blobs).

**Test runner:** `~/.virtualenvs/nornslist-vhmg/bin/python tasks/<test>.py` (pure-helper tests; stdlib only).

**Key reference:** ingenue `web/server.py` `analyze_dir` (~line 1790) is the authoritative detector being mirrored. Regex vocabulary to match:
- requires: `require[\s(]+['"]([A-Za-z0-9_.\-]+)/lib` (dotted names → mx.samples, mx.synths), minus self/core/bundled
- nb consumer: `require[\s(]+['"]nb/|/nb/lib|nb_voice|nb:add`
- nb provider: `nb:add_player`
- engines used: `engine\.name\s*=\s*['"]([A-Za-z0-9_]+)['"]`
- self engine: `Engine_(.+)\.sc$` (basename)
- bundled lib: a `lib/<X>/` directory containing any `.lua`/`.sc`/`.sh`

---

## File Structure

**nornslist repo:**
- Modify `norns_scraper_discourse.py` — new static helpers (`_bundled_libs_from_paths`, `_voice_corpus_paths`, `_detect_voices`, `_has_init_params`, `_redflag_kind`); rewire `_github_fetch_feed_enrichment` and `_build_feed_scripts`; add `fork` in `discover_github_repos`/`_discovered_to_catalog_entry`; bump `FEED_LOGIC_VERSION`→4 and `DISCOVERY_LOGIC_VERSION`→2; remove `_nb_from_keyfile`/`_detect_nb` usage.
- Modify `docs/build_data.py` — `_normalize_row` carries `fork`; `merge()` consumes `voices`, derives `facets.voices`/`facets.installable` + class tags + `installable_reason`; new pure helpers `derive_installable()` and `voice_tags()`.
- Modify `tasks/test_feed.py` — voice classifier + corpus + fork-feed unit cases.
- Create `tasks/test_build_data.py` — installability derivation + voice-tag unit cases + the 5 curated false-positive guards.
- Create `tasks/test_voice_parity.py` — shared Lua/SC fixtures with expected classification (the parity contract with ingenue).
- Create `tasks/voice_census.py` — voice breakdown over catalog/feed.
- Modify `tasks/discovery_census.py` — append installability reclassification breakdown.
- Create `tasks/test_curated_installable.py` — regression: every `source=community` row derives `installable=true`.

**ingenue repo (lockstep):**
- Modify `web/server.py` `analyze_dir` — add `voices` (provides/uses/systems) to the report.
- Modify `web/index.html` — replace `nb`/`nb_role` reads/renders/live-detector with `voices`.

---

## Phase 0 — Corpus foundation (pure helpers)

### Task 0.1: Bundled-lib detection from tree paths

**Files:**
- Modify: `norns_scraper_discourse.py` (add static method near `_facets_from_paths`, ~line 3127)
- Test: `tasks/test_feed.py`

- [ ] **Step 1: Write the failing test** — append to `tasks/test_feed.py` after the engine block:

```python
# --- Phase A: bundled-lib detection (vendored copies excluded from corpus) ---
check("bundled_basic",
      sorted(S._bundled_libs_from_paths(["lib/nb/lib/nb.lua", "lib/nb/README.md", "main.lua"])),
      ["nb"])
check("bundled_needs_code",
      S._bundled_libs_from_paths(["lib/docs/notes.md", "main.lua"]),
      set())  # a lib/<X>/ dir with no code is not a bundled lib
check("bundled_multi",
      sorted(S._bundled_libs_from_paths(["lib/nb/x.lua", "lib/mx/y.sc", "main.lua"])),
      ["mx", "nb"])
check("bundled_ignores_direct_lib_files",
      S._bundled_libs_from_paths(["lib/util.lua", "main.lua"]),
      set())  # lib/util.lua is not under a lib/<X>/ subdir
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: FAIL with `AttributeError: type object 'NornsScraper' has no attribute '_bundled_libs_from_paths'`

- [ ] **Step 3: Implement** — add to `norns_scraper_discourse.py` after `_facets_from_paths`:

```python
    @staticmethod
    def _bundled_libs_from_paths(paths) -> set:
        """Names X of bundled support libs the repo ships under lib/<X>/ (dir
        containing at least one .lua/.sc/.sh). Mirrors ingenue analyze_dir: a
        bundled copy self-resolves its own require's, so its source is EXCLUDED
        from the voice corpus — otherwise a vendored lib/nb/lib/nb.lua would make
        the host falsely look like an nb consumer (the dreamsequence false-pos)."""
        dirs = {}
        for p in paths:
            m = re.match(r"lib/([^/]+)/(.+)$", str(p))
            if m:
                dirs.setdefault(m.group(1).lower(), []).append(m.group(2))
        return {x for x, inner in dirs.items()
                if any(f.lower().endswith((".lua", ".sc", ".sh")) for f in inner)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: PASS (`ALL N CHECKS PASSED`)

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_feed.py
git commit -m "feat(scraper): bundled-lib detection for voice corpus exclusion"
```

### Task 0.2: Corpus candidate-path selection

**Files:**
- Modify: `norns_scraper_discourse.py` (add static method after `_bundled_libs_from_paths`)
- Test: `tasks/test_feed.py`

- [ ] **Step 1: Write the failing test** — append to `tasks/test_feed.py`:

```python
# --- Phase A: corpus candidate paths (bounded; excludes bundled libs) ---
_paths = ["awake.lua", "lib/engine_helper.lua", "lib/nb/lib/nb.lua",
          "lib/Engine_Foo.sc", "README.md", "docs/x.md", "data/preset.json"]
_bundled = S._bundled_libs_from_paths(_paths)
_corpus = S._voice_corpus_paths(_paths, _bundled)
check("corpus_keeps_toplevel_lua", "awake.lua" in _corpus, True)
check("corpus_keeps_lib_lua", "lib/engine_helper.lua" in _corpus, True)
check("corpus_keeps_sc_engine", "lib/Engine_Foo.sc" in _corpus, True)
check("corpus_excludes_bundled", "lib/nb/lib/nb.lua" in _corpus, False)
check("corpus_excludes_nonlua", any(p.endswith(".md") or p.endswith(".json") for p in _corpus), False)
check("corpus_capped",
      len(S._voice_corpus_paths([f"lib/f{i}.lua" for i in range(50)] + ["top.lua"], set())) <= S.VOICE_CORPUS_MAX_FILES,
      True)
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: FAIL with `AttributeError ... _voice_corpus_paths` (and `VOICE_CORPUS_MAX_FILES`)

- [ ] **Step 3: Implement** — add the class constant near `FEED_MAX_IMAGES` (~line 3006):

```python
    VOICE_CORPUS_MAX_FILES = 16  # bounded blob fetch per repo (API-call ceiling)
```

and the method after `_bundled_libs_from_paths`:

```python
    @staticmethod
    def _voice_corpus_paths(paths, bundled) -> list:
        """Files whose contents form the voice/deps corpus: top-level *.lua,
        lib/**/*.lua (minus bundled lib/<X>/ copies), and Engine_*.sc. Deterministic
        order (top-level first, then lib, then engines), capped at
        VOICE_CORPUS_MAX_FILES so a pathological repo can't explode the fetch."""
        bundled = {b.lower() for b in (bundled or set())}
        def is_bundled(p):
            m = re.match(r"lib/([^/]+)/", p)
            return bool(m and m.group(1).lower() in bundled)
        top = [p for p in paths if "/" not in p and p.lower().endswith(".lua")]
        lib = [p for p in paths if p.lower().endswith(".lua")
               and re.search(r"(?:^|/)lib/", p) and not is_bundled(p)]
        sc = [p for p in paths if re.search(r"(?:^|/)Engine_[A-Za-z0-9]+\.sc$", p) and not is_bundled(p)]
        ordered, seen = [], set()
        for group in (sorted(top), sorted(lib), sorted(sc)):
            for p in group:
                if p not in seen:
                    seen.add(p); ordered.append(p)
        return ordered[: NornsScraper.VOICE_CORPUS_MAX_FILES]
```

- [ ] **Step 4: Run to verify it passes**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_feed.py
git commit -m "feat(scraper): bounded voice-corpus candidate-path selection"
```

---

## Phase 1 — Voice classifier (pure)

### Task 1.1: `_detect_voices` — provides / uses / systems

**Files:**
- Modify: `norns_scraper_discourse.py` (add static method; this supersedes `_nb_from_keyfile`/`_detect_nb`)
- Test: `tasks/test_feed.py`

Classifier contract (mirrors ingenue regexes; `facets` passed so engine-provider shape is structural):
- **provides** (drives umbrella tag — "another script can load this voice"):
  - `nb` if `nb:add_player` in blob, OR repo name matches `nb[_-]` / a path matches `nb[_-].+\.lua$|[_-]nb\.lua$` (the `nb_*` voice-pack convention).
  - `sc-engine` if repo ships `Engine_*.sc` AND `"script" not in facets` (engine-only / library+engine / mod+engine repos exist to lend their engine to other scripts; a standalone `script`+`engine` runs its own engine and is not a loadable voice).
- **uses** (subtype tags only, never umbrella):
  - `nb` if `nb_referenced` regex hits (minus bundled) and not already a provider-by-add_player.
  - each `require "X/lib"` where X ∈ {`mx.samples`, `mx.synths`} (and any other dotted lib) → that system.
  - `sc-engine` if `engine.name="Foo"` targets a `Foo` NOT shipped by this repo.
- **systems**: sorted union of provides+uses.

- [ ] **Step 1: Write the failing test** — append to `tasks/test_feed.py`:

```python
# --- Phase 1: voice classifier (corpus-based; mirrors ingenue analyze_dir) ---
def voices(blob, paths=None, facets=None, repo="x"):
    return S._detect_voices(blob, paths or [], set(), facets or [], repo)

# nb provider via add_player
v = voices('nb:add_player("foo", MyPlayer)', facets=["mod"])
check("v_nb_provides", (v["provides"], "nb" in v["uses"]), (["nb"], False))

# nb provider via filename convention (nb_* pack)
v = voices("-- voice pack", paths=["lib/nb_drumcrow.lua"], facets=["mod"], repo="nb_drumcrow")
check("v_nb_pack_filename", "nb" in v["provides"], True)

# nb consumer (uses) — require nb/lib buried in a lib file
v = voices('local nb = require "nb/lib/nb"', facets=["script"])
check("v_nb_uses", (v["uses"], v["provides"]), (["nb"], []))

# vendored nb must NOT flag uses — bundled excluded upstream; simulate empty blob
v2 = S._detect_voices("-- host code, no external nb ref", ["main.lua", "lib/nb/lib/nb.lua"],
                      {"nb"}, ["script"], "host")
check("v_nb_vendored_not_uses", "nb" in v2["uses"], False)

# mx.samples / mx.synths via require
v = voices('engine.name="None"\nlocal mxsamples=require("mx.samples/lib/mx.samples")', facets=["script"])
check("v_mxsamples_uses", "mx.samples" in v["uses"], True)

# sc-engine PROVIDER: ships engine, no top-level script (engine-only/library+engine)
v = voices("SynthDef stuff", paths=["lib/Engine_Ack.sc"], facets=["library", "engine"], repo="ack")
check("v_scengine_provides", "sc-engine" in v["provides"], True)

# sc-engine NON-provider: standalone script that ships its own engine (acid-test shape)
v = voices("SynthDef stuff", paths=["acid-test.lua", "lib/Engine_AcidTest.sc"],
           facets=["script", "engine"], repo="acid-test")
check("v_scengine_own_not_provider", "sc-engine" in v["provides"], False)

# sc-engine USES: references an engine it does not ship
v = voices('engine.name = "Rings"', paths=["main.lua"], facets=["script"], repo="m")
check("v_scengine_uses", "sc-engine" in v["uses"], True)

# pure midi/crow output does NOT count as a voice (the ~300-script noise)
v = voices('crow.output[1].volts=1\nmidi:note_on(60,100)', facets=["script"])
check("v_raw_io_no_voice", (v["provides"], v["uses"]), ([], []))

# systems = union
v = voices('nb:add_player("p", x)\nrequire("mx.synths/lib/mx.synths")', facets=["mod"])
check("v_systems_union", sorted(v["systems"]), ["mx.synths", "nb"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: FAIL with `AttributeError ... _detect_voices`

- [ ] **Step 3: Implement** — add to `norns_scraper_discourse.py` after `_voice_corpus_paths`:

```python
    # Voice systems whose `require "<X>/lib"` presence means the script USES that
    # system's voices. Dotted names matter (mx.samples, mx.synths). Extend as new
    # voice frameworks appear. Mirrors ingenue analyze_dir's requires extraction.
    VOICE_USE_LIBS = {"mx.samples", "mx.synths"}

    @staticmethod
    def _detect_voices(blob: str, paths, bundled, facets, repo: str) -> dict:
        """Classify a repo's relationship to the norns voice ecosystem from its
        corpus blob + tree. Returns {provides, uses, systems}. provides = voices
        OTHER scripts can load (drives the 'additional voices' umbrella tag); uses
        = voice systems this script consumes. Mirrors ingenue's analyze_dir regex
        vocabulary so precomputed signals match its live /api/deps. Pure/offline."""
        text = blob or ""
        facets = list(facets or [])
        bundled = {b.lower() for b in (bundled or set())}
        provides, uses = [], []

        # --- nb ---
        nb_pack_name = bool(re.match(r"nb[_-]", (repo or "").lower()))
        nb_pack_file = any(re.match(r"nb[_-].+\.lua$", os.path.basename(str(p)).lower())
                           or re.search(r"[_-]nb\.lua$", os.path.basename(str(p)).lower())
                           for p in paths)
        if re.search(r"nb:add_player", text) or nb_pack_name or nb_pack_file:
            provides.append("nb")
        elif re.search(r"require[\s(]+['\"]nb/|/nb/lib|nb_voice|nb:add", text) and "nb" not in bundled:
            uses.append("nb")

        # --- required voice libs (mx.samples, mx.synths, …) -> uses ---
        for lib in sorted(set(re.findall(r"require[\s(]+['\"]([A-Za-z0-9_.\-]+)/lib", text))):
            if lib.lower() in bundled:
                continue
            if lib in NornsScraper.VOICE_USE_LIBS:
                uses.append(lib)

        # --- SuperCollider engines ---
        self_engines = {m.group(1).lower() for p in paths
                        for m in [re.search(r"Engine_([A-Za-z0-9]+)\.sc$", os.path.basename(str(p)))] if m}
        if self_engines and "script" not in facets:
            provides.append("sc-engine")          # engine-only/lib/mod repo: lends its engine
        used_engines = {e.lower() for e in re.findall(r"engine\.name\s*=\s*['\"]([A-Za-z0-9]+)['\"]", text)}
        if any(e not in self_engines for e in used_engines):
            uses.append("sc-engine")

        provides = sorted(set(provides))
        uses = sorted(set(u for u in uses if u not in provides))
        return {"provides": provides, "uses": uses, "systems": sorted(set(provides) | set(uses))}
```

- [ ] **Step 4: Run to verify it passes**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_feed.py
git commit -m "feat(scraper): corpus-based voice classifier (provides/uses/systems)"
```

### Task 1.2: `_has_init_params` — runnable-script signal

**Files:**
- Modify: `norns_scraper_discourse.py` (add static method)
- Test: `tasks/test_feed.py`

- [ ] **Step 1: Write the failing test** — append:

```python
# --- Phase 1: runnable-script signals from corpus ---
check("init_params_both", S._has_init_params("function init()\nparams:add{}\nend"), (True, True))
check("init_params_init_only", S._has_init_params("function init ()\n end"), (True, False))
check("init_params_neither", S._has_init_params("local x = 1"), (False, False))
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: FAIL with `AttributeError ... _has_init_params`

- [ ] **Step 3: Implement** — add after `_detect_voices`:

```python
    @staticmethod
    def _has_init_params(blob: str) -> tuple:
        """(has_init, has_params) from the corpus — proof the repo is a runnable
        script (defines init / adds params) vs a bare fragment. Used by the
        installability classifier downstream."""
        text = blob or ""
        return (bool(re.search(r"function\s+init\s*\(", text)),
                bool(re.search(r"params\s*:\s*add", text)))
```

- [ ] **Step 4: Run to verify it passes**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_feed.py
git commit -m "feat(scraper): has_init/has_params runnable-script signal"
```

---

## Phase 2 — Wire corpus + voices into enrichment & feed

### Task 2.1: Fetch corpus blobs in `_github_fetch_feed_enrichment`

**Files:**
- Modify: `norns_scraper_discourse.py:3342-3420` (`_github_fetch_feed_enrichment`)

- [ ] **Step 1: Modify the result dict + tree branch.** In `_github_fetch_feed_enrichment`, change the initial result (~line 3349) from:

```python
        result = {"engine": "", "nb": False, "nb_role": "", "facets": [], "readme": "", "images": [], "sha": "", "demo": ""}
```
to:
```python
        result = {"engine": "", "voices": {"provides": [], "uses": [], "systems": []},
                  "has_init": False, "has_params": False, "facets": [], "readme": "",
                  "images": [], "sha": "", "demo": ""}
```

- [ ] **Step 2: Replace the nb block in the recursive-tree branch.** Replace these lines (~3404-3409):

```python
                    result["engine"] = self._engine_from_paths(paths)
                    result["facets"] = self._facets_from_paths(paths)
                    # accurate nb: read the key file (catches add_param buried in lib/),
                    # falling back to the filename/README heuristic for providers whose
                    # registration lives in a lib file we don't read.
                    nb_kf, nb_role = self._nb_from_keyfile(owner, repo, branch, paths)
                    heuristic_nb = self._detect_nb(readme_md, paths)
                    result["nb"] = bool(nb_kf or heuristic_nb)
                    result["nb_role"] = nb_role or ("provides" if heuristic_nb else "")
```
with:
```python
                    result["engine"] = self._engine_from_paths(paths)
                    facets = self._facets_from_paths(paths)
                    result["facets"] = facets
                    # Corpus-based voice/deps detection (mirrors ingenue analyze_dir):
                    # read all top-level/lib *.lua + Engine_*.sc, EXCLUDING bundled
                    # lib/<X>/ copies, into one blob and classify accurately.
                    bundled = self._bundled_libs_from_paths(paths)
                    corpus = self._voice_corpus_paths(paths, bundled)
                    blob = self._fetch_blobs(owner, repo, branch, corpus)
                    result["voices"] = self._detect_voices(blob, paths, bundled, facets, repo)
                    result["has_init"], result["has_params"] = self._has_init_params(blob)
```

- [ ] **Step 3: Add the `_fetch_blobs` helper** after `_raw_github_url` (~line 3086):

```python
    def _fetch_blobs(self, owner: str, repo: str, branch: str, rel_paths) -> str:
        """Concatenate the raw contents of rel_paths into one corpus blob. Best-
        effort: missing/unreadable files are skipped. Sequential (the path list is
        already capped at VOICE_CORPUS_MAX_FILES) and inside the per-repo enrichment
        task, which itself runs in the enrichment thread pool."""
        from urllib.parse import quote
        parts = []
        for p in rel_paths:
            try:
                seg = "/".join(quote(s) for s in str(p).split("/"))
                r = self.github_session.get(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/{seg}",
                    headers={"Accept": "application/vnd.github.raw"},
                    params={"ref": branch}, timeout=15,
                )
                if r.status_code == 200:
                    parts.append(r.text)
                elif r.status_code == 403:
                    break  # rate-limited: stop early, keep what we have
            except Exception:
                continue
        return "\n".join(parts)
```

- [ ] **Step 4: Verify import compiles**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python -c "import norns_scraper_discourse"`
Expected: no output (clean import)

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py
git commit -m "feat(scraper): fetch voice corpus + classify in feed enrichment"
```

### Task 2.2: Emit `voices` in `_build_feed_scripts`; bump logic version

**Files:**
- Modify: `norns_scraper_discourse.py:3463-3498` (`_build_feed_scripts`) and `:3010` (`FEED_LOGIC_VERSION`)
- Test: `tasks/test_feed.py`

- [ ] **Step 1: Update the feed-build test.** In `tasks/test_feed.py`, replace the `feed_nb_omitted_when_false` check and add voice checks. Find:

```python
check("feed_nb_omitted_when_false", "nb" in scripts["awake"], False)
```
Replace with:
```python
check("feed_no_voices_key_when_empty", "voices" in scripts["awake"], False)

# voices emitted when non-empty
rows_v = [{"Name": "Foo", "Tags": "x", "Last Updated": "2024-01-01", "Project URL": "https://github.com/o/foo"}]
enr_v = {("o", "foo"): {"voices": {"provides": ["nb"], "uses": [], "systems": ["nb"]}}}
sv = NornsScraper._build_feed_scripts(inst, rows_v, enr_v)
check("feed_voices_emitted", sv["foo"].get("voices"), {"provides": ["nb"], "uses": [], "systems": ["nb"]})
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: FAIL (`feed_voices_emitted`: got None) — and `feed_no_voices_key...` may already pass.

- [ ] **Step 3: Implement.** In `_build_feed_scripts`, replace the nb block (~3486-3489):

```python
                if enr.get("nb"):
                    entry["nb"] = True
                if enr.get("nb_role"):
                    entry["nb_role"] = enr["nb_role"]
```
with:
```python
                v = enr.get("voices") or {}
                if v.get("systems"):
                    entry["voices"] = {"provides": list(v.get("provides") or []),
                                       "uses": list(v.get("uses") or []),
                                       "systems": list(v.get("systems") or [])}
                if enr.get("has_init"):
                    entry["has_init"] = True
                if enr.get("has_params"):
                    entry["has_params"] = True
```

Then bump the version at line 3010:
```python
    FEED_LOGIC_VERSION = 4  # v4: voices object (replaces nb/nb_role) + has_init/params from corpus
```

- [ ] **Step 4: Run to verify it passes**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_feed.py
git commit -m "feat(scraper): emit voices/has_init/has_params in feed.json; FEED_LOGIC_VERSION=4"
```

### Task 2.3: Remove dead nb helpers

**Files:**
- Modify: `norns_scraper_discourse.py` (delete `_nb_key_file`, `_nb_from_keyfile`, `_detect_nb` and their stale `_detect_nb` tests)
- Test: `tasks/test_feed.py`

- [ ] **Step 1: Delete the stale nb tests** in `tasks/test_feed.py` — remove the four `_detect_nb` checks (`nb_filename`, `nb_suffix_file`, `nb_readme_phrase`, `nb_note_bridge`, `nb_negative`).

- [ ] **Step 2: Delete the three methods** `_nb_key_file` (~3130), `_nb_from_keyfile` (~3147), `_detect_nb` (~3174) from `norns_scraper_discourse.py`.

- [ ] **Step 3: Verify nothing else references them**

Run: `grep -rn "_nb_from_keyfile\|_nb_key_file\|_detect_nb\b" norns_scraper_discourse.py tasks/ docs/`
Expected: no matches.

- [ ] **Step 4: Run tests + import**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python -c "import norns_scraper_discourse" && ~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py`
Expected: clean import + `ALL N CHECKS PASSED`

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_feed.py
git commit -m "refactor(scraper): drop legacy single-keyfile nb detection"
```

---

## Phase 3 — Capture `fork`; installability raw signals

### Task 3.1: Capture GitHub `fork` flag in discovery

**Files:**
- Modify: `norns_scraper_discourse.py:4084` (the `_task` record in `discover_github_repos`) and `:3829` (`DISCOVERY_LOGIC_VERSION`)

- [ ] **Step 1: Add `fork` to the discovery record.** In `discover_github_repos._task`, in the returned dict (~line 4096), add after `"archived": bool(it.get("archived")),`:

```python
                "fork": bool(it.get("fork")),
```

- [ ] **Step 2: Bump discovery logic version** at line 3829:

```python
    DISCOVERY_LOGIC_VERSION = 2  # v2: capture fork flag for installability classification
```

- [ ] **Step 3: Verify import compiles**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python -c "import norns_scraper_discourse"`
Expected: clean import.

- [ ] **Step 4: Commit**

```bash
git add norns_scraper_discourse.py
git commit -m "feat(scraper): capture GitHub fork flag in discovery records"
```

### Task 3.2: Carry `fork` into the catalog entry

**Files:**
- Modify: `norns_scraper_discourse.py:3582-3608` (`_discovered_to_catalog_entry`)
- Test: `tasks/test_catalog.py` (add a case if the file has a runnable harness; otherwise verify via a one-off)

- [ ] **Step 1: Add fork to the catalog entry.** In `_discovered_to_catalog_entry`, after the `entry["archived"] = True` block (~line 3606), add:

```python
        if rec.get("fork"):
            entry["fork"] = True
```

- [ ] **Step 2: Verify via a one-off**

Run:
```bash
~/.virtualenvs/nornslist-vhmg/bin/python -c "
from norns_scraper_discourse import NornsScraper as S
inst = object.__new__(S)
e = S._discovered_to_catalog_entry(inst, {'name':'x','fork':True,'facets':['script'],'stars':0})
print('fork' in e and e['fork'] is True)
"
```
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add norns_scraper_discourse.py
git commit -m "feat(scraper): persist fork flag on github catalog entries"
```

### Task 3.3: Compute `fork_ahead` in enrichment; emit fork signals in feed

Rationale: *some forks are valuable.* Only unmodified/behind-only forks should be
non-installable; a fork that is AHEAD of its upstream parent is kept (tagged `fork`).
"Ahead" needs the fork's parent (already in the repo-meta response) + one GitHub
compare call, cached by the feed SHA. Unknown ahead-state → treat as ahead (keep).

**Files:**
- Modify: `norns_scraper_discourse.py` — `_github_fetch_feed_enrichment` result dict + fork block, new `_fork_ahead` helper, `_build_feed_scripts` emission, `FEED_LOGIC_VERSION`→5
- Test: `tasks/test_feed.py`

- [ ] **Step 1: Confirm `_repo_meta` exposes fork + parent.** The compare needs the parent repo. Verify the meta call returns the raw GitHub repo object (which includes `fork: bool`, and for forks a `parent` object with `owner.login`, `name`, `default_branch`):

Run: `sed -n '2724,2780p' norns_scraper_discourse.py`
Expected: `_repo_meta` returns the repo JSON (possibly augmented with `_status`). If it strips fields, note it — the code below reads `meta.get("fork")` and `meta.get("parent")` directly, so those keys must survive. If `_repo_meta` trims to a whitelist, ADD `fork` and `parent` to that whitelist as part of this step.

- [ ] **Step 2: Add fork keys to the result dict** in `_github_fetch_feed_enrichment` (the dict introduced in Task 2.1). Change:

```python
        result = {"engine": "", "voices": {"provides": [], "uses": [], "systems": []},
                  "has_init": False, "has_params": False, "facets": [], "readme": "",
                  "images": [], "sha": "", "demo": ""}
```
to add `"fork": False, "fork_ahead": False,`:
```python
        result = {"engine": "", "voices": {"provides": [], "uses": [], "systems": []},
                  "has_init": False, "has_params": False, "fork": False, "fork_ahead": False,
                  "facets": [], "readme": "", "images": [], "sha": "", "demo": ""}
```

- [ ] **Step 3: Set fork signals right after `branch` is resolved** in `_github_fetch_feed_enrichment`. Find the line that sets `result["sha"] = self._github_head_sha(owner, repo, branch)` and add immediately after it:

```python
            result["fork"] = bool(meta.get("fork"))
            if result["fork"]:
                result["fork_ahead"] = self._fork_ahead(owner, repo, branch, meta.get("parent"))
```

- [ ] **Step 4: Add the `_fork_ahead` helper** near `_fetch_blobs`:

```python
    def _fork_ahead(self, owner: str, repo: str, branch: str, parent) -> bool:
        """True if this fork has commits AHEAD of its upstream parent (a diverged
        fork worth keeping). One GitHub compare call. Unknown (no parent / deleted /
        API error) -> True: keep + tag rather than bury a possibly-valuable fork."""
        if not parent:
            return True
        p_owner = (parent.get("owner") or {}).get("login") or ""
        p_repo = parent.get("name") or ""
        p_branch = parent.get("default_branch") or "main"
        if not p_owner or not p_repo:
            return True
        try:
            from urllib.parse import quote
            base = quote(f"{p_owner}:{p_branch}")
            head = quote(f"{owner}:{branch}")
            r = self.github_session.get(
                f"https://api.github.com/repos/{p_owner}/{p_repo}/compare/{base}...{head}",
                timeout=15,
            )
            if r.status_code == 200:
                return int(r.json().get("ahead_by") or 0) > 0
        except Exception:
            pass
        return True  # uncertain -> keep
```

- [ ] **Step 5: Emit fork signals in `_build_feed_scripts`** (only for forks, so community entries stay clean). After the `has_params` emission block from Task 2.2, add:

```python
                if enr.get("fork"):
                    entry["fork"] = True
                    entry["fork_ahead"] = bool(enr.get("fork_ahead"))
```
Bump the version line to:
```python
    FEED_LOGIC_VERSION = 5  # v5: + fork/fork_ahead (installability of forks)
```

- [ ] **Step 6: Add feed-emission tests** in `tasks/test_feed.py`, right after the `feed_voices_emitted` check (reuses the `rows_v` defined there):

```python
sf = NornsScraper._build_feed_scripts(inst, rows_v, {("o", "foo"): {"fork": True, "fork_ahead": True}})
check("feed_fork_emitted", (sf["foo"].get("fork"), sf["foo"].get("fork_ahead")), (True, True))
sf2 = NornsScraper._build_feed_scripts(inst, rows_v, {("o", "foo"): {"fork": False}})
check("feed_fork_omitted_when_not_fork", "fork" in sf2["foo"], False)
```

- [ ] **Step 7: Run tests + import**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_feed.py && ~/.virtualenvs/nornslist-vhmg/bin/python -c "import norns_scraper_discourse"`
Expected: `ALL N CHECKS PASSED` + clean import.

- [ ] **Step 8: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_feed.py
git commit -m "feat(scraper): fork_ahead detection + emit fork signals in feed; FEED_LOGIC_VERSION=5"
```

---

## Phase 4 — build_data.py: derive installable + voice tags

### Task 4.1: Pure installability + voice-tag helpers

**Files:**
- Modify: `docs/build_data.py` (add module-level pure functions near `merge`)
- Create: `tasks/test_build_data.py`

Helper contracts:
- `HIGH_PRECISION_REDFLAG = re.compile(r"\b(tutorial|study|boilerplate|template|exercise|wip)\b", re.I)` — validated 0 false positives on curated.
- `derive_installable(row) -> (bool, list[str])`: returns `(installable, reasons)`. Non-installable iff (`row["fork"]` AND NOT `row["fork_ahead"]`) OR high-precision redflag in name/desc OR no usable facet at all (kind has none of script/mod/library/engine). Community rows (`fork` absent) and any mod/voice pack stay installable. **Diverged forks** (`fork` AND `fork_ahead`) stay installable — they're potentially valuable — and get tagged `fork` (the tag is applied in `merge()`, Task 4.2). Unmodified/behind-only forks (`fork` AND NOT `fork_ahead`) are the only forks excluded.
- `voice_tags(voices) -> list[str]`: umbrella `"additional voice"` iff `provides` non-empty; plus subtype tags (`nb`, `mx.samples`, `mx.synths`, `sc-engine`) and role tags (`nb-ready` when nb in uses but not provides).

- [ ] **Step 1: Write the failing test** — create `tasks/test_build_data.py`:

```python
"""Offline unit tests for docs/build_data.py pure derivation helpers."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
import build_data as B  # noqa: E402

fails = []; _checks = 0
def check(name, got, want):
    global _checks; _checks += 1
    if got != want: fails.append(f"{name}: got {got!r} want {want!r}")

# --- installability gate ---
def inst(**row):
    row.setdefault("name", "x"); row.setdefault("desc", ""); row.setdefault("kind", ["script"])
    row.setdefault("fork", False); row.setdefault("fork_ahead", False); row.setdefault("source", "github")
    return B.derive_installable(row)[0]

check("inst_plain_script", inst(), True)
check("inst_fork_stale_excluded", inst(fork=True), False)            # unmodified/behind-only fork
check("inst_fork_ahead_kept", inst(fork=True, fork_ahead=True), True)  # diverged fork: valuable, kept
check("inst_mod_ok", inst(kind=["mod"]), True)              # mods are installable
check("inst_engine_only_ok", inst(kind=["library", "engine"]), True)  # ack-shape dep is installable
check("inst_no_facet_excluded", inst(kind=[]), False)
check("inst_redflag_tutorial", inst(name="norns-tutorial"), False)
check("inst_redflag_in_desc", inst(desc="a study group exercise"), False)

# curated false-positive guards (these MUST stay installable — low-precision words)
check("inst_acid_test_ok", inst(name="acid-test", desc="generative acid basslines"), True)
check("inst_grid_test_ok", inst(name="grid-test", desc="A utility script for testing grids"), True)
check("inst_playground_ok", inst(name="twins", desc="randomized dual granular playground"), True)
check("inst_example_ok", inst(name="passthrough", desc="midi passthrough library with examples"), True)
check("inst_community_never_fork", inst(source="community", name="awake"), True)

# --- voice tags ---
check("vt_umbrella_on_provides", "additional voice" in B.voice_tags({"provides": ["nb"], "uses": [], "systems": ["nb"]}), True)
check("vt_no_umbrella_uses_only", "additional voice" in B.voice_tags({"provides": [], "uses": ["nb"], "systems": ["nb"]}), False)
check("vt_subtype_nb", "nb" in B.voice_tags({"provides": ["nb"], "uses": [], "systems": ["nb"]}), True)
check("vt_nb_ready_on_uses", "nb-ready" in B.voice_tags({"provides": [], "uses": ["nb"], "systems": ["nb"]}), True)
check("vt_mx_subtype", "mx.samples" in B.voice_tags({"provides": [], "uses": ["mx.samples"], "systems": ["mx.samples"]}), True)
check("vt_empty", B.voice_tags({"provides": [], "uses": [], "systems": []}), [])

if fails:
    print("FAILED:"); [print("  -", f) for f in fails]; sys.exit(1)
print(f"ALL {_checks} CHECKS PASSED")
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_build_data.py`
Expected: FAIL with `AttributeError: module 'build_data' has no attribute 'derive_installable'`

- [ ] **Step 3: Implement** — add to `docs/build_data.py` above `def merge(`:

```python
import re as _re

# Validated against the 348 curated scripts: ZERO false positives. Low-precision
# words (test|playground|example|sandbox) were excluded — they matched 5 real
# curated scripts (acid-test, grid-test, twins, passthrough, cheat_codes_2).
HIGH_PRECISION_REDFLAG = _re.compile(r"\b(tutorial|study|boilerplate|template|exercise|wip)\b", _re.I)
_USABLE_FACETS = {"script", "mod", "library", "engine"}


def derive_installable(row: dict) -> tuple[bool, list[str]]:
    """(installable, reasons). Non-installable ONLY on high-precision structural
    signals so no curated script is ever mis-hidden: an unmodified/behind-only
    fork (no commits ahead of upstream), a high-precision red-flag in name/desc,
    or a repo with no usable facet at all. Mods, voice packs, engine/library deps,
    and diverged forks stay installable. Community rows are never forks (canonical)
    and default installable."""
    reasons = []
    # Some forks are valuable: only EXCLUDE unmodified/behind-only forks (no commits
    # ahead of upstream). A diverged fork (fork_ahead) stays installable and is tagged
    # 'fork' in merge(). Unknown ahead-state is treated as ahead upstream (kept).
    if row.get("fork") and not row.get("fork_ahead"):
        reasons.append("fork-stale")
    blob = f"{row.get('name','')} {row.get('desc','')}"
    if HIGH_PRECISION_REDFLAG.search(blob):
        reasons.append("red-flag")
    kind = row.get("kind") or []
    if not any(k in _USABLE_FACETS for k in kind):
        reasons.append("no-facet")
    return (not reasons, reasons)


def voice_tags(voices: dict) -> list[str]:
    """UI tags from a voices object. Umbrella 'additional voice' iff another script
    can load this voice (provides non-empty). Plus per-system subtype tags and an
    'nb-ready' tag for consumers."""
    voices = voices or {}
    provides = voices.get("provides") or []
    uses = voices.get("uses") or []
    tags = []
    if provides:
        tags.append("additional voice")
    for s in voices.get("systems") or []:
        tags.append(s)
    if "nb" in uses and "nb" not in provides:
        tags.append("nb-ready")
    # dedupe preserving order
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t); out.append(t)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_build_data.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/build_data.py tasks/test_build_data.py
git commit -m "feat(build_data): pure derive_installable + voice_tags helpers"
```

### Task 4.2: Carry `fork`; wire voices + installable into `merge()`

**Files:**
- Modify: `docs/build_data.py:126` (`_normalize_row`) and `:190-240` (`merge`)

- [ ] **Step 1: Carry `fork` through `_normalize_row`.** In the returned dict (~line 126, near `"archived"`), add:

```python
        "fork": bool(d.get("fork")),
```

- [ ] **Step 2: Replace the nb block in `merge()`.** Find (~line 198-222):

```python
        nb = bool(enr.get("nb"))
```
(keep going to the nb write block). Replace the `nb = bool(...)` line with:
```python
        voices = enr.get("voices") or {}
        # Fork signals for installability: `_normalize_row` carries `fork` from the
        # catalog for discovered rows; feed enrichment additionally carries `fork`
        # and `fork_ahead` (computed via the compare call). Prefer the feed values.
        if enr.get("fork") is not None:
            s["fork"] = bool(enr.get("fork"))
        s["fork_ahead"] = bool(enr.get("fork_ahead"))
```
Then replace the nb write block (~216-222):
```python
        if nb:
            s["nb"] = True
            # provides = registers nb voice(s); uses = consumes them. Drives the
            # "nb voices" vs "nb-ready" chip distinction on the catalog site.
            role = enr.get("nb_role")
            if role:
                s["nb_role"] = role
```
with:
```python
        if voices.get("systems"):
            s["voices"] = {"provides": list(voices.get("provides") or []),
                           "uses": list(voices.get("uses") or []),
                           "systems": list(voices.get("systems") or [])}
            for t in voice_tags(voices):                 # surface as filterable tags
                if t.lower() not in {x.lower() for x in s["tags"]}:
                    s["tags"].append(t)
        # Provenance tag for ALL forks (ahead or not), so even kept diverged forks
        # are visibly forks; installability is handled separately below.
        if s.get("fork") and "fork" not in {x.lower() for x in s["tags"]}:
            s["tags"].append("fork")
```

- [ ] **Step 3: Update the `facets` dict** (~line 231). Replace:

```python
        s["facets"] = {
            "engine": bool(engine) or ("engine" in kind),
            "nb": nb,
            "demo": bool(s["demo"]),
            "images": bool(images),
            "readme": bool(readme),
            "doc": bool(s["doc"]),
        }
```
with:
```python
        installable, reasons = derive_installable(s)
        if reasons:
            s["installable_reason"] = reasons
        provides = bool((voices.get("provides") or []))
        s["facets"] = {
            "engine": bool(engine) or ("engine" in kind),
            "voices": provides,                 # umbrella: another script can load it
            "installable": installable,
            "demo": bool(s["demo"]),
            "images": bool(images),
            "readme": bool(readme),
            "doc": bool(s["doc"]),
        }
```

- [ ] **Step 4: Verify build_data runs end-to-end** against the committed data:

Run: `cd /Users/seajay/gits/nornslist && ~/.virtualenvs/nornslist-vhmg/bin/python docs/build_data.py && ~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_build_data.py`
Expected: build_data writes its data output without error; test passes.

- [ ] **Step 5: Commit**

```bash
git add docs/build_data.py
git commit -m "feat(build_data): derive facets.voices/installable + voice tags from feed"
```

### Task 4.3: Catalog SPA frontend — voice chips + default-on installable filter

The public catalog SPA (`docs/index.html`, a single self-contained file) consumes
`docs/data.json`. It currently renders an nb chip from the removed `s.facets.nb`/
`s.nb_role`, and has no installable filter. Update it to the new schema and add a
**default-on** `installable` filter, mirroring the existing `src`-defaults-to-community
pattern (default value omitted from the URL when unchanged, restorable, shown as a
removable active-filter chip). No unit-test harness here — verified by grep for stale
refs + the Phase 8 visual smoke test.

**Files:**
- Modify: `docs/index.html` (the `FEATS` list, `state` init, `facetsHTML`, `readState`/`writeState`)

- [ ] **Step 1: Replace the feature list.** Find (line ~326):
```javascript
  const FEATS=[["demo","▶ demo"],["images","▣ screenshots"],["readme","≣ readme"],["engine","⚙ engine"],["nb","♪ nb voice"],["doc","📖 docs"]];
```
Replace with (drop `nb`, add `installable` first + `voices`):
```javascript
  const FEATS=[["installable","✓ installable"],["voices","♪ additional voice"],["demo","▶ demo"],["images","▣ screenshots"],["readme","≣ readme"],["engine","⚙ engine"],["doc","📖 docs"]];
```
(`FEAT_LBL = Object.fromEntries(FEATS)` updates automatically — no separate edit.)

- [ ] **Step 2: Default the installable filter ON.** Find (line ~321):
```javascript
  const state = { all:[], src:new Set(["community"]), type:new Set(), feat:new Set(), tags:new Set(), q:"", sort:"updated:desc", only:"" };
```
Replace `feat:new Set()` with `feat:new Set(["installable"])`:
```javascript
  const state = { all:[], src:new Set(["community"]), type:new Set(), feat:new Set(["installable"]), tags:new Set(), q:"", sort:"updated:desc", only:"" };
```

- [ ] **Step 3: Add `isDefaultFeat` and use it in `writeState`.** Find (line ~663):
```javascript
  const isDefaultSrc = () => state.src.size===1 && state.src.has("community");
```
Add right after it:
```javascript
  const isDefaultFeat = () => state.feat.size===1 && state.feat.has("installable");
```
Then find (line ~674):
```javascript
      if(state.feat.size) p.set("feat", [...state.feat].join(","));
```
Replace with (so an explicit empty `feat=` records "installable turned off"; absent = default on):
```javascript
      if(!isDefaultFeat()) p.set("feat", [...state.feat].join(","));
```

- [ ] **Step 4: Default-on in `readState`.** Find (line ~703):
```javascript
    state.feat = setOf(p.get("feat"));
```
Replace with:
```javascript
    // absent feat → default {installable}; present (even empty) → honor it (empty = installable off)
    state.feat = p.has("feat") ? setOf(p.get("feat")) : new Set(["installable"]);
```

- [ ] **Step 5: Render voice chips from the new schema.** Find the nb block in `facetsHTML` (lines ~375-378):
```javascript
    if(s.facets && s.facets.nb){
      const provides = s.nb_role !== "uses";   // default to "voices" unless explicitly a consumer
      chips.push(`<span class="facet" style="--fc:var(--accent2)" title="${provides?'registers nb (note-bridge) voice(s)':'consumes nb voices from another script'}">♪ ${provides?'nb voices':'nb-ready'}</span>`);
    }
```
Replace with:
```javascript
    if(s.voices){
      const pr = s.voices.provides||[], us = s.voices.uses||[];
      if(pr.includes("nb"))
        chips.push(`<span class="facet" style="--fc:var(--accent2)" title="registers nb (note-bridge) voice(s) other scripts can play">♪ nb voices</span>`);
      else if(us.includes("nb"))
        chips.push(`<span class="facet" style="--fc:var(--accent2)" title="plays through nb — needs an nb voice installed to make sound">♪ nb-ready</span>`);
      (s.voices.systems||[]).filter(x => x!=="nb").forEach(x =>
        chips.push(`<span class="facet" style="--fc:var(--accent2)" title="voice system: ${esc(x)}">♪ ${esc(x)}</span>`));
    }
```

- [ ] **Step 6: Confirm no stale references remain.**
Run: `grep -n "facets\.nb\b\|s\.nb_role\|nbRole\|\"nb\",\|'nb'," docs/index.html`
Expected: no functional matches (a `♪` label string is fine; the `["nb",...]` FEATS entry must be gone).
Also sanity-check the file still has balanced braces by loading it conceptually — confirm the `FEATS`, `state`, `facetsHTML`, `readState`, `writeState` edits are syntactically intact (matching `(`/`)` and backticks in the replaced template strings).

- [ ] **Step 7: Rebuild data + eyeball.**
Run: `cd /Users/seajay/gits/nornslist && ~/.virtualenvs/nornslist-vhmg/bin/python docs/build_data.py`
Expected: writes `docs/data.json` without error. (Voice/installable values are only fully populated after a live scrape — Phase 8 — but the frontend must not error on the current data.)

- [ ] **Step 8: Commit**
```bash
git add docs/index.html
git commit -m "feat(site): voice chips + default-on installable filter in catalog SPA"
```

---

## Phase 5 — Census + regression tasks

### Task 5.1: Curated installability regression

**Files:**
- Create: `tasks/test_curated_installable.py`

- [ ] **Step 1: Write the test** (this is the spec's hard gate — zero curated exclusions):

```python
"""Regression: every curated (norns.community) script must derive installable=true.
Curated = hand-vetted ground truth; any exclusion is a classifier false positive.
Run: ~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_curated_installable.py"""
import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "docs"))
import build_data as B  # noqa: E402

catalog = json.load(open(os.path.join(ROOT, "catalog.json")))["scripts"]
feed = json.load(open(os.path.join(ROOT, "feed.json")))
fm = feed.get("scripts", feed)

bad = []
for row in catalog:
    if row.get("source") != "community":
        continue
    nrow = B._normalize_row(row)
    enr = fm.get(nrow["name"].lower(), {})
    nrow["kind"] = list(nrow.get("kind") or enr.get("facets") or [])
    installable, reasons = B.derive_installable(nrow)
    if not installable:
        bad.append((nrow["name"], reasons))

if bad:
    print(f"FAILED: {len(bad)} curated scripts wrongly non-installable:")
    for n, r in bad[:40]:
        print(f"  - {n}: {r}")
    sys.exit(1)
print(f"PASS: all {sum(1 for r in catalog if r.get('source')=='community')} curated scripts installable")
```

- [ ] **Step 2: Run it**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_curated_installable.py`
Expected: PASS. If any fail, the classifier is too aggressive — fix `derive_installable` (do NOT special-case names; fix the rule) and re-run.

- [ ] **Step 3: Commit**

```bash
git add tasks/test_curated_installable.py
git commit -m "test: curated-set installability regression (zero false exclusions)"
```

### Task 5.2: Voice census + installability breakdown

**Files:**
- Create: `tasks/voice_census.py`
- Modify: `tasks/discovery_census.py` (append installability breakdown)

- [ ] **Step 1: Write `tasks/voice_census.py`:**

```python
"""Voice-classification census over catalog.json + feed.json (read-only).
Run: ~/.virtualenvs/nornslist-vhmg/bin/python tasks/voice_census.py"""
import os, json, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
feed = json.load(open(os.path.join(ROOT, "feed.json")))
fm = feed.get("scripts", feed)
cat = json.load(open(os.path.join(ROOT, "catalog.json")))["scripts"]
src = {(r.get("Name") or "").strip().lower(): r.get("source") for r in cat}

prov = collections.Counter(); uses = collections.Counter()
n_umbrella = {"community": 0, "github": 0}
for name, e in fm.items():
    v = e.get("voices") or {}
    for p in v.get("provides") or []: prov[p] += 1
    for u in v.get("uses") or []: uses[u] += 1
    if v.get("provides"):
        n_umbrella[src.get(name, "github")] = n_umbrella.get(src.get(name, "github"), 0) + 1

print("=== voice PROVIDERS (umbrella 'additional voice') by system ===")
for k, c in prov.most_common(): print(f"  {c:4d}  {k}")
print("=== voice CONSUMERS (uses) by system ===")
for k, c in uses.most_common(): print(f"  {c:4d}  {k}")
print(f"=== umbrella-tagged scripts: {n_umbrella} ===")
```

- [ ] **Step 2: Run it** (sanity — needs a feed.json with voices; after a scrape):

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/voice_census.py`
Expected: prints provider/consumer breakdown (consumers should be far more than the old `uses=1`).

- [ ] **Step 3: Append installability breakdown to `tasks/discovery_census.py`.** At the end of the script's main output, add:

```python
    # --- installability reclassification breakdown (added with voice/install work) ---
    import json as _json
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
    import build_data as _B
    _cat = _json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "catalog.json")))["scripts"]
    _by = {}
    for _r in _cat:
        _nr = _B._normalize_row(_r)
        _ok, _why = _B.derive_installable(_nr)
        _key = "installable" if _ok else ",".join(_why)
        _by[_key] = _by.get(_key, 0) + 1
    print("\n=== installability breakdown (catalog.json) ===")
    for _k, _c in sorted(_by.items(), key=lambda x: -x[1]):
        print(f"  {_c:4d}  {_k}")
```

- [ ] **Step 4: Run discovery_census** (read-only mode):

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/discovery_census.py --authors 0`
Expected: existing output + the new installability breakdown table.

- [ ] **Step 5: Commit**

```bash
git add tasks/voice_census.py tasks/discovery_census.py
git commit -m "feat(tasks): voice census + installability breakdown in discovery census"
```

---

## Phase 6 — Parity contract test

### Task 6.1: Shared-fixture parity test

**Files:**
- Create: `tasks/test_voice_parity.py`

Pins the scraper's classification to a canonical fixture set. The SAME fixtures must be kept in sync with ingenue's detector (copy this fixture block into ingenue's test when its detector is updated in Phase 7).

- [ ] **Step 1: Write the test:**

```python
"""Parity contract: canonical Lua/SC snippets -> expected voice classification.
These fixtures are the shared source of truth between the nornslist scraper
(_detect_voices) and ingenue's analyze_dir/index.html live detector. Keep both
sides matching this file.
Run: ~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_voice_parity.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from norns_scraper_discourse import NornsScraper as S  # noqa: E402

# (blob, paths, facets, repo) -> expected {provides, uses}
FIXTURES = [
    ('nb:add_player("x", p)', ["m.lua"], ["mod"], "m", {"provides": ["nb"], "uses": []}),
    ('local nb=require"nb/lib/nb"', ["m.lua"], ["script"], "m", {"provides": [], "uses": ["nb"]}),
    ('require("mx.samples/lib/mx.samples")', ["m.lua"], ["script"], "m", {"provides": [], "uses": ["mx.samples"]}),
    ('require("mx.synths/lib/mx.synths")', ["m.lua"], ["script"], "m", {"provides": [], "uses": ["mx.synths"]}),
    ("SynthDef", ["lib/Engine_Ack.sc"], ["library", "engine"], "ack", {"provides": ["sc-engine"], "uses": []}),
    ("SynthDef", ["a.lua", "lib/Engine_A.sc"], ["script", "engine"], "a", {"provides": [], "uses": []}),
    ('engine.name="Rings"', ["m.lua"], ["script"], "m", {"provides": [], "uses": ["sc-engine"]}),
    ("crow.output[1].volts=1", ["m.lua"], ["script"], "m", {"provides": [], "uses": []}),
]

fails = []
for i, (blob, paths, facets, repo, want) in enumerate(FIXTURES):
    got = S._detect_voices(blob, paths, set(), facets, repo)
    if got["provides"] != want["provides"] or got["uses"] != want["uses"]:
        fails.append(f"fixture {i} ({repo}): got p={got['provides']} u={got['uses']} "
                     f"want p={want['provides']} u={want['uses']}")
if fails:
    print("PARITY FAILED:"); [print("  -", f) for f in fails]; sys.exit(1)
print(f"PARITY OK: {len(FIXTURES)} fixtures")
```

- [ ] **Step 2: Run it**

Run: `~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_voice_parity.py`
Expected: `PARITY OK: 8 fixtures`

- [ ] **Step 3: Commit**

```bash
git add tasks/test_voice_parity.py
git commit -m "test: voice-classification parity fixtures (scraper<->ingenue contract)"
```

---

## Phase 7 — ingenue lockstep (separate repo: `~/gits/ingenue`)

> All paths below are in `~/gits/ingenue`. Commit in that repo. No feed back-compat: `voices` is the only schema. Manual/visual testing before deploy (no JS unit harness here).

### Task 7.1: server.py analyze_dir emits `voices`

**Files:**
- Modify: `~/gits/ingenue/web/server.py` (`analyze_dir`, the `rep = {...}` block ~line 1895)

- [ ] **Step 1: Add voice classification to the report.** In `analyze_dir`, after `nb_referenced = ...` (~line 1872) and before `rep = {`, add:

```python
    # Voice classification mirroring nornslist _detect_voices (parity fixtures in
    # nornslist tasks/test_voice_parity.py). provides = voices other scripts load.
    v_provides, v_uses = [], []
    if re.search(r"nb:add_player", blob) or re.match(r"nb[_-]", name.lower()):
        v_provides.append("nb")
    elif nb_referenced and "nb" not in bundled:
        v_uses.append("nb")
    for lib in reqs:
        if lib in ("mx.samples", "mx.synths"):
            v_uses.append(lib)
    has_top_script = any("/" not in f and f.endswith(".lua") for f in files)
    if self_engines and not has_top_script:
        v_provides.append("sc-engine")
    if missing_engines or [e for e in engines if e.lower() not in self_engines]:
        v_uses.append("sc-engine")
    voices = {"provides": sorted(set(v_provides)),
              "uses": sorted(set(u for u in v_uses if u not in v_provides))}
    voices["systems"] = sorted(set(voices["provides"]) | set(voices["uses"]))
```

Then add to the `rep` dict (after the `"nb": ...` line):
```python
        "voices": voices,
```
Leave the legacy `"nb": nb_referenced and "nb" not in bundled` in the report ONLY if other server code reads it; otherwise remove it. Verify:

Run: `grep -n '"nb"\|rep\[.nb.\|\.get(.nb.' ~/gits/ingenue/web/server.py`
If nothing outside this dict reads it, delete the `"nb":` line.

- [ ] **Step 2: Sanity check** the server module parses:

Run: `cd ~/gits/ingenue && python3 -c "import ast; ast.parse(open('web/server.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit (in ingenue)**

```bash
cd ~/gits/ingenue && git add web/server.py
git commit -m "feat(deps): analyze_dir emits voices object (parity with nornslist)"
```

### Task 7.2: index.html consumes `voices` (feed + live + render)

**Files:**
- Modify: `~/gits/ingenue/web/index.html` (lines ~1389, ~2336-2358, ~2571, ~2921-2922, ~2977, ~3331)

- [ ] **Step 1: Feed merge (~line 1389).** Replace:

```javascript
        if(x.engine&&!e.engine) e.engine=x.engine; if(x.nb) e.nb=1; if(x.nb_role) e.nbRole=x.nb_role;
```
with:
```javascript
        if(x.engine&&!e.engine) e.engine=x.engine; if(x.voices) e.voices=x.voices;
```

- [ ] **Step 2: Umbrella tag predicate (~line 2336-2337).** Replace:

```javascript
const NB_TAG='additional voice';
function isNbVoice(p){ if(p.nb) return true; const t=(p.tags||[]).map(x=>String(x).toLowerCase());
```
with (preserving the rest of the function body that follows on its tag-based fallback):
```javascript
const NB_TAG='additional voice';
function provGetsVoice(p){ return !!(p.voices && (p.voices.provides||[]).length); }
function isNbVoice(p){ if(provGetsVoice(p)) return true; const t=(p.tags||[]).map(x=>String(x).toLowerCase());
```

- [ ] **Step 3: Deps report row (~line 2571).** Replace:

```javascript
  if(rep.nb) rows.push(R('🎹','nb voices','plays through nb — install an nb voice (the nb_* player mods) to make sound'));
```
with:
```javascript
  if(rep.voices && (rep.voices.uses||[]).includes('nb'))
    rows.push(R('🎹','nb-ready','plays through nb — install an nb voice (the nb_* player mods) to make sound'));
  if(rep.voices && (rep.voices.provides||[]).includes('nb'))
    rows.push(R('🎹','nb voices','registers nb voice(s) other scripts can play'));
```

- [ ] **Step 4: Live JS detector (~line 2921-2922).** Replace:

```javascript
          if(/nb:add_player/.test(blob)){ nb=1; nbRole='provides'; }          // registers voices → a voice pack
          else if(/nb:add_param|require[\s(]*['"][^'"]*nb\/lib/.test(blob)){ nb=1; nbRole='uses'; } // assignable voices in-script
```
with (compute a `voices` object instead of `nb`/`nbRole`):
```javascript
          let vProv=[],vUse=[];
          if(/nb:add_player/.test(blob)){ vProv.push('nb'); }
          else if(/nb:add_param|require[\s(]*['"][^'"]*nb\/lib/.test(blob)){ vUse.push('nb'); }
          (blob.match(/require[\s(]+['"]([A-Za-z0-9_.\-]+)\/lib/g)||[]).forEach(m=>{
            const lib=(m.match(/['"]([A-Za-z0-9_.\-]+)\/lib/)||[])[1];
            if(lib==='mx.samples'||lib==='mx.synths') vUse.push(lib);
          });
          const voices={provides:[...new Set(vProv)],uses:[...new Set(vUse)].filter(u=>!vProv.includes(u))};
          voices.systems=[...new Set([...voices.provides,...voices.uses])];
```

- [ ] **Step 5: Entry assembly (~line 2977).** Replace the `nb:c.nb?1:0, nbRole:c.nbRole` fields with `voices:c.voices||voices` as appropriate to the local variable in scope (the live-built `voices` from Step 4). Inspect the surrounding `classifyRepo` return to wire the variable name correctly:

Run: `sed -n '2960,2985p' ~/gits/ingenue/web/index.html`
Then set the entry's `voices` to the computed object and remove `nb`/`nbRole`.

- [ ] **Step 6: Chip render (~line 3331).** Replace:

```javascript
  if(p.nb) out+=`<span class="facet" style="--fc:var(--ok,#6c6)">🎹 ${p.nbRole==='provides'?'nb voices':'nb-ready'}</span>`;
```
with:
```javascript
  if(p.voices){ const pr=(p.voices.provides||[]),us=(p.voices.uses||[]);
    if(pr.includes('nb')) out+=`<span class="facet" style="--fc:var(--ok,#6c6)">🎹 nb voices</span>`;
    else if(us.includes('nb')) out+=`<span class="facet" style="--fc:var(--ok,#6c6)">🎹 nb-ready</span>`;
    pr.filter(s=>s!=='nb').forEach(s=>out+=`<span class="facet">🎚 ${s}</span>`);
  }
```

- [ ] **Step 7: Confirm no stale `nb`/`nbRole` reads remain**

Run: `grep -n "\.nb\b\|nbRole\|p\.nb\|e\.nb\|x\.nb\b\|nb_role" ~/gits/ingenue/web/index.html`
Expected: no functional reads of the old fields (matches inside words like `nb-ready` strings are fine).

- [ ] **Step 8: Visual smoke test.** Load the ingenue web UI against a feed.json that has the new `voices` schema (post-scrape, or a hand-edited fixture). Verify: the "additional voice" tag filter still works, provider scripts show the 🎹 "nb voices" chip, consumers show "nb-ready", and the deps modal lists voice rows. Capture before/after.

- [ ] **Step 9: Commit (in ingenue)**

```bash
cd ~/gits/ingenue && git add web/index.html
git commit -m "feat(ui): consume voices schema (replaces nb/nb_role) from feed + live detector"
```

---

## Phase 8 — Live verification (scrape + end-to-end)

### Task 8.1: Targeted live re-enrichment + spot-check

**Files:** none (verification only)

- [ ] **Step 1: Run a bounded live enrichment** to populate `voices` for a known sample. Use the scraper's feed path on a small set (or full nightly if acceptable). Then run the censuses:

```bash
~/.virtualenvs/nornslist-vhmg/bin/python tasks/voice_census.py
~/.virtualenvs/nornslist-vhmg/bin/python tasks/discovery_census.py --authors 0
```
Expected: consumers (`uses`) now in the dozens (vs the old 1); providers ≈ prior 18+; installability breakdown shows forks/red-flags split out, community all installable.

- [ ] **Step 2: Curated regression on the freshly built data**

```bash
~/.virtualenvs/nornslist-vhmg/bin/python docs/build_data.py
~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_curated_installable.py
```
Expected: PASS (zero curated exclusions).

- [ ] **Step 3: Spot-check known scripts** in feed.json:

```bash
~/.virtualenvs/nornslist-vhmg/bin/python -c "
import json; fm=json.load(open('feed.json')); fm=fm.get('scripts',fm)
for k in ['nb_drumcrow','forge','dreamsequence','acid-test']:
    print(k, fm.get(k,{}).get('voices'))
"
```
Expected: `nb_drumcrow` provides nb; `forge` uses nb; `dreamsequence` does NOT show nb in uses (vendored — the bundled-exclusion working); `acid-test` no provides (own engine).

- [ ] **Step 4: Run the full test suite**

```bash
for t in test_feed test_build_data test_voice_parity test_curated_installable; do
  ~/.virtualenvs/nornslist-vhmg/bin/python tasks/$t.py || break
done
```
Expected: all PASS.

- [ ] **Step 5: Commit refreshed data** (catalog.json/feed.json/docs data) per the repo's normal data-commit convention.

---

## Self-Review notes (addressed)

- **Spec coverage:** corpus foundation (P0), voices replace nb/nb_role (P1–2, removal in 2.3), fork capture (P3), installability default-on filter (P4), curated regression + censuses (P5), parity test (P6), ingenue lockstep replace (P7), live verification incl. dreamsequence vendored case (P8). mx-provides is intentionally out of scope per spec (uses-only in `_detect_voices`).
- **Type consistency:** `voices` shape `{provides, uses, systems}` (lists) is identical across `_detect_voices`, `_build_feed_scripts`, `merge()`, `voice_tags`, ingenue. `derive_installable` returns `(bool, list)` everywhere. `facets.voices`/`facets.installable` booleans.
- **No placeholders:** every code step shows the code; commands have expected output.
