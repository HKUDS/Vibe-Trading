"""Source provenance manifest for audited data loads."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceManifest(BaseModel):
    """Observed source selection/fallback metadata for one load."""

    requested_source: str
    selected_source: str
    fallback_chain: list[str] = Field(default_factory=list)
    attempted_sources: list[str] = Field(default_factory=list)
    runtime_source: str | None = None
    cache_hit: bool = False
    fallback_chain_id: str | None = None
