from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, cast

from src.research_ledger.hash_utils import json_safe, redact_secrets, utc_now_iso


@dataclass(frozen=True)
class AlphaGenesisReport:
    report_id: str
    candidate_id: str
    parent_seed_id: str | None = None
    formula: str | None = None
    formula_hash: str | None = None
    factor_definition_hash: str | None = None
    data_snapshot_hash: str | None = None
    pit_contract_present: bool | None = None
    survivorship_bias: bool | None = None
    split_config: dict[str, Any] = field(default_factory=dict)
    data_scope: str = "research"
    predictive_metrics: dict[str, Any] = field(default_factory=dict)
    robustness_metrics: dict[str, Any] = field(default_factory=dict)
    tradability_metrics: dict[str, Any] = field(default_factory=dict)
    novelty_metrics: dict[str, Any] = field(default_factory=dict)
    synergy_metrics: dict[str, Any] = field(default_factory=dict)
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    decision: str = "research_only"
    cap_reasons: list[str] = field(default_factory=list)
    trial_count: int = 0
    trial_group_id: str | None = None
    limitations: list[str] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=utc_now_iso)
    schema_version: str = "alpha_genesis_report.v1"

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], redact_secrets(json_safe(asdict(self))))

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
