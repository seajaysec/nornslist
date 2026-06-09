"""Offline unit tests for GitHub discovery (roadmap #3, no network).

Run: ~/.virtualenvs/nornslist-ddno/bin/python tasks/test_discovery.py

Covers the norns classifier gate (structural proof, NORNS_FP content gate, and
the engine/-directory-is-not-proof fix that kept monome/linux out), cache
freshness, the discovered->catalog mapping, and write_catalog_json dedup/source
tagging (community wins; most-starred GitHub repo wins among same names).
"""
import os
import sys
import json
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from norns_scraper_discourse import NornsScraper  # noqa: E402

S = NornsScraper
fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r} want {want!r}")


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


def tree(paths):
    return FakeResp(200, {"tree": [{"type": "blob", "path": p} for p in paths]})


class FakeSession:
    """Routes /git/trees/ to a tree response and /contents/ to a file body."""
    def __init__(self, paths, keyfile_body=""):
        self.paths = paths
        self.keyfile_body = keyfile_body
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        if "/git/trees/" in url:
            return tree(self.paths)
        if "/contents/" in url:
            return FakeResp(200, text=self.keyfile_body)
        return FakeResp(404)


def bare():
    inst = object.__new__(NornsScraper)
    inst._repo_meta_cache = {}
    inst._repo_meta_lock = threading.Lock()
    inst.max_workers = 4
    return inst


def classify(paths, keyfile_body=""):
    inst = bare()
    inst.github_session = FakeSession(paths, keyfile_body)
    lock = threading.Lock()
    v = inst._classify_norns_repo("o", "r", "main", "2024-01-01T00:00:00Z", {}, lock)
    return v, inst.github_session.calls


# --- structural proof: lib/mod.lua => norns, NO content read ---
v, calls = classify(["lib/mod.lua", "r.lua"])
check("mod_is_norns", v["is_norns"], True)
check("mod_no_content_read", any("/contents/" in c for c in calls), False)

# --- structural proof: a .sc engine file => norns, no content read ---
v, calls = classify(["Engine_Foo.sc", "r.lua"])
check("sc_is_norns", v["is_norns"], True)
check("sc_no_content_read", any("/contents/" in c for c in calls), False)

# --- content gate: top-level lua WITH the norns fingerprint => norns ---
v, calls = classify(["r.lua", "README.md"], keyfile_body="function init()\n  engine.name='x'\nend")
check("content_norns_true", v["is_norns"], True)
check("content_did_read", any("/contents/" in c for c in calls), True)

# --- content gate: top-level lua WITHOUT norns fingerprint => NOT norns ---
v, _ = classify(["r.lua"], keyfile_body="print('hello world')\nlocal x = 1")
check("content_non_norns_false", v["is_norns"], False)

# --- the monome/linux fix: engine/ DIRECTORY (no .sc) + no lua => NOT norns ---
v, calls = classify(["engine/snd.c", "Makefile", "kernel/sched.c"])
check("engine_dir_not_proof", v["is_norns"], False)
check("engine_dir_no_keyfile_no_read", any("/contents/" in c for c in calls), False)

# --- facets carried; logic_version stamped ---
v, _ = classify(["r.lua", "lib/mod.lua"], keyfile_body="norns.")
check("facets_script_and_mod", set(v["facets"]) >= {"script", "mod"}, True)
check("logic_version_stamped", v["logic_version"], S.DISCOVERY_LOGIC_VERSION)

# --- cache freshness ---
inst = bare()
today = S._today_iso()
fresh = {"is_norns": True, "pushed_at": "P", "classified_at": today, "logic_version": S.DISCOVERY_LOGIC_VERSION}
check("disc_fresh_ok", NornsScraper._discovery_fresh(inst, fresh, "P"), True)
check("disc_stale_pushed", NornsScraper._discovery_fresh(inst, fresh, "Q"), False)
check("disc_stale_logic", NornsScraper._discovery_fresh(
    inst, {**fresh, "logic_version": 999}, "P"), False)
check("disc_stale_old", NornsScraper._discovery_fresh(
    inst, {**fresh, "classified_at": "2000-01-01"}, "P"), False)

# --- discovered -> catalog entry mapping ---
inst = bare()
inst.FIELD_MAP = S.FIELD_MAP
rec = {"name": "Foo", "author": "alice", "desc": "a thing", "proj": "https://github.com/alice/foo",
       "upd": "2024-05-05", "topics": ["drone", "grid"], "facets": ["script", "engine"],
       "stars": 12, "archived": True, "source": "github"}
e = inst._discovered_to_catalog_entry(rec)
check("entry_name", e["Name"], "Foo")
check("entry_author", e["Author"], "alice")
check("entry_source", e["source"], "github")
check("entry_tags_from_topics", e["Tags"], ["drone", "grid"])
check("entry_facets", e["facets"], ["script", "engine"])
check("entry_archived", e["archived"], True)
check("entry_status_archived", e["status"], "archived")
check("entry_community_cols_blank", e["Discussion URL"], "")

# --- write_catalog_json: dedup (community wins) + most-starred github wins ---
inst = bare()
inst.FIELD_MAP = S.FIELD_MAP
community_rows = [{"Name": "Awake", "Tags": "grid", "Project URL": "https://github.com/monome/awake"}]
discovered = {
    ("monome", "awake"): {"name": "awake", "stars": 99, "source": "github", "facets": []},  # dup of community -> dropped
    ("a", "dup"): {"name": "Dup", "author": "a", "stars": 3, "source": "github", "facets": []},
    ("b", "dup"): {"name": "dup", "author": "b", "stars": 50, "source": "github", "facets": []},  # higher stars wins
    ("c", "new"): {"name": "Newthing", "author": "c", "stars": 1, "source": "github", "facets": []},
}
with tempfile.TemporaryDirectory() as tmp:
    xlsx = os.path.join(tmp, "s.xlsx")
    inst.write_catalog_json(community_rows, xlsx, discovered=discovered)
    out = json.load(open(os.path.join(tmp, "catalog.json")))["scripts"]
by_name = {s["Name"].lower(): s for s in out}
check("catalog_has_community_awake", by_name["awake"]["source"], "community")
check("catalog_dropped_github_awake_dup", len([s for s in out if s["Name"].lower() == "awake"]), 1)
check("catalog_dup_most_starred_wins", by_name["dup"]["Author"], "b")
check("catalog_has_newthing", by_name["newthing"]["source"], "github")
check("catalog_total", len(out), 3)  # awake(community) + dup(b) + newthing

# --- Phase 2: discovered repo demo + disc -> catalog columns ---
inst = object.__new__(NornsScraper)
rec = {"name": "thing", "author": "o", "desc": "d", "proj": "https://github.com/o/thing",
       "upd": "2024-01-01", "topics": [], "facets": ["script"], "stars": 5,
       "demo": "https://youtu.be/abc123", "disc": "https://llllllll.co/t/thing/1"}
entry = inst._discovered_to_catalog_entry(rec)
check("discovered_demo_mapped", entry["Demo"], "https://youtu.be/abc123")
check("discovered_disc_mapped", entry["Discussion URL"], "https://llllllll.co/t/thing/1")

# --- Phase 2: discovered readme/images carried on catalog entry ---
rec2 = {"name": "thing2", "author": "o", "proj": "https://github.com/o/thing2",
        "facets": ["script"], "readme": "a readme", "images": ["https://x/y.png"]}
e2 = object.__new__(NornsScraper)._discovered_to_catalog_entry(rec2)
check("discovered_readme_carried", e2.get("readme"), "a readme")
check("discovered_images_carried", e2.get("images"), ["https://x/y.png"])

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

if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL DISCOVERY CHECKS PASSED")
