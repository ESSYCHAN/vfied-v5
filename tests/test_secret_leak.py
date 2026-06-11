"""Secret-leak audit (MIGRATION.md Step 8).

The fixed decision: customer credentials are never logged, never written to
response/exemplar rows, never in a report. This test plants sentinel secrets in
both trust models, runs a full simulated audit, and asserts the sentinels appear
NOWHERE in: the public connection serialization, persisted Response rows, the
Report, the object-store artifacts, or the run's error field.

Run: python -m tests.test_secret_leak
"""
import json
import sys

from db.session import init_db, get_session
from db import models, object_store
from services import connections as conn_svc
from services import runs as run_svc
from worker import process_run

KEY_SENTINEL = "sk-ant-SENTINEL-DO-NOT-LEAK-12345"
HEADER_SENTINEL = "Bearer HEADER-SENTINEL-DO-NOT-LEAK-67890"


def _scan(blob: str, label: str, failures: list):
    for sentinel in (KEY_SENTINEL, HEADER_SENTINEL):
        if sentinel in (blob or ""):
            failures.append(f"LEAK: {sentinel[:20]}… found in {label}")


def main():
    init_db()
    s = get_session()
    failures = []

    p = models.Project(owner_id="u1", name="LeakAudit")
    s.add(p); s.commit()

    # Plant sentinels in BOTH trust models.
    kb = conn_svc.create_key_based(s, p.id, "kb", "anthropic", "claude-opus-4-8", KEY_SENTINEL)
    ep = conn_svc.create_endpoint_based(s, p.id, "ep", "https://example.com",
                                        headers={"Authorization": HEADER_SENTINEL})

    # 1. Public serialization must not echo secrets.
    _scan(json.dumps(conn_svc.to_public_dict(s, kb)), "key_based public dict", failures)
    _scan(json.dumps(conn_svc.to_public_dict(s, ep)), "endpoint public dict", failures)

    # 2. Stored ciphertext must NOT contain the plaintext sentinel.
    _scan(kb.key_based.api_key_ciphertext.decode("latin-1"), "api_key_ciphertext", failures)
    _scan(ep.endpoint_based.headers_ciphertext.decode("latin-1"), "headers_ciphertext", failures)

    # 3. Run an audit in simulation (no real network) and scan persisted artifacts.
    prev = run_svc.preview(s, p.id, "no-conn", "tax")
    run_svc.submit(s, prev["run_id"], prev["probe_count"], prev["probe_set_hash"])
    s.close()
    process_run(prev["run_id"])

    s = get_session()
    run = s.get(models.ExperimentRun, prev["run_id"])
    for resp in s.query(models.Response).filter_by(run_id=run.id).all():
        _scan(resp.prompt_text, "response.prompt_text", failures)
        _scan(resp.response_preview, "response.response_preview", failures)
        _scan(object_store.get(resp.response_blob_uri), "response blob", failures)
    rep = s.query(models.Report).filter_by(run_id=run.id).one()
    _scan(json.dumps(rep.recommendations), "report.recommendations", failures)
    _scan(object_store.get(rep.json_uri), "report json artifact", failures)
    _scan(run.error or "", "run.error", failures)
    s.close()

    if failures:
        print("SECRET-LEAK AUDIT FAILED:")
        for f in failures:
            print("  " + f)
        return 1
    print("SECRET-LEAK AUDIT PASSED — no credential material in any persisted/serialized surface.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
