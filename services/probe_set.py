"""Probe-set freezing (MIGRATION.md [INVARIANT] Probe-set freeze).

The cost guarantee from DECIDED (b) only holds if preview and the worker compute
the probe set from the SAME source of truth. So the probe set is resolved ONCE,
at preview, into a concrete ordered list of (family, prompt) pairs, hashed, and
persisted. The worker replays that frozen list — it never re-expands the suite.

Therefore acknowledged_probe_count == executed count by construction (same object),
and the 409 gate at submit is real rather than theatre.

`build_prompt_cases` (the suite expansion that used to live in run_audit and run
once per worker pass) now happens here, exactly once, at preview.
"""
import hashlib
import json

from run_audit import build_prompt_cases


def resolve_probe_set(profile: dict) -> list:
    """Expand a profile's prompt_families into an ordered list of probes.

    Returns [{"family", "prompt", "ordinal"}], ordinal fixing RW update order.
    This is the single point of suite expansion (was run_audit.build_prompt_cases,
    formerly re-run by every worker pass — see MIGRATION.md Step 5 correction).
    """
    cases = build_prompt_cases(profile["prompt_families"])
    return [
        {"family": c["family"], "prompt": c["prompt"], "ordinal": i}
        for i, c in enumerate(cases)
    ]


def hash_probe_set(probe_set: list) -> str:
    """Content hash of the ordered frozen set. Submit must echo this; a profile
    edited after preview yields a different hash -> 409 -> re-disclose."""
    canonical = json.dumps(
        [[p["ordinal"], p["family"], p["prompt"]] for p in probe_set],
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
