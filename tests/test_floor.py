"""Floor + carry-forward: a previously-confirmed repo must not drop just because this run's
search missed it or its corpus fetch flaked. It drops only on a real 404 or a genuine
gate-fail (non-empty corpus that misses the fingerprint).
"""
import json
import re

import norns_ingest as ni

# minimal 1-level tree object for a repo with one top-level .lua → facet "script"
SCRIPT_TREE = {"entries": [{"name": "thing.lua", "type": "blob"}]}
REPO_RE = re.compile(r'repository\(owner:"([^"]+)",name:"([^"]+)"\)')


class FakeGH:
    """Answers the two GraphQL passes classify_batch makes. `exists` maps (o,n)→tree node;
    a repo absent from it 404s. `blobs` maps (o,n)→corpus text ("" simulates a fetch flake)."""

    def __init__(self, exists, blobs):
        self.exists, self.blobs = exists, blobs

    def graphql(self, q):
        repos = REPO_RE.findall(q)
        data = {}
        for i, (o, n) in enumerate(repos):
            alias = ni._gql_alias(i)
            key = (o, n)
            if "... on Blob" in q:                       # pass B: corpus
                data[alias] = {"f0": {"text": self.blobs.get(key, "")}}
            elif key in self.exists:                     # pass A: metadata
                data[alias] = {
                    "nameWithOwner": f"{o}/{n}", "pushedAt": "2024-01-01T00:00:00Z",
                    "stargazerCount": 0, "isPrivate": False, "isFork": False,
                    "isArchived": False, "description": "", "primaryLanguage": {"name": "Lua"},
                    "repositoryTopics": {"nodes": []}, "defaultBranchRef": {"name": "main"},
                    "parent": None, "object": self.exists[key],
                }
            # else: omit alias entirely → 404
        return {"data": data}

    def compare_ahead(self, *a, **k):
        return 1


def _prior(*keys):
    return {k: {"owner": k[0], "name": k[1], "author": k[0], "desc": "", "proj":
                f"https://github.com/{k[0]}/{k[1]}", "upd": "2024-01-01", "topics": [],
                "facets": ["script"], "voices": None, "engine": "", "has_init": False,
                "has_params": False, "has_image": False, "caps": [], "stars": 0,
                "archived": False, "fork": False, "fork_ahead": False, "richness": 0,
                "source": "github"} for k in keys}


def test_corpus_flake_carries_prior_forward():
    key = ("schollz", "ynth")
    gh = FakeGH(exists={key: SCRIPT_TREE}, blobs={key: ""})  # exists, but corpus empty
    recs = ni.classify_batch(gh, [key], prior=_prior(key))
    assert key in recs and recs[key]["carried"] is True


def test_404_prior_repo_is_dropped():
    key = ("gone", "repo")
    gh = FakeGH(exists={}, blobs={})  # not in metadata → 404
    recs = ni.classify_batch(gh, [key], prior=_prior(key))
    assert key not in recs


def test_no_longer_norns_is_dropped_not_carried():
    """Real corpus this run, but it misses the fingerprint → genuine drop, never carried."""
    key = ("someone", "repo")
    gh = FakeGH(exists={key: SCRIPT_TREE}, blobs={key: "print('not norns')"})
    recs = ni.classify_batch(gh, [key], prior=_prior(key))
    assert key not in recs


def test_fresh_repo_with_real_corpus_classifies():
    key = ("new", "script")
    gh = FakeGH(exists={key: SCRIPT_TREE}, blobs={key: "function redraw() end"})
    recs = ni.classify_batch(gh, [key], prior={})  # not a prior repo
    assert key in recs and not recs[key].get("carried")


def test_flake_without_prior_is_not_invented():
    """An empty corpus with NO prior verdict must not be admitted (no noise)."""
    key = ("unknown", "repo")
    gh = FakeGH(exists={key: SCRIPT_TREE}, blobs={key: ""})
    recs = ni.classify_batch(gh, [key], prior={})
    assert key not in recs


# ── prior_records / known_authors parse the written catalog schema ──
def _write_catalog(tmp_path):
    cat = {"scripts": [
        {"Name": "ynth", "Author": "schollz", "Description": "d",
         "Project URL": "https://github.com/schollz/ynth", "Last Updated": "2024-01-01",
         "Tags": ["a"], "facets": ["script"], "voices": None, "engine": "", "stars": 3,
         "status": "active", "has_init": True, "caps": ["grid"]},
    ]}
    p = tmp_path / "catalog.json"
    p.write_text(json.dumps(cat))
    return str(p)


def test_prior_records_roundtrips_fields(tmp_path):
    recs = ni.prior_records(_write_catalog(tmp_path))
    rec = recs[("schollz", "ynth")]
    assert rec["stars"] == 3 and rec["has_init"] is True and rec["caps"] == ["grid"]
    assert rec["facets"] == ["script"]


def test_known_authors_extracts_owner(tmp_path):
    assert ni.known_authors(_write_catalog(tmp_path)) == {"schollz"}


def test_missing_catalog_is_empty():
    assert ni.prior_records("/nonexistent/catalog.json") == {}
    assert ni.known_authors("/nonexistent/catalog.json") == set()


# ── dedup keys on (owner, name), not bare name ──
def _rec(owner, name, stars=0, facets=("script",), fork=False, fork_ahead=False):
    return {"owner": owner, "name": name, "author": owner, "desc": "", "stars": stars,
            "facets": list(facets), "fork": fork, "fork_ahead": fork_ahead}


def test_same_name_different_owner_both_kept():
    rows = ni.dedup_installable([_rec("SolsticeFX", "norns-bookworm", 1),
                                 _rec("reinerterig", "norns-bookworm", 2)])
    assert {(r["owner"], r["name"]) for r in rows} == {
        ("SolsticeFX", "norns-bookworm"), ("reinerterig", "norns-bookworm")}


def test_same_owner_name_case_collapses_to_higher_stars():
    rows = ni.dedup_installable([_rec("a", "Awake", 1), _rec("a", "awake", 5)])
    assert len(rows) == 1 and rows[0]["stars"] == 5


def test_stale_fork_excluded():
    rows = ni.dedup_installable([_rec("x", "fork", fork=True, fork_ahead=False)])
    assert rows == []


# ── per-owner sweep paginates past one page (the 60→1150 fix) ──
OWNER_RE = re.compile(r'repositoryOwner\(login:"([^"]+)"\).*?(?:,after:"([^"]+)")?\)\{pageInfo')


class PagingGH:
    """Serves repositoryOwner.repositories pages from an in-memory {login: [repo,...]}."""

    def __init__(self, repos_by_owner, page=100):
        self.repos, self.page, self.calls = repos_by_owner, page, 0

    def graphql(self, q):
        self.calls += 1
        data = {}
        for i, m in enumerate(OWNER_RE.finditer(q)):
            login, after = m.group(1), m.group(2)
            allr = self.repos.get(login, [])
            start = int(after) if after else 0
            chunk = allr[start:start + self.page]
            end = start + len(chunk)
            data[ni._gql_alias(i)] = {"repositories": {
                "pageInfo": {"hasNextPage": end < len(allr),
                             "endCursor": str(end) if end < len(allr) else None},
                "nodes": [{"name": n, "primaryLanguage": {"name": lang} if lang else None,
                           "isFork": fk, "description": d} for (n, lang, fk, d) in chunk]}}
        return {"data": data}


def test_list_owner_repos_paginates_all_pages():
    repos = {"schollz": [(f"r{i}", "Lua", False, "") for i in range(250)]}
    gh = PagingGH(repos, page=100)
    out = ni.GH.list_owner_repos(gh, ["schollz"])      # fake stands in for self
    assert len(out["schollz"]) == 250                  # not truncated at one page
    assert {r[0] for r in out["schollz"]} == {f"r{i}" for i in range(250)}
    assert gh.calls == 3                               # 100 + 100 + 50
