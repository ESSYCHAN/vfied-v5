"""
Golden regression baseline for the frozen behavioural engine.

Migration invariant (see MIGRATION.md, Frozen core): the RW model, lambda math,
cue lexicons and prompt families must produce identical outputs before and after
the SaaS migration. This harness pins those outputs for the `tax` profile in
SIMULATION mode (no adapter, no network) so they are deterministic.

Usage:
    python -m tests.golden --write     # regenerate the baseline (Step 0, and Step 2 re-baseline)
    python -m tests.golden             # check current engine against the baseline

Gates Steps 2, 5, 8 in the migration plan. Semantic scoring is intentionally
NOT exercised here (it requires anchors/embeddings); this isolates the pure
RW + lambda + cue path, which must never drift.
"""
import argparse
import json
from pathlib import Path

from profiles.loader import load_profile
from run_audit import run_audit

BASELINE_PATH = Path(__file__).parent / "golden_tax.json"


def compute_baseline() -> dict:
    """Run the tax profile in simulation mode and extract the engine outputs.

    Semantic scoring is suppressed two ways so the baseline is network-free and
    deterministic — pinning ONLY the RW + lambda + cue path:
      1. semantic_anchors removed -> evaluate_outcome's anchor branch is skipped.
      2. semantic_scorer.build_anchors_from_exemplars stubbed to return empty
         vectors -> run_audit's internal learned-anchor branch is skipped too.
    """
    import evaluation.semantic_scorer as sem

    profile = dict(load_profile("tax"))
    # Force simulation: without adapter_config, run_audit uses generate_response,
    # which is a pure deterministic function of cues/predicted risk.
    profile.pop("adapter_config", None)
    # Strip static semantic anchors so evaluate_outcome takes the rule-only path.
    profile.pop("semantic_anchors", None)

    # Suppress run_audit's internal learned-anchor build (it would call embeddings).
    original_builder = sem.build_anchors_from_exemplars
    sem.build_anchors_from_exemplars = lambda *a, **k: {"unsafe_vec": None, "safe_vec": None}
    try:
        report = run_audit(profile)
    finally:
        sem.build_anchors_from_exemplars = original_builder

    # Pin only the engine-produced, deterministic fields.
    return {
        "risk_score": report["risk_score"],
        "avg_lambda": report["avg_lambda"],
        "status": report["status"],
        "top_weakness_family": report["top_weakness_family"],
        "top_safe_family": report["top_safe_family"],
        "family_summary": report["family_summary"],
        "weights": report["weights"],
    }


def write_baseline():
    baseline = compute_baseline()
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote golden baseline -> {BASELINE_PATH}")
    print(f"  risk_score={baseline['risk_score']} avg_lambda={baseline['avg_lambda']} status={baseline['status']}")


def check_baseline() -> bool:
    if not BASELINE_PATH.exists():
        print("No baseline found. Run: python -m tests.golden --write")
        return False

    expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    actual = compute_baseline()

    if actual == expected:
        print("GOLDEN OK — engine output matches baseline.")
        return True

    print("GOLDEN MISMATCH — engine output drifted from baseline:")
    for key in sorted(set(expected) | set(actual)):
        if expected.get(key) != actual.get(key):
            print(f"  [{key}]")
            print(f"    expected: {json.dumps(expected.get(key))}")
            print(f"    actual:   {json.dumps(actual.get(key))}")
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Golden regression baseline for the frozen engine")
    parser.add_argument("--write", action="store_true", help="Regenerate the baseline")
    args = parser.parse_args()

    if args.write:
        write_baseline()
    else:
        ok = check_baseline()
        raise SystemExit(0 if ok else 1)
