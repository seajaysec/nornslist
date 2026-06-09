"""Offline unit tests for the feed.json pure helpers (no network).

Run: ~/.virtualenvs/nornslist-ddno/bin/python tasks/test_feed.py
Exercises the deterministic, network-free building blocks of feed generation so
the GitHub-touching code can be trusted without a full 350-repo scrape.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from norns_scraper_discourse import NornsScraper  # noqa: E402

S = NornsScraper  # static/class helpers only — no instance/network needed
fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r} want {want!r}")


# --- engine from tree paths (definitive: Engine_<Name>.sc) ---
check(
    "engine_basic",
    S._engine_from_paths(["lib/Engine_PolyPerc.sc", "awake.lua", "README.md"]),
    "PolyPerc",
)
check("engine_none", S._engine_from_paths(["foo.lua", "x/y.sc"]), "")
check(
    "engine_multi_deterministic",
    S._engine_from_paths(["Engine_Zzz.sc", "lib/Engine_Aaa.sc"]),
    "Aaa",
)
check(
    "engine_not_substring",
    S._engine_from_paths(["lib/MyEngine_Helper.sc"]),
    "",  # must match the Engine_<Name>.sc convention, not arbitrary .sc files
)

# --- nb detection (best-effort heuristic) ---
check("nb_filename", S._detect_nb("", ["lib/nb_voices.lua"]), True)
check("nb_suffix_file", S._detect_nb("", ["lib/myscript_nb.lua"]), True)
check("nb_readme_phrase", S._detect_nb("This adds an nb voice for you", []), True)
check("nb_note_bridge", S._detect_nb("Registers a note bridge player", []), True)
check("nb_negative", S._detect_nb("number of beats in the loop", ["main.lua"]), False)

# --- badge vs real image classification ---
check("badge_shields", S._is_badge_url("https://img.shields.io/badge/x.svg"), True)
check("badge_actions", S._is_badge_url("https://github.com/a/b/workflows/ci/badge.svg"), True)
check("badge_svg", S._is_badge_url("https://example.com/logo.svg"), True)
check("image_png_not_badge", S._is_badge_url("https://example.com/screenshot.png"), False)
check("looks_like_png", S._looks_like_image("https://x/y/shot.PNG?raw=true"), True)
check("looks_like_ghuser", S._looks_like_image("https://user-images.githubusercontent.com/1/2"), True)
check("looks_like_negative", S._looks_like_image("https://example.com/page.html"), False)

# --- README image extraction + relative resolution ---
inst = object.__new__(NornsScraper)  # bypass __init__/network; only pure methods used
md = (
    "# Title\n"
    "![badge](https://img.shields.io/badge/build-passing.svg)\n"
    "![shot](docs/screenshot.png)\n"
    '<img src="/images/ui.jpg" width="400">\n'
    "![remote](https://user-images.githubusercontent.com/9/8)\n"
)
imgs = NornsScraper._extract_readme_images(inst, md, "alice", "cool-script", "main")
check(
    "images_badge_dropped",
    any("shields.io" in u for u in imgs),
    False,
)
check(
    "images_relative_resolved",
    "https://raw.githubusercontent.com/alice/cool-script/main/docs/screenshot.png" in imgs,
    True,
)
check(
    "images_leading_slash_resolved",
    "https://raw.githubusercontent.com/alice/cool-script/main/images/ui.jpg" in imgs,
    True,
)
check(
    "images_remote_kept",
    "https://user-images.githubusercontent.com/9/8" in imgs,
    True,
)

# --- README -> plaintext ---
pt = NornsScraper._readme_to_plaintext(
    "# Heading\n\nSome **bold** and a [link](http://x).\n\n```\ncode block\n```\n\n- bullet one\n"
)
check("readme_no_md_markers", ("#" in pt or "**" in pt or "```" in pt), False)
check("readme_link_text_kept", "link" in pt and "http://x" not in pt, True)
check("readme_prose_kept", "Some bold and a link" in pt, True)
check("readme_truncates", len(NornsScraper._readme_to_plaintext("x " * 2000)) <= S.FEED_README_MAXLEN + 4, True)

# --- tags list parsing ---
check("tags_split", NornsScraper._tags_list("drone, grid, drone, "), ["drone", "grid"])
check("tags_list_input", NornsScraper._tags_list(["A", "a", "B"]), ["A", "B"])
check("tags_empty", NornsScraper._tags_list(""), [])

# --- cache freshness logic ---
today = S._today_iso()
LV = S.FEED_LOGIC_VERSION
check("cache_fresh_same_upd", NornsScraper._feed_cache_fresh(inst, {"source_upd": "2024-01-01", "fetched_at": today, "logic_version": LV}, "2024-01-01"), True)
check("cache_stale_changed_upd", NornsScraper._feed_cache_fresh(inst, {"source_upd": "2024-01-01", "fetched_at": today, "logic_version": LV}, "2024-02-02"), False)
check("cache_stale_error", NornsScraper._feed_cache_fresh(inst, {"source_upd": "2024-01-01", "fetched_at": today, "logic_version": LV, "error": True}, "2024-01-01"), False)
check("cache_stale_old_ttl", NornsScraper._feed_cache_fresh(inst, {"source_upd": "x", "fetched_at": "2000-01-01", "logic_version": LV}, "x"), False)
check("cache_stale_logic_bump", NornsScraper._feed_cache_fresh(inst, {"source_upd": "x", "fetched_at": today, "logic_version": LV + 1}, "x"), False)
check("cache_stale_no_logic_version", NornsScraper._feed_cache_fresh(inst, {"source_upd": "x", "fetched_at": today}, "x"), False)

# --- build feed scripts map (keying, validation, field gating) ---
rows = [
    {"Name": "Awake", "Tags": "grid, generative", "Last Updated": "2024-03-12", "Project URL": "https://github.com/monome/awake"},
    {"Name": "NoUpd", "Tags": "drone", "Last Updated": "not-a-date", "Project URL": ""},
    {"Name": "", "Tags": "skip", "Last Updated": "2024-01-01", "Project URL": ""},
]
enrichment = {("monome", "awake"): {"engine": "PolyPerc", "nb": False, "readme": "desc", "images": ["https://x/y.png"]}}
scripts = NornsScraper._build_feed_scripts(inst, rows, enrichment)
check("feed_key_lowercased", "awake" in scripts, True)
check("feed_engine_set", scripts["awake"].get("engine"), "PolyPerc")
check("feed_nb_omitted_when_false", "nb" in scripts["awake"], False)
check("feed_tags", scripts["awake"].get("tags"), ["grid", "generative"])
check("feed_upd_valid", scripts["awake"].get("upd"), "2024-03-12")
check("feed_invalid_upd_dropped", "upd" in scripts.get("noupd", {}), False)
check("feed_empty_name_skipped", "" in scripts, False)

# --- Phase 1: HEAD sha extraction ---
class _ShaSession:
    """Routes /commits?... to a one-item commit list; records calls."""
    def __init__(self, sha):
        self.sha = sha
        self.calls = []
    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, params))
        if "/commits" in url:
            return FakeResp(200, [{"sha": self.sha}])
        return FakeResp(404)

class FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.headers = {}
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(str(self.status_code))

def _sha_inst(sha):
    inst = object.__new__(NornsScraper)
    inst.github_session = _ShaSession(sha)
    return inst

inst_sha = _sha_inst("abc123def456")
check("head_sha_value", inst_sha._github_head_sha("o", "r", "main"), "abc123def456")
check("head_sha_per_page_1", any(p and p.get("per_page") == 1 for (_u, p) in inst_sha.github_session.calls), True)

# empty / error -> "" (never raises)
class _EmptySession:
    def get(self, *a, **k): return FakeResp(200, [])
inst2 = object.__new__(NornsScraper); inst2.github_session = _EmptySession()
check("head_sha_empty", inst2._github_head_sha("o", "r", "main"), "")

if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print(f"ALL {41 - 0} CHECKS PASSED")
