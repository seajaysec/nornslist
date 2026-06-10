"""Regression: no curated (norns.community) script may be excluded by a signal WE
deliberately apply. Curated = hand-vetted ground truth. HARD-FAIL only on the
intentional exclusion signals `fork-stale` and `red-flag` (a curated script hitting
those is a real classifier false positive). The `no-facet` reason is a data-
completeness artifact (community rows get their facets from feed enrichment; an
un-enriched row has empty kind) — it is reported as a WARNING, not a failure, since
a full scrape (Phase 8) populates those facets.
Run: ~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_curated_installable.py"""
import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "docs"))
import build_data as B  # noqa: E402

catalog = json.load(open(os.path.join(ROOT, "catalog.json")))["scripts"]
feed = json.load(open(os.path.join(ROOT, "feed.json")))
fm = feed.get("scripts", feed)

HARD = {"fork-stale", "red-flag"}
bad, warn = [], []
n_comm = 0
for row in catalog:
    if row.get("source") != "community":
        continue
    n_comm += 1
    nrow = B._normalize_row(row)
    enr = fm.get(nrow["name"].lower(), {})
    nrow["kind"] = list(nrow.get("kind") or enr.get("facets") or [])
    installable, reasons = B.derive_installable(nrow)
    hard = [r for r in reasons if r in HARD]
    if hard:
        bad.append((nrow["name"], hard))
    elif not installable:
        warn.append((nrow["name"], reasons))

if warn:
    print(f"WARN: {len(warn)} curated rows non-installable only via data gaps "
          f"(no-facet — resolved by a full scrape); not a failure:")
    for n, r in warn[:20]:
        print(f"  ~ {n}: {r}")
if bad:
    print(f"FAILED: {len(bad)} curated scripts wrongly excluded by an intentional signal:")
    for n, r in bad[:40]:
        print(f"  - {n}: {r}")
    sys.exit(1)
print(f"PASS: 0/{n_comm} curated scripts excluded by fork-stale/red-flag")
