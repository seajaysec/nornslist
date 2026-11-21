#!/usr/bin/env python3
"""Dev tool — record real (paths, blob) for a set of repos into tests/fixtures/recall.json so
the recall regression test runs offline. Re-run when the fixture set changes:

    GH_PAT=$(gh auth token) python tests/record_fixtures.py

Not a test itself (no `test_` prefix); pytest ignores it.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import norns_ingest as ni  # noqa: E402

# (owner, name, expect_installable) — the known-good norns repos that have flapped out of the
# catalog, plus one multi-script collection. The test asserts each is classified as norns.
RECALL = [
    ("antonhornquist", "ack", True),
    ("256k", "mlr256", True),
    ("aidanreilly", "16klangs", True),
    ("andr-ew", "ledmap", True),
    ("andr-ew", "arqueggiator", True),
    ("schollz", "ynth", True),
    ("TomWhitwell", "TW_Norns", True),
    ("hankyates", "norns-convolution-reverb", True),
]


def main():
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("set GH_PAT")
    gh = ni.GH(token)
    keys = [(o, n) for o, n, _ in RECALL]
    meta = ni._fetch_meta(gh, keys)
    out = {}
    for o, n, expect in RECALL:
        rd = meta.get((o, n))
        if not rd:
            print(f"WARN: no metadata for {o}/{n} (404?) — skipping")
            continue
        paths = ni._paths_from_tree(rd.get("object"))
        files = ni.voice_corpus_paths(paths, ni.bundled_libs(paths))
        blob = ni._fetch_corpus(gh, [((o, n), rd, paths, files)]).get((o, n), "")
        out[f"{o}/{n}"] = {
            "owner": o, "name": n, "expect_installable": expect,
            "description": rd.get("description") or "",
            "topics": [t["topic"]["name"] for t in
                       ((rd.get("repositoryTopics") or {}).get("nodes") or []) if t.get("topic")],
            "is_fork": bool(rd.get("isFork")), "is_archived": bool(rd.get("isArchived")),
            "stars": rd.get("stargazerCount") or 0,
            "paths": paths, "blob": blob,
        }
        print(f"recorded {o}/{n}: {len(paths)} paths, {len(blob)} blob chars")
    dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "recall.json")
    with open(dest, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"wrote {dest}: {len(out)} repos")


if __name__ == "__main__":
    main()
