"""Offline unit tests for catalog.json emission (no network).

Run: ~/.virtualenvs/nornslist-ddno/bin/python tasks/test_catalog.py

catalog.json is the canonical full-rows catalog that docs/build_data.py prefers
over the xlsx. These lock in the row shape and — critically — that tags emitted
as a JSON list survive build_data._normalize_row (the bug that corrupted every
tag when catalog.json first used capitalized "Tags": a list fell through to the
comma-splitter and became ["['art']", 'art']).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from norns_scraper_discourse import NornsScraper  # noqa: E402

S = NornsScraper
fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r} want {want!r}")


inst = object.__new__(NornsScraper)

# --- _catalog_clean: NaN/None -> '', scalars stringified, lists passthrough ---
import math  # noqa: E402

check("clean_none", S._catalog_clean(None), "")
check("clean_nan", S._catalog_clean(float("nan")), "")
check("clean_str", S._catalog_clean("  hi  "), "hi")
check("clean_list_passthrough", S._catalog_clean(["a", "b"]), ["a", "b"])

# --- write_catalog_json: shape, lowercase-name skip, tags-as-list, sorted ---
import json  # noqa: E402
import tempfile  # noqa: E402

inst.FIELD_MAP = S.FIELD_MAP
rows = [
    {"Name": "Zebra", "Author": "z", "Tags": "drone, grid, drone", "Description": "d",
     "Demo": "", "Discussion URL": "", "Project URL": "https://github.com/z/zebra",
     "Documentation URL": "", "Community URL": "", "Playwright Status": "",
     "Last Updated": "2024-01-02", "Out of Sync": ""},
    {"Name": "apple", "Tags": ["art", "Art", "fx"], "Project URL": ""},  # dup-casing + list input
    {"Name": "", "Tags": "skip"},  # nameless -> dropped
]
with tempfile.TemporaryDirectory() as tmp:
    xlsx = os.path.join(tmp, "s.xlsx")
    inst.write_catalog_json(rows, xlsx)
    out = os.path.join(tmp, "catalog.json")
    payload = json.load(open(out))

check("catalog_kind", payload["file_info"]["kind"], "script_catalog")
scripts = payload["scripts"]
check("catalog_drops_nameless", len(scripts), 2)
check("catalog_sorted_by_name", [s["Name"] for s in scripts], ["apple", "Zebra"])
zebra = next(s for s in scripts if s["Name"] == "Zebra")
check("catalog_tags_is_list", isinstance(zebra["Tags"], list), True)
check("catalog_tags_split_deduped", zebra["Tags"], ["drone", "grid"])
check("catalog_all_fieldmap_cols", set(zebra) == set(S.FIELD_MAP), True)
apple = next(s for s in scripts if s["Name"] == "apple")
check("catalog_tags_list_input_deduped", apple["Tags"], ["art", "fx"])  # case-insensitive dedupe

# --- the regression guard: build_data._normalize_row must keep a tags LIST intact ---
DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
sys.path.insert(0, DOCS)
import build_data  # noqa: E402

nr_caps = build_data._normalize_row({"Name": "x", "Tags": ["art", "fx"]})
check("normalize_list_under_Tags", nr_caps["tags"], ["art", "fx"])
nr_lower = build_data._normalize_row({"name": "x", "tags": ["art", "fx"]})
check("normalize_list_under_tags", nr_lower["tags"], ["art", "fx"])
nr_str = build_data._normalize_row({"Name": "x", "Tags": "art, fx, art"})
check("normalize_comma_string", nr_str["tags"], ["art", "fx"])

if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CATALOG CHECKS PASSED")
