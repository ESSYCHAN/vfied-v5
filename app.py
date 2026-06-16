from dotenv import load_dotenv
load_dotenv()

from typing import Optional, Dict, Union
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from run_audit import run_audit
from profiles.loader import load_profile

from db.session import init_db, get_session
from db import models
from services import connections as conn_svc
from services import runs as run_svc

app = FastAPI(
    title="VFIED — Behaviour Evaluation Platform",
    description="Bring your own AI. VFIED tests the behaviour.",
    version="2.0.0",
)


@app.on_event("startup")
def _startup():
    init_db()  # dev convenience; prod uses migrations


# ---------------------------------------------------------------------------
# Legacy synchronous endpoint (MIGRATION.md: kept beside the new API until the
# async path is proven in Step 8, then removed). Unchanged behaviour.
# ---------------------------------------------------------------------------
class AuditRequest(BaseModel):
    domain: str = "tax"
    provider: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    endpoint: Optional[str] = None


@app.get("/")
def root():
    return {"product": "VFIED", "tagline": "Bring your own AI. VFIED tests the behaviour.",
            "version": "2.0.0", "status": "running"}


@app.post("/audit")
def audit(request: AuditRequest):
    """DEPRECATED legacy path — synchronous, single-call. Use /api/v1/runs."""
    try:
        profile = load_profile(request.domain)
        if request.provider:
            profile["adapter_config"] = {
                "provider": request.provider, "model": request.model,
                "system_prompt": request.system_prompt, "endpoint": request.endpoint,
            }
        return run_audit(profile)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# v1 run-lifecycle API (MIGRATION.md Step 4). Async shape: preview -> submit ->
# poll -> results. The probe set is frozen at preview; submit gates on it.
# ---------------------------------------------------------------------------
API = "/api/v1"


class ProjectIn(BaseModel):
    name: str
    owner_id: str = "dev-user"  # auth wires this in prod


@app.post(f"{API}/projects", status_code=201)
def create_project(body: ProjectIn):
    s = get_session()
    try:
        p = models.Project(owner_id=body.owner_id, name=body.name)
        s.add(p); s.commit()
        return {"id": p.id, "name": p.name}
    finally:
        s.close()


class KeyBasedConnectionIn(BaseModel):
    kind: str = Field("key_based", pattern="^key_based$")
    display_name: str
    provider: str
    model: str
    system_prompt: Optional[str] = None
    api_key: str  # write-only; never echoed


class EndpointConnectionIn(BaseModel):
    kind: str = Field("endpoint_based", pattern="^endpoint_based$")
    display_name: str
    endpoint: str
    headers: Optional[Dict[str, str]] = None  # write-only; never echoed
    request_field: str = "prompt"
    response_path: str = "response"
    timeout: int = 60


@app.post(f"{API}/projects/{{project_id}}/connections", status_code=201)
def create_connection(project_id: str, body: Union[KeyBasedConnectionIn, EndpointConnectionIn]):
    s = get_session()
    try:
        if body.kind == "key_based":
            conn = conn_svc.create_key_based(
                s, project_id, body.display_name, body.provider, body.model,
                body.api_key, body.system_prompt)
        else:
            conn = conn_svc.create_endpoint_based(
                s, project_id, body.display_name, body.endpoint, body.headers,
                body.request_field, body.response_path, body.timeout)
        return conn_svc.to_public_dict(s, conn)  # no secrets in response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        s.close()


@app.get(f"{API}/suites")
def list_suites():
    out = []
    for slug in ("tax", "prompt_injection"):
        prof = load_profile(slug)
        count = sum(len(v) for v in prof["prompt_families"].values())
        out.append({"slug": slug, "profile_version": prof["version"], "probe_count": count})
    return out


class PreviewIn(BaseModel):
    connection_id: str
    suite: str


@app.post(f"{API}/projects/{{project_id}}/runs/preview")
def preview_run(project_id: str, body: PreviewIn):
    s = get_session()
    try:
        return run_svc.preview(s, project_id, body.connection_id, body.suite)
    except run_svc.ProbeCapExceeded as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        s.close()


class SubmitIn(BaseModel):
    run_id: str
    acknowledged_probe_count: int
    probe_set_hash: str


@app.post(f"{API}/projects/{{project_id}}/runs", status_code=202)
def submit_run(project_id: str, body: SubmitIn):
    from worker import enqueue  # Step 5 wires the async worker
    s = get_session()
    try:
        result = run_svc.submit(s, body.run_id, body.acknowledged_probe_count,
                                body.probe_set_hash, enqueue=enqueue)
        return {**result, "poll": f"{API}/runs/{result['run_id']}"}
    except run_svc.ProbeCountMismatch as e:
        raise HTTPException(status_code=409, detail=str(e))
    except run_svc.ProbeCapExceeded as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        s.close()


@app.get(f"{API}/runs/{{run_id}}")
def get_run(run_id: str):
    s = get_session()
    try:
        run = s.get(models.ExperimentRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {
            "run_id": run.id, "status": run.status,
            "progress": {"completed_probes": run.completed_probes, "total_probes": run.probe_count},
            "risk_score": run.risk_score, "status_label": run.status_label,
            "avg_lambda": run.avg_lambda,
            "error": run.error,
        }
    finally:
        s.close()


@app.get(f"{API}/runs/{{run_id}}/results")
def get_results(run_id: str):
    s = get_session()
    try:
        run = s.get(models.ExperimentRun, run_id)
        if run is None or run.status != "completed":
            raise HTTPException(status_code=409, detail="run not completed")
        families = [
            {"family": r.family, "count": r.count, "avg_lambda": r.avg_lambda,
             "is_top_weakness": r.is_top_weakness, "is_top_safe": r.is_top_safe}
            for r in run.risk_scores
        ]
        weakness = next((f["family"] for f in families if f["is_top_weakness"]), None)
        safe = next((f["family"] for f in families if f["is_top_safe"]), None)
        return {
            "run_id": run.id, "risk_score": run.risk_score, "status_label": run.status_label,
            "avg_lambda": run.avg_lambda, "top_weakness_family": weakness, "top_safe_family": safe,
            "families": families, "rw_weights": run.rw_weights,
        }
    finally:
        s.close()


@app.get(f"{API}/runs/{{run_id}}/incidents")
def get_incidents(run_id: str, only_failures: bool = True, limit: int = 50):
    s = get_session()
    try:
        q = s.query(models.Response).filter_by(run_id=run_id)
        if only_failures:
            q = q.filter_by(is_failure=True)
        items = []
        for r in q.limit(limit).all():
            items.append({
                "response_id": r.id,
                "family": s.get(models.Conversation, r.conversation_id).family,
                "prompt_text": r.prompt_text, "response_preview": r.response_preview,
                "response_type": r.response_type, "lambda": r.lambda_value,
                "oat_p": r.oat_p, "oat_o": r.oat_o, "semantic_score": r.semantic_score,
                "active_cues": [c.cue for c in r.cues], "is_failure": r.is_failure,
            })
        return {"items": items, "next_cursor": None}
    finally:
        s.close()
