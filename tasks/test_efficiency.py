"""Offline unit tests for the nightly-scrape efficiency caches (no network).

Run: ~/.virtualenvs/nornslist-ddno/bin/python tasks/test_efficiency.py

Covers the three GitHub/index call reductions added to norns_scraper_discourse.py:
  P1  Last-Updated cache, gated on repo `pushed_at` (skip commit-paging for
      repos that weren't pushed since last run).
  P2  `_repo_meta` — one `GET /repos/{owner}/{repo}` per repo per run, shared
      between the Last-Updated pass and feed enrichment.
  P3  `get_main_page` memoization (index page fetched once, not twice, per run).

These use a fake session / monkeypatched instance methods so the cache logic is
trusted without a 345-repo live scrape. Correctness on the wire is covered by the
bounded live smoke test in the PR notes.
"""
import os
import sys
import tempfile

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

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Records every GET; returns scripted responses by exact URL."""

    def __init__(self, routes):
        self.routes = routes  # url -> FakeResp (or callable -> FakeResp)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        r = self.routes.get(url)
        if callable(r):
            return r()
        return r if r is not None else FakeResp(404, {})


def bare():
    """An instance with __init__ bypassed, wired with just the attrs the
    efficiency methods touch (mirrors test_feed.py's object.__new__ approach)."""
    import threading

    inst = object.__new__(NornsScraper)
    inst._repo_meta_cache = {}
    inst._repo_meta_lock = threading.Lock()
    inst._main_page_html = None
    inst.max_workers = 4
    return inst


# ---------------------------------------------------------------------------
# P2 — _repo_meta memoization (one GET /repos per repo per run)
# ---------------------------------------------------------------------------
REPO_URL = "https://api.github.com/repos/alice/cool"
inst = bare()
inst.github_session = FakeSession(
    {REPO_URL: FakeResp(200, {"default_branch": "trunk", "pushed_at": "2024-05-05T10:00:00Z"})}
)
m1 = inst._repo_meta("alice", "cool")
m2 = inst._repo_meta("alice", "cool")  # served from per-run memo
check("repo_meta_branch", m1.get("default_branch"), "trunk")
check("repo_meta_memoized_one_call", inst.github_session.calls.count(REPO_URL), 1)
check("repo_meta_same_object", m1 is m2, True)

inst = bare()
inst.github_session = FakeSession({REPO_URL: FakeResp(404, {})})
check("repo_meta_404_sentinel", inst._repo_meta("alice", "cool").get("_status"), 404)

inst = bare()
inst.github_session = FakeSession({REPO_URL: FakeResp(403, {})})
check("repo_meta_403_sentinel", inst._repo_meta("alice", "cool").get("_status"), 403)
# transient (403) is cached for the run too (avoids hammering), still one call
inst._repo_meta("alice", "cool")
check("repo_meta_403_memoized", inst.github_session.calls.count(REPO_URL), 1)


# ---------------------------------------------------------------------------
# P1 — _lastupd_cache_fresh gating logic
# ---------------------------------------------------------------------------
today = S._today_iso()
PA = "2024-05-05T10:00:00Z"
fresh = {"last_updated": "2024-05-05", "pushed_at": PA, "computed_at": today}
check("lastupd_fresh_same_pushed_at", NornsScraper._lastupd_cache_fresh(inst, fresh, PA), True)
check(
    "lastupd_stale_pushed_at_changed",
    NornsScraper._lastupd_cache_fresh(inst, fresh, "2024-06-06T00:00:00Z"),
    False,
)
check(
    "lastupd_stale_no_date",
    NornsScraper._lastupd_cache_fresh(inst, {"last_updated": "", "pushed_at": PA, "computed_at": today}, PA),
    False,
)
check(
    "lastupd_stale_empty_pushed_at",
    NornsScraper._lastupd_cache_fresh(inst, {"last_updated": "2024-05-05", "pushed_at": "", "computed_at": today}, ""),
    False,
)
check(
    "lastupd_stale_old_ttl",
    NornsScraper._lastupd_cache_fresh(inst, {"last_updated": "x", "pushed_at": PA, "computed_at": "2000-01-01"}, PA),
    False,
)


# ---------------------------------------------------------------------------
# P1 end-to-end — second run with unchanged pushed_at does ZERO commit-paging,
#                 and a changed pushed_at busts the cache.
# ---------------------------------------------------------------------------
def run_apply(pushed_at, compute_calls, excel_path, date_value="2024-05-05"):
    """Run _apply_last_updated once with _repo_meta + _github_latest_non_readme_date
    monkeypatched so we can count the expensive commit-paging calls."""
    inst = bare()
    inst._repo_meta = lambda o, r: {"default_branch": "main", "pushed_at": pushed_at}

    def fake_latest(o, r):
        compute_calls.append((o, r))
        return date_value

    inst._github_latest_non_readme_date = fake_latest
    rows = [{"Name": "Cool", "Project URL": "https://github.com/alice/cool", "Last Updated": ""}]
    inst._apply_last_updated(rows, excel_path)
    return rows


with tempfile.TemporaryDirectory() as tmp:
    xlsx = os.path.join(tmp, "scrape.xlsx")

    calls1 = []
    rows1 = run_apply("2024-05-05T10:00:00Z", calls1, xlsx)
    check("lastupd_first_run_computes", len(calls1), 1)
    check("lastupd_first_run_sets_value", rows1[0]["Last Updated"], "2024-05-05")
    check("lastupd_cache_file_written", os.path.exists(xlsx.replace(".xlsx", ".lastupd_cache.json")), True)

    calls2 = []
    rows2 = run_apply("2024-05-05T10:00:00Z", calls2, xlsx)  # same pushed_at
    check("lastupd_second_run_zero_calls", len(calls2), 0)
    check("lastupd_second_run_value_from_cache", rows2[0]["Last Updated"], "2024-05-05")

    calls3 = []
    run_apply("2024-09-09T00:00:00Z", calls3, xlsx, date_value="2024-09-09")  # pushed -> bust
    check("lastupd_pushed_busts_cache", len(calls3), 1)


# transient repo-meta (pushed_at unknown) must NOT cache -> recompute next run
with tempfile.TemporaryDirectory() as tmp:
    xlsx = os.path.join(tmp, "scrape.xlsx")
    callsA = []
    run_apply("", callsA, xlsx)  # empty pushed_at simulates 403/404 meta
    callsB = []
    run_apply("", callsB, xlsx)
    check("lastupd_transient_not_cached_recomputes", len(callsB), 1)

# empty computed value (no non-README commit found) must NOT cache -> recompute
with tempfile.TemporaryDirectory() as tmp:
    xlsx = os.path.join(tmp, "scrape.xlsx")
    callsA = []
    run_apply("2024-05-05T10:00:00Z", callsA, xlsx, date_value="")
    callsB = []
    run_apply("2024-05-05T10:00:00Z", callsB, xlsx, date_value="")
    check("lastupd_empty_value_not_cached_recomputes", len(callsB), 1)


# ---------------------------------------------------------------------------
# P3 — get_main_page memoization (index page fetched once per run)
# ---------------------------------------------------------------------------
inst = bare()
inst.base_url = "https://norns.community"
inst.session = FakeSession({"https://norns.community": FakeResp(200, text="<html>index</html>")})
h1 = inst.get_main_page()
h2 = inst.get_main_page()
check("main_page_text", h1, "<html>index</html>")
check("main_page_memoized_one_call", inst.session.calls.count("https://norns.community"), 1)
check("main_page_same_value", h1 == h2, True)

# a failed fetch is NOT cached (so a later call can retry)
inst = bare()
inst.base_url = "https://norns.community"
import requests as _rq


class RaisingSession:
    def __init__(self):
        self.calls = 0

    def get(self, url):
        self.calls += 1
        raise _rq.RequestException("boom")


inst.session = RaisingSession()
check("main_page_fail_returns_none", inst.get_main_page(), None)
inst.get_main_page()
check("main_page_fail_not_cached_retries", inst.session.calls, 2)


# --- Phase 2: GH_PAT preferred over GITHUB_TOKEN ---
import os as _os
_saved = {k: _os.environ.get(k) for k in ("GH_PAT", "GITHUB_TOKEN")}
try:
    _os.environ["GH_PAT"] = "pat_secret"
    _os.environ["GITHUB_TOKEN"] = "actions_token"
    _inst = object.__new__(NornsScraper)
    check("token_prefers_gh_pat", _inst._load_github_token(), "pat_secret")
    del _os.environ["GH_PAT"]
    check("token_falls_back", _inst._load_github_token(), "actions_token")
finally:
    for _k, _v in _saved.items():
        if _v is None:
            _os.environ.pop(_k, None)
        else:
            _os.environ[_k] = _v


if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL EFFICIENCY CHECKS PASSED")
