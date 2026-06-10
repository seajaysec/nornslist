"""Parity contract: canonical Lua/SC snippets -> expected voice classification.
These fixtures are the shared source of truth between the nornslist scraper
(_detect_voices) and ingenue's analyze_dir/index.html live detector. Keep both
sides matching this file.
Run: ~/.virtualenvs/nornslist-vhmg/bin/python tasks/test_voice_parity.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from norns_scraper_discourse import NornsScraper as S  # noqa: E402

# (blob, paths, facets, repo) -> expected {provides, uses}
FIXTURES = [
    ('nb:add_player("x", p)', ["m.lua"], ["mod"], "m", {"provides": ["nb"], "uses": []}),
    ('local nb=require"nb/lib/nb"', ["m.lua"], ["script"], "m", {"provides": [], "uses": ["nb"]}),
    ('require("mx.samples/lib/mx.samples")', ["m.lua"], ["script"], "m", {"provides": [], "uses": ["mx.samples"]}),
    ('require("mx.synths/lib/mx.synths")', ["m.lua"], ["script"], "m", {"provides": [], "uses": ["mx.synths"]}),
    ("SynthDef", ["lib/Engine_Ack.sc"], ["library", "engine"], "ack", {"provides": ["sc-engine"], "uses": []}),
    ("SynthDef", ["a.lua", "lib/Engine_A.sc"], ["script", "engine"], "a", {"provides": [], "uses": []}),
    ('engine.name="Rings"', ["m.lua"], ["script"], "m", {"provides": [], "uses": ["sc-engine"]}),
    ("crow.output[1].volts=1", ["m.lua"], ["script"], "m", {"provides": [], "uses": []}),
]

fails = []
for i, (blob, paths, facets, repo, want) in enumerate(FIXTURES):
    got = S._detect_voices(blob, paths, set(), facets, repo)
    if got["provides"] != want["provides"] or got["uses"] != want["uses"]:
        fails.append(f"fixture {i} ({repo}): got p={got['provides']} u={got['uses']} "
                     f"want p={want['provides']} u={want['uses']}")
if fails:
    print("PARITY FAILED:"); [print("  -", f) for f in fails]; sys.exit(1)
print(f"PARITY OK: {len(FIXTURES)} fixtures")
