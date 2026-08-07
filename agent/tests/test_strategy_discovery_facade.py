"""Frozen-contract tests for ``StrategyDiscoveryFacade`` — issue #969.

The facade is a read-only, in-memory query layer over three injected
dependencies (all fakes here, no network, no real stores on disk except a
tmp-path EvidenceStore):

* ``evidence_store`` — real ``EvidenceStore`` on tmp_path (sibling A package)
* ``sdm_store``      — fake with ``list_artifacts(**kw)`` returning objects
                       with .id/.name/.status(.value)/.universe/
                       .signal_definition/.created_at
* ``alpha_registry`` — fake with ``list(**kw) -> [ids]`` and
                       ``get(id) -> obj(.id/.zoo/.meta dict)``

Pinned behaviors: alpha-first merged listing with the ok envelope, quality
floor via QUALITY_ORDER, min_trades / cost_feasible / min_sharpe filters,
unknown-regime error carrying the valid regime list, honest empty evidence
(AC8), per-regime row item shape (AC4), the adversarial borderline scenario
(AC9), and "facade never returns rows the store does not have" (AC3).
"""

from __future__ import annotations

from datetime import date

import pytest

try:
    from src.strategy_discovery import models as sd_models
    from src.strategy_discovery.evidence_store import EvidenceStore
    from src.strategy_discovery.facade import StrategyDiscoveryFacade

    FACADE_AVAILABLE = True
except ImportError:
    sd_models = None
    StrategyDiscoveryFacade = None
    EvidenceStore = None
    FACADE_AVAILABLE = False

requires_facade = pytest.mark.skipif(
    not FACADE_AVAILABLE,
    reason="waiting on sibling A: src.strategy_discovery facade/models/evidence_store not landed yet (issue #969)",
)

#: Fixed clock for queries over the default ``_row`` fixtures (window end
#: 2022-12-31): keeps those rows fresh so the Phase 1 gate tests stay
#: deterministic — decay is computed at read time (plan D1/D2), so these
#: tests inject the clock instead of reading the wall clock.
FRESH_TODAY = "2023-02-01"

#: Fixed clock for the borderline fixtures: fresh for the edge row (window
#: end 2026-02-28) and aging-but-not-stale for the solid row (window end
#: 2024-12-31, age 152d at this date).
BORDERLINE_TODAY = "2025-06-01"

#: Fixed clock for the Phase 2 decay/lifecycle fixtures.
QUERY_TODAY = "2026-08-06"
QUERY_TODAY_DATE = date(2026, 8, 6)

#: Window ends for the decay fixtures (month-end anchored), all relative to
#: QUERY_TODAY_DATE: stale (2022-12-31), aging (2026-02-28), fresh
#: (2026-06-30).
STALE_RANGES = ("2019-01 to 2022-12",)
AGING_RANGES = ("2020-01 to 2026-02",)
FRESH_RANGES = ("2020-01 to 2026-06",)

EVIDENCE_FIELDS = (
    "strategy_id",
    "regime",
    "trades_in_regime",
    "position_size",
    "return_in_regime",
    "benchmark_in_regime",
    "excess_in_regime",
    "sharpe_in_regime",
    "max_drawdown_in_regime",
    "date_ranges",
    "breakeven_fee_bps",
    "cost_sensitive",
    "evidence_quality",
    "warnings",
    "last_verified",
    "evidence_stage",
    "provenance",
    "regime_definition",
)


# ---------------------------------------------------------------------------
# Fakes (the contract is duck-typed: only these surfaces are touched)
# ---------------------------------------------------------------------------


class FakeAlpha:
    def __init__(self, alpha_id, zoo="testzoo", meta=None):
        self.id = alpha_id
        self.zoo = zoo
        self.meta = {
            "name": f"Alpha {alpha_id}",
            "description": f"desc {alpha_id}",
            "universe": "csi300",
        }
        if meta:
            self.meta.update(meta)


class FakeAlphaRegistry:
    def __init__(self, alphas):
        self._alphas = {a.id: a for a in alphas}
        self.list_calls = []
        self.get_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return sorted(self._alphas.keys())

    def get(self, alpha_id):
        self.get_calls.append(alpha_id)
        return self._alphas.get(alpha_id)


class _EnumLike:
    def __init__(self, value):
        self.value = value


class FakeArtifact:
    def __init__(self, artifact_id, name=None, status="active", universe="us_equity"):
        self.id = artifact_id
        self.name = name or f"SDM {artifact_id}"
        self.status = _EnumLike(status)
        self.universe = universe
        self.signal_definition = "close > open"
        self.created_at = "2026-01-01T00:00:00Z"


class FakeSdmStore:
    def __init__(self, artifacts=None):
        self._artifacts = list(artifacts or [])
        self.list_calls = []

    def list_artifacts(self, **kwargs):
        self.list_calls.append(kwargs)
        return list(self._artifacts)

    def get_artifact(self, artifact_id):
        for artifact in self._artifacts:
            if artifact.id == artifact_id:
                return artifact
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store(tmp_path):
    return EvidenceStore(tmp_path / "evidence.db")


def _make_facade(tmp_path, *, alpha_ids=("a1", "a2"), artifacts=(), rows=()):
    store = _make_store(tmp_path)
    if rows:
        store.upsert_rows(list(rows))
    alpha_registry = FakeAlphaRegistry([FakeAlpha(a) for a in alpha_ids])
    artifacts = (
        artifacts
        if not isinstance(artifacts, tuple)
        else [FakeArtifact(a) for a in artifacts]
    )
    sdm_store = FakeSdmStore(artifacts)
    facade = StrategyDiscoveryFacade(
        evidence_store=store,
        sdm_store=sdm_store,
        alpha_registry=alpha_registry,
    )
    return facade, store


def _row(strategy_id, regime, **overrides):
    fields = dict(
        strategy_id=strategy_id,
        regime=regime,
        trades_in_regime=12,
        position_size=1.0,
        return_in_regime=0.083,
        benchmark_in_regime=-0.246,
        excess_in_regime=0.329,
        sharpe_in_regime=0.72,
        max_drawdown_in_regime=-0.152,
        date_ranges=("2018-01 to 2018-12", "2022-01 to 2022-12"),
        breakeven_fee_bps=45.2,
        cost_sensitive=False,
        evidence_quality="adequate",
        warnings=(),
        last_verified="2026-08-01",
    )
    fields.update(overrides)
    return sd_models.EvidenceRow(**fields)


# ---------------------------------------------------------------------------
# list_strategies
# ---------------------------------------------------------------------------


@requires_facade
class TestListStrategies:
    def test_ok_envelope_and_alpha_first_ordering(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path, alpha_ids=("b2", "a1"), artifacts=("zeta", "beta")
        )
        payload = facade.list_strategies(limit=50, offset=0)
        assert payload["status"] == "ok"
        assert payload["total"] == 4
        assert payload["returned"] == 4
        assert payload["offset"] == 0
        assert isinstance(payload["items"], list)
        # Alpha zoo entries come first (sorted), then sdm entries (sorted),
        # each with its source prefix (AC: unified catalog ordering).
        assert [i["strategy_id"] for i in payload["items"]] == [
            "alpha_zoo:a1",
            "alpha_zoo:b2",
            "sdm:beta",
            "sdm:zeta",
        ]

    def test_sources_and_metadata(self, tmp_path) -> None:
        facade, _ = _make_facade(tmp_path, alpha_ids=("a1",), artifacts=("s1",))
        items = {i["strategy_id"]: i for i in facade.list_strategies(limit=50)["items"]}
        alpha_item = items["alpha_zoo:a1"]
        sdm_item = items["sdm:s1"]
        assert alpha_item["source"] == "alpha_zoo"
        assert sdm_item["source"] == "sdm"
        assert isinstance(alpha_item["name"], str) and alpha_item["name"]
        assert sdm_item["name"] == "SDM s1"
        assert sdm_item["status"] == "active"  # enum-like .status.value surfaced
        assert sdm_item["universe"] == "us_equity"

    def test_has_evidence_and_regimes_from_store(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("a1", "a2"),
            rows=(
                _row("alpha_zoo:a1", "bear_market"),
                _row("alpha_zoo:a1", "bull_market"),
            ),
        )
        items = {i["strategy_id"]: i for i in facade.list_strategies(limit=50)["items"]}
        assert items["alpha_zoo:a1"]["has_evidence"] is True
        assert set(items["alpha_zoo:a1"]["regimes_with_evidence"]) == {
            "bear_market",
            "bull_market",
        }
        assert items["alpha_zoo:a2"]["has_evidence"] is False
        # Envelope items are plain dicts (asdict/JSON), so an empty regime set
        # serializes as []; the model-level default stays the pinned () .
        assert items["alpha_zoo:a2"]["regimes_with_evidence"] in ([], ())

    def test_source_filters(self, tmp_path) -> None:
        facade, _ = _make_facade(tmp_path, alpha_ids=("a1",), artifacts=("s1",))
        only_alpha = facade.list_strategies(limit=50, source="alpha_zoo")
        only_sdm = facade.list_strategies(limit=50, source="sdm")
        assert [i["source"] for i in only_alpha["items"]] == ["alpha_zoo"]
        assert [i["source"] for i in only_sdm["items"]] == ["sdm"]

    def test_unknown_source_is_error_envelope(self, tmp_path) -> None:
        facade, _ = _make_facade(tmp_path)
        payload = facade.list_strategies(limit=5, source="bogus_source")
        assert payload["status"] == "error"
        assert payload.get("error"), "error envelope must carry an actionable message"

    def test_pagination_limit_offset(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path, alpha_ids=("a1", "a2", "a3"), artifacts=("s1", "s2")
        )
        page = facade.list_strategies(limit=2, offset=1)
        assert page["total"] == 5
        assert page["returned"] == 2
        assert page["offset"] == 1
        ids = [i["strategy_id"] for i in page["items"]]
        assert ids == ["alpha_zoo:a2", "alpha_zoo:a3"]
        # Offset past the end yields an empty page, not an error.
        tail = facade.list_strategies(limit=10, offset=50)
        assert tail["status"] == "ok"
        assert tail["items"] == []
        assert tail["returned"] == 0


# ---------------------------------------------------------------------------
# query_strategies
# ---------------------------------------------------------------------------


@requires_facade
class TestQueryStrategies:
    def _seed_quality_ladder(self, tmp_path):
        return _make_facade(
            tmp_path,
            alpha_ids=("a1",),
            rows=(
                _row(
                    "alpha_zoo:a1",
                    "bear_market",
                    trades_in_regime=12,
                    evidence_quality="adequate",
                    sharpe_in_regime=0.9,
                ),
                _row(
                    "alpha_zoo:a1",
                    "bull_market",
                    trades_in_regime=12,
                    evidence_quality="marginal",
                    sharpe_in_regime=0.8,
                ),
                _row(
                    "alpha_zoo:a1",
                    "structural",
                    trades_in_regime=12,
                    evidence_quality="insufficient",
                    sharpe_in_regime=0.7,
                ),
            ),
        )

    def test_quality_floors_via_quality_order(self, tmp_path) -> None:
        facade, _ = self._seed_quality_ladder(tmp_path)
        # Default floor is "adequate"; "marginal" admits adequate+marginal;
        # "any" keeps every row including insufficient (QUALITY_ORDER based).
        assert {
            i["regime"] for i in facade.query_strategies(today=FRESH_TODAY)["items"]
        } == {"bear_market"}
        assert {
            i["regime"]
            for i in facade.query_strategies(
                min_evidence_quality="marginal", today=FRESH_TODAY
            )["items"]
        } == {"bear_market", "bull_market"}
        assert (
            len(
                facade.query_strategies(min_evidence_quality="any", today=FRESH_TODAY)[
                    "items"
                ]
            )
            == 3
        )

    def test_min_trades_filter(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("a1",),
            rows=(
                _row("alpha_zoo:a1", "bear_market", trades_in_regime=11),
                _row("alpha_zoo:a1", "bull_market", trades_in_regime=12),
            ),
        )
        payload = facade.query_strategies(
            min_trades=12, min_evidence_quality="any", today=FRESH_TODAY
        )
        assert {i["regime"] for i in payload["items"]} == {"bull_market"}

    def test_cost_feasible_drops_cost_sensitive_rows(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("a1",),
            rows=(
                _row(
                    "alpha_zoo:a1",
                    "bear_market",
                    cost_sensitive=True,
                    breakeven_fee_bps=2.0,
                ),
                _row(
                    "alpha_zoo:a1",
                    "bull_market",
                    cost_sensitive=False,
                    breakeven_fee_bps=45.0,
                ),
            ),
        )
        feasible = facade.query_strategies(cost_feasible=True, today=FRESH_TODAY)
        assert {i["regime"] for i in feasible["items"]} == {"bull_market"}
        everything = facade.query_strategies(cost_feasible=False, today=FRESH_TODAY)
        assert {i["regime"] for i in everything["items"]} == {
            "bear_market",
            "bull_market",
        }

    def test_cost_feasible_is_fail_closed_on_null_breakeven(self, tmp_path) -> None:
        # sergio12S (#969): a null breakeven means the cost screen is
        # unverifiable (multi-position run) — unverifiable is not a pass, so
        # the default filter drops the row; cost_feasible=False reveals it.
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("a1",),
            rows=(
                _row(
                    "alpha_zoo:a1",
                    "bear_market",
                    breakeven_fee_bps=None,
                    cost_sensitive=False,
                    warnings=("multi-position-breakeven: sample caveat",),
                ),
                _row(
                    "alpha_zoo:a1",
                    "bull_market",
                    breakeven_fee_bps=45.0,
                    cost_sensitive=False,
                ),
            ),
        )
        feasible = facade.query_strategies(cost_feasible=True, today=FRESH_TODAY)
        assert {i["regime"] for i in feasible["items"]} == {
            "bull_market"
        }, "a null-breakeven row must not pass the default cost screen"
        everything = facade.query_strategies(cost_feasible=False, today=FRESH_TODAY)
        items = {i["regime"]: i for i in everything["items"]}
        assert set(items) == {"bear_market", "bull_market"}
        assert items["bear_market"]["breakeven_fee_bps"] is None
        assert any(
            w.startswith("multi-position-breakeven:")
            for w in items["bear_market"]["warnings"]
        ), "the revealed row must keep its unverifiability warning"

    def test_min_sharpe_drops_none_sharpe_and_low_sharpe(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("a1",),
            rows=(
                _row("alpha_zoo:a1", "bear_market", sharpe_in_regime=None),
                _row("alpha_zoo:a1", "bull_market", sharpe_in_regime=0.4),
                _row("alpha_zoo:a1", "structural", sharpe_in_regime=0.9),
            ),
        )
        payload = facade.query_strategies(min_sharpe=0.5, today=FRESH_TODAY)
        assert {i["regime"] for i in payload["items"]} == {"structural"}

    def test_unknown_regime_error_lists_valid_regimes(self, tmp_path) -> None:
        facade, _ = _make_facade(tmp_path, rows=(_row("alpha_zoo:a1", "bear_market"),))
        payload = facade.query_strategies(regime="sideways")
        assert payload["status"] == "error"
        message = str(payload.get("error", ""))
        for regime in ("bear_market", "bull_market", "structural"):
            assert (
                regime in message
            ), f"valid regime {regime} missing from error: {message!r}"

    def test_empty_store_returns_honest_note(self, tmp_path) -> None:
        # AC8 + D12: an empty evidence store yields an ok envelope with a note
        # that no evidence has been computed — never rows, never an error. The
        # note names `refresh_strategy_evidence` (agent/MCP tool + the
        # `vibe-trading strategy-evidence refresh` CLI) as the population path.
        facade, _ = _make_facade(tmp_path, alpha_ids=("a1",))
        payload = facade.query_strategies(min_evidence_quality="any")
        assert payload["status"] == "ok"
        assert payload["items"] == []
        note = payload.get("note", "")
        assert (
            note
        ), "empty store query must carry a 'note' explaining no evidence exists"
        assert isinstance(note, str)
        assert "refresh_strategy_evidence" in note, (
            "the note must name refresh_strategy_evidence as the population "
            f"path: {note!r}"
        )
        assert (
            "vibe-trading strategy-evidence refresh" in note
        ), f"the note must name the CLI population command: {note!r}"

    def test_item_shape_carries_every_evidence_field_plus_borderline(
        self, tmp_path
    ) -> None:
        # AC4: per-regime rows, not boolean tags — every EvidenceRow field is
        # surfaced on the item, plus the facade-computed "borderline" flag.
        facade, _ = _make_facade(
            tmp_path, alpha_ids=("a1",), rows=(_row("alpha_zoo:a1", "bear_market"),)
        )
        payload = facade.query_strategies(regime="bear_market", today=FRESH_TODAY)
        item = payload["items"][0]
        for field in EVIDENCE_FIELDS:
            assert field in item, f"query item missing EvidenceRow field: {field}"
        assert "borderline" in item
        assert isinstance(item["borderline"], bool)
        assert item["strategy_id"] == "alpha_zoo:a1"
        assert item["regime"] == "bear_market"

    def test_facade_never_returns_rows_missing_from_store(self, tmp_path) -> None:
        # AC3: evidence comes only from reproducible runs written through the
        # store — nothing the store does not have may surface through queries.
        facade, store = _make_facade(
            tmp_path,
            alpha_ids=("a1", "a2"),
            artifacts=("s1",),
            rows=(
                _row("alpha_zoo:a1", "bear_market"),
                _row("sdm:s1", "bull_market"),
            ),
        )
        payload = facade.query_strategies(min_evidence_quality="any", today=FRESH_TODAY)
        assert payload["items"], "seeded store should produce items"
        for item in payload["items"]:
            stored = store.get_rows(
                strategy_id=item["strategy_id"], regime=item["regime"]
            )
            assert (
                stored
            ), f"facade returned a row the store does not have: {item['strategy_id']}/{item['regime']}"


# ---------------------------------------------------------------------------
# The adversarial borderline scenario (AC9)
# ---------------------------------------------------------------------------


@requires_facade
class TestBorderlineAdversarial:
    """Row that passes every threshold but sits inside ALL borderline buffers.

    trades=11 (> MIN_TRADES=10 but < 10+BORDERLINE_TRADE_BUFFER=15)
    coverage ["2024-01 to 2026-02"] ≈ 2.1y (>= 730d, < 730+365=1095d)
    breakeven=5.1 bps (>= 5.0 cost threshold but < BORDERLINE_BREAKEVEN_BPS=10)
    """

    def _seed(self, tmp_path):
        borderline = _row(
            "alpha_zoo:edge",
            "bear_market",
            trades_in_regime=11,
            date_ranges=("2024-01 to 2026-02",),
            breakeven_fee_bps=5.1,
            cost_sensitive=False,
            evidence_quality="adequate",
            sharpe_in_regime=0.8,
        )
        comfortable = _row(
            "alpha_zoo:solid",
            "bear_market",
            trades_in_regime=200,
            date_ranges=("2019-01 to 2024-12",),  # 2191 days > 1095
            breakeven_fee_bps=120.0,
            cost_sensitive=False,
            evidence_quality="adequate",
            sharpe_in_regime=1.1,
        )
        return _make_facade(
            tmp_path, alpha_ids=("edge", "solid"), rows=(borderline, comfortable)
        )

    def test_borderline_row_passes_filters_but_is_flagged(self, tmp_path) -> None:
        # Guard the fixture itself: coverage ~2.1 years vs 5+ years.
        assert sd_models.coverage_days_from_ranges(["2024-01 to 2026-02"]) == 789
        assert sd_models.coverage_days_from_ranges(["2019-01 to 2024-12"]) == 2191

        facade, _ = self._seed(tmp_path)
        payload = facade.query_strategies(
            regime="bear_market",
            min_evidence_quality="adequate",
            min_trades=10,
            cost_feasible=True,
            today=BORDERLINE_TODAY,
        )
        assert payload["status"] == "ok"
        items = {i["strategy_id"]: i for i in payload["items"]}
        assert (
            "alpha_zoo:edge" in items
        ), "the 11-trade/2.1y/5.1bps row passes all thresholds and must not be filtered out"
        edge = items["alpha_zoo:edge"]
        assert edge["borderline"] is True
        warns = edge.get("warnings") or []
        assert any(
            isinstance(w, str) and w.startswith("borderline-evidence:") for w in warns
        ), f"borderline row must carry a 'borderline-evidence:' warning, got {warns!r}"

    def test_comfortable_row_is_not_borderline(self, tmp_path) -> None:
        facade, _ = self._seed(tmp_path)
        payload = facade.query_strategies(regime="bear_market", today=BORDERLINE_TODAY)
        items = {i["strategy_id"]: i for i in payload["items"]}
        solid = items["alpha_zoo:solid"]
        assert solid["borderline"] is False
        warns = solid.get("warnings") or []
        assert not any(
            isinstance(w, str) and w.startswith("borderline-evidence:") for w in warns
        ), f"comfortable row must not be flagged borderline, got {warns!r}"


# ---------------------------------------------------------------------------
# get_strategy_evidence
# ---------------------------------------------------------------------------


@requires_facade
class TestGetStrategyEvidence:
    def test_found_with_rows_and_regime_filter(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("a1",),
            rows=(
                _row("alpha_zoo:a1", "bear_market"),
                _row("alpha_zoo:a1", "bull_market"),
            ),
        )
        payload = facade.get_strategy_evidence("alpha_zoo:a1")
        assert payload["status"] == "ok"
        assert payload["strategy_id"] == "alpha_zoo:a1"
        assert payload["found"] is True
        assert len(payload["rows"]) == 2
        for row in payload["rows"]:
            for field in EVIDENCE_FIELDS:
                assert field in row, f"get_strategy_evidence row missing field: {field}"

        filtered = facade.get_strategy_evidence("alpha_zoo:a1", regime="bear_market")
        assert filtered["found"] is True
        assert len(filtered["rows"]) == 1
        assert filtered["rows"][0]["regime"] == "bear_market"

    def test_missing_strategy_is_honest_empty_not_error(self, tmp_path) -> None:
        # AC8 pinned envelope: status ok, found=False, empty rows, and a note
        # explaining no evidence exists. This is NOT an error envelope.
        facade, _ = _make_facade(tmp_path, alpha_ids=("a1",))
        payload = facade.get_strategy_evidence("alpha_zoo:does_not_exist")
        assert (
            payload["status"] == "ok"
        ), f"missing strategy must stay 'ok', got {payload!r}"
        assert payload["strategy_id"] == "alpha_zoo:does_not_exist"
        assert "regime" in payload
        assert payload["found"] is False
        assert payload["rows"] == []
        assert payload.get("note"), "honest-empty envelope must carry a note"


# ---------------------------------------------------------------------------
# Default Alpha Zoo registry resolution (process-cached singleton)
# ---------------------------------------------------------------------------


@requires_facade
class TestDefaultAlphaRegistryResolution:
    """The default registry must come from the process-wide
    ``get_default_registry()`` singleton — constructing ``Registry()`` per
    facade instance would re-run the zoo AST scan (~0.85s) every time."""

    def test_default_resolution_uses_shared_singleton(
        self, tmp_path, monkeypatch
    ) -> None:
        sentinel = FakeAlphaRegistry([FakeAlpha("z1")])
        calls = []

        def fake_get_default_registry():
            calls.append(1)
            return sentinel

        monkeypatch.setattr(
            "src.factors.registry.get_default_registry", fake_get_default_registry
        )
        facade = StrategyDiscoveryFacade(
            evidence_store=_make_store(tmp_path),
            sdm_store=FakeSdmStore([]),
        )
        assert facade._get_alpha_registry() is sentinel
        assert facade._get_alpha_registry() is sentinel
        assert calls == [1], "singleton accessor must be hit once, then cached"

    def test_injected_registry_bypasses_singleton(self, tmp_path, monkeypatch) -> None:
        def fake_get_default_registry():
            raise AssertionError("injected registry must not touch the singleton")

        monkeypatch.setattr(
            "src.factors.registry.get_default_registry", fake_get_default_registry
        )
        injected = FakeAlphaRegistry([FakeAlpha("i1")])
        facade = StrategyDiscoveryFacade(
            evidence_store=_make_store(tmp_path),
            sdm_store=FakeSdmStore([]),
            alpha_registry=injected,
        )
        assert facade._get_alpha_registry() is injected


# ---------------------------------------------------------------------------
# Phase 2 (D1/D2/D9): read-time decay gate on query_strategies
# ---------------------------------------------------------------------------


def _decay_row(strategy_id, regime, ranges, **overrides):
    """A row that passes every Phase 1 gate (non-borderline by construction):
    20 trades, adequate quality, comfortable breakeven, long coverage — so
    only the decay/lifecycle gates can move it. Overrides win."""
    fields = dict(
        trades_in_regime=20,
        date_ranges=ranges,
        breakeven_fee_bps=45.0,
        cost_sensitive=False,
        evidence_quality="adequate",
        sharpe_in_regime=0.8,
    )
    fields.update(overrides)
    return _row(strategy_id, regime, **fields)


@requires_facade
class TestDecayGate:
    def test_stale_rows_excluded_by_default_with_count(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("fresh1", "stale1"),
            rows=(
                _decay_row("alpha_zoo:fresh1", "bear_market", FRESH_RANGES),
                _decay_row("alpha_zoo:stale1", "bear_market", STALE_RANGES),
            ),
        )
        payload = facade.query_strategies(today=QUERY_TODAY)
        assert payload["status"] == "ok"
        assert [i["strategy_id"] for i in payload["items"]] == ["alpha_zoo:fresh1"]
        assert payload["stale_excluded"] == 1
        assert payload["lifecycle_excluded"] == 0

    def test_include_stale_surfaces_stale_rows_with_warning(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("fresh1", "stale1"),
            rows=(
                _decay_row("alpha_zoo:fresh1", "bear_market", FRESH_RANGES),
                _decay_row("alpha_zoo:stale1", "bear_market", STALE_RANGES),
            ),
        )
        payload = facade.query_strategies(include_stale=True, today=QUERY_TODAY)
        items = {i["strategy_id"]: i for i in payload["items"]}
        assert set(items) == {"alpha_zoo:fresh1", "alpha_zoo:stale1"}
        assert payload["stale_excluded"] == 0

        stale = items["alpha_zoo:stale1"]
        assert stale["decay_status"] == sd_models.DECAY_STALE
        expected_age = (QUERY_TODAY_DATE - date(2022, 12, 31)).days
        assert stale["evidence_age_days"] == expected_age
        assert any(
            isinstance(w, str) and w.startswith("stale-evidence:")
            for w in stale["warnings"]
        ), f"stale-included row must carry the stale warning: {stale['warnings']!r}"

        fresh = items["alpha_zoo:fresh1"]
        assert fresh["decay_status"] == sd_models.DECAY_FRESH
        assert fresh["evidence_age_days"] == (QUERY_TODAY_DATE - date(2026, 6, 30)).days
        assert not any(
            isinstance(w, str) and w.startswith(("stale-evidence:", "aged-evidence:"))
            for w in fresh["warnings"]
        )

    def test_stale_included_rows_sort_after_non_stale(self, tmp_path) -> None:
        # The stale row has MORE trades, so quality/trade-count ordering alone
        # would rank it first — the stale-last sort key must override that.
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("fresh1", "stale1"),
            rows=(
                _decay_row(
                    "alpha_zoo:fresh1", "bear_market", FRESH_RANGES, trades_in_regime=20
                ),
                _decay_row(
                    "alpha_zoo:stale1", "bear_market", STALE_RANGES, trades_in_regime=50
                ),
            ),
        )
        payload = facade.query_strategies(include_stale=True, today=QUERY_TODAY)
        assert [i["strategy_id"] for i in payload["items"]] == [
            "alpha_zoo:fresh1",
            "alpha_zoo:stale1",
        ]

    def test_aging_rows_flagged_but_not_excluded(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("aging1", "fresh1"),
            rows=(
                _decay_row("alpha_zoo:aging1", "bear_market", AGING_RANGES),
                _decay_row("alpha_zoo:fresh1", "bull_market", FRESH_RANGES),
            ),
        )
        payload = facade.query_strategies(today=QUERY_TODAY)
        items = {i["strategy_id"]: i for i in payload["items"]}
        assert set(items) == {
            "alpha_zoo:aging1",
            "alpha_zoo:fresh1",
        }, "aging rows are never excluded — they carry a warning instead"
        assert payload["stale_excluded"] == 0

        aging = items["alpha_zoo:aging1"]
        assert aging["decay_status"] == sd_models.DECAY_AGING
        assert aging["evidence_age_days"] == (QUERY_TODAY_DATE - date(2026, 2, 28)).days
        assert any(
            isinstance(w, str) and w.startswith("aged-evidence:")
            for w in aging["warnings"]
        ), f"aging row must carry the aged warning: {aging['warnings']!r}"

    def test_staleness_days_reported_but_never_gating(self, tmp_path) -> None:
        # D1: last_verified is report-only. This row was verified yesterday
        # (staleness_days == 1) yet its window ended years ago — it is still
        # stale, and the fresh row with an OLD last_verified is still fresh.
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("fresh1", "stale1"),
            rows=(
                _decay_row(
                    "alpha_zoo:fresh1",
                    "bear_market",
                    FRESH_RANGES,
                    last_verified="2026-01-01",
                ),
                _decay_row(
                    "alpha_zoo:stale1",
                    "bull_market",
                    STALE_RANGES,
                    last_verified="2026-08-05",
                ),
            ),
        )
        payload = facade.query_strategies(include_stale=True, today=QUERY_TODAY)
        items = {i["strategy_id"]: i for i in payload["items"]}
        assert (
            items["alpha_zoo:fresh1"]["staleness_days"]
            == (QUERY_TODAY_DATE - date(2026, 1, 1)).days
        )
        assert items["alpha_zoo:fresh1"]["decay_status"] == sd_models.DECAY_FRESH
        assert items["alpha_zoo:stale1"]["staleness_days"] == 1
        assert items["alpha_zoo:stale1"]["decay_status"] == sd_models.DECAY_STALE

    def test_injected_today_changes_the_verdict_deterministically(
        self, tmp_path
    ) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("a1",),
            rows=(_decay_row("alpha_zoo:a1", "bear_market", STALE_RANGES),),
        )
        near = facade.query_strategies(today="2023-01-15")
        assert [i["strategy_id"] for i in near["items"]] == ["alpha_zoo:a1"]
        assert near["items"][0]["decay_status"] == sd_models.DECAY_FRESH
        assert near["stale_excluded"] == 0

        far = facade.query_strategies(today=QUERY_TODAY)
        assert far["items"] == []
        assert far["stale_excluded"] == 1

    def test_include_stale_must_be_boolean(self, tmp_path) -> None:
        facade, _ = _make_facade(tmp_path, alpha_ids=("a1",))
        payload = facade.query_strategies(include_stale="yes")
        assert payload["status"] == "error"
        assert "include_stale" in payload.get("error", "")

    def test_unparseable_today_is_error_envelope(self, tmp_path) -> None:
        facade, _ = _make_facade(tmp_path, alpha_ids=("a1",))
        for bad in ("not-a-date", "2026-13-45", 20260806):
            payload = facade.query_strategies(today=bad)
            assert payload["status"] == "error", f"today={bad!r} must be rejected"
            assert payload.get("error")


# ---------------------------------------------------------------------------
# Phase 2 (D8/D9): SDM lifecycle gate
# ---------------------------------------------------------------------------


class ExplodingSdmStore:
    """SDM store whose artifact lookup always fails — the lifecycle gate must
    degrade (skip), never crash the query."""

    def list_artifacts(self, **kwargs):
        return []

    def get_artifact(self, artifact_id):
        raise RuntimeError("sdm store exploded")


@requires_facade
class TestLifecycleGate:
    def _seed_sdm_row(self, tmp_path, status):
        return _make_facade(
            tmp_path,
            alpha_ids=(),
            artifacts=[FakeArtifact("s1", status=status)],
            rows=(_decay_row("sdm:s1", "bear_market", FRESH_RANGES),),
        )

    def test_decayed_sdm_artifact_excluded_from_recommendations(self, tmp_path) -> None:
        facade, _ = self._seed_sdm_row(tmp_path, "decayed")
        payload = facade.query_strategies(today=QUERY_TODAY)
        assert payload["items"] == []
        assert payload["lifecycle_excluded"] == 1
        assert payload["stale_excluded"] == 0
        # include_stale does NOT rescue lifecycle-excluded rows.
        still_out = facade.query_strategies(include_stale=True, today=QUERY_TODAY)
        assert still_out["items"] == []
        assert still_out["lifecycle_excluded"] == 1

    def test_disabled_sdm_artifact_excluded(self, tmp_path) -> None:
        facade, _ = self._seed_sdm_row(tmp_path, "disabled")
        payload = facade.query_strategies(today=QUERY_TODAY)
        assert payload["items"] == []
        assert payload["lifecycle_excluded"] == 1

    def test_active_sdm_artifact_not_excluded(self, tmp_path) -> None:
        facade, _ = self._seed_sdm_row(tmp_path, "active")
        payload = facade.query_strategies(today=QUERY_TODAY)
        assert [i["strategy_id"] for i in payload["items"]] == ["sdm:s1"]
        assert payload["lifecycle_excluded"] == 0

    def test_sdm_lookup_failure_degrades_to_no_gate(self, tmp_path) -> None:
        facade = StrategyDiscoveryFacade(
            evidence_store=_make_store(tmp_path),
            sdm_store=ExplodingSdmStore(),
            alpha_registry=FakeAlphaRegistry([]),
        )
        facade._get_evidence_store().upsert_rows(
            [_decay_row("sdm:s1", "bear_market", FRESH_RANGES)]
        )
        payload = facade.query_strategies(today=QUERY_TODAY)
        assert payload["status"] == "ok", "lookup failure must never crash a query"
        assert [i["strategy_id"] for i in payload["items"]] == ["sdm:s1"]
        assert payload["lifecycle_excluded"] == 0

    def test_unknown_sdm_artifact_degrades_to_no_gate(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=(),
            artifacts=[FakeArtifact("other", status="decayed")],
            rows=(_decay_row("sdm:s1", "bear_market", FRESH_RANGES),),
        )
        payload = facade.query_strategies(today=QUERY_TODAY)
        assert [i["strategy_id"] for i in payload["items"]] == ["sdm:s1"]
        assert payload["lifecycle_excluded"] == 0

    def test_stale_and_lifecycle_counts_together(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("fresh1", "stale1"),
            artifacts=[FakeArtifact("s1", status="decayed")],
            rows=(
                _decay_row("alpha_zoo:fresh1", "bear_market", FRESH_RANGES),
                _decay_row("alpha_zoo:stale1", "bull_market", STALE_RANGES),
                _decay_row("sdm:s1", "structural", FRESH_RANGES),
            ),
        )
        payload = facade.query_strategies(today=QUERY_TODAY)
        assert [i["strategy_id"] for i in payload["items"]] == ["alpha_zoo:fresh1"]
        assert payload["stale_excluded"] == 1
        assert payload["lifecycle_excluded"] == 1


# ---------------------------------------------------------------------------
# Phase 2 (D11): empty vs all-excluded notes
# ---------------------------------------------------------------------------


@requires_facade
class TestAllExcludedNote:
    def test_all_excluded_note_reports_gate_breakdown(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("stale1", "low1"),
            rows=(
                _decay_row("alpha_zoo:stale1", "bear_market", STALE_RANGES),
                _decay_row(
                    "alpha_zoo:low1",
                    "bull_market",
                    FRESH_RANGES,
                    evidence_quality="insufficient",
                ),
            ),
        )
        payload = facade.query_strategies(today=QUERY_TODAY)
        assert payload["items"] == []
        note = payload.get("note", "")
        assert note, "non-empty-but-all-excluded must carry a breakdown note"
        assert "1 below the quality/cost/trades/Sharpe floors" in note
        assert "1 stale-excluded" in note
        assert "0 lifecycle-excluded" in note

    def test_all_excluded_note_differs_from_empty_note(self, tmp_path) -> None:
        empty_facade, _ = _make_facade(tmp_path, alpha_ids=("a1",))
        empty_note = empty_facade.query_strategies(today=QUERY_TODAY).get("note", "")

        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("stale1",),
            rows=(_decay_row("alpha_zoo:stale1", "bear_market", STALE_RANGES),),
        )
        excluded_note = facade.query_strategies(today=QUERY_TODAY).get("note", "")

        assert empty_note and excluded_note
        assert empty_note != excluded_note
        assert "refresh_strategy_evidence" in empty_note
        assert "excluded by gates" in excluded_note

    def test_passing_query_carries_no_note(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("fresh1",),
            rows=(_decay_row("alpha_zoo:fresh1", "bear_market", FRESH_RANGES),),
        )
        payload = facade.query_strategies(today=QUERY_TODAY)
        assert payload["items"]
        assert "note" not in payload


# ---------------------------------------------------------------------------
# Phase 2 (D10): get_strategy_evidence inspection surface
# ---------------------------------------------------------------------------


@requires_facade
class TestGetStrategyEvidenceDecay:
    def test_rows_carry_decay_fields(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("aging1",),
            rows=(_decay_row("alpha_zoo:aging1", "bear_market", AGING_RANGES),),
        )
        payload = facade.get_strategy_evidence("alpha_zoo:aging1", today=QUERY_TODAY)
        assert payload["found"] is True
        row = payload["rows"][0]
        assert row["decay_status"] == sd_models.DECAY_AGING
        assert row["evidence_age_days"] == (QUERY_TODAY_DATE - date(2026, 2, 28)).days
        assert row["staleness_days"] == (QUERY_TODAY_DATE - date(2026, 8, 1)).days
        assert any(
            isinstance(w, str) and w.startswith("aged-evidence:")
            for w in row["warnings"]
        )

    def test_stale_rows_returned_unfiltered(self, tmp_path) -> None:
        # D10: the inspection surface never filters — a stale row is returned
        # with its stale warning, not dropped.
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("stale1",),
            rows=(_decay_row("alpha_zoo:stale1", "bear_market", STALE_RANGES),),
        )
        payload = facade.get_strategy_evidence("alpha_zoo:stale1", today=QUERY_TODAY)
        assert payload["found"] is True
        assert len(payload["rows"]) == 1
        row = payload["rows"][0]
        assert row["decay_status"] == sd_models.DECAY_STALE
        assert any(
            isinstance(w, str) and w.startswith("stale-evidence:")
            for w in row["warnings"]
        )

    def test_sdm_lifecycle_note_for_decayed_artifact(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=(),
            artifacts=[FakeArtifact("s1", status="decayed")],
            rows=(_decay_row("sdm:s1", "bear_market", FRESH_RANGES),),
        )
        payload = facade.get_strategy_evidence("sdm:s1", today=QUERY_TODAY)
        note = payload.get("lifecycle_note", "")
        assert note.startswith("sdm-lifecycle:"), f"got {note!r}"
        assert "'decayed'" in note
        assert payload["rows"][0].get("lifecycle_note") == note

    def test_alpha_rows_carry_no_lifecycle_note(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("a1",),
            rows=(_decay_row("alpha_zoo:a1", "bear_market", FRESH_RANGES),),
        )
        payload = facade.get_strategy_evidence("alpha_zoo:a1", today=QUERY_TODAY)
        assert "lifecycle_note" not in payload
        assert "lifecycle_note" not in payload["rows"][0]

    def test_sdm_lookup_failure_omits_note_without_crash(self, tmp_path) -> None:
        facade = StrategyDiscoveryFacade(
            evidence_store=_make_store(tmp_path),
            sdm_store=ExplodingSdmStore(),
            alpha_registry=FakeAlphaRegistry([]),
        )
        facade._get_evidence_store().upsert_rows(
            [_decay_row("sdm:s1", "bear_market", FRESH_RANGES)]
        )
        payload = facade.get_strategy_evidence("sdm:s1", today=QUERY_TODAY)
        assert payload["status"] == "ok"
        assert payload["found"] is True
        assert "lifecycle_note" not in payload

    def test_unparseable_today_is_error_envelope(self, tmp_path) -> None:
        facade, _ = _make_facade(tmp_path, alpha_ids=("a1",))
        payload = facade.get_strategy_evidence("alpha_zoo:a1", today="bogus")
        assert payload["status"] == "error"
        assert payload.get("error")


# ---------------------------------------------------------------------------
# Phase 2 adversarial composition (sergio12S): just inside the staleness
# boundary AND just inside the trades band at the same time
# ---------------------------------------------------------------------------


@requires_facade
class TestDecayBorderlineComposition:
    """One row, two threshold edges at once:

    * trades_in_regime=11 — just inside the borderline trade band
      (MIN_TRADES=10 <= 11 < 10+BORDERLINE_TRADE_BUFFER=15);
    * window end 2026-01-31 with injected clocks 2026-07-29 (age 179, just
      inside the stale boundary ⇒ aging) and 2026-07-30 (age exactly 180 ⇒
      stale, the stricter side — fail-closed).
    """

    COMPOSITION_RANGES = ("2020-01 to 2026-01",)
    INSIDE_TODAY = "2026-07-29"
    BOUNDARY_TODAY = "2026-07-30"

    def _seed(self, tmp_path):
        return _make_facade(
            tmp_path,
            alpha_ids=("edge",),
            rows=(
                _row(
                    "alpha_zoo:edge",
                    "bear_market",
                    trades_in_regime=11,
                    date_ranges=self.COMPOSITION_RANGES,
                    breakeven_fee_bps=45.0,
                    cost_sensitive=False,
                    evidence_quality="adequate",
                    sharpe_in_regime=0.8,
                ),
            ),
        )

    def test_fixture_ages_are_exact(self) -> None:
        end = date(2026, 1, 31)
        assert (date(2026, 7, 29) - end).days == 179
        assert (date(2026, 7, 30) - end).days == 180
        assert sd_models.coverage_days_from_ranges(self.COMPOSITION_RANGES) >= (
            sd_models.MIN_COVERAGE_DAYS + sd_models.BORDERLINE_COVERAGE_BUFFER_DAYS
        ), "coverage must NOT be the borderline axis — trades must be"

    def test_just_inside_boundary_is_aging_with_both_warnings(self, tmp_path) -> None:
        facade, _ = self._seed(tmp_path)
        payload = facade.query_strategies(today=self.INSIDE_TODAY)
        assert payload["stale_excluded"] == 0
        items = {i["strategy_id"]: i for i in payload["items"]}
        assert "alpha_zoo:edge" in items, "age 179 is aging, not stale — keep it"
        edge = items["alpha_zoo:edge"]
        assert edge["decay_status"] == sd_models.DECAY_AGING
        assert edge["evidence_age_days"] == 179
        assert edge["borderline"] is True
        prefixes = {
            w.split(":", 1)[0] + ":" for w in edge["warnings"] if isinstance(w, str)
        }
        assert "aged-evidence:" in prefixes
        assert "borderline-evidence:" in prefixes

    def test_exact_boundary_is_stale_fail_closed(self, tmp_path) -> None:
        facade, _ = self._seed(tmp_path)
        payload = facade.query_strategies(today=self.BOUNDARY_TODAY)
        assert payload["items"] == [], (
            "age exactly 180 belongs to the STRICTER side — the row must be "
            "excluded from default recommendations (fail-closed)"
        )
        assert payload["stale_excluded"] == 1

        revealed = facade.query_strategies(
            include_stale=True, today=self.BOUNDARY_TODAY
        )
        items = {i["strategy_id"]: i for i in revealed["items"]}
        edge = items["alpha_zoo:edge"]
        assert edge["decay_status"] == sd_models.DECAY_STALE
        assert edge["evidence_age_days"] == 180
        prefixes = {
            w.split(":", 1)[0] + ":" for w in edge["warnings"] if isinstance(w, str)
        }
        assert "stale-evidence:" in prefixes
        assert "borderline-evidence:" in prefixes
