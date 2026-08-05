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
        assert {i["regime"] for i in facade.query_strategies()["items"]} == {
            "bear_market"
        }
        assert {
            i["regime"]
            for i in facade.query_strategies(min_evidence_quality="marginal")["items"]
        } == {"bear_market", "bull_market"}
        assert len(facade.query_strategies(min_evidence_quality="any")["items"]) == 3

    def test_min_trades_filter(self, tmp_path) -> None:
        facade, _ = _make_facade(
            tmp_path,
            alpha_ids=("a1",),
            rows=(
                _row("alpha_zoo:a1", "bear_market", trades_in_regime=11),
                _row("alpha_zoo:a1", "bull_market", trades_in_regime=12),
            ),
        )
        payload = facade.query_strategies(min_trades=12, min_evidence_quality="any")
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
        feasible = facade.query_strategies(cost_feasible=True)
        assert {i["regime"] for i in feasible["items"]} == {"bull_market"}
        everything = facade.query_strategies(cost_feasible=False)
        assert {i["regime"] for i in everything["items"]} == {
            "bear_market",
            "bull_market",
        }

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
        payload = facade.query_strategies(min_sharpe=0.5)
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
        # AC8: an empty evidence store yields an ok envelope with a note that
        # no evidence has been computed — never rows, never an error. The
        # note must point at the evidence harness LIBRARY API (the only write
        # path) and never suggest a user-runnable workflow/CLI exists.
        facade, _ = _make_facade(tmp_path, alpha_ids=("a1",))
        payload = facade.query_strategies(min_evidence_quality="any")
        assert payload["status"] == "ok"
        assert payload["items"] == []
        note = payload.get("note", "")
        assert (
            note
        ), "empty store query must carry a 'note' explaining no evidence exists"
        assert isinstance(note, str)
        assert "rebuild_evidence" in note, (
            "the note must name the harness library API as the only write "
            f"path: {note!r}"
        )
        assert (
            "vibe-trading" not in note
        ), f"the note must not suggest a CLI command exists: {note!r}"

    def test_item_shape_carries_every_evidence_field_plus_borderline(
        self, tmp_path
    ) -> None:
        # AC4: per-regime rows, not boolean tags — every EvidenceRow field is
        # surfaced on the item, plus the facade-computed "borderline" flag.
        facade, _ = _make_facade(
            tmp_path, alpha_ids=("a1",), rows=(_row("alpha_zoo:a1", "bear_market"),)
        )
        payload = facade.query_strategies(regime="bear_market")
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
        payload = facade.query_strategies(min_evidence_quality="any")
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
        payload = facade.query_strategies(regime="bear_market")
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
