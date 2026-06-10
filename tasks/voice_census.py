"""Voice-classification census over catalog.json + feed.json (read-only).
Run: ~/.virtualenvs/nornslist-vhmg/bin/python tasks/voice_census.py"""
import os, json, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
feed = json.load(open(os.path.join(ROOT, "feed.json")))
fm = feed.get("scripts", feed)
cat = json.load(open(os.path.join(ROOT, "catalog.json")))["scripts"]
src = {(r.get("Name") or "").strip().lower(): r.get("source") for r in cat}

prov = collections.Counter(); uses = collections.Counter()
n_umbrella = {"community": 0, "github": 0}
for name, e in fm.items():
    v = e.get("voices") or {}
    for p in v.get("provides") or []: prov[p] += 1
    for u in v.get("uses") or []: uses[u] += 1
    if v.get("provides"):
        n_umbrella[src.get(name, "github")] = n_umbrella.get(src.get(name, "github"), 0) + 1

print("=== voice PROVIDERS (umbrella 'additional voice') by system ===")
for k, c in prov.most_common(): print(f"  {c:4d}  {k}")
print("=== voice CONSUMERS (uses) by system ===")
for k, c in uses.most_common(): print(f"  {c:4d}  {k}")
print(f"=== umbrella-tagged scripts: {n_umbrella} ===")
