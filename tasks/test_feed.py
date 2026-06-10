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
_checks = 0


def check(name, got, want):
    global _checks
    _checks += 1
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
check("feed_no_voices_key_when_empty", "voices" in scripts["awake"], False)

# voices emitted when non-empty
rows_v = [{"Name": "Foo", "Tags": "x", "Last Updated": "2024-01-01", "Project URL": "https://github.com/o/foo"}]
enr_v = {("o", "foo"): {"voices": {"provides": ["nb"], "uses": [], "systems": ["nb"]}}}
sv = NornsScraper._build_feed_scripts(inst, rows_v, enr_v)
check("feed_voices_emitted", sv["foo"].get("voices"), {"provides": ["nb"], "uses": [], "systems": ["nb"]})
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

# --- Phase 2: README media extraction (video > audio precedence) ---
md_video = "Here's a demo: https://www.youtube.com/watch?v=abc123XYZ_0 and audio https://soundcloud.com/x/y"
check("media_prefers_video", S._extract_readme_media(md_video), "https://www.youtube.com/watch?v=abc123XYZ_0")

md_audio_only = "listen: https://soundcloud.com/artist/track-name"
check("media_audio_when_no_video", S._extract_readme_media(md_audio_only), "https://soundcloud.com/artist/track-name")

md_vimeo = "[demo](https://vimeo.com/123456789)"
check("media_vimeo", S._extract_readme_media(md_vimeo), "https://vimeo.com/123456789")

check("media_none", S._extract_readme_media("no links here, just prose"), "")
check("media_ignores_plain_github", S._extract_readme_media("https://github.com/o/r"), "")

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

# vendored nb: host requires its OWN bundled nb copy -> NOT an external nb dep.
# Same blob flips to uses=["nb"] when nb is NOT bundled — proving the guard works.
_blob_nb = 'local nb = require "nb/lib/nb"'
check("v_nb_vendored_not_uses",
      "nb" in S._detect_voices(_blob_nb, ["main.lua", "lib/nb/lib/nb.lua"], {"nb"}, ["script"], "host")["uses"],
      False)
check("v_nb_not_vendored_uses",
      "nb" in S._detect_voices(_blob_nb, ["main.lua"], set(), ["script"], "host")["uses"],
      True)

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

# --- Phase 1: runnable-script signals from corpus ---
check("init_params_both", S._has_init_params("function init()\nparams:add{}\nend"), (True, True))
check("init_params_init_only", S._has_init_params("function init ()\n end"), (True, False))
check("init_params_neither", S._has_init_params("local x = 1"), (False, False))

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

if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print(f"ALL {_checks} CHECKS PASSED")
