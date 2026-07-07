"""AuditedDataLoader wrapper for Phase 2 observe-mode data reliability."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.reliability.artifacts.store import ArtifactStore
from src.reliability.artifacts.hashing import sha256_json
from src.reliability.config import reliability_enabled
from src.reliability.data.circuit_breaker import CircuitBreaker
from src.reliability.data.contracts import (
    DataAccessContract,
    DataAuditReport,
    DataSetContract,
    StructuredWarning,
)
from src.reliability.data.errors import AllSourcesOpenError
from src.reliability.data.source_manifest import SourceManifest
from src.reliability.data.validators import validate_data_map
from src.reliability.market_rules.ashare import audit_ashare_assumptions
from src.reliability.pit.checker import PITChecker
from src.reliability.pit.model import PITTimestampSet


class AuditedDataLoader:
    """Wrapper that records data audit metadata without changing fetch output."""

    def __init__(
        self,
        inner: Any,
        *,
        source: str,
        selected_source: str | None = None,
        source_manifest: SourceManifest | None = None,
        dataset_contract: DataSetContract | None = None,
        dataset_kind: str = "ohlcv",
        as_of: datetime | None = None,
        available_at: datetime | None = None,
        market_rule_config: dict[str, Any] | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        artifact_store: ArtifactStore | None = None,
        max_sample_rows: int = 10_000,
    ) -> None:
        self.inner = inner
        self.source = source
        self.selected_source = selected_source or getattr(inner, "name", source)
        self.source_manifest = source_manifest
        self.dataset_contract = dataset_contract
        self.dataset_kind = dataset_kind
        self.as_of = _to_utc(as_of) if as_of is not None else None
        self.available_at = _to_utc(available_at) if available_at is not None else None
        self.market_rule_config = dict(market_rule_config or {})
        self.circuit_breaker = circuit_breaker
        self.artifact_store = artifact_store
        self.max_sample_rows = max_sample_rows
        self.last_audit_report: DataAuditReport | None = None

    @property
    def name(self) -> str:
        return getattr(self.inner, "name", self.selected_source)

    @property
    def markets(self) -> set[str]:
        return getattr(self.inner, "markets", set())

    @property
    def requires_auth(self) -> bool:
        return bool(getattr(self.inner, "requires_auth", False))

    def is_available(self) -> bool:
        """Proxy availability checks to the inner loader."""
        return self.inner.is_available()

    def fetch(
        self,
        codes,
        start_date,
        end_date,
        *,
        interval: str = "1D",
        fields: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch data and record audit metadata when reliability is enabled."""
        if not reliability_enabled():
            return _fetch_inner(self.inner, codes, start_date, end_date, interval=interval, fields=fields)

        manifest = self._manifest(codes)
        request_hash = _request_hash(
            source=self.source,
            codes=list(codes),
            start_date=str(start_date),
            end_date=str(end_date),
            interval=interval,
            fields=fields,
        )
        decisions = self._circuit_decisions(manifest)
        if self._all_nonlocal_sources_open(manifest, decisions):
            report = self._build_empty_audit(
                manifest=manifest,
                request_hash=request_hash,
                start_date=str(start_date),
                end_date=str(end_date),
                interval=interval,
                all_sources_open=True,
                quality_warnings=[
                    StructuredWarning(
                        code="DATA_ALL_SOURCES_OPEN",
                        severity="hard_failure",
                        message="all fallback data sources are circuit-open",
                        metadata={"chain": self._nonlocal_chain(manifest)},
                    )
                ],
                circuit_events=[decision_snapshot for decision_snapshot in decisions.values()],
            )
            self._record_audit(report)
            states = {source: snapshot.state for source, snapshot in decisions.items()}
            raise AllSourcesOpenError(
                "all fallback data sources are circuit-open",
                chain=self._nonlocal_chain(manifest),
                breaker_states=states,
                audit_id=report.audit_id,
            )

        start = time.perf_counter()
        try:
            data_map = _fetch_inner(self.inner, codes, start_date, end_date, interval=interval, fields=fields)
        except Exception as exc:
            if self.circuit_breaker is not None:
                self.circuit_breaker.record_failure(manifest.selected_source, exc)
            raise
        latency_ms = (time.perf_counter() - start) * 1000.0
        if self.circuit_breaker is not None:
            self.circuit_breaker.record_success(manifest.selected_source)

        validation = validate_data_map(data_map, max_sample_rows=self.max_sample_rows)
        pit = self._pit_result(start_date=str(start_date), end_date=str(end_date))
        quality_warnings = list(validation.quality_warnings)
        quality_warnings.extend(pit.warnings)
        market_rule_warnings = self._market_rule_warnings()
        report = DataAuditReport(
            audit_id=f"audit_{uuid.uuid4().hex}",
            schema_version="1.0.0",
            dataset_contract=self.dataset_contract,
            access_contract=self._access_contract(
                manifest=manifest,
                request_hash=request_hash,
                latency_ms=latency_ms,
                circuit_state=decisions.get(manifest.selected_source).state if manifest.selected_source in decisions else None,
            ),
            row_count=validation.row_count,
            symbol_count=validation.symbol_count,
            field_coverage=validation.field_coverage,
            content_sample_hash=validation.content_sample_hash,
            per_symbol_hashes=validation.per_symbol_hashes,
            pit_violations=pit.violations,
            quality_warnings=quality_warnings,
            market_rule_warnings=market_rule_warnings,
            source_circuit_states={source: snapshot.state for source, snapshot in decisions.items()},
            circuit_breaker_events=list(decisions.values()),
            all_sources_open=False,
        )
        self._record_audit(report)
        return data_map

    def _manifest(self, codes: list[str]) -> SourceManifest:
        explicit_local = _explicit_local(self.source, codes)
        if self.source_manifest is not None:
            return self.source_manifest
        selected = "local" if explicit_local else self.selected_source
        chain = ["local"] if explicit_local else [selected]
        return SourceManifest(
            requested_source=self.source,
            selected_source=selected,
            fallback_chain=chain,
            attempted_sources=[selected],
            runtime_source=selected,
            cache_hit=False,
        )

    def _circuit_decisions(self, manifest: SourceManifest) -> dict[str, Any]:
        if self.circuit_breaker is None:
            return {}
        snapshots = {}
        for source in manifest.fallback_chain:
            if source == "local":
                snapshots[source] = self.circuit_breaker.snapshot(source)
                continue
            decision = self.circuit_breaker.before_request(source)
            snapshots[source] = self.circuit_breaker.snapshot(source)
            if decision.warning is not None:
                # The warning is reconstructed in _build_empty_audit for all-open
                # and captured in source_circuit_states for ordinary fetches.
                pass
        return snapshots

    def _all_nonlocal_sources_open(self, manifest: SourceManifest, decisions: dict[str, Any]) -> bool:
        chain = self._nonlocal_chain(manifest)
        if not chain:
            return False
        return bool(decisions) and all(decisions[source].state == "OPEN" for source in chain)

    def _nonlocal_chain(self, manifest: SourceManifest) -> list[str]:
        if _explicit_local(manifest.requested_source, []):
            return []
        return [source for source in manifest.fallback_chain if source != "local"]

    def _build_empty_audit(
        self,
        *,
        manifest: SourceManifest,
        request_hash: str,
        start_date: str,
        end_date: str,
        interval: str,
        all_sources_open: bool,
        quality_warnings: list[StructuredWarning],
        circuit_events: list[Any],
    ) -> DataAuditReport:
        return DataAuditReport(
            audit_id=f"audit_{uuid.uuid4().hex}",
            schema_version="1.0.0",
            dataset_contract=self.dataset_contract,
            access_contract=self._access_contract(
                manifest=manifest,
                request_hash=request_hash,
                latency_ms=None,
                circuit_state="OPEN" if all_sources_open else None,
            ),
            row_count=0,
            symbol_count=0,
            field_coverage={},
            quality_warnings=quality_warnings,
            source_circuit_states={event.source: event.state for event in circuit_events},
            circuit_breaker_events=circuit_events,
            all_sources_open=all_sources_open,
        )

    def _access_contract(
        self,
        *,
        manifest: SourceManifest,
        request_hash: str,
        latency_ms: float | None,
        circuit_state: str | None,
    ) -> DataAccessContract:
        return DataAccessContract(
            source=manifest.requested_source,
            selected_source=manifest.selected_source,
            request_params_hash=request_hash,
            fallback_chain=list(manifest.fallback_chain or [manifest.selected_source]),
            fetched_at=datetime.now(timezone.utc),
            explicit_local=_explicit_local(manifest.requested_source, []),
            fallback_chain_id=manifest.fallback_chain_id,
            circuit_breaker_state=circuit_state,  # type: ignore[arg-type]
            loader_latency_ms=latency_ms,
        )

    def _pit_result(self, *, start_date: str, end_date: str):
        effective_at = _parse_date_utc(end_date) if self.dataset_kind == "ohlcv" else _parse_date_utc(start_date)
        timestamps = PITTimestampSet(
            effective_at=effective_at,
            available_at=self.available_at,
            as_of=self.as_of,
        )
        return PITChecker(dataset_kind=self.dataset_kind, as_of=self.as_of).check(timestamps)

    def _market_rule_warnings(self) -> list[StructuredWarning]:
        asset_class = self.dataset_contract.asset_class if self.dataset_contract is not None else self.market_rule_config.get("asset_class")
        if asset_class == "ashare":
            return audit_ashare_assumptions(self.market_rule_config)
        return []

    def _record_audit(self, report: DataAuditReport) -> None:
        store = self.artifact_store or ArtifactStore()
        try:
            record = store.write_json(
                report.model_dump(mode="json"),
                artifact_type="data_audit",
                generated_by="AuditedDataLoader",
                metadata={"audit_id": report.audit_id, "selected_source": report.access_contract.selected_source},
            )
        except Exception:
            record = None
        if record is not None:
            report.artifact_refs.append(record.to_ref())
        self.last_audit_report = report


def _request_hash(**kwargs: Any) -> str:
    value = {
        key: item
        for key, item in kwargs.items()
        if item is not None
    }
    if "fields" in value:
        value["fields"] = [str(field) for field in value["fields"]]
    value["codes"] = [str(code) for code in value.get("codes", [])]
    return sha256_json(value)


def _fetch_inner(
    inner: Any,
    codes,
    start_date,
    end_date,
    *,
    interval: str,
    fields: list[str] | None,
):
    if fields is None:
        return inner.fetch(codes, start_date, end_date, interval=interval)
    return inner.fetch(codes, start_date, end_date, interval=interval, fields=fields)


def _explicit_local(source: str, codes: list[str]) -> bool:
    normalized = str(source).strip().lower()
    return normalized in {"local", "local:"} or any(str(code).lower().startswith("local:") for code in codes)


def _parse_date_utc(value: str) -> datetime | None:
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize(timezone.utc)
    else:
        ts = ts.tz_convert(timezone.utc)
    return ts.to_pydatetime()


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)
