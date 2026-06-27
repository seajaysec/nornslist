#!/usr/bin/env python3
"""video_search — discover YouTube/Vimeo demo videos for cataloged scripts.

Decoupled from the catalog scan (norns_ingest.py) on purpose: repo discovery is cheap
and frequent, video search is quota-limited and slow, so they run on separate cadences.

Cadence (pick with --daily / --weekly / --monthly):
  daily   — only scripts whose repo changed since we last looked. A new commit is the
            signal that a demo may have just been posted; unchanged repos are skipped.
  weekly  — scripts that still have no demo. Catches anything daily never triggered on,
            budget-capped so we cycle through the backlog over several weeks.
  monthly — re-verify existing demos are still public (drop unlisted/removed) AND a broad
            re-search. The safety net.

A script→demo mapping lives in demos.json (merged into the catalog's Demo field by
norns_ingest). Per-script bookkeeping (last check, last repo push, whether we've tried,
whether searching is worthwhile) lives in video_search_state.json so we never waste quota
re-searching the same dead ends.

Only PUBLIC videos are kept. YouTube/Vimeo search only return public results, and we
re-confirm privacy on monthly; an unlisted video (not publicly discoverable) is never added.
"""
import argparse
import datetime
import json
import os
import re
import time
import urllib.parse
import urllib.request
import urllib.error

import requests

CATALOG = "catalog.json"
DEMOS = "demos.json"
STATE = "video_search_state.json"

# YouTube search.list costs 100 quota units; default daily quota is 10,000. Cap searches
# per run so a weekly/monthly sweep can't blow the budget — the backlog drains over runs.
YT_SEARCH_BUDGET = 70
# Names too short or too generic produce noise, not the script's demo — don't burn quota.
GENERIC = {"awake", "less", "more", "test", "midi", "grid", "arc", "crow", "step", "loop",
           "drone", "noise", "fm", "echo", "play", "tape", "synth", "piano", "drums"}


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _key(path):
    """Last non-comment line of a key file (or '' if absent)."""
    try:
        for line in reversed(open(path).read().splitlines()):
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    except Exception:
        pass
    return ""


def repo_of(url):
    m = re.search(r"github\.com/([^/]+)/([^/\s]+)", url or "")
    return f"{m.group(1)}/{m.group(2)}".lower() if m else None


def searchable(name):
    """Is this script a good search candidate? Very short or generic names match noise."""
    n = (name or "").strip().lower()
    return len(n) >= 4 and n not in GENERIC


def yt_search(key, name, author):
    """Top YouTube results for a script; returns [(id, title, channel)]. Search returns
    only public videos, so a hit is publicly discoverable by construction."""
    if not key:
        return []
    q = urllib.parse.quote(f"{name} norns")
    url = (f"https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
           f"&maxResults=5&q={q}&key={key}")
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return []
        return [(it["id"]["videoId"], it["snippet"]["title"], it["snippet"]["channelTitle"])
                for it in r.json().get("items", []) if it.get("id", {}).get("videoId")]
    except Exception:
        return []


def yt_public(key, vid):
    """Confirm a YouTube video is public (not unlisted/private/removed)."""
    if not key:
        return False
    try:
        r = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=status&id={vid}&key={key}",
                         timeout=30)
        items = r.json().get("items", [])
        return bool(items) and items[0]["status"]["privacyStatus"] == "public"
    except Exception:
        return False


def vimeo_search(token, name, author):
    """Top Vimeo results; returns [(id, name, user)]."""
    if not token:
        return []
    q = urllib.parse.quote(f"{name} norns")
    try:
        r = requests.get(f"https://api.vimeo.com/videos?query={q}&per_page=5",
                         headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r.status_code != 200:
            return []
        out = []
        for v in r.json().get("data", []):
            m = re.search(r"/videos/(\d+)", v.get("uri", ""))
            if m and (v.get("privacy") or {}).get("view") == "anybody":
                out.append((m.group(1), v.get("name", ""), (v.get("user") or {}).get("name", "")))
        return out
    except Exception:
        return []


def matches(name, author, title, channel):
    """Confident match: the script name appears in the video title, and there's norns
    context (the word norns, or the author's handle in the title/channel). Conservative —
    a wrong demo is worse than none."""
    t, c = (title or "").lower(), (channel or "").lower()
    n, a = (name or "").lower(), (author or "").lower()
    if n not in t:
        return False
    return "norns" in t or "monome" in t or (a and (a in t or a in c))


def select_targets(mode, catalog, demos, state, today):
    """Which repos to search this run, per cadence."""
    targets = []
    for s in catalog.get("scripts", []):
        repo = repo_of(s.get("Project URL", ""))
        if not repo or not searchable(s.get("Name", "")):
            continue
        st = state.get(repo, {})
        has_demo = bool(demos.get(repo))
        if mode == "daily":
            # repo changed since we last checked → a demo may have just appeared
            pushed = (s.get("Last Updated") or "")
            if pushed and pushed > (st.get("checked", "")) and not has_demo:
                targets.append(s)
        elif mode == "weekly":
            if not has_demo and not st.get("tried_recently"):
                targets.append(s)
        elif mode == "monthly":
            targets.append(s)   # re-verify everything + re-search gaps
    return targets


def run(mode):
    catalog = _load(CATALOG, {"scripts": []})
    demos = _load(DEMOS, {})
    state = _load(STATE, {})
    today = datetime.date.today().isoformat()
    yt_key = os.environ.get("YT_API_KEY") or _key("yt.api")
    vimeo_token = os.environ.get("VIMEO_TOKEN") or _key("vimeo.api")

    # monthly: prune demos that are no longer public
    if mode == "monthly":
        dropped = 0
        for repo, v in list(demos.items()):
            u = v.get("demo") if isinstance(v, dict) else v
            m = re.search(r"v=([A-Za-z0-9_-]+)", u or "")
            if m and not yt_public(yt_key, m.group(1)):
                del demos[repo]; dropped += 1
        if dropped:
            print(f"monthly: dropped {dropped} demos no longer public")

    targets = select_targets(mode, catalog, demos, state, today)
    print(f"{mode}: {len(targets)} candidate scripts")
    searches = found = 0
    for s in targets:
        repo = repo_of(s["Project URL"])
        if mode != "daily" and searches >= YT_SEARCH_BUDGET:
            break   # quota guard; remaining drain on the next run
        name, author = s.get("Name", ""), s.get("Author", "")
        hit = None
        for vid, title, chan in yt_search(yt_key, name, author):
            if matches(name, author, title, chan):
                hit = f"https://www.youtube.com/watch?v={vid}"; break
        if not hit:
            for vid, title, user in vimeo_search(vimeo_token, name, author):
                if matches(name, author, title, user):
                    hit = f"https://vimeo.com/{vid}"; break
        searches += 1
        st = state.setdefault(repo, {})
        st["checked"] = today
        st["tried_recently"] = True
        if hit:
            demos[repo] = {"demo": hit, "checked": today}
            found += 1
        time.sleep(0.2)

    # weekly resets the "tried_recently" flag so the backlog re-cycles over time
    if mode == "monthly":
        for st in state.values():
            st["tried_recently"] = False

    json.dump(demos, open(DEMOS, "w"), indent=1, ensure_ascii=False, sort_keys=True)
    json.dump(state, open(STATE, "w"), indent=1, ensure_ascii=False, sort_keys=True)
    print(f"{mode}: {searches} searches, {found} new demos, {len(demos)} total")


def main():
    ap = argparse.ArgumentParser(description="Discover YouTube/Vimeo demos for norns scripts")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--daily", action="store_const", const="daily", dest="mode")
    g.add_argument("--weekly", action="store_const", const="weekly", dest="mode")
    g.add_argument("--monthly", action="store_const", const="monthly", dest="mode")
    run(ap.parse_args().mode)


if __name__ == "__main__":
    main()
