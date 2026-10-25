"""HTTP API for the Supersede UI.

Run from the backend folder:

    uvicorn api.app:app --reload --port 8000

Environment:
    SUPERSEDE_DB   SQLite file (default supersede.db)
    SUPERSEDE_LLM  mock (default) or azure; azure also needs AZURE_OPENAI_* vars
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from supersede.service import Supersede

app = FastAPI(title="Supersede", version="0.1.0", description="Decision provenance for AI agents")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

svc = Supersede()
svc.seed_demo()


# -- request bodies ------------------------------------------------------

class StartRun(BaseModel):
    customer_id: Optional[str] = Field(None, description="Demo customer to run again, e.g. KYC-2041")
    inputs: Optional[dict] = None
    run_time: str = "2026-10-15"
    options: Optional[dict] = None


class Resume(BaseModel):
    action: str = Field(..., pattern="^(approve|edit|reject)$")
    swaps: Optional[dict[str, str]] = None
    note: str = ""


class Fork(BaseModel):
    from_step: int = Field(..., ge=1)
    swaps: Optional[dict[str, str]] = None
    guard: Optional[bool] = None
    reason: str = "manual fork"


class RuleToggle(BaseModel):
    key: str
    on: bool


class Feedback(BaseModel):
    verdict: str = Field(..., pattern="^(correct|wrong|needs_review)$")
    note: str = ""
    author: str = "reviewer"


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"not found: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# -- routes --------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "llm": svc.llm_mode}


@app.get("/api/overview")
def overview() -> dict:
    return svc.overview()


@app.get("/api/runs")
def runs(include_forks: bool = False) -> list[dict]:
    return svc.list_runs(include_forks=include_forks)


@app.post("/api/runs")
def start_run(body: StartRun) -> dict:
    if not body.customer_id and not body.inputs:
        raise HTTPException(status_code=400, detail="give customer_id or inputs")
    return _call(svc.start_run, customer_id=body.customer_id, inputs=body.inputs, run_time=body.run_time, options=body.options)


@app.get("/api/runs/{run_id}")
def run_report(run_id: str, refresh: bool = False) -> dict:
    return _call(svc.report, run_id, refresh=refresh)


@app.get("/api/runs/{run_id}/steps/{step}/state")
def run_state(run_id: str, step: int) -> dict:
    return _call(svc.state, run_id, step)


@app.post("/api/runs/{run_id}/resume")
def resume(run_id: str, body: Resume) -> dict:
    return _call(svc.resume, run_id, body.action, swaps=body.swaps, note=body.note)


@app.post("/api/runs/{run_id}/fork")
def fork(run_id: str, body: Fork) -> dict:
    return _call(svc.fork, run_id, from_step=body.from_step, swaps=body.swaps, guard=body.guard, reason=body.reason)


@app.post("/api/runs/{run_id}/rules")
def toggle_rule(run_id: str, body: RuleToggle) -> dict:
    return _call(svc.set_rule, run_id, body.key, body.on)


@app.post("/api/runs/{run_id}/feedback")
def feedback(run_id: str, body: Feedback) -> dict:
    return _call(svc.add_feedback, run_id, body.verdict, body.note, body.author)


@app.post("/api/demo/reset")
def reset_demo() -> dict:
    svc.reset_demo()
    return {"ok": True, "runs": len(svc.store.list_runs())}


# Serve the built frontend (frontend/dist) when it exists, so one command runs everything.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
