"""Measure GitHub-discovery coverage vs the community.json ground truth.

Roadmap #3, step 1: before broadening discovery we must know which of the ~351
community.json repos a naive `norns language:lua` repo search misses, and why.
This script is read-only (search + repo-meta only) and prints a coverage report
+ a categorised breakdown of the misses so the multi-strategy design is driven
by data, not guesswork.

Run: ~/.virtualenvs/nornslist-ddno/bin/python tasks/discovery_coverage.py
"""
import os
import re
import sys
import time
import logging

logging.disable(logging.WARNING)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from norns_scraper_discourse import NornsScraper  # noqa: E402

GH = "https://api.github.com"


def parse_repo(url):
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", url or "")
    if not m:
        return None
    return (m.group(1).lower(), m.group(2).lower().removesuffix(".git"))


def search_repos(sc, q, cap_pages=10):
    """Return (total_count, set_of_(owner,repo)) for a repo search, paginated to
    the GitHub 1000-result cap (per_page=100 * 10 pages)."""
    found = set()
    total = None
    for page in range(1, cap_pages + 1):
        r = sc.github_session.get(
            f"{GH}/search/repositories",
            params={"q": q, "per_page": 100, "page": page, "sort": "updated", "order": "desc"},
            timeout=30,
        )
        if r.status_code == 403:
            print(f"  ! rate-limited on '{q}' page {page}; partial result")
            break
        r.raise_for_status()
        j = r.json()
        if total is None:
            total = j.get("total_count")
        items = j.get("items") or []
        for it in items:
            owner = (it.get("owner") or {}).get("login", "").lower()
            name = (it.get("name") or "").lower()
            if owner and name:
                found.add((owner, name))
        if len(items) < 100:
            break
        time.sleep(2.0)  # search API: ~30 req/min authenticated
    return total, found


def main():
    sc = NornsScraper()
    entries = sc.fetch_community_json()
    truth = {}
    for e in entries:
        rp = parse_repo(e.get("project_url"))
        if rp:
            truth[rp] = e.get("project_name")
    non_gh = [e.get("project_name") for e in entries if not parse_repo(e.get("project_url"))]
    print(f"community.json: {len(entries)} entries, {len(truth)} unique GitHub repos, "
          f"{len(non_gh)} non-GitHub")
    if non_gh:
        print(f"  non-GitHub project_urls: {non_gh}")

    strategies = {
        "norns language:lua": "norns language:lua",
        "topic:norns": "topic:norns",
        "norns in:name,description,readme": "norns",
    }
    covered_by = {}
    union = set()
    for label, q in strategies.items():
        total, found = search_repos(sc, q)
        covered = found & set(truth)
        covered_by[label] = covered
        union |= found
        print(f"\n[{label}]  total_count={total}  retrieved={len(found)}  "
              f"covers {len(covered)}/{len(truth)} community repos "
              f"({100*len(covered)//max(1,len(truth))}%)")

    union_covered = union & set(truth)
    missed = set(truth) - union
    print(f"\n=== UNION of strategies: covers {len(union_covered)}/{len(truth)} "
          f"({100*len(union_covered)//max(1,len(truth))}%) ===")
    print(f"MISSED {len(missed)} community repos by ALL strategies above.")

    # Categorise a sample of misses by probing repo meta (404 / archived / fork /
    # not lua-dominant / lacks 'norns' anywhere obvious).
    print("\nProbing missed repos (meta) to categorise...")
    cats = {"404_gone": [], "archived": [], "fork": [], "not_lua": [], "renamed_redirect": [], "exists_other": []}
    for (owner, repo) in sorted(missed):
        meta = sc._repo_meta(owner, repo)
        st = meta.get("_status", 200)
        if st == 404:
            cats["404_gone"].append(f"{owner}/{repo}")
            continue
        if st == 403:
            continue
        if meta.get("archived"):
            cats["archived"].append(f"{owner}/{repo}")
        if meta.get("fork"):
            cats["fork"].append(f"{owner}/{repo}")
        lang = (meta.get("language") or "").lower()
        if lang and lang != "lua":
            cats["not_lua"].append(f"{owner}/{repo} ({lang})")
        full = (meta.get("full_name") or "").lower()
        if full and full != f"{owner}/{repo}":
            cats["renamed_redirect"].append(f"{owner}/{repo} -> {full}")
        cats["exists_other"].append(f"{owner}/{repo}")
        time.sleep(0.05)

    for cat, items in cats.items():
        print(f"\n-- {cat}: {len(items)}")
        for it in items[:40]:
            print(f"    {it}")
        if len(items) > 40:
            print(f"    ... +{len(items)-40} more")


if __name__ == "__main__":
    main()
