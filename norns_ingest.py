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
# Forks of these are the norns OS/firmware itself (Fates, PiBoy, Bookworm ports, …), not
# installable scripts — nobody forks the whole operating system to write a script. Caught by
# parent, so it scales to any future OS port without naming each one (not "dumb hardcoding").
INFRA_FORK_PARENTS = {
    "monome/norns", "monome/dust", "monome/norns-shield", "monome/norns-image",
    "monome/maiden", "monome/crow", "monome/teletype", "monome/softcut",
    "monome/libmonome", "monome/serialosc", "fates-project/norns", "okyeron/shieldxl",
}
# A fork is a distinct script only if its CODE has meaningfully diverged from its parent.
# Measured as .lua/.sc lines changed (additions+deletions) in the fork-vs-parent diff, NOT
# commit count: a squashed fork that rewrote the script in one commit reads ahead_by=1 but
# shows its full line delta here (benregnier/plonky +1154, schollz/cheat_codes_2 +156). A fork
# that changed fewer than this many code lines is a mirror/personal copy and is dropped. Tunable.
FORK_DIVERGENCE_LINES = 20
CODE_EXT = (".lua", ".sc")
VOICE_USE_LIBS = {"mx.samples", "mx.synths"}
VOICE_CORPUS_MAX_FILES = 16
USABLE_FACETS = {"script", "collection", "mod", "library", "engine"}
# 8+ top-level .lua files = a multi-script collection (personal script dump / study series),
# not a single installable script. We still TRACK these (they're real norns) but label them
# 'collection' so a consumer can show or filter them apart from single scripts.
COLLECTION_MIN = 8
INSTALL_REDFLAG = re.compile(r"\b(tutorial|study|boilerplate|template|exercise|wip)\b", re.I)
URL_RE = re.compile(r"https?://\S+", re.I)
# Richness = how many DISTINCT norns marker categories the code uses (1..N). Used for
# ranking AND as the weak-match gate in _record. Factored out so the two always agree.
RICHNESS_RE = re.compile(
    r"engine\.|softcut\.|screen\.|params:add|function redraw|function enc|function key|"
    r"grid\.connect|arc\.connect|metro\.|musicutil|controlspec|mod\.hook")
# STRONG markers are norns-specific Lua that virtually never appears in other languages —
# a single one confirms norns. The WEAK markers in NORNS_FP (engine./screen./metro.) also
# match JavaScript, game engines, T-Engine roguelikes, etc., so a repo whose ONLY hit is a
# weak marker (richness < 2, no strong) is a coincidence and is rejected. This kills false
# positives (a "Website" repo matching only `screen.`, a roguelike matching only `engine.`)
# without dropping real scripts, which always carry redraw/enc/key callbacks or params:add.
NORNS_STRONG = re.compile(
    r"params:add|function redraw\(|function enc\(|function key\(|softcut\.|"
    r"grid\.connect|arc\.connect|mod\.hook|mod\.menu|_norns|\bnorns\.")
# Native norns mods (e.g. ndi-mod, hdmi-mod) carry no Lua — they submodule norns at
# dep/norns and build against it in C/C++. dep/norns IS the fingerprint (unambiguous).
DEP_NORNS_RE = re.compile(r"(?:^|/)dep/norns(?:/|$)")
# Norns-ecosystem context in a repo's name/description/topics. These terms (esp. norns,
# monome, softcut, seamstress) essentially never appear outside the monome ecosystem, so a
# repo with norns code structure + ≥1 norns marker + this context is norns even if the
# sampled corpus only caught a single weak marker. This rescues real-but-minimal scripts,
# libraries, and iii/crow-ecosystem scripts (reverse_io, glyph, tty-console, iiiano) that a
# pure-corpus gate would drop, WITHOUT admitting the coincidental matches (a roguelike, a
# Factorio mod, a website) — those carry no norns context.
NORNS_CONTEXT = re.compile(
    r"norns|monome|softcut|seamstress|teletype|matron|maiden|\bcrow\b|\biii\b|\bnb[_\- ]", re.I)
# Gate for which non-Lua repos in an author sweep are even worth classifying as native mods.
NORNS_HINT = re.compile(r"norns|monome|softcut|grid|arc|crow|seamstress|\bmod\b", re.I)

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
    # Native mod: no Lua, but submodules norns at dep/norns and builds against it (C/C++).
    # The dep/norns submodule is itself the norns proof — these are real installable mods
    # (ndi-mod, hdmi-mod) the Lua-only facet detector can't see.
    has_native_mod = any(DEP_NORNS_RE.search(p) for p in ps)
    f = []
    # 8+ top-level .lua = a multi-script collection, not a single script. Tracked, but
    # labelled 'collection' so consumers can separate them from single scripts. (Single
    # scripts with root helper modules typically have ≤ 7 .lua; dumps/study series have more.)
    if len(top_lua) >= COLLECTION_MIN:
        f.append("collection")
    elif top_lua:
        f.append("script")
    if has_mod or has_native_mod:
        f.append("mod")
    if not top_lua and not has_mod and not has_native_mod and lib_lua:
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
    if self_eng and not ({"script", "collection"} & set(facets)):
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
    if rec.get("fork") and not rec.get("fork_diverged"):
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

    def list_owner_repos(self, logins):
        """For a batch of owner logins, return {login: [(name, lang, isFork, desc), …]} of ALL
        their own repos via batched, cursor-paginated GraphQL. Not limited to GitHub's
        `language:lua` tag, so it surfaces mods, SC-heavy, and doc-heavy norns repos the old
        lua-search missed. Fully paginated: a prolific author (schollz has 1150 repos) used to
        be truncated at the first 60-by-push, so their OLDER scripts (ynth, …) never surfaced
        and flapped out of the catalog on discovery variance — now every repo is swept."""
        out = {o: [] for o in logins}
        cursors = {}                       # login -> endCursor; present => more pages to fetch
        pending = list(logins)
        while pending:
            q = "query{" + "".join(
                f'{_gql_alias(i)}:repositoryOwner(login:{json.dumps(o)}){{'
                'repositories(first:100,ownerAffiliations:OWNER,'
                'orderBy:{field:PUSHED_AT,direction:DESC}'
                + (f',after:{json.dumps(cursors[o])}' if o in cursors else '')
                + '){pageInfo{hasNextPage endCursor} nodes{'
                'name isFork primaryLanguage{name} description}}}'
                for i, o in enumerate(pending)) + "}"
            data = (self.graphql(q) or {}).get("data") or {}
            nxt = []
            for i, o in enumerate(pending):
                repos = (data.get(_gql_alias(i)) or {}).get("repositories") or {}
                out[o].extend((r.get("name"), (r.get("primaryLanguage") or {}).get("name"),
                               bool(r.get("isFork")), r.get("description") or "")
                              for r in (repos.get("nodes") or []) if r.get("name"))
                pi = repos.get("pageInfo") or {}
                if pi.get("hasNextPage") and pi.get("endCursor"):
                    cursors[o] = pi["endCursor"]
                    nxt.append(o)
            pending = nxt
        return out

    def compare_code_lines(self, owner, name, parent_full, base, head):
        """.lua/.sc lines that differ between a fork and its parent (additions+deletions in the
        cumulative diff) — the fork's actual code divergence. Squash-proof: a fork that rewrote
        the script in one squashed commit still shows its full line delta here, where commit
        count (ahead_by) would read 1. None on error (caller keeps the fork rather than drop on
        a transient failure). One REST call; only for forks (a minority)."""
        po = parent_full.split("/", 1)[0]
        try:
            r = self.s.get(
                f"https://api.github.com/repos/{owner}/{name}/compare/{po}:{base}...{head}",
                timeout=30)
            if r.status_code != 200:
                return None
            files = (r.json() or {}).get("files") or []
            return sum(f.get("additions", 0) + f.get("deletions", 0) for f in files
                       if str(f.get("filename", "")).lower().endswith(CODE_EXT))
        except Exception:
            return None

    def graphql(self, query):
        for _ in range(3):
            try:
                r = self.s.post("https://api.github.com/graphql",
                                json={"query": query}, timeout=40)
            except Exception:
                time.sleep(5)
                continue
            if r.status_code == 200:
                try:
                    return r.json()
                except Exception:
                    # transient empty/truncated 200 body — retry rather than crash the run.
                    # (With the per-owner repo sweep issuing many more GraphQL calls, a rare
                    # bad response is expected; one must never abort the whole catalog build.)
                    time.sleep(5)
                    continue
            if r.status_code in (403, 502, 503):
                time.sleep(int(r.headers.get("Retry-After") or 10))
                continue
            return {}
        return {}


def _gql_alias(i):
    return f"r{i}"


def _fetch_meta(gh, repos):
    """Batched metadata + 2-level tree fetch with split-retry. A transient GraphQL error (or
    one oversized repo) blanks the whole `data` block; without bisection that would look like
    18 simultaneous deletions and silently drop confirmed repos. Returns {(owner,name): node}
    for the repos GitHub actually returned (a genuine 404 stays absent even at size 1)."""
    if not repos:
        return {}
    q = "query{" + "".join(
        f'{_gql_alias(i)}:repository(owner:{json.dumps(o)},name:{json.dumps(n)}){{'
        'nameWithOwner pushedAt stargazerCount isPrivate isFork isArchived description '
        'primaryLanguage{name} repositoryTopics(first:20){nodes{topic{name}}} '
        'defaultBranchRef{name} parent{nameWithOwner defaultBranchRef{name}} '
        'object(expression:"HEAD:"){... on Tree{entries{name type '
        'object{... on Tree{entries{name type}}}}}}}'
        for i, (o, n) in enumerate(repos)) + "}"
    data = (gh.graphql(q) or {}).get("data") or {}
    if not data and len(repos) > 1:
        mid = len(repos) // 2
        out = _fetch_meta(gh, repos[:mid])
        out.update(_fetch_meta(gh, repos[mid:]))
        return out
    return {key: data[_gql_alias(i)] for i, key in enumerate(repos) if data.get(_gql_alias(i))}


def classify_batch(gh, repos, prior=None):
    """repos: list of (owner, name). Returns {(owner,name): record} for norns repos.
    Two GraphQL passes: (A) metadata + tree names for many repos at once, (B) corpus
    file text for the .lua-bearing candidates. No per-repo REST calls.

    `prior`: {(owner,name): record} from the previous catalog. When a prior repo's metadata
    comes back fine (it still exists) but this run's corpus blob is empty (a transient
    node/size flake), we carry the prior verdict forward instead of dropping it — a confirmed
    repo leaves only on a real 404 (absent from pass A) or a genuine gate-fail (non-empty
    corpus that misses the fingerprint)."""
    prior = prior or {}
    records = {}
    # ── pass A: metadata + 2-level tree names (split-retry so a flake ≠ mass deletion) ──
    meta = {}
    for chunk in _chunks(repos, 18):
        meta.update(_fetch_meta(gh, chunk))
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
            blob = blobs.get(key, "")
            rec = _record(key, rd, paths, blob)
            if rec:
                records[key] = rec
            elif not blob and key in prior:
                # exists (pass A returned it) + has norns structure (it's in `cand`) but no
                # corpus text this run -> transient fetch flake, keep the confirmed verdict.
                records[key] = dict(prior[key], carried=True)
    # ── fork identity: a fork is a distinct script only if it has meaningfully DIVERGED from
    # its parent — "forked & evolved in a new direction", not a personal mirror. The signal is
    # how far the fork is ahead of its parent (its own commits), NOT whether it kept the name:
    # the personal copies of orca/awake/cheat_codes_2 sit at ahead_by 1-2 (lazy), while genuine
    # same-name derivatives (aidanreilly/bowery +22, clickbox/pitfalls +113) sit far higher and
    # are kept. Detached forks (parent gone) are independent by definition; forks of the OS
    # firmware are not scripts. One REST compare per fork (a minority of records). ──
    drop_infra = []
    for key, rec in records.items():
        if not rec.get("fork"):
            continue
        rd = meta.get(key) or {}
        parent = rd.get("parent") or {}
        pfull = parent.get("nameWithOwner")
        if not pfull:
            rec["fork_diverged"] = True
            continue
        if pfull.lower() in {p.lower() for p in INFRA_FORK_PARENTS}:
            drop_infra.append(key)   # fork of the OS/firmware → not a script
            continue
        base = (parent.get("defaultBranchRef") or {}).get("name") or "main"
        head = (rd.get("defaultBranchRef") or {}).get("name") or "main"
        changed = gh.compare_code_lines(key[0], key[1], pfull, base, head)
        rec["fork_diverged"] = (changed is None) or (changed >= FORK_DIVERGENCE_LINES)
    for key in drop_infra:
        del records[key]
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


def detect_caps(blob):
    """I/O capabilities, detected from the corpus rather than author-set GitHub topics — so
    coverage is high and consistent, one canonical name each (a consumer can tag/filter on
    'grid' without every grid script happening to carry a 'grid' or 'monome-grid' topic)."""
    t = blob or ""
    caps = []
    if re.search(r"\bgrid\.connect\b", t):
        caps.append("grid")
    if re.search(r"\barc\.connect\b", t):
        caps.append("arc")
    if re.search(r"\bcrow\.", t):
        caps.append("crow")
    if re.search(r"\bmidi\.connect\b", t):
        caps.append("midi")
    return sorted(set(caps))


def _record(key, rd, paths, blob):
    blob = blob or ""
    o, n = key
    native_mod = any(DEP_NORNS_RE.search(str(p)) for p in paths)
    # norns-richness: distinct fingerprint marker categories present (1..N)
    richness = len(set(RICHNESS_RE.findall(blob)))
    topics = " ".join(t["topic"]["name"] for t in
                      ((rd.get("repositoryTopics") or {}).get("nodes") or []) if t.get("topic"))
    ctx = bool(NORNS_CONTEXT.search(f"{n} {rd.get('description') or ''} {topics}"))
    # Norns gate — confirmed iff ANY of:
    #   • native mod (dep/norns submodule is the proof; no Lua to fingerprint)
    #   • a STRONG marker (params:add / redraw|enc|key callbacks / softcut. / grid|arc.connect)
    #   • ≥2 distinct markers (multiple independent norns signals)
    #   • ≥1 marker AND norns context in name/desc/topics (rescues minimal/iii/crow scripts)
    # A lone weak marker with no norns context is a coincidence (a roguelike's engine.,
    # a website's screen., a Factorio mod) — reject.
    if not (native_mod or NORNS_STRONG.search(blob) or richness >= 2
            or (NORNS_FP.search(blob) and ctx)):
        return None
    facets = facets_from_paths(paths)
    if not any(f in USABLE_FACETS for f in facets):
        return None
    bl = bundled_libs(paths)
    voices = detect_voices(blob, paths, bl, facets, n)
    has_i, has_p = has_init_params(blob)
    # committed image files (screenshots/, img/, root .png …) — a cheap "has a picture"
    # signal from the tree we already have, so a consumer can filter for scripts with imagery
    has_img = any(str(p).lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
                  for p in paths)
    return {
        "owner": o, "name": n, "author": o,
        "desc": strip_urls(rd.get("description") or ""),
        "proj": f"https://github.com/{o}/{n}",
        "upd": (rd.get("pushedAt") or "")[:10],
        "topics": [t["topic"]["name"] for t in
                   ((rd.get("repositoryTopics") or {}).get("nodes") or []) if t.get("topic")][:8],
        "facets": facets, "voices": voices, "engine": engine_from_paths(paths),
        "has_init": has_i, "has_params": has_p, "has_image": has_img,
        "caps": detect_caps(blob),
        "stars": rd.get("stargazerCount") or 0,
        "archived": bool(rd.get("isArchived")), "fork": bool(rd.get("isFork")),
        "fork_diverged": False, "richness": richness, "source": "github",
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
def known_authors(catalog_path):
    """Authors of the previous catalog = the persisted set of confirmed norns authors.
    Sweeping them every run means once an author is found, ALL their scripts stay covered
    forever — the catalog is its own growing memory, so coverage only improves and never
    needs hand-tuning. Absent/unreadable catalog (first run) → empty set."""
    try:
        with open(catalog_path) as f:
            data = json.load(f)
        out = set()
        for s in data.get("scripts", []):
            m = re.search(r"github\.com/([^/]+)/", s.get("Project URL", "") or "")
            if m:
                out.add(m.group(1))
        return out
    except Exception:
        return set()


def prior_records(catalog_path):
    """Previous catalog entries re-shaped as classifier records, keyed by (owner, name).
    Two jobs: (1) the floor — every prior repo is re-fed into classification each run so it
    is re-verified against the live fingerprint instead of relying on this run's search to
    rediscover it; (2) carry-forward — the value is reused verbatim when this run's corpus
    fetch flakes (see classify_batch). Absent/unreadable catalog (first run) → empty."""
    try:
        with open(catalog_path) as f:
            data = json.load(f)
    except Exception:
        return {}
    out = {}
    for s in data.get("scripts", []):
        m = re.search(r"github\.com/([^/]+)/([^/\s]+)", s.get("Project URL", "") or "")
        if not m:
            continue
        o, n = m.group(1), m.group(2)
        out[(o, n)] = {
            "owner": o, "name": n, "author": s.get("Author") or o,
            "desc": s.get("Description", ""), "proj": s.get("Project URL", ""),
            "upd": s.get("Last Updated", ""), "topics": s.get("Tags", []),
            "facets": s.get("facets", []), "voices": s.get("voices"),
            "engine": s.get("engine", ""), "has_init": s.get("has_init", False),
            "has_params": s.get("has_params", False), "has_image": s.get("has_image", False),
            "caps": s.get("caps", []), "stars": s.get("stars", 0),
            "archived": s.get("status") == "archived", "fork": False, "fork_diverged": False,
            "richness": 0, "source": "github",
        }
    return out


def discover(gh, catalog_path="catalog.json"):
    cand = set()     # {(owner, name)}
    owners = set()   # every owner we should sweep for their other repos

    def add_full(full):
        if "/" in full:
            o, n = full.split("/", 1)
            cand.add((o, n))
            owners.add(o)

    log.info("phase 1: keyword/topic search")
    for q in REPO_QUERIES:
        for it in gh.search_repos(q):
            add_full(it.get("full_name") or "")
    log.info(f"  after keyword search: {len(cand)} repos, {len(owners)} owners")

    log.info("phase 2: code search (norns API usage in .lua)")
    for q in CODE_QUERIES:
        for full in gh.search_code(q):
            add_full(full)
    log.info(f"  after code search: {len(cand)} repos, {len(owners)} owners")

    log.info("phase 3: author network (seed authors' followers/following)")
    for a in SEED_AUTHORS:
        owners.update(gh.user_network(a))
    owners.update(SEED_AUTHORS)
    owners.update(known_authors(catalog_path))   # persisted: every author ever cataloged
    log.info(f"  owner pool: {len(owners)}")

    # phase 4: sweep EVERY owner's repos via batched, fully-paginated GraphQL — no per-author
    # cap (a 1150-repo author is swept in full, so their older scripts surface instead of being
    # truncated at the first 60-by-push). Not limited to GitHub's language:lua tag, so it also
    # catches native mods (C/C++) and SC-heavy repos. classify_batch fingerprints out non-norns.
    log.info("phase 4: per-owner repo sweep (batched GraphQL, fully paginated)")
    before = len(cand)
    for chunk in _chunks(sorted(owners), 12):
        for o, repos in gh.list_owner_repos(chunk).items():
            for name, lang, _isfork, desc in repos:
                if lang in ("Lua", "SuperCollider") or (
                        lang in ("C", "C++", "CMake") and NORNS_HINT.search(f"{name} {desc}")):
                    cand.add((o, name))
    log.info(f"  after sweep: {len(cand)} candidates (+{len(cand) - before})")

    # phase 5: floor — re-feed every previously-cataloged repo so it is re-verified this run
    # regardless of whether search/sweep happened to surface it. This is what stops confirmed
    # scripts (e.g. an old script by a 1000-repo author) flapping out when discovery misses
    # them. classify_batch re-checks each against the live fingerprint, so the floor can only
    # KEEP repos that are still norns — it never admits noise.
    prior = prior_records(catalog_path)
    floor_only = set(prior) - cand
    cand |= set(prior)
    log.info(f"  floor: +{len(floor_only)} prior repos not surfaced by discovery this run")

    log.info(f"classifying {len(cand)} candidates via GraphQL…")
    records = classify_batch(gh, sorted(cand), prior=prior)
    carried = sum(1 for r in records.values() if r.get("carried"))
    log.info(f"  norns repos: {len(records)} ({carried} carried forward on corpus flake)")

    rows = dedup_installable(records.values())
    log.info(f"  installable + deduped: {len(rows)}")
    return rank(rows)


def dedup_installable(records):
    """Keep installable records, deduped by (owner, name) — case collapses, but two DIFFERENT
    owners sharing a name are distinct repos and both kept. Bare-name dedup (the old behaviour)
    silently dropped the lower-starred one (e.g. two `norns-bookworm`). Fork mirrors are
    already excluded by is_installable; a divergent fork is a genuine separate repo."""
    best = {}
    for rec in records:
        if not is_installable(rec):
            continue
        k = (rec["owner"].lower(), rec["name"].lower())
        if k not in best or rec["stars"] > best[k]["stars"]:
            best[k] = rec
    return list(best.values())


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


def load_demos(path="demos.json"):
    """repo (owner/name, lowercased) -> demo video URL. Maintained by video_search.py
    (the decoupled YouTube/Vimeo discovery), merged into the catalog's Demo field here so
    a consumer can embed a demo without computing it. Absent file -> no demos."""
    try:
        with open(path) as f:
            return {k.lower(): (v.get("demo") if isinstance(v, dict) else v) or ""
                    for k, v in json.load(f).items()}
    except Exception:
        return {}


def write_catalog(rows, path):
    demos = load_demos()
    scripts = []
    for r in rows:
        m = re.search(r"github\.com/([^/]+)/([^/\s]+)", r["proj"])
        demo = demos.get(f"{m.group(1)}/{m.group(2)}".lower(), "") if m else ""
        e = {"Name": r["name"], "Author": r["author"], "Description": r.get("desc", ""),
             "Project URL": r["proj"], "Last Updated": r.get("upd", ""),
             "Tags": r.get("topics", []), "Demo": demo, "Discussion URL": "",
             "Documentation URL": "", "Community URL": "",
             "source": "github", "status": "archived" if r.get("archived") else "active",
             "stars": r.get("stars", 0), "facets": r.get("facets", []),
             "voices": r.get("voices"), "engine": r.get("engine", ""),
             "rank": r.get("rank", 0), "score": r.get("score", 0)}
        if r.get("has_init"):
            e["has_init"] = True
        if r.get("has_params"):
            e["has_params"] = True
        if r.get("has_image"):
            e["has_image"] = True
        if r.get("caps"):
            e["caps"] = r["caps"]
        scripts.append(e)
    json.dump({"file_info": {"version": 2, "kind": "script_catalog",
                             "name": "nornslist", "default_sort": "score:desc"},
               "date": datetime.date.today().isoformat(), "scripts": scripts},
              open(path, "w"), ensure_ascii=False, separators=(",", ":"))
    log.info(f"wrote {path}: {len(scripts)} scripts "
             f"({sum(1 for s in scripts if s['engine'])} engines)")


def main():
    ap = argparse.ArgumentParser(description="Build a norns script catalog from public GitHub")
    ap.add_argument("--out", default="catalog.json")
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
    # the existing catalog (committed, present on a fresh checkout) seeds the known-author
    # sweep, so coverage carries forward and grows across runs
    rows = discover(gh, catalog_path=a.out)
    write_catalog(rows, a.out)


if __name__ == "__main__":
    main()
