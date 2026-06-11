"""Connection creation (MIGRATION.md Step 4 + trust-model split).

Two trust models, two code paths — never one nullable blob. Secrets are encrypted
on receipt and NEVER echoed back: key-based returns only api_key_last4; endpoint
returns no headers at all.
"""
import json

from db import crypto, models


def create_key_based(session, project_id: str, display_name: str,
                     provider: str, model: str, api_key: str, system_prompt: str = None):
    if provider not in ("anthropic",):  # MVP guard; widen in v2
        raise ValueError(f"Unsupported key-based provider in MVP: {provider}")

    conn = models.Connection(project_id=project_id, kind="key_based", display_name=display_name)
    session.add(conn)
    session.flush()
    session.add(models.ConnectionKeyBased(
        connection_id=conn.id,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        api_key_ciphertext=crypto.encrypt(api_key),   # 🔒 encrypted at rest
        api_key_kms_key_id=crypto.kms_key_id(),
        api_key_last4=api_key[-4:] if api_key else None,
    ))
    session.commit()
    return conn


def create_endpoint_based(session, project_id: str, display_name: str,
                         endpoint: str, headers: dict = None,
                         request_field: str = "prompt", response_path: str = "response",
                         timeout: int = 60):
    conn = models.Connection(project_id=project_id, kind="endpoint_based", display_name=display_name)
    session.add(conn)
    session.flush()
    # DECIDED (a): encrypt the WHOLE headers blob opaquely (no per-header classifier).
    headers_ct = crypto.encrypt(json.dumps(headers)) if headers else None
    session.add(models.ConnectionEndpointBased(
        connection_id=conn.id,
        endpoint=endpoint,
        headers_ciphertext=headers_ct,
        headers_kms_key_id=crypto.kms_key_id() if headers_ct else None,
        request_field=request_field,
        response_path=response_path,
        timeout=timeout,
    ))
    session.commit()
    return conn


def to_public_dict(session, conn: models.Connection) -> dict:
    """Serialize a connection WITHOUT any secret material."""
    base = {"id": conn.id, "kind": conn.kind, "display_name": conn.display_name}
    if conn.kind == "key_based":
        kb = conn.key_based
        base.update({"provider": kb.provider, "model": kb.model, "api_key_last4": kb.api_key_last4})
    else:
        ep = conn.endpoint_based
        base.update({"endpoint": ep.endpoint, "request_field": ep.request_field,
                     "response_path": ep.response_path, "timeout": ep.timeout})
        # headers intentionally omitted — never echoed.
    return base


def build_adapter_config(conn: models.Connection) -> tuple:
    """Reconstruct the adapter_config dict + decrypted credential for a run.

    Called JUST-IN-TIME in the worker. The decrypted secret is returned to the
    caller's memory only; it is never persisted or logged. Returns
    (adapter_config, credential).
    """
    if conn.kind == "key_based":
        kb = conn.key_based
        credential = crypto.decrypt(kb.api_key_ciphertext)  # JIT decrypt
        return ({"provider": kb.provider, "model": kb.model, "system_prompt": kb.system_prompt},
                credential)
    ep = conn.endpoint_based
    headers = json.loads(crypto.decrypt(ep.headers_ciphertext)) if ep.headers_ciphertext else {}
    return ({"provider": "http", "endpoint": ep.endpoint, "headers": headers,
             "request_field": ep.request_field, "response_path": ep.response_path,
             "timeout": ep.timeout},
            None)  # endpoint mode: VFIED holds no separate credential
