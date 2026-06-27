#!/usr/bin/env python3
"""nornslist — discover monome norns scripts from public GitHub and emit catalog.json.

Lean, headless. Discovers scripts from public GitHub via keyword/topic search, code
search, per-author sweep, and author-network expansion. README text/images are not
stored; consumers fetch them live.

Discovery:
  FIND (union of candidate repos):
    - keyword/topic search        (norns language:lua, topic:norns, …)
    - CODE search                 (softcut./engine./params:add/redraw in .lua) — finds
                                   untagged scripts the keyword search never sees
    - author sweep                (each candidate owner's other Lua repos)
    - author NETWORK              (followers/following of known norns authors)
  CLASSIFY:
    - norns fingerprint via BATCHED GraphQL (tree + corpus text, many repos/request),
      replacing the per-repo REST tree-fetch that used to rate-limit.
  RANK (hidden-gem):
    - norns-richness + recency + log(stars) + author-cluster, weighted so obscure-but-
      real scripts surface instead of being buried under the popular ones.
  EMIT: catalog.json (the single published feed; released as the `latest` asset).
"""
import argparse
import base64
import datetime
import json
import logging
import math
import os
import re
import sys
import time

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("nornslist")

# ── norns detection (ported verbatim from the proven classifier) ───────────────
NORNS_FP = re.compile(
    r"engine\.|softcut\.|\bscreen\.|params:add|function init\(|function redraw\(|"
    r"function enc\(|function key\(|controlspec|musicutil|grid\.connect|"
    r"arc\.connect|metro\.|norns\.|_norns|mod\.hook|mod\.menu"
)
GH_BLOCK = {
    "monome/norns", "monome/norns-shield", "okyeron/shieldxl",
    "p3r7/awesome-monome-norns", "monome/norns-image", "monome/dust",
    "monome/norns-community", "figrhed/norns-on-raspberry-pi",
    "jguzak/shieldxl_battery",
}
VOICE_USE_LIBS = {"mx.samples", "mx.synths"}
VOICE_CORPUS_MAX_FILES = 16
USABLE_FACETS = {"script", "mod", "library", "engine"}
INSTALL_REDFLAG = re.compile(r"\b(tutorial|study|boilerplate|template|exercise|wip)\b", re.I)
URL_RE = re.compile(r"https?://\S+", re.I)

# Seed authors for the network expansion — well-known norns contributors. The sweep
# pulls in the people THEY follow / who follow them (the norns orbit), not a catalog.
SEED_AUTHORS = ["tehn", "catfact", "sixolet", "schollz", "okyeron", "dndrks", "p3r7"]

CODE_QUERIES = [
    'softcut.buffer language:lua', 'engine.name language:lua',
    '"params:add" "function redraw" language:lua', '"grid.connect" language:lua',
    '"function enc" "function key" "function redraw" language:lua',
]
REPO_QUERIES = [
    "norns language:lua", "topic:norns", "norns monome language:lua",
    "fork:true norns language:lua",
]


def strip_urls(t):
    return URL_RE.sub("", t).strip() if t else (t or "")


def engine_from_paths(paths):
    names = [m.group(1) for p in paths
             for m in [re.search(r"(?:^|/)Engine_([A-Za-z0-9]+)\.sc$", str(p))] if m]
    return sorted(set(names))[0] if names else ""


def facets_from_paths(paths):
    ps = [str(p) for p in paths]
    top_lua = [p for p in ps if "/" not in p and p.lower().endswith(".lua")]
    has_mod = "lib/mod.lua" in ps
    lib_lua = [p for p in ps if p.lower().endswith(".lua") and re.search(r"(?:^|/)lib/", p)]
    has_engine = any(p.lower().endswith(".sc") for p in ps) or any(re.search(r"(?:^|/)engine/", p) for p in ps)
    # Monorepo guard: repos with 8+ top-level .lua files are collections (multiple scripts
    # sharing a repo), not a single installable script. Single scripts with helper modules
    # at root typically have ≤ 7 files; study series and personal script dumps have many more.
    if len(top_lua) > 7:
        return []
    f = []
    if top_lua:
        f.append("script")
    if has_mod:
        f.append("mod")
    if not top_lua and not has_mod and lib_lua:
        f.append("library")
    if has_engine:
        f.append("engine")
    return f


def bundled_libs(paths):
    dirs = {}
    for p in paths:
        m = re.match(r"lib/([^/]+)/(.+)$", str(p))
        if m:
            dirs.setdefault(m.group(1).lower(), []).append(m.group(2))
    return {x for x, inner in dirs.items()
            if any(f.lower().endswith((".lua", ".sc", ".sh")) for f in inner)}


def voice_corpus_paths(paths, bundled):
    bundled = {b.lower() for b in (bundled or set())}
    def is_b(p):
        m = re.match(r"lib/([^/]+)/", p)
        return bool(m and m.group(1).lower() in bundled)
    top = [p for p in paths if "/" not in p and p.lower().endswith(".lua")]
    lib = [p for p in paths if p.lower().endswith(".lua") and re.search(r"(?:^|/)lib/", p) and not is_b(p)]
    sc = [p for p in paths if re.search(r"(?:^|/)Engine_[A-Za-z0-9]+\.sc$", p) and not is_b(p)]
    return (sorted(top) + sorted(lib) + sorted(sc))[:VOICE_CORPUS_MAX_FILES]


def detect_voices(blob, paths, bundled, facets, repo):
    text = blob or ""
    facets = list(facets or [])
    bundled = {b.lower() for b in (bundled or set())}
    provides, uses = [], []
    nb_pack = bool(re.match(r"nb[_-]", (repo or "").lower()))
    if re.search(r"nb:add_player\b", text) or nb_pack:
        provides.append("nb")
    elif re.search(r"require[\s(]*['\"]nb/|/nb/lib|nb_voice|nb:add", text) and "nb" not in bundled:
        uses.append("nb")
    for lib in sorted(set(re.findall(r"require[\s(]*['\"]([A-Za-z0-9_.\-]+)/lib", text))):
        if lib.lower() not in bundled and lib in VOICE_USE_LIBS:
            uses.append(lib)
    def is_bp(p):
        m = re.match(r"lib/([^/]+)/", str(p))
        return bool(m and m.group(1).lower() in bundled)
    self_eng = {m.group(1).lower() for p in paths if not is_bp(p)
                for m in [re.search(r"Engine_([A-Za-z0-9]+)\.sc$", os.path.basename(str(p)))] if m}
    if self_eng and "script" not in facets:
        provides.append("sc-engine")
    used_eng = {e.lower() for e in re.findall(r"engine\.name\s*=\s*['\"]([A-Za-z0-9]+)['\"]", text)}
    if any(e not in self_eng for e in used_eng):
        uses.append("sc-engine")
    provides = sorted(set(provides))
    uses = sorted(set(u for u in uses if u not in provides))
    return {"provides": provides, "uses": uses, "systems": sorted(set(provides) | set(uses))}


def has_init_params(blob):
    t = blob or ""
    return bool(re.search(r"function\s+init\s*\(", t)), bool(re.search(r"params\s*:\s*add", t))


def is_installable(rec):
    if rec.get("fork") and not rec.get("fork_ahead"):
        return False
    if INSTALL_REDFLAG.search(f"{rec.get('name','')} {rec.get('desc','')}"):
        return False
    return any(f in USABLE_FACETS for f in (rec.get("facets") or []))


# ── GitHub client ──────────────────────────────────────────────────────────────
class GH:
    def __init__(self, token):
        self.s = requests.Session()
        h = {"Accept": "application/vnd.github+json", "User-Agent": "nornslist"}
        if token:
            h["Authorization"] = f"token {token}"
        self.s.headers.update(h)
        self.token = token
        self._last_search = 0.0

    def _throttle(self, gap):
        d = gap - (time.time() - self._last_search)
        if d > 0:
            time.sleep(d)
        self._last_search = time.time()

    def search_repos(self, q, max_pages=10):
        out, seen = [], set()
        for page in range(1, max_pages + 1):
            self._throttle(2.0)
            try:
                r = self.s.get("https://api.github.com/search/repositories",
                               params={"q": q, "per_page": 100, "page": page,
                                       "sort": "updated", "order": "desc"}, timeout=30)
            except Exception:
                break
            if r.status_code == 403:
                time.sleep(int(r.headers.get("Retry-After") or 15))
                continue
            if r.status_code != 200:
                break
            batch = (r.json() or {}).get("items") or []
            for it in batch:
                if it.get("id") not in seen:
                    seen.add(it.get("id"))
                    out.append(it)
            if len(batch) < 100:
                break
        return out

    def search_code(self, q, max_pages=3):
        """Code search — finds repos by norns API usage in .lua, regardless of name/
        topic. Auth-only, ~10 req/min, default-branch + indexed repos only."""
        repos = set()
        for page in range(1, max_pages + 1):
            self._throttle(6.5)   # code search secondary limit is strict
            try:
                r = self.s.get("https://api.github.com/search/code",
                               params={"q": q, "per_page": 100, "page": page}, timeout=30)
            except Exception:
                break
            if r.status_code == 403:
                time.sleep(int(r.headers.get("Retry-After") or 30))
                continue
            if r.status_code != 200:
                break
            items = (r.json() or {}).get("items") or []
            for it in items:
                full = ((it.get("repository") or {}).get("full_name") or "")
                if full:
                    repos.add(full)
            if len(items) < 100:
                break
        return repos

    def user_network(self, login, cap=60):
        """followers + following logins for a seed author (the norns orbit)."""
        out = set()
        for rel in ("followers", "following"):
            try:
                r = self.s.get(f"https://api.github.com/users/{login}/{rel}",
                               params={"per_page": cap}, timeout=30)
                if r.status_code == 200:
                    out.update(u.get("login") for u in (r.json() or []) if u.get("login"))
            except Exception:
                pass
        return out

    def user_lua_repos(self, login):
        """A user's non-fork Lua repos (names), to feed the candidate set."""
        return self.search_repos(f"user:{login} language:lua", max_pages=3)

    def graphql(self, query):
        for _ in range(3):
            try:
                r = self.s.post("https://api.github.com/graphql",
                                json={"query": query}, timeout=40)
            except Exception:
                time.sleep(5)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (403, 502, 503):
                time.sleep(int(r.headers.get("Retry-After") or 10))
                continue
            return {}
        return {}


def _gql_alias(i):
    return f"r{i}"


def classify_batch(gh, repos):
    """repos: list of (owner, name). Returns {(owner,name): record} for norns repos.
    Two GraphQL passes: (A) metadata + tree names for many repos at once, (B) corpus
    file text for the .lua-bearing candidates. No per-repo REST calls."""
    records = {}
    # ── pass A: metadata + 2-level tree names ──
    meta = {}
    for chunk in _chunks(repos, 18):
        q = "query{" + "".join(
            f'{_gql_alias(i)}:repository(owner:{json.dumps(o)},name:{json.dumps(n)}){{'
            'nameWithOwner pushedAt stargazerCount isPrivate isFork isArchived description '
            'primaryLanguage{name} repositoryTopics(first:20){nodes{topic{name}}} '
            'defaultBranchRef{name} '
            'object(expression:"HEAD:"){... on Tree{entries{name type '
            'object{... on Tree{entries{name type}}}}}}}'
            for i, (o, n) in enumerate(chunk)) + "}"
        data = (gh.graphql(q) or {}).get("data") or {}
        for i, (o, n) in enumerate(chunk):
            rd = data.get(_gql_alias(i))
            if rd:
                meta[(o, n)] = rd
    # build path lists + pre-filter (not private, not blocked, real norns structure)
    cand = {}
    for key, rd in meta.items():
        o, n = key
        if rd.get("isPrivate") or f"{o}/{n}".lower() in {b.lower() for b in GH_BLOCK}:
            continue
        paths = _paths_from_tree(rd.get("object"))
        if not facets_from_paths(paths):   # require a real norns structure (top-level .lua /
            continue                       # lib mod-or-lib / engine), not any stray .lua
        cand[key] = (rd, paths)
    # ── pass B: corpus text for candidates (resilient batched fetch) ──
    for chunk in _chunks(list(cand.items()), 8):
        plan = [(key, rd, paths, voice_corpus_paths(paths, bundled_libs(paths)))
                for key, (rd, paths) in chunk]
        blobs = _fetch_corpus(gh, plan)
        for key, rd, paths, files in plan:
            rec = _record(key, rd, paths, blobs.get(key, ""))
            if rec:
                records[key] = rec
    return records


def _fetch_corpus(gh, plan):
    """One batched GraphQL request for every repo's corpus text; if it comes back
    empty (a giant repo blew the node/size limit), split and retry so one bad repo
    can't blank the batch. plan: list of (key, rd, paths, files)."""
    if not plan:
        return {}
    parts = []
    for i, (key, rd, paths, files) in enumerate(plan):
        o, n = key
        fa = "".join(f'f{j}:object(expression:{json.dumps("HEAD:"+f)}){{... on Blob{{text}}}} '
                     for j, f in enumerate(files))
        parts.append(f'{_gql_alias(i)}:repository(owner:{json.dumps(o)},name:{json.dumps(n)}){{{fa}}}')
    data = (gh.graphql("query{" + "".join(parts) + "}") or {}).get("data") or {}
    if not data and len(plan) > 1:
        mid = len(plan) // 2
        out = _fetch_corpus(gh, plan[:mid])
        out.update(_fetch_corpus(gh, plan[mid:]))
        return out
    out = {}
    for i, (key, rd, paths, files) in enumerate(plan):
        rdata = data.get(_gql_alias(i)) or {}
        out[key] = "\n".join((rdata.get(f"f{j}") or {}).get("text") or "" for j in range(len(files)))
    return out


def _record(key, rd, paths, blob):
    if not NORNS_FP.search(blob or ""):
        return None
    o, n = key
    facets = facets_from_paths(paths)
    if not any(f in USABLE_FACETS for f in facets):
        return None
    bl = bundled_libs(paths)
    voices = detect_voices(blob, paths, bl, facets, n)
    has_i, has_p = has_init_params(blob)
    # norns-richness: distinct fingerprint marker categories present (1..N)
    richness = len(set(re.findall(
        r"engine\.|softcut\.|screen\.|params:add|function redraw|function enc|function key|"
        r"grid\.connect|arc\.connect|metro\.|musicutil|controlspec|mod\.hook", blob or "")))
    return {
        "owner": o, "name": n, "author": o,
        "desc": strip_urls(rd.get("description") or ""),
        "proj": f"https://github.com/{o}/{n}",
        "upd": (rd.get("pushedAt") or "")[:10],
        "topics": [t["topic"]["name"] for t in
                   ((rd.get("repositoryTopics") or {}).get("nodes") or []) if t.get("topic")][:8],
        "facets": facets, "voices": voices, "engine": engine_from_paths(paths),
        "has_init": has_i, "has_params": has_p,
        "stars": rd.get("stargazerCount") or 0,
        "archived": bool(rd.get("isArchived")), "fork": bool(rd.get("isFork")),
        "fork_ahead": False, "richness": richness, "source": "github",
    }


def _paths_from_tree(obj, prefix=""):
    out = []
    if not obj:
        return out
    for e in (obj.get("entries") or []):
        name = e.get("name")
        p = f"{prefix}{name}"
        if e.get("type") == "blob":
            out.append(p)
        elif e.get("type") == "tree":
            sub = e.get("object")
            if sub and sub.get("entries"):
                for se in sub["entries"]:
                    if se.get("type") == "blob":
                        out.append(f"{p}/{se.get('name')}")
            else:
                out.append(p + "/")
    return out


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ── discovery ────────────────────────────────────────────────────────────────
def discover(gh, max_authors=120):
    cand = set()   # {(owner, name)}

    def add_full(full):
        if "/" in full:
            o, n = full.split("/", 1)
            cand.add((o, n))

    log.info("phase 1: keyword/topic search")
    for q in REPO_QUERIES:
        for it in gh.search_repos(q):
            add_full(it.get("full_name") or "")
    log.info(f"  after keyword search: {len(cand)} candidates")

    log.info("phase 2: code search (norns API usage in .lua)")
    for q in CODE_QUERIES:
        for full in gh.search_code(q):
            add_full(full)
    log.info(f"  after code search: {len(cand)} candidates")

    log.info("phase 3: author network (seed authors' followers/following)")
    net = set()
    for a in SEED_AUTHORS:
        net.update(gh.user_network(a))
    log.info(f"  network authors: {len(net)}")

    log.info("phase 4: per-author sweep")
    owners = sorted({o for o, _ in cand} | net)[:max_authors]
    for o in owners:
        for it in gh.user_lua_repos(o):
            add_full(it.get("full_name") or "")
    log.info(f"  after author sweep: {len(cand)} candidates")

    log.info(f"classifying {len(cand)} candidates via GraphQL…")
    records = classify_batch(gh, sorted(cand))
    log.info(f"  norns repos: {len(records)}")

    # dedup by lowercase name (forks/case collapse onto the most-starred copy)
    best = {}
    for rec in records.values():
        if not is_installable(rec):
            continue
        k = rec["name"].lower()
        if k not in best or rec["stars"] > best[k]["stars"]:
            best[k] = rec
    rows = list(best.values())
    log.info(f"  installable + deduped: {len(rows)}")
    return rank(rows)


def rank(rows):
    """Hidden-gem score: norns-richness + recency + log(stars) + author cluster, so
    obscure-but-real scripts surface. Stars are deliberately the weakest term."""
    today = datetime.date.today()
    cluster = {}
    for r in rows:
        cluster[r["author"].lower()] = cluster.get(r["author"].lower(), 0) + 1

    def recency(upd):
        try:
            d = (today - datetime.date.fromisoformat(upd)).days
            return math.exp(-d / 365.0)          # 1.0 today → ~0.37 a year ago
        except Exception:
            return 0.0

    for r in rows:
        r["score"] = round(
            2.0 * (r.get("richness", 0) / 12.0)            # how norns-y the code is
            + 1.5 * recency(r.get("upd", ""))              # recent activity
            + 0.8 * math.log1p(r.get("stars", 0))          # popularity (weak)
            + 0.5 * math.log1p(cluster.get(r["author"].lower(), 1) - 1),  # prolific author
            4)
    rows.sort(key=lambda r: (-r["score"], -r.get("stars", 0), r["name"].lower()))
    for i, r in enumerate(rows):
        r["rank"] = i
    return rows


# ── output ───────────────────────────────────────────────────────────────────
FIELD = {"name": "Name", "author": "Author", "desc": "Description", "proj": "Project URL",
         "upd": "Last Updated", "topics": "Tags"}


def write_catalog(rows, path):
    scripts = []
    for r in rows:
        e = {"Name": r["name"], "Author": r["author"], "Description": r.get("desc", ""),
             "Project URL": r["proj"], "Last Updated": r.get("upd", ""),
             "Tags": r.get("topics", []), "Demo": "", "Discussion URL": "",
             "Documentation URL": "", "Community URL": "",
             "source": "github", "status": "archived" if r.get("archived") else "active",
             "stars": r.get("stars", 0), "facets": r.get("facets", []),
             "voices": r.get("voices"), "engine": r.get("engine", ""),
             "rank": r.get("rank", 0), "score": r.get("score", 0)}
        if r.get("has_init"):
            e["has_init"] = True
        if r.get("has_params"):
            e["has_params"] = True
        scripts.append(e)
    json.dump({"file_info": {"version": 2, "kind": "script_catalog"},
               "date": datetime.date.today().isoformat(), "scripts": scripts},
              open(path, "w"), ensure_ascii=False, separators=(",", ":"))
    log.info(f"wrote {path}: {len(scripts)} scripts "
             f"({sum(1 for s in scripts if s['engine'])} engines)")


def main():
    ap = argparse.ArgumentParser(description="Build a norns script catalog from public GitHub")
    ap.add_argument("--out", default="catalog.json")
    ap.add_argument("--max-authors", type=int, default=120)
    ap.add_argument("--classify", nargs="*", help="debug: classify these owner/name repos and print")
    a = ap.parse_args()
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN") or ""
    gh = GH(token)
    if a.classify:
        repos = [tuple(x.split("/", 1)) for x in a.classify if "/" in x]
        recs = classify_batch(gh, repos)
        for k, r in recs.items():
            print(json.dumps({**r, "voices": r["voices"]}, indent=1))
        print(f"\n{len(recs)}/{len(repos)} classified as installable norns scripts")
        return
    rows = discover(gh, max_authors=a.max_authors)
    write_catalog(rows, a.out)


if __name__ == "__main__":
    main()
