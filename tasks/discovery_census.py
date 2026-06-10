"""Census + gate-quality check for GitHub discovery (roadmap #3).

Two things to prove before wiring discovery into the catalog:
  1. GATE QUALITY — the NORNS_FP classifier must KEEP real norns repos (no false
     negatives). We sample known community repos and confirm they classify as norns.
  2. NET-NEW YIELD — how many norns repos exist beyond community.json, and do a
     few sampled passes/rejects look right (false-positive eyeball)?

Usage:
  python tasks/discovery_census.py --authors 0      # broad strategies only (fast)
  python tasks/discovery_census.py --authors 40     # + first 40 known authors
  python tasks/discovery_census.py --authors all    # full aggressive sweep (slow)
"""
import os
import re
import sys
import argparse
import logging

logging.disable(logging.INFO)  # keep WARN+ (rate-limit notices) but drop chatter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from norns_scraper_discourse import NornsScraper  # noqa: E402


def parse_repo(url):
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", url or "")
    return (m.group(1).lower(), m.group(2).lower().removesuffix(".git")) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--authors", default="0", help="0 | N | all")
    ap.add_argument("--excel", default="norns_scripts_discourse.xlsx")
    args = ap.parse_args()
    max_auth = None if args.authors == "all" else int(args.authors)

    sc = NornsScraper()
    entries = sc.fetch_community_json()
    community = {}
    for e in entries:
        rp = parse_repo(e.get("project_url"))
        if rp:
            community[rp] = e.get("project_name")
    owners = {o for (o, _) in community}
    print(f"community: {len(community)} repos, {len(owners)} unique owners")

    # ---- 1. GATE QUALITY: sample known community repos, expect ~100% norns ----
    import threading
    sample = sorted(community)[:: max(1, len(community) // 30)][:30]
    lock = threading.Lock()
    cache = {}
    kept = 0
    misses = []
    for (owner, repo) in sample:
        meta = sc._repo_meta(owner, repo)
        if meta.get("_status") in (403, 404):
            continue
        v = sc._classify_norns_repo(owner, repo, meta.get("default_branch"),
                                    meta.get("pushed_at"), cache, lock)
        if v.get("is_norns"):
            kept += 1
        elif v.get("is_norns") is False:
            misses.append(f"{owner}/{repo}")
    print(f"\n[gate quality] {kept}/{len(sample)} sampled community repos classified norns; "
          f"false-negatives: {misses or 'none'}")

    # ---- 2. NET-NEW YIELD ----
    print(f"\n[discovery] running (authors={args.authors})...")
    discovered = sc.discover_github_repos(set(community), args.excel,
                                          aggressive=True, max_author_searches=max_auth)
    print(f"\n=== NET-NEW norns repos beyond community.json: {len(discovered)} ===")
    by_facet = {}
    archived = 0
    for rec in discovered.values():
        archived += 1 if rec["archived"] else 0
        for f in (rec["facets"] or ["(none)"]):
            by_facet[f] = by_facet.get(f, 0) + 1
    print(f"facets: {by_facet} | archived: {archived}")
    print("\nsample passes (by stars):")
    for rec in sorted(discovered.values(), key=lambda r: -r["stars"])[:20]:
        print(f"  {rec['owner']}/{rec['name']}  ★{rec['stars']}  {rec['facets']}  "
              f"{(rec['desc'] or '')[:60]}")


    # --- installability reclassification breakdown (added with voice/install work) ---
    import json as _json
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
    import build_data as _B
    _cat = _json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "catalog.json")))["scripts"]
    _by = {}
    for _r in _cat:
        _nr = _B._normalize_row(_r)
        _ok, _why = _B.derive_installable(_nr)
        _key = "installable" if _ok else ",".join(_why)
        _by[_key] = _by.get(_key, 0) + 1
    print("\n=== installability breakdown (catalog.json) ===")
    for _k, _c in sorted(_by.items(), key=lambda x: -x[1]):
        print(f"  {_c:4d}  {_k}")


if __name__ == "__main__":
    main()
