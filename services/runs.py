"""Run lifecycle: preview (freeze) and submit (gated enqueue).

MIGRATION.md Step 4 + the freeze invariant + DECIDED (b).

Flow:
  preview(project, connection, suite)
      -> resolve+freeze the probe set, persist it on a 'queued' run row,
         return {run_id, probe_count, probe_set_hash, billing_note, cap, embedder_id}
  submit(run_id, acknowledged_probe_count, probe_set_hash)
      -> 409 unless BOTH the count and the hash match the frozen run (re-disclose
         if the suite drifted). Enforce the cap. Then enqueue for the worker.

Preview already creates the run (status 'queued') so the frozen probe set has a
home; submit just transitions it to 'enqueued'/'queued-for-worker'. A previewed-
but-never-submitted run is an abandoned draft (a sweeper can GC old drafts).
"""
from datetime import datetime

from db import models
from profiles.loader import load_profile
from services.probe_set import resolve_probe_set, hash_probe_set

# Cost cap (MIGRATION.md: probe count visible AND capped before a run).
PROBE_CAP = 100


class ProbeCountMismatch(Exception):
    """Raised when submit's acknowledged count/hash != the frozen run -> HTTP 409."""


class ProbeCapExceeded(Exception):
    """Raised when a probe set exceeds PROBE_CAP -> HTTP 422."""


def _embedder_id() -> str:
    from evaluation.embedder import get_embedder
    return get_embedder().embedder_id


def preview(session, project_id: str, connection_id: str, suite_slug: str) -> dict:
    """Freeze the probe set for (project, connection, suite) and disclose cost."""
    profile = load_profile(suite_slug)
    probe_set = resolve_probe_set(profile)
    probe_count = len(probe_set)
    set_hash = hash_probe_set(probe_set)

    if probe_count > PROBE_CAP:
        raise ProbeCapExceeded(f"{probe_count} probes exceeds cap of {PROBE_CAP}")

    conn = session.get(models.Connection, connection_id)
    model_under_test = None
    if conn and conn.kind == "key_based":
        model_under_test = conn.key_based.model

    # Persist the run with its FROZEN probe set (the worker replays exactly this).
    run = models.ExperimentRun(
        project_id=project_id,
        connection_id=connection_id,
        suite_id=_ensure_suite(session, suite_slug, profile["version"], probe_count),
        status="draft",
        probe_count=probe_count,
        probe_set_hash=set_hash,
        profile_version=profile["version"],
        model_under_test=model_under_test,
        embedder_id=_embedder_id(),
    )
    session.add(run)
    session.flush()
    for p in probe_set:
        session.add(models.RunProbe(run_id=run.id, family=p["family"],
                                    prompt=p["prompt"], ordinal=p["ordinal"]))
    session.commit()

    return {
        "run_id": run.id,
        "suite": suite_slug,
        "probe_count": probe_count,
        "probe_set_hash": set_hash,
        "embedder_id": run.embedder_id,
        "billing_note": _billing_note(conn, probe_count),
        "cap": {"max_probes": PROBE_CAP, "within_cap": probe_count <= PROBE_CAP},
    }


def submit(session, run_id: str, acknowledged_probe_count: int, probe_set_hash: str,
           enqueue=None) -> dict:
    """Gate on (count, hash) then enqueue. 409 on any mismatch."""
    run = session.get(models.ExperimentRun, run_id)
    if run is None:
        raise ValueError("run not found")

    # 🔑 freeze gate: both the acknowledged count AND the hash must match the
    # frozen run. A profile edited since preview changes the hash -> 409.
    if acknowledged_probe_count != run.probe_count or probe_set_hash != run.probe_set_hash:
        raise ProbeCountMismatch(
            "probe set changed since preview; re-preview required "
            f"(expected count={run.probe_count}, hash={run.probe_set_hash[:12]}…)"
        )

    if run.probe_count > PROBE_CAP:
        raise ProbeCapExceeded(f"{run.probe_count} exceeds cap {PROBE_CAP}")

    run.status = "queued"
    run.queued_at = datetime.utcnow()
    session.commit()

    if enqueue is not None:
        enqueue(run.id)

    return {"run_id": run.id, "status": run.status, "probe_count": run.probe_count}


def _billing_note(conn, probe_count: int) -> str:
    if conn is None:
        return f"{probe_count} inference calls will run in simulation (no model connected)."
    if conn.kind == "key_based":
        return f"{probe_count} inference calls will be charged to YOUR {conn.key_based.provider} key."
    return f"{probe_count} inference calls will hit YOUR endpoint ({conn.endpoint_based.endpoint})."


def _ensure_suite(session, slug: str, version: str, probe_count: int) -> str:
    existing = (session.query(models.Suite)
                .filter_by(slug=slug, profile_version=version).one_or_none())
    if existing:
        return existing.id
    suite = models.Suite(slug=slug, profile_version=version, probe_count=probe_count)
    session.add(suite)
    session.flush()
    return suite.id
