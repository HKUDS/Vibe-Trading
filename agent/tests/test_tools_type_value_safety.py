"""Argument type/value safety at tool entrypoints (PR #913).

Two rules are enforced here, and the distinction matters:

* An **absent** optional argument may fall back to its documented default.
* An **explicitly malformed** argument (non-numeric, NaN/Infinity, or an integer
  too large for a float) must NOT be silently replaced by a default. Read-only
  data tools clamp such values, but every entrypoint that spends money or places
  an order fails closed with an error envelope *before* the side effect.

Every test here is hermetic: no network call, no ``~/.vibe-trading`` access, and
each one reaches the branch it claims to cover.
"""

from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from src.tools import qveris_tool as qt
from src.tools import shadow_account_tool as sat
from src.tools.alpha_zoo_tool import run_alpha_zoo
from src.tools.block_trades_tool import _clamp_days as block_trades_clamp_days
from src.tools.fred_macro_tool import _clamp_limit as fred_clamp_limit
from src.tools.iwencai_tool import _coerce_limit as iwencai_coerce_limit
from src.tools.lockup_expiry_tool import _clamp_horizon as lockup_clamp_horizon
from src.tools.margin_trading_tool import _clamp_days as margin_clamp_days
from src.tools.northbound_tool import _clamp_lookback
from src.tools.options_chain_tool import _coerce_expiration
from src.tools.options_pricing_tool import OptionsPricingTool
from src.tools.report_audit_tool import ReportAuditTool
from src.tools.research_reports_tool import _clamp_limit as research_clamp_limit
from src.tools.sec_filings_tool import _clamp_limit as sec_clamp_limit
from src.tools.session_search_tool import SessionSearchTool
from src.tools.shareholder_count_tool import _clamp_periods as shareholder_clamp_periods
from src.tools.stock_news_tool import _clamp_limit as stock_news_clamp_limit
from src.tools.symbol_search_tool import _clamp_limit as symbol_clamp_limit
from src.tools.trading_connector_tool import (
    InvalidTradingArgument,
    TradingPlaceOrderTool,
    _int_or_none,
    _num_or_none,
)
from src.tools.web_search_tool import WebSearchTool

pytestmark = pytest.mark.unit

# A JSON integer with no float representation. NOTE: ``int()`` of an int is the
# identity, so this only overflows on paths that go through ``float()`` — the
# ``int()``-based clamp helpers legitimately clamp it to their maximum instead.
# Kept under Python's 4300-digit int→str limit so pytest can build a test id.
_UNREPRESENTABLE_INT = 10 ** 400


# ── read-only clamp helpers: non-finite falls back, finite is unchanged ────────


def test_clamp_helpers_survive_non_finite_and_preserve_finite_values() -> None:
    """Read-only limit helpers clamp junk instead of raising OverflowError.

    ``int(float("inf"))`` raises OverflowError — that is the failure mode these
    helpers now absorb. A huge *integer* needs no absorbing: ``int()`` accepts it
    and the normal range clamp applies.
    """
    assert _clamp_lookback(float("inf")) == 30
    assert _clamp_lookback(float("-inf")) == 30
    assert _clamp_lookback(_UNREPRESENTABLE_INT) == 250  # clamped to the max lookback
    assert block_trades_clamp_days(float("inf")) == 30
    assert fred_clamp_limit(float("inf")) == 2000
    assert iwencai_coerce_limit(float("inf")) == 20
    assert lockup_clamp_horizon(float("inf")) == 90
    assert margin_clamp_days(float("inf")) == 30
    assert research_clamp_limit(float("inf")) == 20
    assert sec_clamp_limit(float("inf")) == 20
    assert shareholder_clamp_periods(float("inf")) == 24
    assert stock_news_clamp_limit(float("inf")) == 20
    assert symbol_clamp_limit(float("inf")) == 10
    assert _coerce_expiration(float("inf")) is None
    assert _coerce_expiration(float("-inf")) is None

    # Finite requests must be untouched by the hardening.
    assert _clamp_lookback(7) == 7
    assert _clamp_lookback("7") == 7
    assert fred_clamp_limit(50) == 50
    assert _coerce_expiration(3) == 3


def test_alpha_zoo_rejects_non_finite_limit() -> None:
    """run_alpha_zoo answers with an error envelope, not an OverflowError."""
    for bad in (float("inf"), float("-inf"), float("nan"), "many", None):
        res = run_alpha_zoo(action="list_alphas", limit=bad)
        assert res["status"] == "error"
        assert "limit must be" in res["error"]


# ── trading connector: action-bearing, so it must fail closed ─────────────────


def test_trading_numeric_helpers_reject_malformed_values() -> None:
    """Malformed order numerics raise instead of degrading to None."""
    assert _num_or_none(None) is None
    assert _num_or_none("") is None
    assert _num_or_none(2) == 2.0
    assert _int_or_none(None) is None
    assert _int_or_none("7") == 7

    for bad in (float("nan"), float("inf"), float("-inf"), {}, [], "invalid", _UNREPRESENTABLE_INT):
        with pytest.raises(InvalidTradingArgument):
            _num_or_none(bad, "quantity")
        with pytest.raises(InvalidTradingArgument):
            _int_or_none(bad, "port")

    # A fractional port is not a whole number and must not be truncated.
    with pytest.raises(InvalidTradingArgument):
        _int_or_none(7.5, "port")


@pytest.mark.parametrize(
    "bad_kwargs",
    [
        {"quantity": "bad", "notional": 100},
        {"quantity": float("nan")},
        {"quantity": float("inf")},
        {"quantity": 5, "limit_price": "abc"},
        {"quantity": 5, "port": "not-a-port"},
        {"quantity": 5, "client_id": float("inf")},
    ],
)
def test_place_order_never_reaches_service_with_malformed_arguments(
    monkeypatch: pytest.MonkeyPatch, bad_kwargs: dict[str, Any]
) -> None:
    """Regression: `quantity="bad", notional=100` must not become a $100 order."""
    calls: list[dict[str, Any]] = []

    def fail_place_order(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        raise AssertionError("place_order must not be called for malformed input")

    monkeypatch.setattr("src.tools.trading_connector_tool.place_order", fail_place_order)

    payload = json.loads(
        TradingPlaceOrderTool().execute(
            symbol="NVDA", connection="alpaca-paper-trade", side="buy", **bad_kwargs
        )
    )

    assert payload["status"] == "error"
    assert payload["error"]
    assert calls == []


def test_place_order_still_forwards_valid_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fail-closed guard must not break a well-formed order."""
    seen: dict[str, Any] = {}

    def fake_place_order(symbol: str, connection: Any, **kwargs: Any) -> dict[str, Any]:
        seen.update({"symbol": symbol, "connection": connection, **kwargs})
        return {"status": "ok"}

    monkeypatch.setattr("src.tools.trading_connector_tool.place_order", fake_place_order)

    payload = json.loads(
        TradingPlaceOrderTool().execute(
            symbol="NVDA",
            connection="alpaca-paper-trade",
            side="buy",
            quantity=2,
            notional=0,
            port=7497,
        )
    )

    assert payload["status"] == "ok"
    assert seen["quantity"] == 2.0
    assert seen["notional"] is None
    assert seen["port"] == 7497


# ── QVeris: not read-only, spends real credits ────────────────────────────────


@pytest.fixture()
def paid_qveris(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Configure paid-mode QVeris against a tmp config file (never the real key)."""
    monkeypatch.setattr(qt, "QVERIS_CONFIG_PATH", tmp_path / "qveris.json")
    monkeypatch.delenv("QVERIS_API_KEY", raising=False)
    monkeypatch.delenv("QVERIS_BASE_URL", raising=False)
    qt._SESSION_SPEND.clear()
    qt._SESSION_RESERVED.clear()
    qt.save_qveris_config(
        qt.QVerisConfig(enabled=True, api_key="sk-test", mode="paid", budget_credits_per_session=50.0)
    )
    yield
    qt._SESSION_SPEND.clear()
    qt._SESSION_RESERVED.clear()


def _forbid_qveris_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any QVeris client construction an outright test failure."""

    def fail(self: Any) -> Any:
        raise AssertionError("no QVeris client may be built for an invalid request")

    monkeypatch.setattr(qt.QVerisSearchTool, "_client", fail)
    monkeypatch.setattr(qt.QVerisExecuteTool, "_client", fail)


@pytest.mark.parametrize("kwargs", [{}, {"query": None}, {"query": "   "}, {"query": 5}])
def test_qveris_search_rejects_missing_query(
    paid_qveris: None, monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any]
) -> None:
    """A missing query must not be sent to the marketplace as an empty search."""
    _forbid_qveris_client(monkeypatch)

    payload = json.loads(qt.QVerisSearchTool().execute(**kwargs))

    assert payload["ok"] is False
    assert "query is required" in payload["error"]


@pytest.mark.parametrize("bad_limit", [float("inf"), float("nan"), "many", 0, -3, 2.5, {}])
def test_qveris_search_rejects_malformed_limit(
    paid_qveris: None, monkeypatch: pytest.MonkeyPatch, bad_limit: Any
) -> None:
    """An explicitly malformed limit errors instead of quietly becoming 20."""
    _forbid_qveris_client(monkeypatch)

    payload = json.loads(qt.QVerisSearchTool().execute(query="btc", limit=bad_limit))

    assert payload["ok"] is False
    assert "limit must be a positive integer" in payload["error"]


def test_qveris_search_forwards_valid_request(paid_qveris: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed search still reaches the client with a defaulted limit."""
    seen: dict[str, Any] = {}

    class FakeClient:
        def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
            seen.update({"query": query, **kwargs})
            return {"results": []}

    monkeypatch.setattr(qt.QVerisSearchTool, "_client", lambda self: FakeClient())

    payload = json.loads(qt.QVerisSearchTool().execute(query="  btc  "))

    assert payload["ok"] is True
    assert seen["query"] == "btc"
    assert seen["limit"] == 20


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"tool_id": "t1"}, "parameters is required"),
        ({"tool_id": "t1", "parameters": None}, "parameters is required"),
        ({"tool_id": "t1", "parameters": "{}"}, "parameters is required"),
        ({"tool_id": "t1", "parameters": []}, "parameters is required"),
        ({"parameters": {"x": 1}}, "tool_id is required"),
        ({"tool_id": "", "parameters": {"x": 1}}, "tool_id is required"),
        ({"tool_id": "t1", "parameters": {}, "max_response_size": float("inf")}, "max_response_size"),
        ({"tool_id": "t1", "parameters": {}, "max_response_size": "big"}, "max_response_size"),
    ],
)
def test_qveris_execute_never_bills_an_invalid_request(
    paid_qveris: None, monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any], expected: str
) -> None:
    """A schema-invalid billable call is refused before quote/budget/execute."""
    _forbid_qveris_client(monkeypatch)

    payload = json.loads(qt.QVerisExecuteTool().execute(**kwargs))

    assert payload["ok"] is False
    assert expected in payload["error"]
    assert qt._SESSION_RESERVED == {}
    assert qt._SESSION_SPEND == {}


def test_qveris_execute_accepts_a_genuinely_empty_parameters_object(
    paid_qveris: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`parameters={}` is a valid supplied value — only a MISSING field is refused."""
    seen: dict[str, Any] = {}

    class FakeClient:
        def execute(self, tool_id: str, **kwargs: Any) -> dict[str, Any]:
            seen.update({"tool_id": tool_id, **kwargs})
            return {"success": True, "cost": 1.0, "result": {}}

    monkeypatch.setattr(qt.QVerisExecuteTool, "_client", lambda self: FakeClient())

    payload = json.loads(
        qt.QVerisExecuteTool().execute(
            tool_id="tool_1", parameters={}, session_id="s1", expected_cost="1 credit"
        )
    )

    assert payload["ok"] is True
    assert seen["parameters"] == {}
    assert seen["max_response_size"] == 20480


# ── report_audit extract options ──────────────────────────────────────────────


def test_report_audit_rejects_invalid_ratio_and_seed() -> None:
    """Malformed sampling options error instead of silently reshaping the sample."""
    bad_ratio = json.loads(
        ReportAuditTool().execute(command="extract", report_text="收入：1亿", ratio="invalid")
    )
    assert bad_ratio["status"] == "error"
    assert "invalid ratio" in bad_ratio["error"]

    bad_seed = json.loads(
        ReportAuditTool().execute(command="extract", report_text="收入：1亿", seed=float("inf"))
    )
    assert bad_seed["status"] == "error"
    assert "invalid seed" in bad_seed["error"]


# ── options pricing ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad_spot", [None, "", {}, [], "abc"])
def test_options_pricing_rejects_unusable_spot(bad_spot: Any) -> None:
    """A missing/malformed required argument returns an error envelope."""
    payload = json.loads(
        OptionsPricingTool().execute(
            spot=bad_spot, strike=100, expiry_days=30, volatility=0.2, option_type="call"
        )
    )
    assert payload["status"] == "error"
    assert payload["error"]


# ── session search: must not touch ~/.vibe-trading/sessions.db ────────────────


def test_session_search_rejects_malformed_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit junk max_results errors before the session index is opened."""

    def fail_get_shared_index() -> Any:
        raise AssertionError("the shared session index must not be opened")

    monkeypatch.setattr("src.session.search.get_shared_index", fail_get_shared_index)

    for bad in (float("nan"), float("inf"), "lots", {}, []):
        payload = json.loads(SessionSearchTool().execute(query="btc", max_results=bad))
        assert payload["status"] == "error"
        assert "max_results must be an integer" in payload["error"]


def test_session_search_absent_max_results_defaults_to_three(monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent max_results still defaults, and the default reaches the index."""
    seen: dict[str, Any] = {}

    class FakeIndex:
        def search(self, query: str, max_sessions: int = 3) -> list[Any]:
            seen.update({"query": query, "max_sessions": max_sessions})
            return []

    monkeypatch.setattr("src.session.search.get_shared_index", lambda: FakeIndex())

    payload = json.loads(SessionSearchTool().execute(query="btc"))

    assert payload["status"] == "ok"
    assert seen == {"query": "btc", "max_sessions": 3}


# ── web search: must not perform a real search ───────────────────────────────


@pytest.fixture(autouse=True)
def _no_search_env(monkeypatch: pytest.MonkeyPatch):
    """Keep the Aliyun IQS fast path and backend overrides out of these tests."""
    monkeypatch.delenv("ALIYUN_IQS_API_KEY", raising=False)
    monkeypatch.delenv("VIBE_TRADING_SEARCH_BACKENDS", raising=False)
    monkeypatch.delenv("VIBE_TRADING_SEARCH_BING_FALLBACK", raising=False)


def _install_fake_ddgs(monkeypatch: pytest.MonkeyPatch, recorder: dict[str, Any]) -> None:
    """Replace the ``ddgs`` module so no HTTP request can be issued."""
    module = ModuleType("ddgs")

    class FakeDDGS:
        def __enter__(self) -> "FakeDDGS":
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

        def text(self, query: str, max_results: int = 5, **kwargs: Any) -> list[dict[str, str]]:
            recorder["calls"] = recorder.get("calls", 0) + 1
            recorder["max_results"] = max_results
            return [{"title": "T", "href": "https://example.test/a", "body": "b"}]

    module.DDGS = FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", module)


@pytest.mark.parametrize("bad_query", [None, "", "   ", 5, {}])
def test_web_search_rejects_unusable_query(monkeypatch: pytest.MonkeyPatch, bad_query: Any) -> None:
    """A junk query is refused without any search being attempted."""
    recorder: dict[str, Any] = {}
    _install_fake_ddgs(monkeypatch, recorder)

    payload = json.loads(WebSearchTool().execute(query=bad_query))

    assert payload["status"] == "error"
    assert "query is mandatory" in payload["error"]
    assert recorder.get("calls", 0) == 0


@pytest.mark.parametrize("bad_max", [float("nan"), float("inf"), "five", {}, []])
def test_web_search_rejects_malformed_max_results(monkeypatch: pytest.MonkeyPatch, bad_max: Any) -> None:
    """An explicit junk max_results errors instead of searching with 5."""
    recorder: dict[str, Any] = {}
    _install_fake_ddgs(monkeypatch, recorder)

    payload = json.loads(WebSearchTool().execute(query="nvidia", max_results=bad_max))

    assert payload["status"] == "error"
    assert "max_results must be an integer" in payload["error"]
    assert recorder.get("calls", 0) == 0


def test_web_search_absent_max_results_defaults_to_five(monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent max_results defaults to 5 and is forwarded to the backend."""
    recorder: dict[str, Any] = {}
    _install_fake_ddgs(monkeypatch, recorder)

    payload = json.loads(WebSearchTool().execute(query="nvidia"))

    assert payload["status"] == "ok"
    assert recorder["calls"] == 1
    assert recorder["max_results"] == 5


# ── shadow account ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("field", ["min_support", "max_rules"])
def test_extract_shadow_strategy_rejects_malformed_integers(
    monkeypatch: pytest.MonkeyPatch, tmp_path, field: str
) -> None:
    """A malformed rule-mining option errors before the journal is parsed."""
    journal = tmp_path / "journal.csv"
    journal.write_text("x\n", encoding="utf-8")

    def fail_extract(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the journal must not be parsed for malformed options")

    monkeypatch.setattr(sat, "extract_shadow_profile", fail_extract)
    monkeypatch.setattr(sat, "safe_user_path", lambda raw: journal)

    payload = json.loads(
        sat.ExtractShadowStrategyTool().execute(journal_path=str(journal), **{field: float("inf")})
    )

    assert payload["status"] == "error"
    assert f"{field} must be an integer" in payload["error"]


def test_scan_shadow_signals_rejects_malformed_per_market(monkeypatch: pytest.MonkeyPatch) -> None:
    """per_market is validated before the profile load, so the branch is reached."""

    def fail_load(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no profile should be loaded for a malformed per_market")

    monkeypatch.setattr(sat, "load_profile", fail_load)

    payload = json.loads(
        sat.ScanShadowSignalsTool().execute(shadow_id="shadow-1", per_market=float("inf"))
    )

    assert payload["status"] == "error"
    assert "per_market must be an integer" in payload["error"]


def test_scan_shadow_signals_absent_per_market_defaults_to_three(monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent per_market defaults to 3 and reaches the scanner."""
    seen: dict[str, Any] = {}

    monkeypatch.setattr(sat, "load_profile", lambda shadow_id: SimpleNamespace(shadow_id=shadow_id))

    def fake_scan(profile: Any, target_date: Any = None, per_market: int = 3) -> list[Any]:
        seen.update({"shadow_id": profile.shadow_id, "target_date": target_date, "per_market": per_market})
        return []

    monkeypatch.setattr(sat, "scan_today_signals", fake_scan)

    payload = json.loads(sat.ScanShadowSignalsTool().execute(shadow_id="shadow-1"))

    assert payload["status"] == "ok"
    assert seen == {"shadow_id": "shadow-1", "target_date": None, "per_market": 3}
