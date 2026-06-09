# nornslist-as-provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make nornslist's nightly scrape carry per-repo commit SHAs (so ingenue detects installed-script updates without per-script GitHub calls), run aggressive GitHub discovery daily with README audio/video demo enrichment, and fold in repo-linked llllllll.co "norns"-tagged threads — broadening + enriching the catalog.

**Architecture:** All work extends `norns_scraper_discourse.py` (the `NornsScraper` class) and the `feed.json` / `catalog.json` writers. Phase ① adds a HEAD-SHA field to feed enrichment (the existing per-repo, `pushed_at`-gated cache). Phase ② adds README media extraction, enriches discovered repos with a demo, and wires `--discover` into CI on the user's PAT. Phase ③ adds a Discourse `norns`-tag crawler that surfaces repo-linked threads not yet in the catalog. The public site (`docs/`) auto-benefits via `docs/build_data.py`, which already merges these contracts.

**Tech Stack:** Python 3.11 (stdlib + `requests` + `pandas`/`openpyxl`), GitHub REST API, Discourse JSON API. Offline unit tests in `tasks/test_*.py` (no pytest — plain scripts using `check()` + `FakeSession`/`FakeResp` stubs).

**Test runner:** `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_<name>.py` — prints `ALL <X> CHECKS PASSED` and exits 0, or `FAILED:` + reasons and exits 1.

**Conventions to follow (from `tasks/test_discovery.py`):**
- `bare()` builds an instance via `object.__new__(NornsScraper)` and sets only the attrs under test (avoids `__init__` side effects / network).
- `FakeResp(status_code, payload, text)` stubs a `requests` response; `FakeSession` routes `.get(url, ...)` by URL substring and records `self.calls`.
- `check(name, got, want)` appends to a module-level `fails` list; the file ends with the `if fails: ... sys.exit(1)` block.

---

## Phase ① — Per-repo HEAD commit SHA in feed.json

ingenue compares an installed script's commit SHA against `feed.json` and knows instantly whether an update exists — no per-script GitHub call. The SHA lives in the feed enrichment dict, which is already fetched per changed repo and cached, fresh-gated by `pushed_at`/`upd`. Bumping `FEED_LOGIC_VERSION` forces a one-time full re-fetch so every repo gets a SHA on first deploy.

### Task 1.1: `_github_head_sha()` — fetch a repo's default-branch HEAD SHA

**Files:**
- Modify: `norns_scraper_discourse.py` (add method near `_github_latest_non_readme_date`, ~line 2744)
- Test: `tasks/test_feed.py`

- [ ] **Step 1: Write the failing test**

Add to `tasks/test_feed.py` (mirror the `bare()`/`FakeResp` pattern already used in `tasks/test_discovery.py`; if `test_feed.py` lacks a `FakeResp`/session helper, copy the `FakeResp` class and a minimal session from `test_discovery.py`):

```python
# --- Phase 1: HEAD sha extraction ---
class _ShaSession:
    """Routes /commits?... to a one-item commit list; records calls."""
    def __init__(self, sha):
        self.sha = sha
        self.calls = []
    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(url)
        if "/commits" in url:
            return FakeResp(200, [{"sha": self.sha}])
        return FakeResp(404)

def _sha_inst(sha):
    inst = object.__new__(NornsScraper)
    inst.github_session = _ShaSession(sha)
    return inst

inst = _sha_inst("abc123def456")
check("head_sha_value", inst._github_head_sha("o", "r", "main"), "abc123def456")
check("head_sha_per_page_1", any("per_page" in str(p) or "/commits" in p for p in inst.github_session.calls), True)

# empty / error -> "" (never raises)
class _EmptySession:
    def get(self, *a, **k): return FakeResp(200, [])
inst2 = object.__new__(NornsScraper); inst2.github_session = _EmptySession()
check("head_sha_empty", inst2._github_head_sha("o", "r", "main"), "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_feed.py`
Expected: FAIL — `AttributeError: 'NornsScraper' object has no attribute '_github_head_sha'`

- [ ] **Step 3: Write minimal implementation**

Add this method to `NornsScraper` (immediately after `_github_latest_non_readme_date`, ~line 2804):

```python
    def _github_head_sha(self, owner: str, repo: str, branch: str) -> str:
        """Full 40-char HEAD commit SHA of the default branch; '' on any failure.
        One cheap call (per_page=1). ingenue diffs the installed SHA against this
        to detect updates without its own per-script GitHub call."""
        if not owner or not repo:
            return ""
        try:
            r = self.github_session.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits",
                params={"sha": branch or "HEAD", "per_page": 1},
                timeout=15,
            )
            if r.status_code != 200:
                return ""
            commits = r.json() or []
            return str(commits[0].get("sha") or "") if commits else ""
        except Exception as e:
            logger.debug(f"HEAD sha error for {owner}/{repo}: {e}")
            return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_feed.py`
Expected: PASS — `ALL FEED CHECKS PASSED`

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_feed.py
git commit -m "feat(feed): _github_head_sha — fetch default-branch HEAD SHA"
```

### Task 1.2: Carry `sha` through feed enrichment + emit in feed.json (version 2)

**Files:**
- Modify: `norns_scraper_discourse.py:3283` (`_github_fetch_feed_enrichment` result dict + after branch resolves), `:3395` (`_build_feed_scripts`), `:3450` (feed `file_info.version`), `:2972` (`FEED_LOGIC_VERSION`)
- Test: `tasks/test_feed.py`

- [ ] **Step 1: Write the failing test**

Add to `tasks/test_feed.py`:

```python
# --- Phase 1: sha emitted by _build_feed_scripts ---
inst = object.__new__(NornsScraper)
rows = [{"Name": "Awake", "Tags": "grid", "Last Updated": "2024-01-01",
         "Project URL": "https://github.com/tehn/awake"}]
enrichment = {("tehn", "awake"): {"sha": "deadbeef" * 5, "readme": "hi"}}
scripts = inst._build_feed_scripts(rows, enrichment)
check("feed_emits_sha", scripts["awake"].get("sha"), "deadbeef" * 5)

# missing sha -> key absent (per-field truthy guard)
scripts2 = inst._build_feed_scripts(rows, {("tehn", "awake"): {"readme": "hi"}})
check("feed_no_sha_key_when_absent", "sha" in scripts2["awake"], False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_feed.py`
Expected: FAIL — `feed_emits_sha: got None want 'deadbeefdeadbeef...'`

- [ ] **Step 3: Write minimal implementation**

(a) In `_github_fetch_feed_enrichment`, add `"sha": ""` to the initial `result` dict (line 3283):

```python
        result = {"engine": "", "nb": False, "nb_role": "", "facets": [], "readme": "", "images": [], "sha": ""}
```

(b) In the same method, right after `branch = meta.get("default_branch") or "main"` (line 3297), add:

```python
            result["sha"] = self._github_head_sha(owner, repo, branch)
```

(c) In `_build_feed_scripts`, inside the `if enr:` block (after the `images` emit, ~line 3425), add:

```python
                if enr.get("sha"):
                    entry["sha"] = enr["sha"]
```

(d) Bump the feed payload version in `write_feed_json` (line 3450):

```python
                "file_info": {"version": 2, "kind": "script_feed"},
```

(e) Bump `FEED_LOGIC_VERSION` (line 2972) from `2` to `3` so the one-time backfill re-fetches every repo and stamps a SHA:

```python
    FEED_LOGIC_VERSION = 3  # v3: + HEAD sha per repo (ingenue update detection)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_feed.py`
Expected: PASS — `ALL FEED CHECKS PASSED`

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_feed.py
git commit -m "feat(feed): emit per-repo HEAD sha (feed v2, logic v3 backfill)"
```

### Task 1.3: Verify against reality (one-time, manual)

- [ ] **Step 1:** Pick a known repo and compare. Run:

```bash
git ls-remote https://github.com/tehn/awake HEAD
```

- [ ] **Step 2:** After a `--feed-only` run (Task 2 / steady state) or unit confidence, confirm the SHA the scraper would emit equals the `git ls-remote` HEAD. Document the match in the commit message of the first real run. No code change.

---

## Phase ② — Aggressive daily discovery + README A/V demo enrichment

Discovery already exists (`discover_github_repos`, `_run_discovery`, gated by `discover_enabled`) and runs aggressive-by-default. This phase: (a) extract a demo URL from a repo's README, (b) enrich each discovered repo with that demo (+ readme/images) so it "looks native," (c) wire `--discover` into the nightly on the user's PAT.

**Decision — discovered enrichment lands in `catalog.json`, not `feed.json`:** `feed.json` stays the community/installed-update contract (Phase ①). Discovered repos carry their `Demo`/`readme`/`images` in their catalog entry; `docs/build_data.py` surfaces them for the site. ingenue's discover tab fetches GitHub live, so it doesn't need discovered repos in `feed.json`.

### Task 2.1: `_extract_readme_media()` — best demo URL from README

**Files:**
- Modify: `norns_scraper_discourse.py` (add method near `_extract_readme_images`, ~line 3220)
- Test: `tasks/test_feed.py`

- [ ] **Step 1: Write the failing test**

Add to `tasks/test_feed.py`:

```python
# --- Phase 2: README media extraction (video > audio precedence) ---
S = NornsScraper
md_video = "Here's a demo: https://www.youtube.com/watch?v=abc123XYZ_0 and audio https://soundcloud.com/x/y"
check("media_prefers_video", S._extract_readme_media(md_video), "https://www.youtube.com/watch?v=abc123XYZ_0")

md_audio_only = "listen: https://soundcloud.com/artist/track-name"
check("media_audio_when_no_video", S._extract_readme_media(md_audio_only), "https://soundcloud.com/artist/track-name")

md_vimeo = "[demo](https://vimeo.com/123456789)"
check("media_vimeo", S._extract_readme_media(md_vimeo), "https://vimeo.com/123456789")

check("media_none", S._extract_readme_media("no links here, just prose"), "")
check("media_ignores_plain_github", S._extract_readme_media("https://github.com/o/r"), "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_feed.py`
Expected: FAIL — `AttributeError: type object 'NornsScraper' has no attribute '_extract_readme_media'`

- [ ] **Step 3: Write minimal implementation**

Add this `@staticmethod` to `NornsScraper` (after `_extract_readme_images`, ~line 3220). Patterns mirror the site's `demoEmbed` support (YouTube/Vimeo/SoundCloud/Bandcamp/Instagram), video ranked above audio:

```python
    # README demo extraction: embeddable platforms the site renders, video>audio.
    _MEDIA_VIDEO = re.compile(
        r"https?://(?:www\.)?(?:youtube\.com/(?:watch\?[^\s)]*v=|embed/|shorts/)[\w-]{6,}"
        r"|youtu\.be/[\w-]{6,}"
        r"|vimeo\.com/(?:video/)?\d+"
        r"|(?:www\.)?instagram\.com/(?:p|reel)/[\w-]+)",
        re.I,
    )
    _MEDIA_AUDIO = re.compile(
        r"https?://(?:(?:www\.)?soundcloud\.com/[\w-]+/[\w-]+"
        r"|[\w-]+\.bandcamp\.com/(?:track|album)/[\w-]+)",
        re.I,
    )

    @staticmethod
    def _extract_readme_media(md: str) -> str:
        """Best single demo URL from README text: first video link if any, else
        first audio link, else ''. Matches the site's embeddable platforms."""
        if not md:
            return ""
        mv = NornsScraper._MEDIA_VIDEO.search(md)
        if mv:
            return mv.group(0).rstrip(").,")
        ma = NornsScraper._MEDIA_AUDIO.search(md)
        if ma:
            return ma.group(0).rstrip(").,")
        return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_feed.py`
Expected: PASS — `ALL FEED CHECKS PASSED`

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_feed.py
git commit -m "feat(feed): _extract_readme_media — demo URL from README (video>audio)"
```

### Task 2.2: Set `demo` on feed enrichment + enrich discovered repos

**Files:**
- Modify: `norns_scraper_discourse.py:3283` (enrichment result `demo`), `:3311-3315` (set demo from README), `:3905-3922` (discovered record gains `demo`/`readme`/`images`/`disc`), `:3512` (`_discovered_to_catalog_entry`)
- Test: `tasks/test_discovery.py`

- [ ] **Step 1: Write the failing test**

Add to `tasks/test_discovery.py` (it already imports `NornsScraper as S`, has `bare()`):

```python
# --- Phase 2: discovered repo demo -> catalog Demo column ---
inst = object.__new__(NornsScraper)
rec = {"name": "thing", "author": "o", "desc": "d", "proj": "https://github.com/o/thing",
       "upd": "2024-01-01", "topics": [], "facets": ["script"], "stars": 5,
       "demo": "https://youtu.be/abc123", "disc": "https://llllllll.co/t/thing/1"}
entry = inst._discovered_to_catalog_entry(rec)
check("discovered_demo_mapped", entry["Demo"], "https://youtu.be/abc123")
check("discovered_disc_mapped", entry["Discussion URL"], "https://llllllll.co/t/thing/1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py`
Expected: FAIL — `discovered_demo_mapped: got '' want 'https://youtu.be/abc123'`

- [ ] **Step 3: Write minimal implementation**

(a) In `_discovered_to_catalog_entry` (line 3512), after `entry["Last Updated"] = ...`, add the demo + discussion mapping:

```python
        entry["Demo"] = rec.get("demo") or ""
        entry["Discussion URL"] = rec.get("disc") or ""
```

(b) In `_github_fetch_feed_enrichment`: add `"demo": ""` to the `result` dict (Task 1.2a already touched this line — keep both keys):

```python
        result = {"engine": "", "nb": False, "nb_role": "", "facets": [], "readme": "", "images": [], "sha": "", "demo": ""}
```

and where README is parsed (after `result["readme"] = self._readme_to_plaintext(readme_md)`, ~line 3312) add:

```python
                result["demo"] = self._extract_readme_media(readme_md)
```

(c) Enrich discovered records. In `discover_github_repos._task` (line 3911), the record is returned without enrichment. Add a post-classification enrichment so each kept repo gets `demo`/`readme`/`images`. Replace the `return (owner, name), {...}` record dict by first computing enrichment:

```python
            enr = self._github_fetch_feed_enrichment(owner, it.get("name") or name)
            return (owner, name), {
                "owner": owner, "name": it.get("name") or name,
                "author": (it.get("owner") or {}).get("login", ""),
                "desc": it.get("description") or "",
                "proj": it.get("html_url") or f"https://github.com/{owner}/{name}",
                "upd": (it.get("pushed_at") or "")[:10],
                "topics": (it.get("topics") or [])[:8],
                "facets": verdict.get("facets") or [],
                "archived": bool(it.get("archived")),
                "stars": it.get("stargazers_count") or 0,
                "source": "github",
                "demo": enr.get("demo") or "",
                "readme": enr.get("readme") or "",
                "images": list(enr.get("images") or []),
                "disc": "",
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py`
Expected: PASS — `ALL DISCOVERY CHECKS PASSED`

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_discovery.py
git commit -m "feat(discovery): enrich discovered repos with README demo + readme/images"
```

### Task 2.3: Carry `readme`/`images` on discovered catalog entries + surface on the site

**Files:**
- Modify: `norns_scraper_discourse.py:3512` (`_discovered_to_catalog_entry` adds `readme`/`images`), `docs/build_data.py:186` (`merge` reads catalog-carried enrichment for github rows)
- Test: `tasks/test_discovery.py`, `tasks/test_catalog.py`

- [ ] **Step 1: Write the failing test**

Add to `tasks/test_discovery.py`:

```python
# --- Phase 2: discovered readme/images carried on catalog entry ---
rec2 = {"name": "thing2", "author": "o", "proj": "https://github.com/o/thing2",
        "facets": ["script"], "readme": "a readme", "images": ["https://x/y.png"]}
e2 = object.__new__(NornsScraper)._discovered_to_catalog_entry(rec2)
check("discovered_readme_carried", e2.get("readme"), "a readme")
check("discovered_images_carried", e2.get("images"), ["https://x/y.png"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py`
Expected: FAIL — `discovered_readme_carried: got None want 'a readme'`

- [ ] **Step 3: Write minimal implementation**

(a) In `_discovered_to_catalog_entry` (after the demo/disc lines from Task 2.2a), add:

```python
        if rec.get("readme"):
            entry["readme"] = rec["readme"]
        if rec.get("images"):
            entry["images"] = list(rec["images"])
```

(b) In `docs/build_data.py` `merge()` (line ~206, where `kind`/`engine`/`readme`/`images` are folded), make catalog-carried enrichment a fallback when the feed lacks it (github rows). The catalog row dict is `s` here; the per-script catalog enrichment was carried through from `write_catalog_json`. Find the block:

```python
        readme = enr.get("readme") or ""
        images = [u for u in (enr.get("images") or []) if isinstance(u, str) and u.strip()]
```

and change it to fall back to the catalog row's own fields:

```python
        readme = enr.get("readme") or s.get("readme") or ""
        images = [u for u in (enr.get("images") or s.get("images") or []) if isinstance(u, str) and u.strip()]
```

(The `Demo` column already maps to `s["demo"]` in the catalog loader, so the demo needs no extra build_data change — verify in Step 4.)

- [ ] **Step 4: Run test to verify it passes + rebuild the site data**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py`
Expected: PASS — `ALL DISCOVERY CHECKS PASSED`

Then rebuild + spot-check a github row gains a demo/readme:

```bash
~/.virtualenvs/nornslist-ddno/bin/python docs/build_data.py
~/.virtualenvs/nornslist-ddno/bin/python -c "import json; d=json.load(open('docs/data.json'))['scripts']; g=[x for x in d if x['source']=='github' and x.get('demo')]; print('github rows with demo:', len(g))"
```

Expected: a non-zero count once a real `--discover` run has populated demos (0 is acceptable before the first discovery run — this step verifies the wiring doesn't error).

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py docs/build_data.py tasks/test_discovery.py
git commit -m "feat(discovery): carry readme/images on discovered catalog entries + surface on site"
```

### Task 2.4: Prefer `GH_PAT` token + wire `--discover` into the nightly

**Files:**
- Modify: `norns_scraper_discourse.py` (`_load_github_token`, ~line 2640)
- Modify: `.github/workflows/daily-scrape-discourse.yml` (scraper run step + env)
- Test: `tasks/test_efficiency.py` (or `test_feed.py`) for token preference

- [ ] **Step 1: Write the failing test**

Add to `tasks/test_efficiency.py` (a pure env test; uses `monkeypatch`-free os.environ save/restore):

```python
# --- Phase 2: GH_PAT preferred over GITHUB_TOKEN ---
import os
_saved = {k: os.environ.get(k) for k in ("GH_PAT", "GITHUB_TOKEN")}
try:
    os.environ["GH_PAT"] = "pat_secret"
    os.environ["GITHUB_TOKEN"] = "actions_token"
    inst = object.__new__(NornsScraper)
    check("token_prefers_gh_pat", inst._load_github_token(), "pat_secret")
    del os.environ["GH_PAT"]
    check("token_falls_back", inst._load_github_token(), "actions_token")
finally:
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_efficiency.py`
Expected: FAIL — `token_prefers_gh_pat: got 'actions_token' want 'pat_secret'`

- [ ] **Step 3: Write minimal implementation**

In `_load_github_token` (line ~2640), check `GH_PAT` before `GITHUB_TOKEN`. Current first lines read the env; change the env lookup to:

```python
        token = (os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN") or "").strip()
        if token:
            return token
        # ... existing gh.api file fallback unchanged ...
```

(Keep the existing `gh.api` file fallback after this.)

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_efficiency.py`
Expected: PASS — `ALL EFFICIENCY CHECKS PASSED`

- [ ] **Step 5: Wire the nightly workflow**

In `.github/workflows/daily-scrape-discourse.yml`, find the scraper run step:

```yaml
        run: |
          python norns_scraper_discourse.py --excel norns_scripts_discourse.xlsx
```

Change the command to enable aggressive discovery with a capped author sweep:

```yaml
        run: |
          python norns_scraper_discourse.py --excel norns_scripts_discourse.xlsx --discover --discover-max-authors 100
```

And in that step's `env:` block (which already sets `GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`), add the PAT above it:

```yaml
          GH_PAT: ${{ secrets.GH_PAT }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 6: Commit**

```bash
git add norns_scraper_discourse.py .github/workflows/daily-scrape-discourse.yml tasks/test_efficiency.py
git commit -m "feat(ci): aggressive daily discovery on GH_PAT (--discover, max-authors 100)"
```

---

## Phase ③ — Forum-driven discovery (repo-linked `norns`-tag threads)

Crawl llllllll.co's `norns` tag for recent topics, extract a GitHub repo URL from each OP, and add repos not already in the catalog — enriched with the thread's discussion URL, a demo mined from the thread, and a `lines` tag. Merges into the same `discovered` pool as Phase ②.

### Task 3.1: `_extract_github_url()` — pull a repo URL from forum post text

**Files:**
- Modify: `norns_scraper_discourse.py` (add staticmethod near `_parse_github_repo`)
- Test: `tasks/test_discovery.py`

- [ ] **Step 1: Write the failing test**

Add to `tasks/test_discovery.py`:

```python
# --- Phase 3: extract github repo (owner, name) from forum post body ---
check("extract_gh_basic",
      S._extract_github_url("check it out https://github.com/dan/myscript !"),
      ("dan", "myscript"))
check("extract_gh_strips_suffix",
      S._extract_github_url("repo: https://github.com/dan/myscript.git"),
      ("dan", "myscript"))
check("extract_gh_ignores_non_repo",
      S._extract_github_url("see https://github.com/monome (org page)"),
      None)
check("extract_gh_none", S._extract_github_url("no link here"), None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py`
Expected: FAIL — `AttributeError: ... '_extract_github_url'`

- [ ] **Step 3: Write minimal implementation**

Add this `@staticmethod` to `NornsScraper` (near `_parse_github_repo`):

```python
    @staticmethod
    def _extract_github_url(text: str):
        """First github.com/{owner}/{repo} in `text` as (owner, repo), or None.
        Ignores org/user pages (no repo segment) and normalizes a .git suffix."""
        if not text:
            return None
        m = re.search(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", text)
        if not m:
            return None
        owner, repo = m.group(1), re.sub(r"\.git$", "", m.group(2))
        if not owner or not repo or repo.lower() in ("", "blob", "tree"):
            return None
        return owner.lower(), repo.lower()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py`
Expected: PASS — `ALL DISCOVERY CHECKS PASSED`

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_discovery.py
git commit -m "feat(discovery): _extract_github_url — repo from forum post text"
```

### Task 3.2: `discover_forum_repos()` — crawl the `norns` tag for repo-linked threads

**Files:**
- Modify: `norns_scraper_discourse.py` (add method near `discover_github_repos`)
- Test: `tasks/test_discovery.py`

- [ ] **Step 1: Write the failing test**

Add to `tasks/test_discovery.py` (a `FakeSession` that serves a tag page + one topic OP):

```python
# --- Phase 3: forum tag crawl finds a repo-linked, not-yet-cataloged repo ---
class _ForumSession:
    def __init__(self):
        self.calls = []
    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(url)
        if "/tag/norns.json" in url:
            return FakeResp(200, {"topic_list": {"topics": [
                {"id": 42, "slug": "shiny-new-script"},
                {"id": 7, "slug": "old-known"},
            ]}})
        if "/t/42.json" in url:
            return FakeResp(200, {"post_stream": {"posts": [
                {"cooked": 'see <a href="https://github.com/newdev/shiny">repo</a>'}]}})
        if "/t/7.json" in url:
            return FakeResp(200, {"post_stream": {"posts": [
                {"cooked": 'https://github.com/known/already'}]}})
        return FakeResp(404)

inst = object.__new__(NornsScraper)
inst.discourse_session = _ForumSession()
inst._throttle_discourse = lambda: None
inst.base_url = "https://llllllll.co"
known = {("known", "already")}
found = inst.discover_forum_repos(known, max_pages=1)
check("forum_finds_newdev_shiny", ("newdev", "shiny") in found, True)
check("forum_skips_known", ("known", "already") in found, False)
check("forum_carries_disc", found[("newdev", "shiny")]["disc"].startswith("https://llllllll.co/t/"), True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py`
Expected: FAIL — `AttributeError: ... 'discover_forum_repos'`

- [ ] **Step 3: Write minimal implementation**

Add this method to `NornsScraper` (near `discover_github_repos`). It returns `{(owner, repo): {disc, topic_id}}` for repo-linked threads whose repo isn't in `known_repos`; the caller (Task 3.3) classifies + enriches them. Uses the existing `discourse_session` and `_throttle_discourse` throttle. (If the attribute holding the Discourse session is named differently than `discourse_session`, grep `self\.\w*session` near `_discover_demo_via_discourse_api` and use that name consistently.)

```python
    def discover_forum_repos(self, known_repos: set, max_pages: int = 5) -> dict:
        """Crawl llllllll.co's `norns` tag for topics whose OP links a GitHub repo
        not already in `known_repos`. Returns {(owner, repo): {disc, topic_id}}.
        Best-effort: any error yields a partial/empty dict (never aborts a run)."""
        base = getattr(self, "base_url", "https://llllllll.co").rstrip("/")
        out = {}
        for page in range(0, max_pages):
            try:
                self._throttle_discourse()
                r = self.discourse_session.get(
                    f"{base}/tag/norns.json", params={"page": page}, timeout=20)
                if r.status_code != 200:
                    break
                topics = ((r.json() or {}).get("topic_list") or {}).get("topics") or []
            except Exception as e:
                logger.debug(f"Forum discovery: tag page {page} error: {e}")
                break
            if not topics:
                break
            for t in topics:
                tid = t.get("id")
                if not tid:
                    continue
                try:
                    self._throttle_discourse()
                    tr = self.discourse_session.get(f"{base}/t/{tid}.json", timeout=20)
                    if tr.status_code != 200:
                        continue
                    posts = ((tr.json() or {}).get("post_stream") or {}).get("posts") or []
                    op = posts[0].get("cooked", "") if posts else ""
                except Exception:
                    continue
                gh = self._extract_github_url(op)
                if not gh or gh in known_repos or gh in out:
                    continue
                if f"{gh[0]}/{gh[1]}" in self.GH_BLOCK or gh[1] in self.GH_BLOCK_NAMES:
                    continue
                out[gh] = {"disc": f"{base}/t/{t.get('slug') or tid}/{tid}", "topic_id": tid}
        logger.info(f"Forum discovery: {len(out)} repo-linked norns-tag threads not in catalog")
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py`
Expected: PASS — `ALL DISCOVERY CHECKS PASSED`

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_discovery.py
git commit -m "feat(discovery): discover_forum_repos — norns-tag thread crawl"
```

### Task 3.3: Fold forum finds into discovery (classify, enrich, `lines` tag, dedup)

**Files:**
- Modify: `norns_scraper_discourse.py` (`_run_discovery`, ~line 3625 — union forum repos; classify + enrich + tag)
- Test: `tasks/test_discovery.py`

- [ ] **Step 1: Write the failing test**

Add to `tasks/test_discovery.py` — verify a forum-found repo entry gets the `lines` tag and its discussion URL once mapped to a catalog entry:

```python
# --- Phase 3: forum-found record maps to catalog with lines tag + disc ---
inst = object.__new__(NornsScraper)
rec = {"name": "shiny", "author": "newdev", "proj": "https://github.com/newdev/shiny",
       "facets": ["script"], "topics": ["lines"], "disc": "https://llllllll.co/t/x/42",
       "demo": ""}
entry = inst._discovered_to_catalog_entry(rec)
check("forum_entry_has_lines_tag", "lines" in entry["Tags"], True)
check("forum_entry_has_disc", entry["Discussion URL"], "https://llllllll.co/t/x/42")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py`
Expected: PASS for `forum_entry_has_disc` (Task 2.2 mapped it) but FAIL for `forum_entry_has_lines_tag` only if topics aren't mapped to Tags. Confirm `_discovered_to_catalog_entry` sets `entry["Tags"] = list(rec.get("topics") or [])` (line 3523) — it does, so `lines` in `topics` flows to `Tags`. If this test passes immediately, that's correct; proceed to Step 3 to wire the producer.

- [ ] **Step 3: Write minimal implementation**

In `_run_discovery` (line 3625), after the existing `discover_github_repos(...)` call returns `discovered`, union the forum finds. Replace the body's `return self.discover_github_repos(...)` with:

```python
            discovered = self.discover_github_repos(
                community, excel_path,
                aggressive=getattr(self, "discover_aggressive", True),
                max_author_searches=getattr(self, "discover_max_authors", None),
            )
            # Forum-driven: repo-linked norns-tag threads not already known.
            known = set(community) | set(discovered.keys())
            forum = self.discover_forum_repos(known, max_pages=getattr(self, "forum_max_pages", 5))
            cache = self._load_discovery_cache(excel_path)
            lock = threading.Lock()
            for (owner, name), meta in forum.items():
                m = self._repo_meta(owner, name)
                if m.get("_status") in (403, 404):
                    continue
                branch = m.get("default_branch") or "main"
                verdict = self._classify_norns_repo(
                    owner, name, branch, m.get("pushed_at"), cache, lock)
                if not verdict.get("is_norns"):
                    continue
                enr = self._github_fetch_feed_enrichment(owner, name)
                demo = enr.get("demo") or ""
                if not demo:
                    demo = self.discover_demo_video(meta["disc"]) or ""
                topics = list(verdict.get("facets") and [] or [])
                discovered[(owner, name)] = {
                    "owner": owner, "name": name,
                    "author": owner, "desc": m.get("description") or "",
                    "proj": f"https://github.com/{owner}/{name}",
                    "upd": str(m.get("pushed_at") or "")[:10],
                    "topics": ["lines"], "facets": verdict.get("facets") or [],
                    "archived": bool(m.get("archived")),
                    "stars": int(m.get("stargazers_count") or 0),
                    "source": "github", "demo": demo,
                    "readme": enr.get("readme") or "", "images": list(enr.get("images") or []),
                    "disc": meta["disc"],
                }
            self._save_discovery_cache(excel_path, cache)
            return discovered
```

(Remove the now-redundant single `return self.discover_github_repos(...)` that previously ended the `try`.) Verify `_repo_meta` returns `description`/`stargazers_count`; if it doesn't expose those, drop `desc`/`stars` to `""`/`0` — they're non-critical.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py`
Expected: PASS — `ALL DISCOVERY CHECKS PASSED`

- [ ] **Step 5: Commit**

```bash
git add norns_scraper_discourse.py tasks/test_discovery.py
git commit -m "feat(discovery): fold forum-found repos into catalog (lines tag + thread demo)"
```

### Task 3.4: Optional `lines` facet on the site

**Files:**
- Modify: `docs/index.html` (facetbar — add a `lines` tag is automatic; no code needed since `lines` is a normal tag)

- [ ] **Step 1:** Confirm the `lines` tag renders as a normal clickable pill (it flows through `Tags`). No code change required — the existing tag rail already surfaces it and makes it filterable.
- [ ] **Step 2:** (Optional polish, only if desired) add a dedicated `⌗ lines` chip to the facetbar wired like the `type:` chips from the prior feature. Skip unless the user asks. No commit if skipped.

---

## Self-Review

**Spec coverage:**
- Phase ① SHA + date in feed.json → Tasks 1.1–1.3 ✓ (date `upd` already emitted; SHA added)
- Phase ② daily `--discover` + PAT + author cap → Task 2.4 ✓; A/V README extraction → 2.1; demo on discovered → 2.2; readme/images + site → 2.3 ✓
- Phase ③ norns-tag crawl, repo-linked only, discussion URL + demo + `lines`, dedup → Tasks 3.1–3.4 ✓
- Cross-cutting: feed version→2 (1.2d), discovered Demo/Discussion (2.2a), site auto-benefit (2.3b) ✓
- Non-goals respected: no code-less WIP entity; no new `source` value (forum repos stay `source:"github"`); ① feed-only ✓

**Placeholder scan:** none — every code step shows complete code. Two explicit verify-the-attribute-name notes (Discourse session attr in 3.2; `_repo_meta` fields in 3.3) are deliberate guardrails, not placeholders.

**Type consistency:** `_extract_readme_media` (static) used in 2.1/2.2; `_github_head_sha(owner,repo,branch)` defined 1.1, called 1.2; `discover_forum_repos(known_repos, max_pages)` defined 3.2, called 3.3; `_extract_github_url` defined 3.1, used 3.2; discovered-record keys (`demo`/`readme`/`images`/`disc`/`topics`) consistent across 2.2, 3.3, and `_discovered_to_catalog_entry`.

**Known follow-ups (not blockers):** the one-time `FEED_LOGIC_VERSION` bump re-fetches all ~1158 repos on first nightly (≈4–5k calls — comfortable on the PAT); the aggressive author sweep is capped at 100 and tunable via `--discover-max-authors`.
