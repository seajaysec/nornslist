"""Offline unit tests for docs/build_data.py pure derivation helpers."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
import build_data as B  # noqa: E402

fails = []; _checks = 0
def check(name, got, want):
    global _checks; _checks += 1
    if got != want: fails.append(f"{name}: got {got!r} want {want!r}")

# --- installability gate ---
def inst(**row):
    row.setdefault("name", "x"); row.setdefault("desc", ""); row.setdefault("kind", ["script"])
    row.setdefault("fork", False); row.setdefault("fork_ahead", False); row.setdefault("source", "github")
    return B.derive_installable(row)[0]

check("inst_plain_script", inst(), True)
check("inst_fork_stale_excluded", inst(fork=True), False)            # unmodified/behind-only fork
check("inst_fork_ahead_kept", inst(fork=True, fork_ahead=True), True)  # diverged fork: valuable, kept
check("inst_mod_ok", inst(kind=["mod"]), True)              # mods are installable
check("inst_engine_only_ok", inst(kind=["library", "engine"]), True)  # ack-shape dep is installable
check("inst_no_facet_excluded", inst(kind=[]), False)
check("inst_redflag_tutorial", inst(name="norns-tutorial"), False)
check("inst_redflag_in_desc", inst(desc="a study group exercise"), False)

# curated false-positive guards (these MUST stay installable — low-precision words)
check("inst_acid_test_ok", inst(name="acid-test", desc="generative acid basslines"), True)
check("inst_grid_test_ok", inst(name="grid-test", desc="A utility script for testing grids"), True)
check("inst_playground_ok", inst(name="twins", desc="randomized dual granular playground"), True)
check("inst_example_ok", inst(name="passthrough", desc="midi passthrough library with examples"), True)
check("inst_community_never_fork", inst(source="community", name="awake"), True)

# --- voice tags ---
check("vt_umbrella_on_provides", "additional voice" in B.voice_tags({"provides": ["nb"], "uses": [], "systems": ["nb"]}), True)
check("vt_no_umbrella_uses_only", "additional voice" in B.voice_tags({"provides": [], "uses": ["nb"], "systems": ["nb"]}), False)
check("vt_subtype_nb", "nb" in B.voice_tags({"provides": ["nb"], "uses": [], "systems": ["nb"]}), True)
check("vt_nb_ready_on_uses", "nb-ready" in B.voice_tags({"provides": [], "uses": ["nb"], "systems": ["nb"]}), True)
check("vt_mx_subtype", "mx.samples" in B.voice_tags({"provides": [], "uses": ["mx.samples"], "systems": ["mx.samples"]}), True)
check("vt_empty", B.voice_tags({"provides": [], "uses": [], "systems": []}), [])

if fails:
    print("FAILED:"); [print("  -", f) for f in fails]; sys.exit(1)
print(f"ALL {_checks} CHECKS PASSED")
