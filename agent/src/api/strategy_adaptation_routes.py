"""Authenticated strategy adaptation and evidence refresh entry points."""

from src.tools.path_utils import FileRoots

from src.config.accessor import get_env_config

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict


class AdaptationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_id: str
    name: str
    universe: str
    config: dict[str, Any]
    position_sizing: str | None = None


class EvidenceRefreshRequest(BaseModel):
    runs: list[dict[str, Any]]


def register_strategy_adaptation_routes(app: FastAPI, write_auth) -> None:
    """Mount mutation routes behind the settings-write guard."""

    @app.post("/api/strategy-adaptations", dependencies=[Depends(write_auth)])
    def prepare(payload: AdaptationRequest):
        from src.strategy_discovery.adaptation_workflow import prepare_adaptation

        try:
            return prepare_adaptation(**payload.model_dump())
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/strategy-adaptations/evidence", dependencies=[Depends(write_auth)])
    def refresh(payload: EvidenceRefreshRequest):
        from src.tools.strategy_discovery_tool import refresh_strategy_evidence_core

        return refresh_strategy_evidence_core(
            runs=payload.runs, scope="strategies", roots=FileRoots.from_config(get_env_config().api),
        )
