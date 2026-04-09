from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from run_audit import run_audit, print_summary, save_report
from profiles.loader import load_profile

app = FastAPI(
    title="AI Behaviour Lab",
    description="Audit any AI system for safety vulnerabilities",
    version="1.0.0",
)


class AuditRequest(BaseModel):
    domain: str = "tax"
    provider: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    endpoint: Optional[str] = None


@app.get("/")
def root():
    return {
        "product": "AI Behaviour Lab",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/domains")
def list_domains():
    return {
        "available_domains": ["tax", "legal"]
    }


@app.post("/audit")
def audit(request: AuditRequest):
    try:
        profile = load_profile(request.domain)

        if request.provider:
            profile["adapter_config"] = {
                "provider": request.provider,
                "model": request.model,
                "system_prompt": request.system_prompt,
                "endpoint": request.endpoint,
            }

        report = run_audit(profile)
        save_report(report)
        return report

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))