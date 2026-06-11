"""Object storage abstraction (MIGRATION.md Step 3).

Large response blobs and report artifacts (PDF/JSON) go here, not in Postgres.
Dev: filesystem-backed under ./_objectstore, tenant-prefixed by project_id.
Prod: swap `put`/`get`/`signed_url` for S3/GCS; the interface is unchanged.

Tenant prefixing (project_id/...) replaces the current global JSONL files in
collector.py, which pooled all tenants' data into one shared file.
"""
import os
from pathlib import Path

_ROOT = Path(os.getenv("VFIED_OBJECT_STORE", "_objectstore"))


def put(project_id: str, key: str, data: str) -> str:
    """Store text data, return a uri. Key is namespaced by project for isolation."""
    path = _ROOT / project_id / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return f"obj://{project_id}/{key}"


def get(uri: str) -> str:
    assert uri.startswith("obj://")
    rel = uri[len("obj://"):]
    return (_ROOT / rel).read_text(encoding="utf-8")


def signed_url(uri: str) -> str:
    """Dev: return the local path. Prod: a time-limited signed S3/GCS URL."""
    assert uri.startswith("obj://")
    rel = uri[len("obj://"):]
    return str((_ROOT / rel).resolve())
