"""Recall + precision guards for the norns classifier. These are the tests that were missing
when real scripts (ack, mlr256, ynth, TW_Norns) silently dropped out of the catalog.

Recall cases use recorded real-repo fixtures (tests/fixtures/recall.json); precision and facet
cases are synthetic so they're deterministic and need no network.
"""
import json
import os

import pytest

import norns_ingest as ni

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "recall.json")
with open(FIXTURES) as f:
    RECALL = json.load(f)


def _rd(fx):
    """Reconstruct the GraphQL repo node _record expects from a recorded fixture."""
    return {
        "description": fx.get("description") or "",
        "repositoryTopics": {"nodes": [{"topic": {"name": t}} for t in fx.get("topics", [])]},
        "pushedAt": "2024-01-01T00:00:00Z", "stargazerCount": fx.get("stars", 0),
        "isArchived": fx.get("is_archived", False), "isFork": fx.get("is_fork", False),
    }


# ── recall: every known-good norns repo must be recognised as norns + installable ──
@pytest.mark.parametrize("full", sorted(RECALL))
def test_known_repo_classifies_as_installable_norns(full):
    fx = RECALL[full]
    key = (fx["owner"], fx["name"])
    rec = ni._record(key, _rd(fx), fx["paths"], fx["blob"])
    assert rec is not None, f"{full} was rejected by the norns gate (false negative)"
    # usable facet = installable once fork-ahead is resolved (a separate REST step in the
    # pipeline, not part of _record). is_installable would reject an unresolved fork here.
    assert any(f in ni.USABLE_FACETS for f in rec["facets"]), f"{full} has no usable facet"


def test_tw_norns_is_a_collection():
    """A 9-script repo must be tracked as a 'collection', not dropped by the monorepo guard."""
    fx = RECALL["TomWhitwell/TW_Norns"]
    facets = ni.facets_from_paths(fx["paths"])
    assert "collection" in facets
    assert "script" not in facets


# ── facets: path-shape → facet labels ──
def test_single_script_facet():
    assert ni.facets_from_paths(["awake.lua", "README.md"]) == ["script"]


def test_seven_top_lua_is_still_a_script():
    paths = [f"s{i}.lua" for i in range(7)]
    assert "script" in ni.facets_from_paths(paths)
    assert "collection" not in ni.facets_from_paths(paths)


def test_eight_top_lua_becomes_collection():
    paths = [f"s{i}.lua" for i in range(8)]
    facets = ni.facets_from_paths(paths)
    assert "collection" in facets and "script" not in facets


def test_mod_and_engine_and_library_facets():
    assert "mod" in ni.facets_from_paths(["lib/mod.lua"])
    assert "engine" in ni.facets_from_paths(["awake.lua", "lib/Engine_Foo.sc"])
    assert ni.facets_from_paths(["lib/helper.lua"]) == ["library"]


def test_native_mod_with_no_lua():
    assert ni.facets_from_paths(["dep/norns/foo.h", "src/mod.cpp"]) == ["mod"]


# ── precision: non-norns repos must be rejected ──
def test_rejects_weak_marker_without_context():
    """A roguelike whose only hit is `engine.` (weak) with no norns context — coincidence."""
    rec = ni._record(("someone", "roguelike"),
                     {"description": "a dungeon crawler", "repositoryTopics": {"nodes": []}},
                     ["main.lua"], "function love.load() engine.start() end")
    assert rec is None


def test_rejects_website_screen_only():
    rec = ni._record(("someone", "portfolio"),
                     {"description": "my website", "repositoryTopics": {"nodes": []}},
                     ["app.lua"], "screen.render()")
    assert rec is None


def test_weak_marker_with_norns_context_is_accepted():
    """Same single weak marker, but the repo names norns → real minimal script."""
    rec = ni._record(("someone", "tiny-norns-script"),
                     {"description": "a norns script", "repositoryTopics": {"nodes": []}},
                     ["script.lua"], "metro.init()")
    assert rec is not None


def test_strong_marker_alone_is_accepted():
    rec = ni._record(("someone", "thing"),
                     {"description": "", "repositoryTopics": {"nodes": []}},
                     ["thing.lua"], "function redraw() end")
    assert rec is not None


# ── empty corpus: reject unless we have a prior verdict to carry forward ──
def test_empty_corpus_non_native_is_rejected():
    rec = ni._record(("someone", "thing"),
                     {"description": "", "repositoryTopics": {"nodes": []}},
                     ["thing.lua"], "")
    assert rec is None


def test_empty_corpus_native_mod_still_passes():
    """dep/norns is the fingerprint; a native mod needs no corpus text."""
    rec = ni._record(("someone", "hdmi-mod"),
                     {"description": "", "repositoryTopics": {"nodes": []}},
                     ["dep/norns/x.h", "src/mod.cpp"], "")
    assert rec is not None
