"""Authenticated, side-effect-free failure experiments and persisted latency reports."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from arcagent.console.api import Database, authenticate
from arcagent.persistence.models import Call
from evals.replay import compare_replays, scenario_catalog

router = APIRouter(prefix="/api/console", dependencies=[Depends(authenticate)])


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1, max_length=64)
    baseline_config: dict = Field(default_factory=dict, max_length=3)
    candidate_config: dict = Field(default_factory=dict, max_length=3)


@router.get("/lab/scenarios")
def scenarios() -> dict:
    return {"items": scenario_catalog(), "simulated": True}


@router.post("/lab/replay")
def run_replay(request: ReplayRequest) -> dict:
    try:
        return compare_replays(request.model_dump())
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Invalid scenario or configuration") from exc


@router.get("/calls/{call_id}/latency")
def call_latency(call_id: Annotated[int, Path(gt=0, le=2_147_483_647)], session: Database) -> dict:
    from arcagent.console.latency import latency_report

    call = session.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "Call not found")
    return latency_report(call.turns)
