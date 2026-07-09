from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Literal, cast

import pandas as pd

from src.research_ledger.hash_utils import (
    canonical_json_hash,
    json_safe,
    redact_secrets,
    utc_now_iso,
)


@dataclass(frozen=True)
class DataSnapshotManifest:
    schema_version: Literal["data_snapshot.v1"]
    snapshot_id: str
    sources_used: list[str]
    source_config_hash: str
    calendar: str
    timezone: str
    adjustment_policy: str
    symbol_mapping_hash: str
    universe_hash: str
    pit_contract_present: bool
    survivorship_bias: bool
    corporate_action_policy: str | None
    suspension_policy: str | None
    limit_price_policy: str | None
    st_policy: str | None
    row_counts: dict[str, int]
    missingness_summary: dict[str, float]
    generated_at: str
    snapshot_hash: str
    universe: str
    period: str
    redacted_source_config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json_safe(asdict(self)))

    def finalize_hash(self) -> "DataSnapshotManifest":
        digest = canonical_json_hash(
            self.to_dict(),
            exclude_keys=("snapshot_hash", "generated_at"),
        )
        return replace(self, snapshot_hash=digest)


def _meta(panel: dict[str, Any]) -> dict[str, Any]:
    raw = panel.get("_meta")
    return dict(raw) if isinstance(raw, dict) else {}


def _data_frames(panel: dict[str, Any]) -> dict[str, pd.DataFrame]:
    return {k: v for k, v in panel.items() if isinstance(v, pd.DataFrame)}


def _row_counts(frames: dict[str, pd.DataFrame]) -> dict[str, int]:
    return {name: int(len(frame.index)) for name, frame in sorted(frames.items())}


def _missingness(frames: dict[str, pd.DataFrame]) -> dict[str, float]:
    summary: dict[str, float] = {}
    for name, frame in sorted(frames.items()):
        total = int(frame.shape[0] * frame.shape[1])
        summary[name] = 0.0 if total == 0 else float(frame.isna().sum().sum() / total)
    return summary


def _universe_payload(frames: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    return {name: [str(col) for col in frame.columns] for name, frame in sorted(frames.items())}


def build_data_snapshot(
    panel: dict[str, Any],
    universe: str,
    period: str,
    source_config: dict[str, Any],
) -> DataSnapshotManifest:
    frames = _data_frames(panel)
    meta = _meta(panel)
    redacted_config = redact_secrets(source_config)
    source_config_hash = canonical_json_hash(redacted_config)
    universe_payload = _universe_payload(frames)
    universe_hash = canonical_json_hash(
        {"universe": universe, "period": period, "members": universe_payload}
    )
    manifest = DataSnapshotManifest(
        schema_version="data_snapshot.v1",
        snapshot_id=canonical_json_hash(
            {"universe": universe, "period": period, "source_config_hash": source_config_hash}
        ),
        sources_used=sorted(frames.keys()),
        source_config_hash=source_config_hash,
        calendar=str(meta.get("calendar") or "UNKNOWN"),
        timezone=str(meta.get("timezone") or "UNKNOWN"),
        adjustment_policy=str(meta.get("adjustment_policy") or "unspecified"),
        symbol_mapping_hash=canonical_json_hash(universe_payload),
        universe_hash=universe_hash,
        pit_contract_present=bool(meta.get("pit_contract_present", False)),
        survivorship_bias=bool(meta.get("survivorship_bias", False)),
        corporate_action_policy=meta.get("corporate_action_policy"),
        suspension_policy=meta.get("suspension_policy"),
        limit_price_policy=meta.get("limit_price_policy"),
        st_policy=meta.get("st_policy"),
        row_counts=_row_counts(frames),
        missingness_summary=_missingness(frames),
        generated_at=utc_now_iso(),
        snapshot_hash="",
        universe=universe,
        period=period,
        redacted_source_config=redacted_config,
    )
    return manifest.finalize_hash()
