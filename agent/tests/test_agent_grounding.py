"""Regression coverage for identity and numeric grounding (#887, #886)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from src.agent.context import ContextBuilder
from src.agent.grounding import (
    GroundingLedger,
    _infer_currency,
    _infer_instrument_type,
    _infer_venue,
    _JOINED_CRYPTO_RE,
    _normalize_symbol,
    _scan_symbols,
    _symbol_from_csv_filename,
    _timestamp_matches_claim_date,
)
from src.agent.loop import AgentLoop, _is_tool_success
from src.agent.tools import BaseTool, ToolRegistry
from src.agent.trace import TraceWriter
from tests.message_roles_helpers import assert_system_messages_only_lead


def _resolver_payload(
    symbol: str = "562500.SS",
    *,
    candidates: list[dict[str, Any]] | None = None,
    query: str = "机器人ETF",
) -> str:
    rows = candidates
    if rows is None:
        rows = [
            {
                "symbol": symbol,
                "name": "机器人ETF",
                "market": "cn",
                "type": "ETF",
                "source": "yahoo",
                "also_from": ["eastmoney"],
            }
        ]
    return json.dumps(
        {
            "ok": True,
            "source": "symbol_search",
            "data": {
                "query": query,
                "count": len(rows),
                "candidates": rows,
                "sources": {"eastmoney": "ok", "yahoo": "ok"},
            },
        },
        ensure_ascii=False,
    )


def _market_payload(symbol: str = "562500.SS") -> str:
    return json.dumps(
        {
            symbol: [
                {
                    "trade_date": "2026-06-23",
                    "open": 1.141,
                    "high": 1.164,
                    "low": 1.121,
                    "close": 1.137,
                    "volume": 123456,
                },
                {
                    "trade_date": "2026-06-24",
                    "open": 1.137,
                    "high": 1.180,
                    "low": 1.110,
                    "close": 1.171,
                    "volume": 234567,
                },
            ],
            "_provenance": {
                symbol: {
                    "source": "yahoo",
                    "requested_source": "auto",
                    "detected_source": "yahoo",
                    "fallback_used": False,
                    "currency_conversion": "none",
                }
            },
        }
    )


class _ResolverTool(BaseTool):
    name = "search_symbol"
    description = "Resolve a company or instrument name."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    repeatable = True

    def __init__(self, result: str) -> None:
        self.result = result
        self.calls = 0

    def execute(self, **kwargs: Any) -> str:
        self.calls += 1
        return self.result


class _MarketTool(BaseTool):
    name = "get_market_data"
    description = "Fetch OHLCV bars."
    parameters = {
        "type": "object",
        "properties": {"codes": {"type": "array", "items": {"type": "string"}}},
        "required": ["codes"],
    }
    repeatable = True

    def __init__(self, result: str) -> None:
        self.result = result
        self.calls = 0

    def execute(self, **kwargs: Any) -> str:
        self.calls += 1
        return self.result


class _PrivateCompanySkillTool(BaseTool):
    name = "load_skill"
    description = "Load a skill."
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    repeatable = True

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, **kwargs: Any) -> str:
        self.calls += 1
        return json.dumps({"status": "ok", "content": "private company workflow"})


def _tool_call(call_id: str, tool_name: str, **arguments: Any) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, name=tool_name, arguments=arguments)


def _build_direct_agent(
    tmp_path: Path,
    resolver_result: str,
) -> tuple[AgentLoop, _ResolverTool, _MarketTool, _PrivateCompanySkillTool, TraceWriter]:
    resolver = _ResolverTool(resolver_result)
    market = _MarketTool(_market_payload())
    private_skill = _PrivateCompanySkillTool()
    registry = ToolRegistry()
    for tool in (resolver, market, private_skill):
        registry.register(tool)
    agent = AgentLoop(registry=registry, llm=SimpleNamespace(), max_iterations=5)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)
    agent._grounding = GroundingLedger(
        run_dir=run_dir,
        user_message="分析机器人ETF并给出买入价",
    )
    return agent, resolver, market, private_skill, TraceWriter(run_dir)


def test_canadian_symbols_have_grounding_identity() -> None:
    """TSX and TSXV symbols retain venue and CAD identity."""
    assert _scan_symbols("Compare TD.TO with PNG.V") == {"TD.TO", "PNG.V"}
    assert _infer_venue("TD.TO") == "toronto"
    assert _infer_venue("PNG.V") == "tsx_venture"
    assert _infer_currency("TD.TO") == "CAD"
    assert _infer_currency("PNG.V") == "CAD"


def test_ok_false_tool_envelope_is_failure() -> None:
    """Business failures must not be recorded as successful tool calls (#886)."""
    assert _is_tool_success('{"ok": false, "error": "upstream failed"}') is False
    assert _is_tool_success('{"success": false, "message": "denied"}') is False
    assert _is_tool_success('{"status": "failed"}') is False
    assert _is_tool_success('{"ok": true, "data": {}}') is True


def test_resolver_and_consumer_in_same_batch_cannot_race(
    tmp_path: Path,
) -> None:
    """A consumer sees the identity snapshot from before its whole LLM batch."""
    agent, resolver, market, _, trace = _build_direct_agent(
        tmp_path,
        _resolver_payload(),
    )
    messages: list[dict[str, Any]] = []
    react_trace: list[dict[str, Any]] = []

    agent._process_tool_calls(
        [
            _tool_call("resolve", "search_symbol", query="机器人ETF"),
            _tool_call(
                "prices-too-early",
                "get_market_data",
                codes=["562500.SH"],
                start_date="2026-06-23",
                end_date="2026-06-24",
            ),
        ],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        1,
    )

    assert resolver.calls == 1
    assert market.calls == 0
    assert agent._grounding.authorized_symbols == {"562500.SH"}
    blocked = [json.loads(message["content"]) for message in messages]
    assert any(item.get("error_code") == "identity_required" for item in blocked)

    agent._process_tool_calls(
        [
            _tool_call(
                "prices-after-lock",
                "get_market_data",
                codes=["562500.SS"],
                start_date="2026-06-23",
                end_date="2026-06-24",
                source="auto",
            )
        ],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        2,
    )
    trace.close()

    assert market.calls == 1
    artifact = json.loads(
        (tmp_path / "run" / "artifacts" / "grounding_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert artifact["identity"]["status"] == "locked"
    assert any(
        record["field"] == "close"
        and record["value"] == 1.137
        and record["source"] == "yahoo"
        and record["currency"] == "CNY"
        and record["currency_conversion"] == "none"
        for record in artifact["evidence"]
    )


def test_market_sensitive_skill_waits_for_prior_identity_batch(
    tmp_path: Path,
) -> None:
    """Workflow selection cannot race the resolver in the same assistant turn."""
    agent, resolver, _, skill, trace = _build_direct_agent(tmp_path, _resolver_payload())
    messages: list[dict[str, Any]] = []
    react_trace: list[dict[str, Any]] = []

    agent._process_tool_calls(
        [
            _tool_call("resolve", "search_symbol", query="机器人ETF"),
            _tool_call("workflow-too-early", "load_skill", name="valuation-model"),
        ],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        1,
    )

    assert resolver.calls == 1
    assert skill.calls == 0
    assert json.loads(messages[-1]["content"])["error_code"] == "identity_required"

    agent._process_tool_calls(
        [_tool_call("workflow-after-lock", "load_skill", name="valuation-model")],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        2,
    )
    trace.close()

    assert skill.calls == 1


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("get_sec_filings", {"ticker": "AAPL"}),
        ("get_market_data", {"codes": ["AAPL"]}),
        ("get_fundamentals", {"symbols": ["AAPL"]}),
        ("technical_indicators", {"symbol": "AAPL"}),
        ("portfolio_risk_xray", {"symbols": ["AAPL"]}),
        ("trading_history", {"symbol": "AAPL"}),
    ],
)
def test_bare_ticker_is_allowed_whenever_it_names_one_locked_identity(
    tmp_path: Path,
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    """A bare ticker is safe by uniqueness, not by a hand-maintained tool list.

    Every spelling here is the first example in that tool's own parameter
    schema. The list this replaced named nine tools, so the other five were
    rejected for using their documented contract.
    """
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="请分析 AAPL.US 的价格",
    )

    authorization = ledger.authorize_tool_call(
        tool_name,
        arguments,
        batch_authorized_symbols=ledger.authorized_symbols,
        call_id="consumer",
    )

    assert authorization.allowed is True


def test_bare_ticker_stays_blocked_when_it_names_more_than_one_identity(
    tmp_path: Path,
) -> None:
    """Uniqueness is the whole guarantee, so a shared base must not resolve."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="对比 600519.SH 与 600519.SZ 的价格",
    )

    authorization = ledger.authorize_tool_call(
        "get_market_data",
        {"codes": ["600519"]},
        batch_authorized_symbols=ledger.authorized_symbols,
        call_id="prices",
    )

    assert ledger.authorized_symbols == {"600519.SH", "600519.SZ"}
    assert authorization.allowed is False
    assert authorization.error_code == "identity_mismatch"


@pytest.mark.parametrize(
    ("locked", "requested"),
    [
        ("600519.SH", "600519.SS"),
        ("600519.SH", "sh600519"),
        ("00700.HK", "700.HK"),
        ("00700.HK", "0700.HK"),
        ("BTC-USDT", "BTC/USDT"),
        # Joined crypto pairs (no separator) are the same identity as the
        # dashed/slashed spelling. Without this normalization, a ``BTCUSDT``
        # argument against a locked ``BTC-USDT`` is rejected as
        # ``identity_mismatch`` by ``_match_authorized_symbol``.
        ("BTC-USDT", "BTCUSDT"),
        ("ETH-USDT", "ETHUSDT"),
        ("BTC-USDC", "BTCUSDC"),
    ],
)
def test_provider_spellings_of_one_instrument_are_one_identity(
    tmp_path: Path,
    locked: str,
    requested: str,
) -> None:
    """A suffix convention, an exchange prefix, or a separator is not a venue."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message=f"{locked} 现价多少")

    authorization = ledger.authorize_tool_call(
        "get_market_data",
        {"codes": [requested]},
        batch_authorized_symbols=ledger.authorized_symbols,
        call_id="prices",
    )

    assert ledger.authorized_symbols == {locked}
    assert authorization.allowed is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The four unambiguous stablecoin suffixes, with several bases.
        ("BTCUSDT", "BTC-USDT"),
        ("ETHUSDT", "ETH-USDT"),
        ("SOLUSDT", "SOL-USDT"),
        ("BTCUSDC", "BTC-USDC"),
        ("BTCBUSD", "BTC-BUSD"),
        ("ETHTUSD", "ETH-TUSD"),
        ("btcusdt", "BTC-USDT"),  # case-insensitive
        # Edge: the suffix alone is too short to split (the base must have
        # at least one character).
        ("USDT", "USDT"),
        ("USDC", "USDC"),
        # Edge: a numeric prefix is not a crypto base.
        ("123USDT", "123USDT"),
        # Negatives: existing shapes must be untouched.
        ("BTC-USDT", "BTC-USDT"),
        ("BTC/USD", "BTC-USD"),
        ("VALOUR-BTC-0-SEK.ST", "VALOUR-BTC-0-SEK.ST"),
        ("AAPL.US", "AAPL.US"),
        ("600519.SH", "600519.SH"),
    ],
)
def test_normalize_joined_crypto_pairs(raw: str, expected: str) -> None:
    """A joined crypto pair (no separator) normalizes to its dashed form."""
    assert _normalize_symbol(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("BTCUSDT", {"BTC-USDT"}),
        ("BTCUSDT spot price", {"BTC-USDT"}),
        ("ETH/USDT latest price", {"ETH-USDT"}),
        ("BTC-USDT close", {"BTC-USDT"}),
        ("BTCUSDT, ETH-USDT, BTC-USD", {"BTC-USDT", "ETH-USDT", "BTC-USD"}),
    ],
)
def test_scan_symbols_detects_joined_pairs(text: str, expected: set[str]) -> None:
    """A bare joined crypto pair is scanned as the canonical symbol."""
    assert _scan_symbols(text) == expected


# The other arm of the same decision, pinned as two mechanisms because it is
# two mechanisms. Nothing covered either of them: adding "USD" back to the
# suffix list passed every other test in this file while folding spot gold to
# XAU-USD, the exact tokenized-gold misresolution #1282 exists to stop.
#
# 1. Bare "USD" is kept out of the suffix list, so an FX or metal pair never
#    matches the joined-pair regex in the first place.
@pytest.mark.parametrize("raw", ["XAUUSD", "XAGUSD", "XPDUSD", "EURUSD", "GBPUSD"])
def test_bare_usd_quote_never_matches_the_joined_pair_regex(raw: str) -> None:
    assert _JOINED_CRYPTO_RE.fullmatch(raw) is None
    assert "-USD" not in _normalize_symbol(raw)


# 2. XPTUSD is the case the suffix list alone cannot catch: it is XPT + USD
#    (platinum), but it also ends in "TUSD", so the regex DOES match and the
#    alpha base "XP" passes the isalpha guard. Without the metal-pair check it
#    normalizes to XP-TUSD — a crypto pair that does not exist. FX pairs have
#    canonical_fx_pair as a second line of defence; XAU/XPT are metal codes,
#    not fiat codes, so they have none.
def test_metal_usd_pair_is_not_split_on_the_tusd_suffix() -> None:
    assert _JOINED_CRYPTO_RE.fullmatch("XPTUSD") is not None, (
        "precondition: the regex does match, which is why the guard is needed"
    )
    assert _normalize_symbol("XPTUSD") == "XPTUSD"


# ...and the guard must not swallow genuine pairs quoted in TrueUSD.
def test_genuine_tusd_pairs_still_fold() -> None:
    assert _normalize_symbol("LINKTUSD") == "LINK-TUSD"
    assert _normalize_symbol("ADABUSD") == "ADA-BUSD"
    assert _normalize_symbol("OPUSDT") == "OP-USDT"


def test_binance_pair_resolution_authorizes_crypto_consumers(tmp_path: Path) -> None:
    """Issue #1234: an exact connector pair must survive unrelated Yahoo hits."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="Check the ETH-USDT orderbook and current price.",
    )
    before_resolution = ledger.authorized_symbols
    resolver = ledger.authorize_tool_call(
        "search_symbol",
        {"query": "ETH-USDT"},
        batch_authorized_symbols=before_resolution,
        call_id="resolve-crypto",
    )
    assert resolver.allowed is True

    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "ETH-USDT"},
        result=json.dumps(
            {
                "ok": True,
                "source": "symbol_search",
                "data": {
                    "query": "ETH-USDT",
                    "count": 2,
                    "sources": {"binance": "ok", "yahoo": "ok"},
                    "candidates": [
                        {
                            "symbol": "ETH-USDT",
                            "market": "crypto",
                            "type": "cryptocurrency",
                            "exchange": "BINANCE",
                            "source": "binance",
                        },
                        {
                            "symbol": "AETHUSDT-USD",
                            "market": "global",
                            "type": "cryptocurrency",
                            "exchange": "CCC",
                            "source": "yahoo",
                        },
                    ],
                },
            }
        ),
        call_id="resolve-crypto",
        success=True,
    )

    authorization = ledger.authorize_tool_call(
        "orderbook_depth",
        {"symbol": "ETH-USDT", "exchange": "binance"},
        batch_authorized_symbols=ledger.authorized_symbols,
        batch_identity_status=ledger.identity_status,
        call_id="crypto-book",
    )

    assert ledger.identity_status == "locked"
    assert ledger.authorized_symbols == {"ETH-USDT"}
    assert authorization.allowed is True


def test_stale_history_identity_does_not_unlock_new_subject(tmp_path: Path) -> None:
    """A previous turn's AAPL identity cannot authorize a SpaceX price request."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="SpaceX 在什么价格买入比较合适？",
        history=[{"role": "user", "content": "请分析 AAPL.US"}],
    )

    authorization = ledger.authorize_tool_call(
        "get_market_data",
        {"codes": ["AAPL.US"]},
        batch_authorized_symbols=ledger.authorized_symbols,
        call_id="stale-price",
    )

    assert ledger.authorized_symbols == set()
    assert authorization.allowed is False
    assert authorization.error_code == "identity_required"


def test_single_clean_not_found_source_is_not_enough_for_private_routing(
    tmp_path: Path,
) -> None:
    """A partial resolver outage cannot turn a public entity into private research."""
    resolver_result = json.dumps(
        {
            "ok": True,
            "source": "symbol_search",
            "data": {
                "query": "Acme",
                "count": 0,
                "candidates": [],
                "sources": {
                    "eastmoney": "ok",
                    "yahoo": "HTTP 429",
                },
            },
        }
    )
    agent, _, _, private_skill, trace = _build_direct_agent(tmp_path, resolver_result)
    messages: list[dict[str, Any]] = []
    react_trace: list[dict[str, Any]] = []

    agent._process_tool_calls(
        [_tool_call("resolve", "search_symbol", query="Acme")],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        1,
    )
    agent._process_tool_calls(
        [_tool_call("private", "load_skill", name="private-company-research")],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        2,
    )
    trace.close()

    assert agent._grounding.identity_status == "invalidated"
    assert private_skill.calls == 0
    assert json.loads(messages[-1]["content"])["error_code"] == "identity_required"


def test_explicit_symbol_and_resolver_suffix_alias_are_one_identity(
    tmp_path: Path,
) -> None:
    """``.SS`` and ``.SH`` name the same Shanghai listing, not a contradiction.

    Reading them as rivals is what made every Shanghai query unusable: the two
    sources publish one listing under both spellings, so no tie-break existed.
    """
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="请分析 562500.SS 并给出买入价",
    )
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "机器人ETF"},
        result=_resolver_payload("562500.SH"),
        call_id="resolver-alias",
        success=True,
    )

    authorization = ledger.authorize_tool_call(
        "get_market_data",
        {"codes": ["562500.SS"]},
        batch_authorized_symbols=ledger.authorized_symbols,
        batch_identity_status=ledger.identity_status,
        call_id="prices",
    )

    assert ledger.identity_status == "locked"
    assert ledger.authorized_symbols == {"562500.SH"}
    assert authorization.allowed is True


@pytest.mark.parametrize(
    ("symbol", "expected_venue", "expected_type"),
    [
        # Spot gold: bare 6-letter, dashed, slashed, Yahoo forex notation.
        # Before this fix, the shape-based fallback in _infer_venue / _infer_instrument_type
        # mis-classified any dashed / slashed symbol as crypto_or_fx / crypto.
        ("XAUUSD", "forex", "forex"),
        ("XAU-USD", "forex", "forex"),
        ("XAU/USD", "forex", "forex"),
        ("XAUUSD=X", "forex", "forex"),
        # COMEX gold futures via Yahoo continuous-front-month notation.
        ("GC=F", "futures", "future"),
        # Tokenized gold stays crypto.
        ("XAUT-USDT", "crypto_or_fx", "crypto"),
        ("PAXG-USDT", "crypto_or_fx", "crypto"),
        # Regression: existing crypto / US equity behavior unchanged.
        ("BTC-USDT", "crypto_or_fx", "crypto"),
        ("GLD", None, "listed_security"),
        ("AAPL.US", "us", "listed_security"),
    ],
)
def test_runtime_registry_classifies_gold_fx_futures_consistently(
    symbol, expected_venue, expected_type
) -> None:
    """The runtime registry must agree with the engine classifier for gold / FX / futures.

    PR #1280 added the metal/FX/futures patterns to the engine
    ``_MARKET_PATTERNS`` and the correlation helper. This test pins the
    third copy (the shape-based fallback in
    ``_infer_venue`` / ``_infer_instrument_type``) to the same
    whitelist. Without this, a bare ``XAUUSD`` query would surface in
    the registry as ``venue=None, type=listed_security`` and a dashed
    ``XAU-USD`` would surface as ``venue=crypto_or_fx, type=crypto``,
    contradicting the engine's actual classification. The user observed
    this exact runtime state in the agent before the fix.
    """
    assert _infer_venue(symbol) == expected_venue
    assert _infer_instrument_type(symbol) == expected_type
    # Quote currency is non-None only for dashed / slashed shapes.
    if "-" in symbol or "/" in symbol:
        # Whitelist-based ``USD`` leg: only metals/FX/forex (not crypto).
        if symbol.endswith("-USD") and symbol not in {"XAUT-USD", "PAXG-USD"}:
            assert _infer_currency(symbol) == "USD"
        # Otherwise the trailing 3-5 letter leg is the quote currency.
        elif symbol.endswith("-USDT") or symbol.endswith("-USDC") or \
             symbol.endswith("-BUSD") or symbol.endswith("-TUSD") or \
             symbol.endswith("-FDUSD"):
            assert _infer_currency(symbol) in {"USDT", "USDC", "BUSD", "TUSD", "FDUSD"}


def test_resolver_answering_a_different_venue_is_still_conflicting(
    tmp_path: Path,
) -> None:
    """Folding a suffix alias must not fold a genuinely different exchange."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="请分析 600519.SH 并给出买入价",
    )
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "600519.SH"},
        result=_resolver_payload("600519.SZ", query="600519.SH"),
        call_id="resolver-venue",
        success=True,
    )

    authorization = ledger.authorize_tool_call(
        "get_market_data",
        {"codes": ["600519.SZ"]},
        batch_authorized_symbols=ledger.authorized_symbols,
        batch_identity_status=ledger.identity_status,
        call_id="prices",
    )

    assert ledger.identity_status == "conflicting"
    assert authorization.allowed is False
    assert authorization.error_code == "identity_conflict"


def test_locked_symbol_rejects_silent_exchange_rewrite(
    tmp_path: Path,
) -> None:
    """The consumer may not move the locked listing to another exchange."""
    agent, _, market, _, trace = _build_direct_agent(tmp_path, _resolver_payload())
    messages: list[dict[str, Any]] = []
    react_trace: list[dict[str, Any]] = []

    agent._process_tool_calls(
        [_tool_call("resolve", "search_symbol", query="机器人ETF")],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        1,
    )
    agent._process_tool_calls(
        [_tool_call("wrong-venue", "get_market_data", codes=["562500.SZ"])],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        2,
    )
    trace.close()

    assert market.calls == 0
    assert json.loads(messages[-1]["content"])["error_code"] == "identity_mismatch"


def test_listed_identity_blocks_private_company_workflow(
    tmp_path: Path,
) -> None:
    """Model memory cannot relabel a strongly resolved listing as private."""
    candidates = [
        {
            "symbol": "SPCX.US",
            "name": "SpaceX",
            "market": "us",
            "type": "equity",
            "exchange": "NMS",
            "source": "eastmoney",
            "also_from": ["yahoo"],
            "cik": "0001181412",
        }
    ]
    agent, _, _, private_skill, trace = _build_direct_agent(
        tmp_path,
        _resolver_payload("SPCX.US", candidates=candidates, query="SpaceX"),
    )
    messages: list[dict[str, Any]] = []
    react_trace: list[dict[str, Any]] = []

    agent._process_tool_calls(
        [_tool_call("resolve", "search_symbol", query="SpaceX")],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        1,
    )
    agent._process_tool_calls(
        [_tool_call("private", "load_skill", name="private-company-research")],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        2,
    )
    trace.close()

    assert private_skill.calls == 0
    assert json.loads(messages[-1]["content"])["error_code"] == "identity_conflict"
    validation = agent._grounding.validate_final_answer(
        "SpaceX is a private company and is not publicly traded."
    )
    assert validation.valid is False
    assert any(issue["code"] == "listed_identity_relabelled_private" for issue in validation.issues)


def test_not_found_identity_allows_private_company_workflow(
    tmp_path: Path,
) -> None:
    """A clean multi-source not-found result keeps genuine private research usable."""
    agent, _, _, private_skill, trace = _build_direct_agent(
        tmp_path,
        _resolver_payload(candidates=[], query="Acme Private Labs"),
    )
    messages: list[dict[str, Any]] = []
    react_trace: list[dict[str, Any]] = []

    agent._process_tool_calls(
        [_tool_call("resolve", "search_symbol", query="Acme Private Labs")],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        1,
    )
    agent._process_tool_calls(
        [_tool_call("private", "load_skill", name="private-company-research")],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        2,
    )
    trace.close()

    assert private_skill.calls == 1
    assert agent._grounding.identity_status == "not_found"


def test_ambiguous_resolution_keeps_consumers_blocked(tmp_path: Path) -> None:
    """Multiple weak candidates must become first-class ambiguous state."""
    candidates = [
        {"symbol": "ABC.US", "name": "ABC Holdings", "source": "yahoo"},
        {"symbol": "ABC.HK", "name": "ABC Group", "source": "eastmoney"},
    ]
    agent, _, market, _, trace = _build_direct_agent(
        tmp_path,
        _resolver_payload(candidates=candidates, query="ABC"),
    )
    messages: list[dict[str, Any]] = []
    react_trace: list[dict[str, Any]] = []

    agent._process_tool_calls(
        [_tool_call("resolve", "search_symbol", query="ABC")],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        1,
    )
    agent._process_tool_calls(
        [_tool_call("prices", "get_market_data", codes=["ABC.US"])],
        ContextBuilder,
        messages,
        trace,
        react_trace,
        2,
    )
    trace.close()

    assert agent._grounding.identity_status == "ambiguous"
    assert market.calls == 0
    assert json.loads(messages[-1]["content"])["error_code"] == "identity_conflict"


def test_final_numeric_gate_rejects_known_trace_contradiction(tmp_path: Path) -> None:
    """Known 1.11-1.18 evidence cannot become 0.88-0.91 in the answer."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="请分析 562500.SS 并给出买入价",
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={
            "codes": ["562500.SS"],
            "source": "auto",
        },
        result=_market_payload(),
        call_id="prices",
        success=True,
    )

    bad = ledger.validate_final_answer(
        """| 日期 | 开盘 | 最高 | 最低 | 收盘 |
|---|---:|---:|---:|---:|
| 2026-06-23 | 0.895 | 0.907 | 0.892 | 0.903 |

建议重仓买入价为 0.881。"""
    )
    good = ledger.validate_final_answer(
        "562500.SS（Yahoo，CNY）在 2026-06-23 的已观测开盘价为 1.141，收盘价为 1.137。"
    )

    assert bad.valid is False
    assert any(issue["code"] == "numeric_claim_conflict" for issue in bad.issues)
    assert good.valid is True


def test_run_dir_ohlc_csv_is_observed_evidence(tmp_path: Path) -> None:
    """A bash-written OHLC CSV grounds the prices the answer quotes.

    The bash+yfinance workaround writes per-symbol CSVs into the run directory
    (e.g. ``data/raw/BYN_V.csv``) instead of returning bars through
    ``get_market_data``. Those prices are real observed output, so the final
    answer may cite them; a price outside the file must still be rejected.
    """
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "BYN_V.csv").write_text(
        "Date,Open,High,Low,Close,Adj Close,Volume\n"
        "2026-08-06,0.35,0.37,0.34,0.36,0.36,500000\n"
        "2026-08-07,0.36,0.38,0.355,0.375,0.375,600000\n",
        encoding="utf-8",
    )
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="请分析 BYN.V 并推荐买入价",
    )

    inside = ledger.validate_final_answer(
        "BYN.V（yfinance，CAD）在 2026-08-07 的已观测收盘价为 0.375。"
    )
    fabricated = ledger.validate_final_answer(
        "BYN.V（yfinance，CAD）在 2026-08-07 的已观测收盘价为 0.88。"
    )

    assert inside.valid is True, inside.issues
    assert fabricated.valid is False
    assert any(issue["code"] == "numeric_claim_conflict" for issue in fabricated.issues)


def test_run_dir_ohlc_csv_tsx_filename_maps_symbol(tmp_path: Path) -> None:
    """PDI_TO.csv maps to PDI.TO and grounds its CAD price."""
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "PDI_TO.csv").write_text(
        "Date,Open,High,Low,Close\n"
        "2026-08-07,10.0,10.5,9.9,10.2\n",
        encoding="utf-8",
    )
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="请分析 PDI.TO 并推荐买入价",
    )

    good = ledger.validate_final_answer(
        "PDI.TO（yfinance，CAD）在 2026-08-07 的已观测收盘价为 10.2。"
    )

    assert good.valid is True, good.issues


def test_weekday_suffixed_claim_dates_match_evidence() -> None:
    """Yearless dates with weekday/intraday annotations still match evidence.

    Reports write a trading day as ``08-10(一)``, ``08-10(周一)盘中`` or
    ``08-10盘中`` rather than bare ``08-10``. Before the prefix matcher, such
    a date cell matched no evidence row and every correct price in the row
    was rejected as ``numeric_claim_unavailable`` (#1015 session regression).
    """
    assert _timestamp_matches_claim_date("2026-08-10T00:00:00", "08-10(一)") is True
    assert _timestamp_matches_claim_date("2026-08-10T00:00:00", "08-10(周一)盘中") is True
    assert _timestamp_matches_claim_date("2026-08-10T00:00:00", "08-10盘中") is True
    assert _timestamp_matches_claim_date("2026-08-10T00:00:00", "08-10") is True
    assert _timestamp_matches_claim_date("2026-08-10T00:00:00", "2026-08-10") is True
    assert _timestamp_matches_claim_date("2026-08-10T00:00:00", "2026-08-10(一)") is True
    assert _timestamp_matches_claim_date("2026-08-10T00:00:00", "08-11") is False
    assert _timestamp_matches_claim_date("2026-08-10T00:00:00", "no-date") is False


def test_run_dir_ohlc_csv_us_filename_maps_symbol(tmp_path: Path) -> None:
    """INTC_US.csv maps to INTC.US and grounds weekday-suffixed date rows.

    Regression for a real session: the agent wrote ``data/raw/INTC_US.csv``
    and drafted the report in the file's own date format (``08-10(一)``).
    The filename used to map to None (no ``_US`` rule), so the CSV was never
    ingested; combined with the weekday-suffixed date cell, every correct
    price in the draft was rejected and the run surrendered after three
    failed drafts without updating the report.
    """
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "INTC_US.csv").write_text(
        "Date,Open,High,Low,Close,Adj Close,Volume\n"
        "2026-08-07,102.33,103.66,98.03,101.65,101.65,76760600\n"
        "2026-08-10,98.26,100.03,96.30,97.52,97.52,101153400\n",
        encoding="utf-8",
    )

    assert _symbol_from_csv_filename("INTC_US") == "INTC.US"

    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="please update intel-tech-trend-6-months.md",
    )
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "INTC"},
        result=json.dumps({
            "ok": True,
            "data": {
                "candidates": [
                    {"symbol": "INTC.US", "name": "Intel Corporation", "market": "us",
                     "type": "equity", "exchange": "NMS", "source": "yahoo"},
                ]
            },
        }),
        call_id="lock1",
        success=True,
    )

    table = (
        "INTC.US（yfinance，USD）日线如下：\n"
        "| 日期 | 开盘 | 最高 | 最低 | 收盘 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 08-07(五) | 102.33 | 103.66 | 98.03 | 101.65 |\n"
        "| 08-10(一) | 98.26 | 100.03 | 96.30 | 97.52 |\n"
    )
    result = ledger.validate_final_answer(table)
    assert result.valid is True, result.issues

    # The date is masked in prose, but a fabricated price is still caught.
    fabricated = ledger.validate_final_answer(
        "INTC.US（yfinance，USD）08-10(一) 开盘价 88.88，收盘价 97.52，数据源 yahoo。"
    )
    assert fabricated.valid is False
    assert any(
        issue["code"] == "numeric_claim_conflict" for issue in fabricated.issues
    )


def test_run_dir_ohlc_csv_stray_symbol_is_ignored(tmp_path: Path) -> None:
    """A CSV for a symbol the run never handled does not mint identity."""
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "ZZZ_US.csv").write_text(
        "Date,Open,High,Low,Close\n"
        "2026-08-07,100.0,100.0,100.0,100.0\n",
        encoding="utf-8",
    )
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="请分析 BYN.V 并推荐买入价",
    )

    result = ledger.validate_final_answer(
        "ZZZ.US（yfinance，USD）在 2026-08-07 的已观测收盘价为 100.0。"
    )

    # The symbol is not entitled, so the price cannot be grounded.
    assert result.valid is False
    assert any(
        issue["code"] in {"numeric_claim_unavailable", "canonical_symbol_not_surfaced"}
        for issue in result.issues
    )


def test_numeric_gate_validates_derived_formula_and_provenance(tmp_path: Path) -> None:
    """A derived entry level must calculate correctly from observed evidence."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="请分析 562500.SS 并给出买入价",
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["562500.SS"], "source": "auto"},
        result=_market_payload(),
        call_id="prices",
        success=True,
    )

    bad_math = ledger.validate_final_answer(
        "562500.SS（Yahoo，CNY）的推导买入价：(1.141 + 1.137) / 2 = 0.881。"
    )
    no_observed_input = ledger.validate_final_answer(
        "562500.SS（Yahoo，CNY）的推导买入价：(0.88 + 0.90) / 2 = 0.89。"
    )
    good = ledger.validate_final_answer(
        "562500.SS（Yahoo，CNY）的推导买入价：(1.141 + 1.137) / 2 = 1.139。"
    )
    missing_provenance = ledger.validate_final_answer(
        "2026-06-23 的已观测收盘价为 1.137。"
    )

    assert bad_math.valid is False
    assert no_observed_input.valid is False
    assert good.valid is True
    assert missing_provenance.valid is False
    assert {
        issue["code"] for issue in missing_provenance.issues
    } >= {
        "canonical_symbol_not_surfaced",
        "data_source_not_surfaced",
        "currency_not_surfaced",
    }


class _Response:
    def __init__(
        self,
        *,
        content: str = "",
        tool_calls: list[SimpleNamespace] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.reasoning_content = None
        self.has_tool_calls = bool(self.tool_calls)


class _CorrectingLLM:
    model_name = "grounding-test"

    def __init__(self) -> None:
        self.responses = [
            _Response(
                tool_calls=[
                    _tool_call("resolve", "search_symbol", query="机器人ETF"),
                    _tool_call(
                        "too-early",
                        "get_market_data",
                        codes=["562500.SH"],
                        start_date="2026-06-23",
                        end_date="2026-06-24",
                    ),
                ]
            ),
            _Response(
                tool_calls=[
                    _tool_call(
                        "prices",
                        "get_market_data",
                        codes=["562500.SS"],
                        start_date="2026-06-23",
                        end_date="2026-06-24",
                        source="auto",
                    )
                ]
            ),
            _Response(content="建议买入价为 0.881。"),
            _Response(
                content=(
                    "562500.SS（Yahoo，CNY）在 2026-06-23 的已观测收盘价为 1.137。"
                )
            ),
        ]
        self.messages_history: list[list[dict[str, Any]]] = []

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
        on_reasoning_chunk: Callable[[str], None] | None = None,
        timeout: int | None = None,
        idle_timeout_s: float | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> _Response:
        self.messages_history.append(list(messages))
        response = self.responses.pop(0)
        if response.content and on_text_chunk:
            on_text_chunk(response.content)
        return response

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> _Response:
        return _Response()


def test_agent_loop_rejects_then_corrects_ungrounded_final_answer(
    tmp_path: Path,
) -> None:
    """Rejected numeric drafts never become the returned or streamed answer."""
    resolver = _ResolverTool(_resolver_payload())
    market = _MarketTool(_market_payload())
    registry = ToolRegistry()
    registry.register(resolver)
    registry.register(market)
    events: list[tuple[str, dict[str, Any]]] = []
    llm = _CorrectingLLM()
    agent = AgentLoop(
        registry=registry,
        llm=llm,
        max_iterations=4,
        event_callback=lambda event, data: events.append((event, data)),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)

    result = agent.run("请分析机器人ETF并给出买入价")

    assert result["status"] == "success"
    assert "1.137" in result["content"]
    assert "0.881" not in result["content"]
    assert market.calls == 1
    # The correction nudge must not be a mid-conversation system message.
    assert_system_messages_only_lead(llm.messages_history)
    streamed = "".join(
        data.get("delta", "") for event, data in events if event == "text_delta"
    )
    assert "0.881" not in streamed
    assert "1.137" in streamed
    completed_thinking = "".join(
        data.get("content", "")
        for event, data in events
        if event == "thinking_done"
    )
    assert "0.881" not in completed_thinking
    artifact = json.loads(
        (run_dir / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8")
    )
    assert artifact["validations"][0]["valid"] is False
    assert artifact["validations"][-1]["valid"] is True


_SHORTLIST_QUERY = "A股低价高增长股票"
_SHORTLIST_PAYLOAD = _resolver_payload(
    candidates=[
        {"symbol": "000543.SZ", "name": "皖能电力", "market": "cn", "source": "eastmoney"},
        {"symbol": "000727.SZ", "name": "冠捷科技", "market": "cn", "source": "eastmoney"},
    ],
    query=_SHORTLIST_QUERY,
)
_NARROWED_PAYLOAD = _resolver_payload(
    candidates=[
        {"symbol": "000543.SZ", "name": "皖能电力", "market": "cn", "source": "eastmoney"},
    ],
    query="000543.SZ",
)
_SCREENED_MARKET_PAYLOAD = json.dumps(
    {
        "000543.SZ": [
            {
                "trade_date": "2026-08-01",
                "open": 7.9,
                "high": 8.5,
                "low": 7.9,
                "close": 8.2,
                "volume": 100000,
            }
        ],
        "_provenance": {
            "000543.SZ": {
                "source": "tencent",
                "requested_source": "auto",
                "detected_source": "tencent",
                "fallback_used": False,
                "currency_conversion": "none",
            }
        },
    }
)


def _screened_ledger(tmp_path: Path) -> GroundingLedger:
    """Return a ledger that screened broadly, then locked one candidate."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="推荐A股低价高增长股票并给出买入价",
    )
    for call_id, query, payload in (
        ("shortlist", _SHORTLIST_QUERY, _SHORTLIST_PAYLOAD),
        ("narrow", "000543.SZ", _NARROWED_PAYLOAD),
    ):
        ledger.authorize_tool_call(
            "search_symbol",
            {"query": query},
            batch_authorized_symbols=ledger.authorized_symbols,
            call_id=call_id,
        )
        ledger.ingest_tool_result(
            tool_name="search_symbol",
            arguments={"query": query},
            result=payload,
            call_id=call_id,
            success=True,
        )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["000543.SZ"]},
        result=_SCREENED_MARKET_PAYLOAD,
        call_id="prices",
        success=True,
    )
    return ledger


def test_screening_shortlist_does_not_block_workflow_selection(tmp_path: Path) -> None:
    """A many-candidate screening result is an answer, not a stalled resolution (#955)."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="推荐A股低价高增长股票并给出买入价",
    )
    ledger.authorize_tool_call(
        "search_symbol",
        {"query": _SHORTLIST_QUERY},
        batch_authorized_symbols=ledger.authorized_symbols,
        call_id="shortlist",
    )
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": _SHORTLIST_QUERY},
        result=_SHORTLIST_PAYLOAD,
        call_id="shortlist",
        success=True,
    )

    assert ledger.identity_status == "ambiguous"
    skill = ledger.authorize_tool_call(
        "load_skill",
        {"name": "stock-selection"},
        batch_authorized_symbols=ledger.authorized_symbols,
        call_id="skill",
        batch_identity_status=ledger.identity_status,
    )

    assert skill.allowed is True


def test_narrowed_lock_retires_the_screening_shortlist(tmp_path: Path) -> None:
    """Locking a shortlisted candidate must unblock the run's final answer (#955)."""
    ledger = _screened_ledger(tmp_path)

    assert ledger.identity_status == "locked"
    assert ledger.authorized_symbols == {"000543.SZ"}
    prices = ledger.authorize_tool_call(
        "get_market_data",
        {"codes": ["000543.SZ"]},
        batch_authorized_symbols=ledger.authorized_symbols,
        call_id="prices",
        batch_identity_status=ledger.identity_status,
    )

    assert prices.allowed is True


def test_price_validation_ignores_symbol_date_and_quantity_digits(tmp_path: Path) -> None:
    """Ticker, calendar, holding-period, and position-cost digits are not prices (#955)."""
    ledger = _screened_ledger(tmp_path)

    for draft in (
        "000543.SZ 截至 8 月 3 日收盘价 8.20 CNY（source: tencent）",
        "000543.SZ 买入价 8.20 CNY（100 股成本 820 CNY；source: tencent）",
        "000543.SZ 建议持有 1–4 周，买入价 8.20 CNY（source: tencent）",
    ):
        result = ledger.validate_final_answer(draft)
        assert result.valid is True, (draft, result.issues)


def test_price_validation_still_rejects_a_quote_outside_observed_range(
    tmp_path: Path,
) -> None:
    """Masking non-price digits must not weaken the contradiction check (#955)."""
    ledger = _screened_ledger(tmp_path)

    result = ledger.validate_final_answer("000543.SZ 收盘价 42.00 CNY（source: tencent）")

    assert result.valid is False
    assert [issue["code"] for issue in result.issues] == ["numeric_claim_conflict"]


def test_price_validation_ignores_score_indicator_and_window_digits(
    tmp_path: Path,
) -> None:
    """Confidence scores, indicator readings, and lookback windows are not prices (#1001).

    A well-formed verdict line carries a conviction score, the moving-average
    windows it cites, and an oscillator reading. Compared against an OHLC range
    every one of them contradicts it, which rejected drafts that were correct.
    """
    ledger = _screened_ledger(tmp_path)

    for draft in (
        # The reported shape: a labelled score on a 1-10 scale.
        "000543.SZ VERDICT: FLAT CONFIDENCE: 6 REASON: 收盘价 8.20 CNY（source: tencent）",
        "000543.SZ CONFIDENCE: 6/10，收盘价 8.20 CNY（source: tencent）",
        # The hyphenated English compound the quantity mask used to stall on.
        "000543.SZ 现价 8.20 CNY 距 52-week high 有距离（source: tencent）",
        "000543.SZ 收盘价 8.20 CNY 低于其 20/50/200-day 均线（source: tencent）",
        # An indicator reading sharing a clause with a genuine quote.
        "000543.SZ 现价 8.20 CNY 而 RSI 46.7（source: tencent）",
    ):
        result = ledger.validate_final_answer(draft)
        assert result.valid is True, (draft, result.issues)


def test_price_validation_ignores_formula_variable_digits(tmp_path: Path) -> None:
    """A price word used as a formula variable is not an asserted price (#1354).

    The gate uses one structural rule, not a catalogue of phrasings: a number
    after a price word is a claimed value only when nothing formula-like sits
    between them. A closed marker set — comparison/division operators or an
    indicator identifier followed by digits — marks the number an operand; an
    observation binder ("was", "at", 报收/收于/…) after that marker re-attaches it
    to the price word, so "close above SMA50 and was 2500" stays a claim while
    "close/SMA50 > 1" claims nothing. An ASCII sentence boundary (" . ") ends
    the price word's reach, so a bare year two sentences later is not claimed.
    """
    ledger = _screened_ledger(tmp_path)

    for draft in (
        # Division + comparison: window and threshold, not a price.
        "000543.SZ close/SMA50 > 1 时买入（source: tencent）",
        # Signal value after a signal word / arrow / 触发.
        "000543.SZ close acima da EMA30 dispara sinal +1（source: tencent）",
        "000543.SZ close above EMA20 -> +1（source: tencent）",
        "000543.SZ 收盘价上穿MA20 触发 +1 信号（source: tencent）",
        # Plain comparison against a level, not a quote.
        "000543.SZ close > 1 时买入（source: tencent）",
        # Indicator reading with a directional connective.
        "000543.SZ close/SMA50 > 1 and RSI below 30（source: tencent）",
        # Colon after the signal word (ASCII '.' is not a clause separator,
        # so "Sinal: +1" can share a clause with the price word).
        "000543.SZ close acima da EMA30. Sinal: +1（source: tencent）",
        # Indicator identifier + digits between the price word and the number,
        # even when the operator is spelled out in prose.
        "000543.SZ close vs SMA20 maior que 1（source: tencent）",
        "000543.SZ close minus SMA20 fallen below 0（source: tencent）",
    ):
        result = ledger.validate_final_answer(draft)
        assert result.valid is True, (draft, result.issues)

    # Strict-narrowing bar: the formula language must not launder an observed
    # value. Verified adversarially; each shape stays a claim.
    for launder in (
        # no operator, no indicator digits: the plain claim
        "000543.SZ close was 2500（source: tencent）",
        # digit-carrying connector bridging to an indicator
        "000543.SZ close was 2500 and SMA50 2450（source: tencent）",
        # observation verb trailing the formula in the same clause
        "000543.SZ close above SMA50 and was 2500 yesterday（source: tencent）",
        # at-attached level trailing the formula
        "000543.SZ close above SMA50 at 2450（source: tencent）",
        # equality claim, not a formula
        "000543.SZ close = 2500（source: tencent）",
        # second price word after a comma stays gated
        "000543.SZ close above SMA50, and closed at 2500 yesterday（source: tencent）",
        # Chinese observation syntax
        "000543.SZ 收盘价报收 2500（source: tencent）",
        # multi-digit value after a signal word is a price, not a signal
        "000543.SZ close signal 2500（source: tencent）",
        # "above" with a price word is a claim, not an indicator reading
        "000543.SZ close above 2500（source: tencent）",
    ):
        result = ledger.validate_final_answer(launder)
        assert result.valid is False, launder
        assert "numeric_claim_conflict" in {issue["code"] for issue in result.issues}


def test_direct_price_values_structural_rule() -> None:
    """The structural rule decides operand vs. claim at the number level (#1354)."""
    extract = GroundingLedger._direct_price_values
    # Formula operands — a marker between the price word and the number.
    for text in (
        "close/SMA50 > 1.0",
        "close acima da EMA30 dispara sinal +1",
        "收盘价上穿MA20 触发 +1 信号",
        "close/SMA50 > 1 and RSI below 30",
        "close vs SMA20 maior que 1",
        "close minus SMA20 fallen below 0",
        # CJK-adjacent indicator (no ASCII space): the marker's \b must not
        # treat a CJK letter as a word character, or 上穿MA20 is invisible.
        "收盘价上穿SMA20 2500",
    ):
        assert extract(text) == [], text
    # Observed values — no marker, or an observation binder after the marker.
    assert extract("close was 2500") == [2500.0]
    assert extract("close above 2500") == [2500.0]
    assert extract("close = 2500") == [2500.0]
    assert extract("close above SMA50 and was 2500 yesterday") == [2500.0]
    assert extract("close above SMA50 at 2450") == [2450.0]
    assert extract("收盘价报收 2500") == [2500.0]
    # Sentence boundary: the price word cannot reach a later sentence.
    assert extract("close was 210. In 2024 the market rallied") == [210.0]
    assert extract("close. Sinal: 2500") == []


def test_price_validation_ignores_short_dates_and_percent_ranges(
    tmp_path: Path,
) -> None:
    """A year-less date and a percentage range are not prices (#983).

    Taken from the trace attached to #983: "8/5 收盘 5.97" contributed 8 and 5,
    and "1–2%" contributed its lower bound, because the percent tail check only
    masks the number the sign touches.
    """
    ledger = _screened_ledger(tmp_path)

    for draft in (
        "000543.SZ 8/5 收盘价 8.20 CNY（source: tencent）",
        "000543.SZ 现价 8.20 CNY，距阻力位仅 1–2%（source: tencent）",
        "000543.SZ 现价 8.20 CNY，距阻力位仅 1-2%（source: tencent）",
    ):
        result = ledger.validate_final_answer(draft)
        assert result.valid is True, (draft, result.issues)


def test_numbers_without_dates_or_percent_masks_cjk_glued_iso_dates() -> None:
    """An ISO date running into CJK text is one date, not three prices (#1122).

    ``\b`` is Unicode-aware, so CJK letters count as word characters and
    ``(2026-07-14最低)`` had no boundary after ``14`` -- the date survived and
    contributed 2026/7/14 as candidate prices. ``re.ASCII`` restores the byte
    boundary so the whole date masks while a genuine quote beside it stays.
    """
    assert (
        GroundingLedger._numbers_without_dates_or_percent("若跌破观测支撑位0.980 CNY (2026-07-14最低)")
        == []
    )
    assert (
        GroundingLedger._numbers_without_dates_or_percent("收盘价 8.20 CNY 自2026-07-14以来最低")
        == [8.2]
    )


def test_iso_date_running_into_cjk_text_is_still_masked(tmp_path: Path) -> None:
    """The end-to-end gate no longer rejects a correct report over a glued date (#1122)."""
    ledger = _screened_ledger(tmp_path)

    for draft in (
        "000543.SZ 收盘价 8.20 CNY（2026-07-14最低）（source: tencent）",
        "000543.SZ 收盘价 8.20 CNY 自2026-07-14以来最低（source: tencent）",
    ):
        result = ledger.validate_final_answer(draft)
        assert result.valid is True, (draft, result.issues)


def test_short_date_mask_does_not_swallow_a_plain_ratio(tmp_path: Path) -> None:
    """The month/day mask is bounded, so an ordinary ratio still reads (#983).

    "P/E 15" and the window enumeration "20/50/200-day" both contain slashes.
    Neither may be consumed as a date, or the mask would hide real figures.
    """
    ledger = _screened_ledger(tmp_path)

    result = ledger.validate_final_answer("000543.SZ 收盘价 42.00 CNY，P/E 15（source: tencent）")

    assert result.valid is False
    assert [issue["code"] for issue in result.issues] == ["numeric_claim_conflict"]
    assert [issue["value"] for issue in result.issues] == [42.0]


def test_masked_window_does_not_shield_a_wrong_quote_in_the_same_clause(
    tmp_path: Path,
) -> None:
    """The new masks are span-local: a bad quote beside one is still caught (#1001).

    This is the lower side of the guard. Masking ``52-week`` must remove only
    the window length; a contradicted price in the same clause has to survive
    the mask and reject the draft, or the fix would have bought precision by
    silencing the check it exists to run.
    """
    ledger = _screened_ledger(tmp_path)

    for draft in (
        "000543.SZ 52-week high 之下，收盘价 42.00 CNY（source: tencent）",
        "000543.SZ CONFIDENCE: 6 REASON: 收盘价 42.00 CNY（source: tencent）",
        "000543.SZ RSI 46.7，收盘价 42.00 CNY（source: tencent）",
    ):
        result = ledger.validate_final_answer(draft)
        assert result.valid is False, draft
        assert [issue["code"] for issue in result.issues] == ["numeric_claim_conflict"], draft


def test_screening_run_reaches_a_final_answer_through_the_agent_loop(
    tmp_path: Path,
) -> None:
    """End-to-end: screen, load a workflow skill, narrow, quote, and answer (#955)."""
    agent, resolver, market, skill, trace = _build_direct_agent(tmp_path, _SHORTLIST_PAYLOAD)
    market.result = _SCREENED_MARKET_PAYLOAD
    agent._grounding = GroundingLedger(
        run_dir=Path(agent.memory.run_dir),
        user_message="推荐A股低价高增长股票并给出买入价",
    )
    messages: list[dict[str, Any]] = []
    react_trace: list[dict[str, Any]] = []

    def batch(*calls: SimpleNamespace, iteration: int) -> None:
        agent._process_tool_calls(
            list(calls), ContextBuilder, messages, trace, react_trace, iteration
        )

    batch(_tool_call("shortlist", "search_symbol", query=_SHORTLIST_QUERY), iteration=1)
    batch(_tool_call("workflow", "load_skill", name="stock-selection"), iteration=2)
    assert skill.calls == 1

    resolver.result = _NARROWED_PAYLOAD
    batch(_tool_call("narrow", "search_symbol", query="000543.SZ"), iteration=3)
    batch(_tool_call("prices", "get_market_data", codes=["000543.SZ"]), iteration=4)
    trace.close()

    assert market.calls == 1
    validation = agent._grounding.validate_final_answer(
        "000543.SZ 买入价 8.20 CNY（100 股成本 820 CNY；source: tencent）"
    )
    assert validation.valid is True, validation.issues


def test_price_table_with_a_year_less_date_matches_its_evidence(tmp_path: Path) -> None:
    """A table dated ``08-01`` must find the evidence stamped ``2026-08-01`` (#983).

    The date filter was ``timestamp.startswith(date_value)``, which can only
    succeed when the answer repeats the year. A report writing the trading day
    the ordinary way matched nothing, so every cell in the row came back as
    having no supporting evidence — 79 such rejections in the trace attached to
    #983, every value sitting inside the observed range.
    """
    ledger = _screened_ledger(tmp_path)

    for date_cell in ("08-01", "8/1", "8月1日", "2026-08-01"):
        draft = (
            "000543.SZ 行情（source: tencent; currency: CNY）\n\n"
            "| 日期 | 开盘 | 最高 | 最低 | 收盘 |\n"
            "| --- | --- | --- | --- | --- |\n"
            f"| {date_cell} | 7.90 | 8.50 | 7.90 | 8.20 |\n"
        )
        result = ledger.validate_final_answer(draft)
        assert result.valid is True, (date_cell, result.issues)


def test_year_less_date_still_rejects_a_wrong_quote(tmp_path: Path) -> None:
    """Matching the day must not stop the value from being checked (#983).

    Resolving the date is what lets the comparison happen at all; it must not
    become a way to pass without one.
    """
    ledger = _screened_ledger(tmp_path)

    draft = (
        "000543.SZ 行情（source: tencent; currency: CNY）\n\n"
        "| 日期 | 开盘 | 最高 | 最低 | 收盘 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 08-01 | 7.90 | 8.50 | 7.90 | 42.00 |\n"
    )
    result = ledger.validate_final_answer(draft)

    assert result.valid is False
    assert "numeric_claim_conflict" in {issue["code"] for issue in result.issues}


def test_a_date_that_names_a_different_day_is_still_unavailable(tmp_path: Path) -> None:
    """Loosening the year must not collapse distinct trading days together."""
    ledger = _screened_ledger(tmp_path)

    draft = (
        "000543.SZ 行情（source: tencent; currency: CNY）\n\n"
        "| 日期 | 开盘 | 最高 | 最低 | 收盘 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 07-15 | 7.90 | 8.50 | 7.90 | 8.20 |\n"
    )
    result = ledger.validate_final_answer(draft)

    assert result.valid is False
    assert "numeric_claim_unavailable" in {issue["code"] for issue in result.issues}


# ---------------------------------------------------------------------------
# #983: a trading plan quotes levels it does not claim to have observed.
#
# The committee report attached to that issue was refused for its own entry
# triggers and target zones. With no price evidence yet in the parent session
# they came back as numeric_claim_unavailable; once the run fetched prices the
# same numbers came back as numeric_claim_conflict. One false positive, two
# codes.
# ---------------------------------------------------------------------------

_PLAN_LEVELS_FROM_983 = [
    "- **转多信号：** 收盘 ≥6.45 且量 ≥35M手",
    "- **转空强化：** 收盘 <5.36 且 3 日不收复 → 年线 4.63 成目标区",
    "| B 破位空 | 任意收盘 <5.36 | 收盘 ≥5.75 且量 ≥20M手 |",
    "目标位 6.80，止损 5.20",
    "若收盘 5.36 则减仓",
    "target price 6.80 with stop-loss 5.20",
]


@pytest.mark.parametrize("segment", _PLAN_LEVELS_FROM_983, ids=range(len(_PLAN_LEVELS_FROM_983)))
def test_plan_levels_are_not_read_as_observed_price_claims(segment: str) -> None:
    """A trigger, a target and a hypothesis assert nothing about observed data."""
    assert GroundingLedger._numbers_without_dates_or_percent(segment) == []


# The other side of the same guard. Every entry here is an assertion about what
# the instrument did, and each must survive the mask above — otherwise the
# relaxation is a way to state a price without being checked.
_ASSERTIONS_THAT_MUST_STAY_CHECKED = [
    ("8/5 收盘 5.97", [5.97]),
    ("现价 5.97", [5.97]),
    ("收盘价为 6.03", [6.03]),
    ("the close was 6.03", [6.03]),
    # Span-local: the target is masked, the quote beside it is not.
    ("现价 5.97，目标位 6.45", [5.97]),
    # A conditional opener must not reach back over a quote already made.
    ("收盘 6.03，若跌破 5.36 减仓", [6.03]),
    ("开盘 6.80 最高 7.18 最低 6.68", [6.80, 7.18, 6.68]),
]


@pytest.mark.parametrize(
    "segment,expected",
    _ASSERTIONS_THAT_MUST_STAY_CHECKED,
    ids=[c[0][:24] for c in _ASSERTIONS_THAT_MUST_STAY_CHECKED],
)
def test_plan_level_mask_leaves_observed_quotes_checked(
    segment: str, expected: list[float],
) -> None:
    assert GroundingLedger._numbers_without_dates_or_percent(segment) == expected


# A currency token between the anchor and the number used to break every
# prospective branch: "收盘 <$2.86" left 2.86 to be compared against observed
# OHLC, "目标位 $6.80" left 6.8, and "trigger at $119.68" left 119.68. These
# are levels, not observed quotes, so each must mask entirely.
_CURRENCY_PREFIXED_PLAN_LEVELS = [
    "收盘 <$2.86",
    "目标位 $6.80，止损位 C$5.20",
    "trigger at $119.68",
    "支撑位 $190.12",
    "target price of $6.80",
    "收盘 ≥ $135 且低点 > $119.68",
]


@pytest.mark.parametrize(
    "segment", _CURRENCY_PREFIXED_PLAN_LEVELS, ids=range(len(_CURRENCY_PREFIXED_PLAN_LEVELS))
)
def test_currency_prefixed_plan_levels_are_not_read_as_observed_prices(segment: str) -> None:
    """A currency-prefixed trigger or target is prospective, not observed."""
    assert GroundingLedger._numbers_without_dates_or_percent(segment) == []


# A historical reference names a price the instrument once traded at. The
# SPCX.US weekly plan quoted "6/16 ATH 225.64" next to the 8/12 high 149.60;
# 225.64 fell outside the session's observed OHLC range (105.11–149.6) and was
# rejected as a conflict even though it is a reference, not a current quote.
_REFERENCE_LEVEL_SEGMENTS = [
    ("8/12 高 149.60 为 6/16 ATH 225.64 以来最高", [149.60]),
    ("8/12 高 149.60 为 6/16 历史高点 225.64 以来最高", [149.60]),
    ("8/12 高 149.60 为 6/16 all-time high 225.64 以来最高", [149.60]),
    ("52W 高 543.14", []),
    ("52-week low of $190.12", []),
    ("52W low (C$7.27)", []),
    ("历史最低 $60.82", []),
    ("ATH (C$7.31)", []),
]


@pytest.mark.parametrize(
    "segment,expected",
    _REFERENCE_LEVEL_SEGMENTS,
    ids=[c[0][:28] for c in _REFERENCE_LEVEL_SEGMENTS],
)
def test_reference_levels_are_not_read_as_observed_price_claims(
    segment: str, expected: list[float],
) -> None:
    """An ATH/52-week/historical extreme is a reference, not a current quote."""
    assert GroundingLedger._numbers_without_dates_or_percent(segment) == expected


# A validation report cites a plan file by line number ("~line 206",
# "第 206 行"). The number is a document location, not a price, and was
# compared against observed OHLC as a claim before this mask existed.
_LINE_REFERENCE_SEGMENTS = [
    "**文档 ~line 206「8/12 高 149.60 为 6/16 ATH 225.64 以来最高」不成立",
    "line 206",
    "lines 206-208",
    "第 206 行",
    "第 206–208 行",
    "行 206",
]


@pytest.mark.parametrize(
    "segment", _LINE_REFERENCE_SEGMENTS, ids=range(len(_LINE_REFERENCE_SEGMENTS))
)
def test_line_number_references_are_not_read_as_price_claims(segment: str) -> None:
    """A line citation is a document location, not an observed price."""
    if segment.startswith("**文档"):
        # The quoted 149.60 beside the line citation stays checked.
        assert GroundingLedger._numbers_without_dates_or_percent(segment) == [149.6]
    else:
        assert GroundingLedger._numbers_without_dates_or_percent(segment) == []


# Validation summaries count findings: "1 项事实错误", "2 项不一致", and
# "16 个交易日" are count nouns, not prices. The count survived extraction
# and was rejected against the observed OHLC range before 项/个交易日 joined
# the quantity units.
_COUNT_NOUN_SEGMENTS = [
    ("- ❌ **1 项事实错误**:", []),
    ("⚠️ **2 项不一致**", []),
    ("3 项", []),
    ("16 个交易日", []),
    # 149.60 is masked here too: "高点高于 149.60" is a comparison level.
    ("6/17–7/10 有 16 个交易日高点高于 149.60", []),
]


@pytest.mark.parametrize(
    "segment,expected",
    _COUNT_NOUN_SEGMENTS,
    ids=[c[0][:22] for c in _COUNT_NOUN_SEGMENTS],
)
def test_count_nouns_are_not_read_as_price_claims(
    segment: str, expected: list[float],
) -> None:
    """项/个交易日 counts are quantities, not prices."""
    assert GroundingLedger._numbers_without_dates_or_percent(segment) == expected


_SINCE_REFERENCE_SEGMENTS = [
    ("正确为 7/10(150.57)以来最高", []),
    ("收 146.15 为 7/9(收 152.16)以来最高", [146.15]),
    ("highest since 7/10 (150.57)", []),
    # The current bar's own high is not a since-reference and stays checked.
    ("8/12 高 149.60 为 6/16 ATH 225.64 以来最高", [149.6]),
]


@pytest.mark.parametrize(
    "segment,expected",
    _SINCE_REFERENCE_SEGMENTS,
    ids=[c[0][:24] for c in _SINCE_REFERENCE_SEGMENTS],
)
def test_since_references_are_not_read_as_observed_price_claims(
    segment: str, expected: list[float],
) -> None:
    """A date-anchored "highest since" value is a reference, not a quote."""
    assert GroundingLedger._numbers_without_dates_or_percent(segment) == expected


_NUMBERED_HEADING_SEGMENTS = [
    "### 6. 关键价位/旁证核验",
    "## 12. 结论",
    "# 3. 身份与数据源",
    "### 8/13 周中判定",
    # The section number masks; the observed quote beside it stays checked.
    ("### 6. 8/12 高 149.60 为 6/16 ATH 以来最高", [149.6]),
]


@pytest.mark.parametrize(
    "segment", _NUMBERED_HEADING_SEGMENTS, ids=range(len(_NUMBERED_HEADING_SEGMENTS))
)
def test_numbered_headings_are_not_read_as_price_claims(segment: str) -> None:
    """A markdown heading number is a section index, not a price."""
    if isinstance(segment, tuple):
        segment, expected = segment
        assert GroundingLedger._numbers_without_dates_or_percent(segment) == expected
    else:
        assert GroundingLedger._numbers_without_dates_or_percent(segment) == []


_RATIO_AND_FX_SEGMENTS = [
    ("TO 报价实际是按 6:1 平价锚定的", []),
    ("25/25 行 OHLCV、25/25 项派生百分比、7/7 日 CDR 6:1 折算", []),
    ("远小于当前 USD/CAD≈1.36 的量级", []),
    ("汇率 1.36", []),
    # `EUR/USD` is this project's canonical forex symbol, so an asserted pair
    # rate is a quote and stays checked; only an approximated conversion basis
    # is masked. Masking both would let an invented FX rate through the gate.
    ("usd/cad=1.36", [1.36]),
    ("USD/CAD 1.36", [1.36]),
    ("USD/CAD ≈ 1.36", []),
]


@pytest.mark.parametrize(
    "segment,expected",
    _RATIO_AND_FX_SEGMENTS,
    ids=[c[0][:24] for c in _RATIO_AND_FX_SEGMENTS],
)
def test_ratios_and_fx_rates_are_not_read_as_price_claims(
    segment: str, expected: list[float],
) -> None:
    """A conversion ratio or forex rate is not an instrument quote."""
    assert GroundingLedger._numbers_without_dates_or_percent(segment) == expected


def test_plan_level_mask_does_not_shield_a_wrong_quote_end_to_end(tmp_path: Path) -> None:
    """The end-to-end gate still rejects a fabricated quote beside a plan level."""
    ledger = _screened_ledger(tmp_path)

    result = ledger.validate_final_answer(
        "000543.SZ 收盘价 42.00 CNY，目标位 45.00（source: tencent）"
    )

    assert result.valid is False
    assert "numeric_claim_conflict" in {issue["code"] for issue in result.issues}


def test_plan_level_alone_reaches_a_valid_answer(tmp_path: Path) -> None:
    """A plan stated without quoting an observed price passes the numeric gate."""
    ledger = _screened_ledger(tmp_path)

    result = ledger.validate_final_answer(
        "000543.SZ 收盘价 8.20 CNY（source: tencent）。"
        "转多信号：收盘 ≥9.10；转空强化：收盘 <7.40 且 3 日不收复 → 目标位 6.90。"
    )

    assert result.valid is True, result.issues


def _spcx_us_ledger(tmp_path: Path) -> GroundingLedger:
    """A ledger that locked SPCX.US and observed 8/7–8/12 OHLC bars."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="以 SPCX.US（纳斯达克，SpaceX 本体）作为美股侧参考",
    )
    query = "SPCX.US"
    ledger.authorize_tool_call(
        "search_symbol",
        {"query": query},
        batch_authorized_symbols=ledger.authorized_symbols,
        call_id="resolve",
    )
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": query},
        result=_resolver_payload(symbol="SPCX.US", query=query),
        call_id="resolve",
        success=True,
    )
    payload = json.dumps(
        {
            "SPCX.US": [
                {
                    "trade_date": "2026-08-07",
                    "open": 114.97,
                    "high": 133.48,
                    "low": 114.53,
                    "close": 133.11,
                    "volume": 242130700,
                },
                {
                    "trade_date": "2026-08-10",
                    "open": 134.95,
                    "high": 139.26,
                    "low": 130.17,
                    "close": 138.74,
                    "volume": 169934300,
                },
                {
                    "trade_date": "2026-08-11",
                    "open": 138.66,
                    "high": 139.98,
                    "low": 130.50,
                    "close": 133.29,
                    "volume": 108900600,
                },
                {
                    "trade_date": "2026-08-12",
                    "open": 135.05,
                    "high": 149.60,
                    "low": 134.01,
                    "close": 146.15,
                    "volume": 165771792,
                },
            ],
            "_provenance": {
                "SPCX.US": {
                    "source": "yahoo",
                    "requested_source": "auto",
                    "detected_source": "yahoo",
                    "fallback_used": False,
                    "currency_conversion": "none",
                }
            },
        },
        ensure_ascii=False,
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["SPCX.US"]},
        result=payload,
        call_id="prices",
        success=True,
    )
    return ledger


def test_reference_level_and_currency_thresholds_pass_end_to_end(tmp_path: Path) -> None:
    """The SPCX.US verdict prose passes once references and thresholds mask."""
    ledger = _spcx_us_ledger(tmp_path)

    result = ledger.validate_final_answer(
        "SPCX.US 8/10 收 138.74 USD、8/12 高 149.60 USD（source: yahoo）。"
        "8/12 高 149.60 为 6/16 ATH 225.64 以来最高；"
        "8/10 收盘 138.74 ≥ $135 且 ≥ $119.68 触发成立。"
    )

    assert result.valid is True, result.issues


def test_validation_summary_with_counts_and_line_cites_passes_end_to_end(
    tmp_path: Path,
) -> None:
    """A validation verdict naming counts and line citations passes the gate."""
    ledger = _spcx_us_ledger(tmp_path)

    result = ledger.validate_final_answer(
        "SPCX.US 核验(USD, source: yahoo):❌ 1 项事实错误 — "
        "文档 ~line 206「8/12 高 149.60 为 6/16 ATH 以来最高」不成立,"
        "6/17–7/10 有 16 个交易日高点高于 149.60,正确为 7/10(150.57)以来最高。"
    )

    assert result.valid is True, result.issues


def _shanghai_shortlist() -> str:
    """One Shanghai listing as the two sources actually publish it."""
    return _resolver_payload(
        candidates=[
            {
                "symbol": "600519.SH",
                "name": "贵州茅台",
                "market": "cn",
                "type": "沪A",
                "source": "eastmoney",
            },
            {
                "symbol": "600519.SS",
                "name": "Kweichow Moutai Co Ltd",
                "market": "cn",
                "type": "EQUITY",
                "source": "yahoo",
            },
        ],
        query="600519",
    )


def test_shanghai_ticker_resolves_to_one_locked_identity(tmp_path: Path) -> None:
    """Eastmoney's .SH and Yahoo's .SS describe one listing, so one lock."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="600519 现价多少")
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "600519"},
        result=_shanghai_shortlist(),
        call_id="resolve",
        success=True,
    )

    assert ledger.identity_status == "locked"
    assert ledger.authorized_symbols == {"600519.SH"}


def test_shanghai_lock_depends_on_symbol_canonicalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation guard: drop canonicalization and Shanghai dead-ends again."""
    monkeypatch.setattr(
        "src.agent.grounding._normalize_symbol",
        lambda value: str(value or "").strip().upper(),
    )
    ledger = GroundingLedger(run_dir=tmp_path, user_message="600519 现价多少")
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "600519"},
        result=_shanghai_shortlist(),
        call_id="resolve",
        success=True,
    )

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_zero_candidates_with_a_skipped_source_are_not_found(tmp_path: Path) -> None:
    """A source that cannot serve the query shape does not block the answer.

    The counterpart — a source that actually failed — is covered by
    ``test_single_clean_not_found_source_is_not_enough_for_private_routing``,
    which must keep reporting ``invalidated``.
    """
    ledger = GroundingLedger(run_dir=tmp_path, user_message="这家公司现在股价多少")
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "某某不存在公司"},
        result=json.dumps(
            {
                "ok": True,
                "source": "symbol_search",
                "data": {
                    "query": "某某不存在公司",
                    "count": 0,
                    "candidates": [],
                    "sources": {
                        "eastmoney": "ok",
                        "yahoo": "skipped: non-ASCII query is not supported",
                    },
                },
            },
            ensure_ascii=False,
        ),
        call_id="resolve",
        success=True,
    )

    assert ledger.identity_status == "not_found"
    assert ledger.validate_final_answer("没有查到这家公司，无法给出结论。").valid is True


def test_a_failed_side_query_does_not_retract_a_locked_identity(
    tmp_path: Path,
) -> None:
    """One flaky resolver call must not end the run's ability to answer."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="茅台现价多少")
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "茅台"},
        result=json.dumps({"ok": False, "error": "timeout"}),
        call_id="flaky",
        success=False,
    )
    assert ledger.identity_status == "invalidated"

    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "贵州茅台"},
        result=_resolver_payload("600519.SH", query="贵州茅台"),
        call_id="retry",
        success=True,
    )

    assert ledger.identity_status == "locked"
    assert ledger.authorize_tool_call(
        "get_market_data",
        {"codes": ["600519.SH"]},
        batch_authorized_symbols=ledger.authorized_symbols,
        batch_identity_status=ledger.identity_status,
        call_id="prices",
    ).allowed is True


def test_a_conflict_outranks_a_lock_from_another_query(tmp_path: Path) -> None:
    """A contradiction is a fact about the data, so a lock cannot mask it."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="对比 600519.SH 和 AAPL.US 的现价",
    )
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "600519.SH"},
        result=_resolver_payload("600519.SZ", query="600519.SH"),
        call_id="venue-swap",
        success=True,
    )

    assert ledger.identity_status == "conflicting"


def _cny_ledger(tmp_path: Path) -> GroundingLedger:
    """A ledger holding one Shanghai quote sourced from yahoo, priced in CNY."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="562500.SH 现价多少")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["562500.SH"]},
        result=_market_payload(),
        call_id="prices",
        success=True,
    )
    return ledger


def test_a_chinese_answer_may_name_its_source_and_currency_in_chinese(
    tmp_path: Path,
) -> None:
    """The answer follows the user's language; the gate must read that language."""
    result = _cny_ledger(tmp_path).validate_final_answer(
        "562500.SH 最新收盘价 1.171 元，数据来源：雅虎财经。"
    )

    assert result.valid is True, result.issues


def test_another_currencys_yuan_does_not_satisfy_a_cny_requirement(
    tmp_path: Path,
) -> None:
    """A bare 元 counts for CNY only when no other currency's character owns it."""
    result = _cny_ledger(tmp_path).validate_final_answer(
        "562500.SH 最新收盘价 1.171 港元，数据来源：雅虎财经。"
    )

    assert result.valid is False
    assert "currency_not_surfaced" in {issue["code"] for issue in result.issues}


def test_an_unnamed_source_is_still_reported(tmp_path: Path) -> None:
    """Accepting a localized provider name is not accepting no provider name."""
    result = _cny_ledger(tmp_path).validate_final_answer("562500.SH 最新收盘价 1.171 元。")

    assert result.valid is False
    assert "data_source_not_surfaced" in {issue["code"] for issue in result.issues}


def _comparison_ledger(tmp_path: Path) -> GroundingLedger:
    """A ledger holding quotes for two instruments, as a comparison run does."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="对比 562500.SH 与 AAPL.US 现价",
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["562500.SH"]},
        result=_market_payload(),
        call_id="cn-prices",
        success=True,
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["AAPL.US"]},
        result=_market_payload("AAPL.US"),
        call_id="us-prices",
        success=True,
    )
    return ledger


def test_a_comparison_naming_its_subject_by_name_is_valid(tmp_path: Path) -> None:
    """Prose that identifies its subject in words must not be refused."""
    result = _comparison_ledger(tmp_path).validate_final_answer(
        "## 562500.SH vs AAPL.US（来源 yahoo）\n"
        "562500.SH 收盘价 1.171 元。\n"
        "苹果的收盘价是 1.171 美元，两者收在同一水平。"
    )

    assert result.valid is True, result.issues


def test_a_comparison_with_an_invented_quote_is_still_rejected(
    tmp_path: Path,
) -> None:
    """Checking against the union of observed quotes is not checking nothing."""
    result = _comparison_ledger(tmp_path).validate_final_answer(
        "## 562500.SH vs AAPL.US（来源 yahoo）\n"
        "562500.SH 收盘价 1.171 元。\n"
        "苹果的收盘价是 999.99 美元。"
    )

    assert result.valid is False
    assert {"numeric_claim_conflict", "numeric_claim_unavailable"} & {
        issue["code"] for issue in result.issues
    }


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        (
            "什么是市盈率估值法？请解释一下原理",
            "市盈率是市值与净利润的比值，用于横向比较同行业公司的相对贵贱。",
        ),
        (
            "explain how to trade using RSI",
            "RSI above 70 is conventionally read as overbought, below 30 as oversold.",
        ),
    ],
)
def test_a_conceptual_question_reaches_its_answer(
    tmp_path: Path,
    question: str,
    answer: str,
) -> None:
    """A run that never named an instrument has no identity to get wrong.

    The trigger phrase is matched against the user message, so these questions
    demanded a locked identity that no correct answer could ever supply.
    """
    ledger = GroundingLedger(run_dir=tmp_path, user_message=question)

    assert ledger.validate_final_answer(answer).valid is True


@pytest.mark.parametrize(
    "answer",
    [
        "贵州茅台现价约 1300 元，建议买入。",
        "600519.SH 收盘价 1300.00 元（source: tencent），建议买入。",
    ],
)
def test_an_unevidenced_price_is_still_rejected_without_any_tool_call(
    tmp_path: Path,
    answer: str,
) -> None:
    """Relaxing the identity check must not license a remembered quote."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="茅台适合买入吗")

    result = ledger.validate_final_answer(answer)

    assert result.valid is False
    assert {"numeric_claim_unavailable", "unsourced_symbol_figures"} & {
        issue["code"] for issue in result.issues
    }


@pytest.mark.parametrize(
    ("draft", "paren_width"),
    [
        ("同期五粮液（000858.SZ）收 168.50 元。", "full-width"),
        ("同期五粮液(000858.SZ)收 168.50 元。", "half-width"),
    ],
)
def test_fullwidth_parentheses_do_not_split_symbol_from_figure(
    tmp_path: Path,
    draft: str,
    paren_width: str,
) -> None:
    """#1260: 公司名（代码）价格 must stay in one clause for the gate.

    Full-width （） were treated as clause separators, so the symbol landed in
    one segment and the figure in the next and the unsourced-symbol gate
    never saw them together — a false negative that flipped on parenthesis
    width alone. Both widths must fire now; the half-width form is the
    control that already passed.
    """
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="What is Kweichow Moutai (600519.SH) trading at this week?",
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={
            "codes": ["600519.SH"],
            "start_date": "2026-08-24",
            "end_date": "2026-08-28",
            "source": "baostock",
        },
        result=json.dumps(
            {
                "600519.SH": [
                    {
                        "trade_date": "2026-08-28T00:00:00",
                        "open": 1289.0,
                        "high": 1297.89,
                        "low": 1288.0,
                        "close": 1297.4,
                        "volume": 16126.11,
                    }
                ],
                "_provenance": {
                    "600519.SH": {
                        "source": "baostock",
                        "fallback_used": False,
                        "currency_conversion": "none",
                        "volume_unit": "lots",
                    }
                },
            }
        ),
        call_id="c1",
        success=True,
    )

    issues = [
        issue
        for issue in ledger.validate_final_answer(draft).issues
        if issue.get("code") == "unsourced_symbol_figures"
    ]

    assert issues, f"{paren_width} parentheses must fire unsourced_symbol_figures"
    # Pin the offending symbol, not just "some issue fired": the gate must
    # blame the unsourced 000858.SZ, not the sourced 600519.SH.
    assert [issue["symbol"] for issue in issues] == ["000858.SZ"]


def test_unsourced_symbol_without_a_figure_stays_silent(tmp_path: Path) -> None:
    """#1260 guard arm: figure co-presence is what the gate checks.

    The regression test above pins that the gate fires when symbol and figure
    share a clause. This arm pins the inverse: an unsourced symbol with NO
    nearby figure must not fire unsourced_symbol_figures, so the gate's
    figure-presence guard (_numbers_without_dates_or_percent) cannot be
    dropped without this test failing.
    """
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="What is Kweichow Moutai (600519.SH) trading at this week?",
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={
            "codes": ["600519.SH"],
            "start_date": "2026-08-24",
            "end_date": "2026-08-28",
            "source": "baostock",
        },
        result=json.dumps(
            {
                "600519.SH": [
                    {
                        "trade_date": "2026-08-28T00:00:00",
                        "open": 1289.0,
                        "high": 1297.89,
                        "low": 1288.0,
                        "close": 1297.4,
                        "volume": 16126.11,
                    }
                ],
                "_provenance": {
                    "600519.SH": {
                        "source": "baostock",
                        "fallback_used": False,
                        "currency_conversion": "none",
                        "volume_unit": "lots",
                    }
                },
            }
        ),
        call_id="c1",
        success=True,
    )

    issues = [
        issue
        for issue in ledger.validate_final_answer(
            "同期五粮液（000858.SZ）是知名白酒企业。"
        ).issues
        if issue.get("code") == "unsourced_symbol_figures"
    ]

    assert issues == []


def test_a_shortlist_answers_the_user_but_still_cannot_fetch_a_quote(
    tmp_path: Path,
) -> None:
    """#955 closed half of this: the skill loaded, the answer stayed blocked."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="推荐几只低估值的高股息A股")
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "高股息"},
        result=_resolver_payload(
            candidates=[
                {"symbol": "601398.SH", "name": "工商银行", "source": "eastmoney"},
                {"symbol": "600028.SH", "name": "中国石化", "source": "eastmoney"},
            ],
            query="高股息",
        ),
        call_id="screen",
        success=True,
    )

    assert ledger.identity_status == "ambiguous"
    assert ledger.validate_final_answer(
        "候选清单命中多个标的，请确认你要看哪一只，我再去取行情。"
    ).valid is True
    assert ledger.authorize_tool_call(
        "get_market_data",
        {"codes": ["601398.SH"]},
        batch_authorized_symbols=ledger.authorized_symbols,
        batch_identity_status=ledger.identity_status,
        call_id="prices",
    ).allowed is False


def _large_cap_ledger(tmp_path: Path) -> GroundingLedger:
    """A ledger holding a quote large enough to be written with separators."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="600519.SH 收盘价多少")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["600519.SH"]},
        result=json.dumps(
            {
                "600519.SH": [
                    {
                        "trade_date": "2026-08-07",
                        "open": 1308.66,
                        "high": 1315.28,
                        "low": 1301.00,
                        "close": 1309.22,
                        "volume": 24976.0,
                    }
                ],
                "_provenance": {
                    "600519.SH": {
                        "source": "tencent",
                        "requested_source": "auto",
                        "currency_conversion": "none",
                    }
                },
            }
        ),
        call_id="prices",
        success=True,
    )
    return ledger


def test_a_grouped_price_is_not_split_into_a_bogus_claim(tmp_path: Path) -> None:
    """"¥1,309.22" must stay one number when the clause is split.

    The comma is both a clause separator and a thousands separator, and the
    split ran first, leaving a clause ending in "¥1". That 1 was compared
    against the observed 1300.01–1363.35 range and rejected — which is every
    price above 999 written the ordinary way.
    """
    result = _large_cap_ledger(tmp_path).validate_final_answer(
        "贵州茅台 600519.SH 最近一个交易日的收盘价为 ¥1,309.22，数据来源：腾讯行情。"
    )

    assert result.valid is True, result.issues


def test_a_grouped_price_that_contradicts_evidence_is_still_rejected(
    tmp_path: Path,
) -> None:
    """Keeping the group together is not the same as skipping the check."""
    result = _large_cap_ledger(tmp_path).validate_final_answer(
        "贵州茅台 600519.SH 最近一个交易日的收盘价为 ¥1,888.88，数据来源：腾讯行情。"
    )

    assert result.valid is False
    assert "numeric_claim_conflict" in {issue["code"] for issue in result.issues}


def test_a_clause_comma_still_separates_clauses(tmp_path: Path) -> None:
    """Only a real thousands group is protected, not every comma."""
    result = _large_cap_ledger(tmp_path).validate_final_answer(
        "600519.SH 数据来源：腾讯行情, 收盘价 ¥1,888.88 元。"
    )

    assert result.valid is False
    assert "numeric_claim_conflict" in {issue["code"] for issue in result.issues}


@pytest.mark.parametrize("query", ["贵州茅台", "ZZZZ.V"])
def test_every_resolver_skip_marker_is_understood_as_a_non_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
) -> None:
    """Lock the cross-module contract for "this source cannot serve this query".

    The resolver skips Yahoo for a non-ASCII query and Eastmoney for a Canadian
    one. This ledger recognizes a non-failure only by the status prefix, so a
    second spelling on the tool side silently turns "not listed" into a blocking
    ``invalidated`` identity — which is exactly what an "unsupported: ..." status
    did before the two were unified.
    """
    from src.tools import symbol_search_tool as resolver

    monkeypatch.setattr(resolver.eastmoney_client, "get_json", lambda *a, **k: {})
    monkeypatch.setattr(resolver.yahoo_client, "search", lambda *a, **k: [])

    result = resolver.SymbolSearchTool().execute(query=query)
    statuses = json.loads(result)["data"]["sources"]
    assert any(value.startswith("skipped:") for value in statuses.values()), statuses

    ledger = GroundingLedger(run_dir=tmp_path, user_message="这家公司现在股价多少")
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": query},
        result=result,
        call_id="resolve",
        success=True,
    )

    assert ledger.identity_status == "not_found"
    assert ledger.validate_final_answer("没有查到这家公司，无法给出结论。").valid is True


@pytest.mark.parametrize(
    ("symbol", "written"),
    [("562500.SH", "¥1.171"), ("PDI.TO", "C$1.171")],
)
def test_a_currency_symbol_counts_as_naming_the_currency(
    tmp_path: Path,
    symbol: str,
    written: str,
) -> None:
    """A model writes a quote as ¥ or C$, not as the ISO code."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message=f"{symbol} 现价多少")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": [symbol]},
        result=_market_payload(symbol),
        call_id="prices",
        success=True,
    )

    result = ledger.validate_final_answer(
        f"{symbol} 最新收盘价 {written}，数据来源：雅虎财经。"
    )

    assert result.valid is True, result.issues


def test_price_validation_ignores_markdown_ordered_list_markers(
    tmp_path: Path,
) -> None:
    """Line-leading ordered-list numbers are prose, not prices (#BUGS-1).

    A verdict written as a numbered Markdown list ("1. **原料药价格持续低迷**")
    must not let the marker "1." be parsed as a float and rejected against the
    observed OHLC range as a numeric_claim_conflict.
    """
    ledger = _screened_ledger(tmp_path)
    symbol = "000543.SZ"  # populated by _screened_ledger

    for draft in (
        f"1. **原料药价格持续低迷**，{symbol} 现价 8.20 CNY（source: tencent）",
        f"1. 原料药价格持续低迷\n2. 板块持续走强\n3. 建议关注 {symbol} 收盘价 8.20 CNY（source: tencent）",
        f"  1. 第一项描述\n  2. 第二项描述，{symbol} 收盘价 8.20 CNY（source: tencent）",
        f"结论如下：\n1) 原料药承压，{symbol} 8.20 CNY 可建仓（source: tencent）",
    ):
        result = ledger.validate_final_answer(draft)
        assert result.valid is True, (draft, result.issues)


def test_markdown_list_marker_mask_does_not_weaken_contradiction_check(
    tmp_path: Path,
) -> None:
    """Masking list markers must not shield a genuinely out-of-range quote (#BUGS-1).

    A wrong quote sitting in a numbered list item is still caught, so the mask is
    span-local: it removes only the marker, not a contradicted price that follows.
    """
    ledger = _screened_ledger(tmp_path)
    symbol = "000543.SZ"

    result = ledger.validate_final_answer(
        f"1. 原料药价格持续低迷，{symbol} 收盘价 42.00 CNY（source: tencent）"
    )

    codes = [issue["code"] for issue in result.issues]
    assert "numeric_claim_conflict" in codes
    assert [issue["value"] for issue in result.issues if issue["code"] == "numeric_claim_conflict"] == [42.0]


@pytest.mark.parametrize(
    "segment",
    [
        "买入股数 = 初始资金 × (1 - 单边成本率) / 期初收盘价",
        "期末市值 = 买入股数 × 期末收盘价 × (1 - fee_rate)",
        "net proceeds = shares * closing price * (1 - transaction_rate)",
    ],
)
def test_rate_formula_identity_is_not_read_as_a_price(segment: str) -> None:
    """The identity in ``1 - rate`` is arithmetic, not a one-unit quote."""
    assert GroundingLedger._numbers_without_dates_or_percent(segment) == []


def test_rate_formula_mask_does_not_hide_an_observed_one_unit_quote() -> None:
    """A genuine price of 1 remains checked outside a rate expression."""
    assert GroundingLedger._numbers_without_dates_or_percent("closing price = 1 CNY") == [1.0]


def test_in_text_decimal_survives_list_marker_mask(
    tmp_path: Path,
) -> None:
    """An ordinary decimal like 1.5 (digit after the dot) is never a list marker (#BUGS-1).

    The mask only matches a digit run at line start followed by "." or ")" and
    whitespace, so a genuine in-text decimal must remain a candidate price.
    """
    ledger = _screened_ledger(tmp_path)
    symbol = "000543.SZ"

    for draft in (
        f"{symbol} 目标价 1.5 CNY，收盘价 8.20 CNY（source: tencent）",
        f"{symbol} 变动 0.03 CNY，收盘价 8.20 CNY（source: tencent）",
    ):
        result = ledger.validate_final_answer(draft)
        assert result.valid is True, (draft, result.issues)


def test_order_level_prices_are_not_observed_quotes(tmp_path: Path) -> None:
    """GTC order limits (100 @ $3.50) are prospective, not observed prices.

    Regression for the RXRX run: the draft "两档 GTC (100 @ $3.50 / 100 @ $4.00)
    均未触发 (周高 $3.42 < $3.50)" was rejected with numeric_claim_conflict for
    100, 3.5 and 4.0 against the observed OHLC range. Order levels are levels,
    like targets/stops, and share counts are quantities - neither is a claim
    about an observed quote.
    """
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "RXRX_US.csv").write_text(
        "Date,Open,High,Low,Close\n"
        "2026-08-07,3.25,3.26,3.18,3.20\n"
        "2026-08-08,3.10,3.42,3.05,3.35\n",
        encoding="utf-8",
    )
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="请分析 RXRX.US 并更新周报",
    )
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "RXRX"},
        result=json.dumps({
            "ok": True,
            "data": {
                "candidates": [
                    {"symbol": "RXRX.US", "name": "Recursion Pharmaceuticals", "market": "us",
                     "type": "equity", "exchange": "NMS", "source": "yahoo"},
                ]
            },
        }),
        call_id="lock1",
        success=True,
    )

    answer = (
        "RXRX.US（yahoo，USD）本周高 $3.42。订单: 两档 GTC (100 @ $3.50 / 100 @ $4.00) "
        "均未触发 (周高 $3.42 < $3.50) — 价格推断未成交。"
    )
    result = ledger.validate_final_answer(answer)
    assert result.valid is True, result.issues

    # A genuinely fabricated close is still rejected.
    fabricated = ledger.validate_final_answer(
        "RXRX.US（yahoo，USD）本周高 $3.42。另: 收盘 2.50 已确认。"
    )
    assert fabricated.valid is False
    assert any(
        issue["code"] == "numeric_claim_conflict" for issue in fabricated.issues
    )


def test_dash_form_trading_day_is_a_date_but_a_price_range_is_not() -> None:
    """A report writes the day as "08-10(一)"; a target still writes "10-20 元".

    The dash carries both meanings, so the mask splits them: a zero-padded
    month reads as a date on its own, October through December need a weekday
    or session marker, and a range with neither stays checkable.
    """
    extract = GroundingLedger._numbers_without_dates_or_percent

    assert extract("08-10(一) 收盘 8.20 CNY") == [8.2]
    assert extract("08-10盘中最低 8.20 CNY") == [8.2]
    assert extract("08-10 close 8.20 USD") == [8.2]
    assert extract("10-20(周一)盘中 8.20 CNY") == [8.2]

    # No date marker and no zero-padded month: an ordinary quoted range, and
    # masking it would stop checking a claim the ledger exists to check.
    assert extract("区间 8-10 元") == [8.0, 10.0]
    assert extract("跌 12-25 元") == [12.0, 25.0]


def test_a_level_stated_as_a_range_masks_both_bounds(tmp_path: Path) -> None:
    """Masking only the lower bound left a negative upper bound behind.

    The separator touches the second number, so "目标价 10-20 元" used to
    reduce to "-20" — and a negative price is outside every OHLC window, which
    made a correct draft impossible to pass rather than merely unchecked.
    """
    extract = GroundingLedger._numbers_without_dates_or_percent

    for draft in ("目标价 10-20 元", "支撑位 8-10 元", "阻力位 12.0~13.5", "52周高 15.0-16.0"):
        assert extract(draft) == [], draft

    # A single-value level is unchanged, and an observed quote beside a ranged
    # level is still extracted and checked.
    assert extract("止损位 7.5 元") == []
    assert extract("目标价 10-20 元，现价 8.20 CNY") == [8.2]

    ledger = _screened_ledger(tmp_path)
    result = ledger.validate_final_answer(
        "000543.SZ 收盘价 8.20 CNY，目标价 10-20 元（source: tencent）"
    )
    assert result.valid is True, result.issues


def test_an_order_line_is_an_instruction_not_an_observation(tmp_path: Path) -> None:
    """"100 @ $3.50" states where a limit sits; 100 was never a price at all.

    A GTC summary in a weekly update was read as two observed quotes and
    rejected against the session's range, which is the same category error the
    target/stop masks already prevent.
    """
    extract = GroundingLedger._numbers_without_dates_or_percent

    for draft in (
        "GTC 100 @ $3.50",
        "buy 100 @ $3.50 GTC",
        "挂单 100 股 @ 4.00",
        "限价单 100 @ 3.50",
        "委托价 3.50",
    ):
        assert extract(draft) == [], draft

    # 买入价/卖出价 stay OUT of the label set: in running prose they name the
    # price a report says it observed, and masking them let an ungrounded
    # quote through the gate.
    assert extract("买入价 0.881") == [0.881]

    # There is no bare "@ <price>" branch either. Dates are masked before this
    # runs, so an observed close written "2026-08-10 @ 8.20" would reach the
    # order mask as "@ 8.20" and stop being checked at all.
    assert extract("收盘 2026-08-10 @ 8.20") == [8.2]

    # An observed quote standing beside an order line is still checked, and a
    # bare handle carries no price to mask.
    assert extract("现价 8.20 CNY，挂单 100 @ 8.50") == [8.2]
    assert extract("联系 @user 获取") == []

    ledger = _screened_ledger(tmp_path)
    result = ledger.validate_final_answer(
        "000543.SZ 收盘价 8.20 CNY，挂单 100 股 @ 12.00（source: tencent）"
    )
    assert result.valid is True, result.issues


def test_a_report_style_date_cell_still_matches_its_evidence_row() -> None:
    """"08-10(一)" and "08-10盘中" are the same trading day as "08-10".

    A weekday or session suffix made the cell match no evidence row, so every
    price in that row was reported numeric_claim_unavailable even though the
    run had fetched the bar.
    """
    from src.agent.grounding import _timestamp_matches_claim_date

    stamp = "2026-08-10T15:00:00Z"
    for claim in ("08-10", "8-10", "08-10(一)", "08-10(周一)", "08-10(周一)盘中", "08-10盘中", "08-10收盘"):
        assert _timestamp_matches_claim_date(stamp, claim) is True, claim

    # The suffix is decoration, not a wildcard — a different day still misses.
    assert _timestamp_matches_claim_date(stamp, "08-11(一)") is False


def test_a_us_csv_stem_resolves_to_its_venue_suffix() -> None:
    """``INTC_US.csv`` is ``INTC.US``; without the row it was no evidence at all."""
    from src.agent.grounding import _symbol_from_csv_filename

    assert _symbol_from_csv_filename("INTC_US") == "INTC.US"
    assert _symbol_from_csv_filename("BYN_V") == "BYN.V"
    assert _symbol_from_csv_filename("GC_F") == "GC=F"
    # A bare name has no venue suffix and must stay unresolvable.
    assert _symbol_from_csv_filename("AAPL") is None


class TestFiatPairAndIndexNormalization:
    """Search, fetch and grounding agree on one FX spelling; ^ is a symbol."""

    def test_fiat_pair_spellings_normalize_to_yahoo_form(self) -> None:
        from src.agent.grounding import _normalize_symbol

        assert _normalize_symbol("GBP/USD") == "GBPUSD=X"
        assert _normalize_symbol("GBPUSD") == "GBPUSD=X"
        assert _normalize_symbol("GBPUSD=X") == "GBPUSD=X"
        # Crypto/metals keep their pair form — not fiat/fiat FX.
        assert _normalize_symbol("ETH/USD") == "ETH-USD"
        assert _normalize_symbol("XAU/USD") == "XAU-USD"

    def test_scanned_slashed_pair_matches_resolver_answer(self) -> None:
        """The query-as-asserted scan must agree with the chosen candidate."""
        from src.agent.grounding import _scan_symbols

        assert _scan_symbols("use GBP/USD spot") == {"GBPUSD=X"}

    def test_index_symbols_are_scanned_and_typed(self) -> None:
        from src.agent.grounding import (
            _infer_currency,
            _infer_instrument_type,
            _scan_symbols,
        )

        assert _scan_symbols("quote ^SPX") == {"^SPX"}
        assert _infer_instrument_type("^SPX", "INDEX") == "index"
        assert _infer_instrument_type("^SPX") == "index"
        assert _infer_currency("GBPUSD=X") == "USD"

    def test_ingest_search_symbol_does_not_create_conflicting_identity(self) -> None:
        """The flagship regression: ingest('GBP/USD') must lock, never conflict."""
        from src.agent.grounding import _normalize_symbol

        # Chosen (from search_symbol) and asserted (the query text) must be
        # the same canonical identity — the comparison in _ingest_resolution.
        chosen = _normalize_symbol("GBPUSD=X")
        asserted = _scan_symbols("GBP/USD")
        assert chosen in asserted


def test_fx_pair_resolution_authorizes_market_data_consumer(tmp_path: Path) -> None:
    """Issue: search_symbol('GBP/USD') must lock, and get_market_data('GBPUSD=X')
    must be authorized — the slashed query used to normalize to the crypto
    spelling (GBP-USD), disagreeing with the chosen GBPUSD=X candidate and
    creating a conflicting identity that outranked every later lock.
    """
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="Get me the GBP/USD spot rate.",
    )
    before_resolution = ledger.authorized_symbols
    resolver = ledger.authorize_tool_call(
        "search_symbol",
        {"query": "GBP/USD"},
        batch_authorized_symbols=before_resolution,
        call_id="resolve-fx",
    )
    assert resolver.allowed is True

    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": "GBP/USD"},
        result=json.dumps(
            {
                "ok": True,
                "source": "symbol_search",
                "data": {
                    "query": "GBP/USD",
                    "count": 1,
                    "sources": {"yahoo": "ok", "fx_normalizer": "ok"},
                    "candidates": [
                        {
                            "symbol": "GBPUSD=X",
                            "name": "GBP/USD",
                            "market": "fx",
                            "type": "currency",
                            "exchange": "CCY",
                            "source": "fx_normalizer",
                        },
                    ],
                },
            }
        ),
        call_id="resolve-fx",
        success=True,
    )

    authorization = ledger.authorize_tool_call(
        "get_market_data",
        {"codes": ["GBPUSD=X"]},
        batch_authorized_symbols=ledger.authorized_symbols,
        batch_identity_status=ledger.identity_status,
        call_id="fx-prices",
    )

    assert ledger.identity_status == "locked"
    assert ledger.authorized_symbols == {"GBPUSD=X"}
    assert authorization.allowed is True


def test_backtest_metrics_rejected_when_analysis_tool_failed(
    tmp_path: Path,
) -> None:
    """#1336: failed analysis tools cannot ground backtest-style metrics."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="比较几支标的并回测不同市场状态",
    )
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": "runs/compare"},
        result=(
            '{"status": "error", "error": "market data unavailable after dedup"}'
        ),
        call_id="bt-failed",
        success=False,
    )

    bad = ledger.validate_final_answer(
        "| 策略 | Return vol | MaxDD | Prob. of hitting target |\n"
        "|---|---:|---:|---:|\n"
        "| M1 | 12.4% | -8.1% | 55% |"
    )

    assert bad.valid is False, bad.issues
    assert any(
        issue["code"] == "analysis_claim_unavailable" for issue in bad.issues
    )


def test_backtest_metrics_rejected_when_no_analysis_result(
    tmp_path: Path,
) -> None:
    """#1336: without any completed analysis, metric prose is unsupported."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="比较几个标的的历史行情",
    )

    bad = ledger.validate_final_answer(
        "历史回测显示策略年化波动率约 18.2%，最大回撤 -9.4%，"
        "夏普比率 1.21，命中目标概率 58%。"
    )

    assert bad.valid is False, bad.issues
    assert any(
        issue["code"] == "analysis_claim_unavailable" for issue in bad.issues
    )


def test_backtest_metrics_accepted_after_successful_backtest(
    tmp_path: Path,
) -> None:
    """#1336: a genuinely completed backtest grounds metrics its artifact holds."""
    run_dir = tmp_path / "runs" / "compare"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifacts" / "metrics.csv").write_text(
        "total_return,sharpe,max_drawdown\n0.124,1.21,-0.081\n",
        encoding="utf-8",
    )
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="比较几支标的并回测不同市场状态",
    )
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(run_dir)},
        result=json.dumps(
            {
                "status": "ok",
                "exit_code": 0,
                "run_dir": str(run_dir),
                "artifacts": {
                    "metrics.csv": str(run_dir / "artifacts" / "metrics.csv")
                },
            }
        ),
        call_id="bt-ok",
        success=True,
    )

    good = ledger.validate_final_answer(
        "| 策略 | 年化收益 | 夏普比率 | MaxDD |\n"
        "|---|---:|---:|---:|\n"
        "| M1 | 12.4% | 1.21 | -8.1% |"
    )

    assert good.valid is True, good.issues


def test_analysis_mention_without_figures_is_allowed(tmp_path: Path) -> None:
    """#1336: refusal prose naming the gap is not a quantitative claim."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="回测这几个标的",
    )

    good = ledger.validate_final_answer(
        "回测未能完成（行情数据不可用），因此无法给出波动率或回撤数据。"
    )

    assert good.valid is True, good.issues


def test_metrics_from_successful_numeric_tool_are_allowed(
    tmp_path: Path,
) -> None:
    """A successful generic analysis result grounds its returned metrics.

    The real tool returns fractions (annualized_vol 0.182, max_drawdown
    -0.094) while answers quote percents — the unit scaling must match.
    """
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="分析组合风险",
    )
    ledger.ingest_tool_result(
        tool_name="portfolio_risk_xray",
        arguments={"symbols": ["AAPL.US"]},
        result=json.dumps(
            {
                "status": "ok",
                "data": {
                    "volatility": {"annualized_vol": 0.182},
                    "drawdown": {"max_drawdown": -0.094},
                    "sharpe": 1.21,
                },
            }
        ),
        call_id="risk-ok",
        success=True,
    )

    good = ledger.validate_final_answer(
        "组合年化波动率 18.2%，最大回撤 -9.4%，夏普比率 1.21。"
    )

    assert good.valid is True, good.issues


def test_partially_unsupported_analysis_metrics_are_rejected(
    tmp_path: Path,
) -> None:
    """One observed metric cannot launder another invented metric."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="分析组合风险",
    )
    ledger.ingest_tool_result(
        tool_name="portfolio_risk_xray",
        arguments={"symbols": ["AAPL.US"]},
        result=json.dumps(
            {
                "status": "ok",
                "data": {"volatility": {"annualized_vol": 0.182}},
            }
        ),
        call_id="risk-partial",
        success=True,
    )

    bad = ledger.validate_final_answer(
        "组合年化波动率 18.2%，最大回撤 -9.4%。"
    )

    assert bad.valid is False, bad.issues
    assert any(
        issue["code"] == "analysis_claim_unavailable" for issue in bad.issues
    )


def test_forecast_probability_is_not_a_measured_claim(tmp_path: Path) -> None:
    """#1336 gates measured facts, not forward-looking forecasts."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="明天市场会怎么样",
    )

    good = ledger.validate_final_answer(
        "预计明日上涨概率 70%，波动率可能放大。"
    )

    assert good.valid is True, good.issues


def test_valid_price_does_not_launder_unsupported_analysis_metric(
    tmp_path: Path,
) -> None:
    """A valid quote must not make an invented backtest metric acceptable."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="AAPL.US 现价多少",
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["AAPL.US"]},
        result=json.dumps(
            {"AAPL.US": [{"trade_date": "2026-09-02", "close": 18.2}]}
        ),
        call_id="quote",
        success=True,
    )

    result = ledger.validate_final_answer(
        "AAPL.US 收盘价 18.2 USD。历史回测年化波动率 18.2%。"
    )

    assert result.valid is False, result.issues
    assert any(issue["code"] == "analysis_claim_unavailable" for issue in result.issues)


def test_successful_backtest_only_supports_metrics_in_its_artifact(
    tmp_path: Path,
) -> None:
    """One successful result must not authorize unrelated invented metrics."""
    metrics = tmp_path / "artifacts" / "metrics.csv"
    metrics.parent.mkdir()
    metrics.write_text("annual_return,sharpe\n0.182,1.21\n", encoding="utf-8")
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="回测策略",
    )
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(tmp_path)},
        result=json.dumps(
            {
                "status": "ok",
                "run_dir": str(tmp_path),
                "artifacts": {"metrics": str(metrics)},
            }
        ),
        call_id="backtest",
        success=True,
    )

    result = ledger.validate_final_answer(
        "策略年化收益 18.2%，夏普比率 1.21，最大回撤 -9.4%。"
    )

    assert result.valid is False, result.issues
    assert any(issue.get("value") == "-9.4%" for issue in result.issues)


def test_skipped_analysis_result_does_not_authorize_metrics(tmp_path: Path) -> None:
    """A skipped/deduplicated call is not a completed analysis."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测策略")
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(tmp_path)},
        result=json.dumps({"skipped": True, "reason": "already completed"}),
        call_id="backtest-skipped",
        success=True,
    )

    result = ledger.validate_final_answer("回测年化收益 18.2%，最大回撤 -9.4%。")

    assert result.valid is False, result.issues


def test_integer_historical_window_claim_is_rejected(tmp_path: Path) -> None:
    """Categorical claims about all historical windows need evidence too."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="分析策略")

    result = ledger.validate_final_answer("所有历史 12 个月窗口均实现正收益。")

    assert result.valid is False, result.issues
    assert any(issue["code"] == "analysis_claim_unavailable" for issue in result.issues)


def test_analysis_definition_is_not_rejected(tmp_path: Path) -> None:
    """A threshold definition is not a measured result from this session."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="什么是夏普比率？")

    result = ledger.validate_final_answer("夏普比率大于 1.0 通常被认为较好。")

    assert result.valid is True, result.issues


def test_forecast_table_cell_does_not_exempt_measured_cell(
    tmp_path: Path,
) -> None:
    """A forecast column must not hide an unsupported historical metric cell."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="比较两种策略")

    result = ledger.validate_final_answer(
        "| 策略 | 预计收益 | 历史最大回撤 |\n"
        "|---|---:|---:|\n"
        "| M1 | 预计 12.4% | -8.1% |"
    )

    assert result.valid is False, result.issues
    assert any(issue["code"] == "analysis_claim_unavailable" for issue in result.issues)


def test_analysis_completion_is_persisted_with_metric_provenance(
    tmp_path: Path,
) -> None:
    """The grounding artifact records why an analysis figure was accepted."""
    metrics = tmp_path / "artifacts" / "metrics.csv"
    metrics.parent.mkdir()
    metrics.write_text("annual_return\n0.182\n", encoding="utf-8")
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测策略")
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(tmp_path)},
        result=json.dumps(
            {
                "status": "ok",
                "run_dir": str(tmp_path),
                "artifacts": {"metrics": str(metrics)},
            }
        ),
        call_id="backtest",
        success=True,
    )

    artifact = json.loads(
        (tmp_path / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8")
    )

    assert artifact["analysis_evidence"]
    assert artifact["analysis_evidence"][0]["metric"] == "return"


def test_derived_interval_return_from_observed_endpoints_is_allowed(
    tmp_path: Path,
) -> None:
    """#1338 review: a return figure derived from observed endpoints stays legal.

    Both endpoints are observed evidence and the answer states the growth
    inline — arithmetic on sourced inputs, not an invented backtest metric.
    """
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="AAPL.US 最近一个月走势如何",
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["AAPL.US"]},
        result=json.dumps(
            {
                "AAPL.US": [
                    {"trade_date": "2026-08-03", "close": 100.0},
                    {"trade_date": "2026-09-02", "close": 112.4},
                ]
            }
        ),
        call_id="quote",
        success=True,
    )

    good = ledger.validate_final_answer(
        "AAPL.US 从 2026-08-03 的 100.0 涨到 2026-09-02 的 112.4，"
        "区间收益率为 12.4%。"
    )

    assert good.valid is True, good.issues


def test_derived_cumulative_return_english_is_allowed(tmp_path: Path) -> None:
    """#1338 review: same derivation exemption for the English shape."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="AAPL.US price history",
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["AAPL.US"]},
        result=json.dumps(
            {
                "AAPL.US": [
                    {"trade_date": "2026-08-03", "close": 100.0},
                    {"trade_date": "2026-09-02", "close": 112.4},
                ]
            }
        ),
        call_id="quote",
        success=True,
    )

    good = ledger.validate_final_answer(
        "AAPL.US rose from 100.0 to 112.4, a cumulative return of 12.4% "
        "over the window."
    )

    assert good.valid is True, good.issues


def test_unanchored_return_claim_is_still_rejected(tmp_path: Path) -> None:
    """Without the from/to frame, a return figure stays gated."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="AAPL.US 价格",
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["AAPL.US"]},
        result=json.dumps(
            {
                "AAPL.US": [
                    {"trade_date": "2026-08-03", "close": 100.0},
                    {"trade_date": "2026-09-02", "close": 112.4},
                ]
            }
        ),
        call_id="quote",
        success=True,
    )

    bad = ledger.validate_final_answer(
        "AAPL.US 区间收益率为 12.4%，历史回测年化收益 18.2%。"
    )

    assert bad.valid is False, bad.issues
    assert any(
        issue["code"] == "analysis_claim_unavailable" for issue in bad.issues
    )


def test_wrong_derived_return_arithmetic_is_rejected(tmp_path: Path) -> None:
    """A from/to frame with arithmetic that no observed pair supports fails."""
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="AAPL.US 价格",
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["AAPL.US"]},
        result=json.dumps(
            {
                "AAPL.US": [
                    {"trade_date": "2026-08-03", "close": 100.0},
                    {"trade_date": "2026-09-02", "close": 112.4},
                ]
            }
        ),
        call_id="quote",
        success=True,
    )

    bad = ledger.validate_final_answer(
        "AAPL.US 从 2026-08-03 的 100.0 涨到 2026-09-02 的 112.4，"
        "区间收益率为 30.5%。"
    )

    assert bad.valid is False, bad.issues
    assert any(
        issue.get("value") == "30.5%" for issue in bad.issues
    )


def test_research_paper_reported_metrics_are_grounded(tmp_path: Path) -> None:
    """#1338 review: attributed paper figures must not be suppressed.

    research_papers reports `reported_annualized_return` / `reported_max_drawdown`
    — compound leaves whose kind must resolve by token, not verbatim alias.
    """
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="查一下动量策略论文的回测表现",
    )
    ledger.ingest_tool_result(
        tool_name="research_papers",
        arguments={"query": "momentum"},
        result=json.dumps(
            {
                "status": "ok",
                "data": {
                    "results": [
                        {
                            "title": "Momentum crashes",
                            "reported_annualized_return": 0.182,
                            "reported_max_drawdown": -0.094,
                        }
                    ]
                },
            }
        ),
        call_id="rp-ok",
        success=True,
    )

    good = ledger.validate_final_answer(
        "该论文报告其策略年化收益 18.2%，最大回撤 -9.4%（论文自述，非本次回测）。"
    )

    assert good.valid is True, good.issues


def test_compound_metric_leaf_kind_resolution() -> None:
    """Token-split kind resolution covers the compound-leaf family."""
    from src.agent.grounding import _metric_kind_for_path

    assert _metric_kind_for_path("results[0].reported_annualized_return") == "return"
    assert _metric_kind_for_path("strategy_max_drawdown") == "drawdown"
    assert _metric_kind_for_path("data.benchmark_return_vol") == "vol"
    assert _metric_kind_for_path("data.hit_rate_daily") == "win_rate"
    assert _metric_kind_for_path("data.risk_free_rate") is None
    assert _metric_kind_for_path("data.trade_count") is None


def test_analysis_gates_accept_attributed_paper_restatement(tmp_path: Path) -> None:
    """An attributed figure is a citation, not an invented measurement (#1338
    review): 'The paper reports a Sharpe ratio of 1.8' must pass with zero tool
    results, in both languages, while unattributed phrasing stays blocked."""
    for answer in (
        "The paper reports a Sharpe ratio of 1.8 for the momentum factor.",
        "该论文报告其策略夏普比率为 1.8。",
        "研究机构指出该策略年化收益 18.2%。",
        "文献指出因子年化收益 18.2%。",
        "Analysts estimate an annualized volatility of 22%.",
    ):
        ledger = GroundingLedger(run_dir=tmp_path, user_message="Research the factor.")
        issues = ledger.validate_final_answer(answer).issues
        assert not [i for i in issues if i.get("code") == "analysis_claim_unavailable"], (
            answer,
            issues,
        )


def test_analysis_gate_still_rejects_unattributed_and_unsourced(
    tmp_path: Path,
) -> None:
    """The attribution exemption must not launder model-memory figures: the
    review's pinned reject pair and an invented metric with an ordinary prose
    subject keep failing."""
    for answer in (
        "TSLA.US last traded at 412.35 USD.",
        "特斯拉现价 412.35 美元。",
        "The strategy reports a Sharpe ratio of 1.8.",
    ):
        ledger = GroundingLedger(run_dir=tmp_path, user_message="Analyze something.")
        ledger.ingest_tool_result(
            tool_name="get_market_data",
            arguments={"codes": ["AAPL.US"]},
            result=json.dumps(
                {
                    "AAPL.US": [
                        {
                            "trade_date": "2026-09-02T00:00:00",
                            "close": 112.4,
                        }
                    ]
                }
            ),
            call_id="md-1",
            success=True,
        )
        issues = ledger.validate_final_answer(answer).issues
        assert issues, answer
        assert not any(
            issue.get("code") == "analysis_claim_unavailable" and "1.8" not in str(issue)
            for issue in issues
        ), answer


def test_attribution_exemption_cannot_launders_self_claims(tmp_path: Path) -> None:
    """The #1336 attack shape must not escape via attribution vocabulary:
    "the backtest/data shows" is a self-claim, and a citation in one clause
    must not exempt an invented sibling metric in the next."""
    for answer in (
        "The backtest data shows an annualized return of 25%.",
        "回测数据显示策略年化收益 25%。",
        "数据显示策略夏普比率为 3.5。",
        "根据本次回测，年化波动率 18.2%。",
        "The strategy reports a Sharpe ratio of 1.8.",
        "研究显示策略年化收益 25%。",
        "研究报告显示策略年化收益 25%。",
        "回测研究显示策略年化收益 25%。",
        "投资者普遍认为其年化收益 25%。",
        # citation in clause 1, invented sibling in clause 2
        "The paper reports a Sharpe ratio of 1.8, and our strategy achieved "
        "an annualized return of 47.3%.",
    ):
        ledger = GroundingLedger(run_dir=tmp_path, user_message="Research the factor.")
        issues = ledger.validate_final_answer(answer).issues
        assert [i for i in issues if i.get("code") == "analysis_claim_unavailable"], (
            answer,
            issues,
        )


def test_attribution_never_exempts_a_price_claim(tmp_path: Path) -> None:
    """A citation subject must not launder a fabricated quote.

    The attribution exemption is legitimate in the ANALYSIS gate — a paper's
    Sharpe is a figure this run could never have observed. A price is the
    opposite: it is exactly what this run observes, so attributing it to a
    source is the laundering shape the price gate exists to catch. With the
    exemption applied to `_validate_price_claims`, every line below passed
    with zero tool evidence.
    """
    for answer in (
        "Analysts say TSLA.US last traded at 412.35 USD.",
        "分析师指出特斯拉现价 412.35 美元。",
        "The paper reports that AAPL.US closed at 189.20.",
        "据研究机构报告，AAPL.US 收盘价为 189.20。",
        "The filing reports the stock closed at 412.35.",
    ):
        ledger = GroundingLedger(run_dir=tmp_path, user_message="Quote the price.")
        issues = ledger.validate_final_answer(answer).issues
        assert issues, f"attributed price accepted with zero evidence: {answer}"


def test_derived_return_exemption_is_structural_not_phrasal(tmp_path: Path) -> None:
    """The same derivation must get the same verdict in both languages.

    Keying the exemption on a growth PHRASE ("从…到" / "from…to") made the
    gate stricter for every wording the list missed. The pairs below state the
    identical arithmetic on the identical observed endpoints; asserting the
    two verdicts are EQUAL is what stops the next patch moving the breakage to
    the other language, exactly as test_grounding_language_parity does.
    """

    def verdict(answer: str) -> bool:
        ledger = GroundingLedger(run_dir=tmp_path, user_message="AAPL.US 走势")
        ledger.ingest_tool_result(
            tool_name="get_market_data",
            arguments={"codes": ["AAPL.US"]},
            result=json.dumps(
                {
                    "AAPL.US": [
                        {"trade_date": "2026-08-03", "close": 100.0},
                        {"trade_date": "2026-09-02", "close": 112.4},
                    ]
                }
            ),
            call_id="quote",
            success=True,
        )
        return bool(ledger.validate_final_answer(answer).issues)

    # Accepted in both: operands present in the clause and sourced.
    for english, chinese in (
        (
            "AAPL.US rose from 100.0 to 112.4, a cumulative return of 12.4%.",
            "AAPL.US 第一日收盘 100.0 美元，第二日收盘 112.4 美元，收益率 12.4%。",
        ),
    ):
        en, zh = verdict(english), verdict(chinese)
        assert en == zh, f"verdicts disagree by language: EN={en} ZH={zh}"
        assert en is False, f"sourced derivation rejected: {english}"

    # Still rejected in both: no operands in the clause, or wrong arithmetic.
    for answer in (
        "AAPL.US delivered a cumulative return of 12.4% over the window.",
        "AAPL.US 区间收益率为 12.4%。",
        "AAPL.US rose from 100.0 to 112.4, a cumulative return of 15.0%.",
        "AAPL.US 从 100.0 涨到 112.4，区间收益率为 15.0%。",
    ):
        assert verdict(answer) is True, f"unanchored/wrong return accepted: {answer}"
def test_generic_header_table_metric_rows_are_gated(tmp_path: Path) -> None:
    """#1336 must not be dodgeable by formatting the claim as a generic-header
    table (| 指标 | 数值 | / | Metric | Value |) with the metric kind in the
    row instead of prose or a metric-headed table."""
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测策略")

    result = ledger.validate_final_answer(
        "| 指标 | 数值 |\n|---|---:|\n| 年化收益 | 18.2% |\n| 最大回撤 | -9.4% |"
    )

    assert result.valid is False, result.issues
    assert [
        i for i in result.issues if i.get("code") == "analysis_claim_unavailable"
    ]

    # a comparison marker must not launder an unsupported figure through a
    # metric-headed table either: prose rejects "夏普比率 > 1.5。" without
    # evidence, so the table form must be rejected too
    result = ledger.validate_final_answer("| 夏普比率 |\n|---|---|\n| > 1.5 |")
    assert result.valid is False, result.issues

    # value-first layout (kind in a later cell) is gated too
    result = ledger.validate_final_answer(
        "| 数值 | 指标 |\n|---|---|\n| 18.2% | 年化收益率 |"
    )
    assert result.valid is False, result.issues
    # the bare fragment the prose detector treats as a metric word is gated
    result = ledger.validate_final_answer(
        "| 指标 | 数值 |\n|---|---|\n| 年化 | 18.2% |"
    )
    assert result.valid is False, result.issues
    # multiple (label, value) pairs in one row are each gated with their own kind
    result = ledger.validate_final_answer(
        "| 指标 | 数值 | 指标 | 数值 |\n|---|---|---|---|\n| 年化波动率 | 18.2% | 最大回撤 | -9.4% |"
    )
    assert result.valid is False, result.issues
    assert len([i for i in result.issues if i.get("code") == "analysis_claim_unavailable"]) == 2


def test_generic_header_table_matches_prose_verdicts(tmp_path: Path) -> None:
    """The generic-header fallback must produce the SAME verdict as prose for
    the same claim — never looser (formatting dodge) and never stricter.

    Prose without evidence rejects comparison phrasing ("最大回撤小于 -5%
    触发风控。"), rejects the definitional frame split across the number
    ("夏普比率通常大于1.0认为较好。"), and rejects a bare claim; with
    kind-matched evidence all of them pass. Tables must do exactly that.
    """
    bare = GroundingLedger(run_dir=tmp_path / "bare", user_message="回测策略")
    # comparison phrasing rejected without evidence, like prose
    assert bare.validate_final_answer(
        "| 指标 | 标准 |\n|---|---|\n| 最大回撤 | 小于 -5% 触发风控 |"
    ).valid is False
    # definitional frame split by the number: prose rejects it, tables must not
    # be looser than prose or the split becomes the new formatting dodge
    assert bare.validate_final_answer(
        "| 指标 | 备注 |\n|---|---|\n| 夏普比率 | 通常大于1.0认为较好 |"
    ).valid is False
    # a label cell smuggling its own measurement is prose-identical to
    # "年化收益率为 18.2%" — rejected
    assert bare.validate_final_answer(
        "| 指标 | 数值 |\n|---|---|\n| 年化收益率 18.2% | - |"
    ).valid is False

    backed = GroundingLedger(run_dir=tmp_path / "backed", user_message="回测策略")
    backed.ingest_tool_result(
        tool_name="portfolio_risk_xray",
        arguments={"symbols": ["AAPL"]},
        result=json.dumps({"annualized_vol": 0.182, "max_drawdown": -0.05}),
        call_id="x",
        success=True,
    )
    # value-backed row accepted
    assert backed.validate_final_answer(
        "| 指标 | 数值 |\n|---|---:|\n| 年化波动率 | 18.2% |"
    ).valid is True
    # the same comparison phrasing passes once the figure is kind-backed
    assert backed.validate_final_answer(
        "| 指标 | 标准 |\n|---|---|\n| 最大回撤 | 小于 -5% 触发风控 |"
    ).valid is True
    # contiguous definitional frame ("通常认为…") is exempt in prose, so in
    # tables too — the frame regex is the boundary, not the formatting
    assert backed.validate_final_answer(
        "| 指标 | 备注 |\n|---|---|\n| 夏普比率 | 通常认为大于 1.0 较好 |"
    ).valid is True
    # an annotation column past the value cell is not attributed to the label:
    # the prose verdict for "年化波动率 18.2%，较去年提升 2%。" with this evidence
    # is valid, so the table form must not be stricter (parity).
    assert backed.validate_final_answer(
        "| 指标 | 数值 | 备注 |\n|---|---|---|\n| 年化波动率 | 18.2% | 较去年提升 2% |"
    ).valid is True
    # a FORECAST frame in the label frames the claimed value clause-wide:
    # prose "预计夏普比率为 1.2。" and the metric-header path (header_forecast
    # column skip) both accept; the generic path must not be stricter.
    assert bare.validate_final_answer(
        "| 指标 | 数值 |\n|---|---|\n| 预计夏普比率 | 1.2 |"
    ).valid is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Futu writes the venue as a prefix; every one of them must land on
        # the same identity the market-data chain uses.
        ("HK.06693", "06693.HK"),
        ("HK.00700", "00700.HK"),
        ("HK.700", "00700.HK"),  # zero-padded like the suffix spelling
        ("US.AAPL", "AAPL.US"),
        ("US.BRK-B", "BRK-B.US"),
        ("SH.600519", "600519.SH"),
        ("SS.600519", "600519.SH"),  # Yahoo's Shanghai alias folds onto .SH
        ("SZ.000001", "000001.SZ"),
        ("BJ.430047", "430047.BJ"),
        # Negatives: a non-numeric venue code is not a listing (HK.HSI is an
        # index feed), and the suffix spellings stay untouched.
        ("HK.HSI", "HK.HSI"),
        ("06693.HK", "06693.HK"),
        ("AAPL.US", "AAPL.US"),
        ("600519.SH", "600519.SH"),
    ],
)
def test_normalize_venue_prefixed_symbols(raw: str, expected: str) -> None:
    """A Futu-style venue prefix normalizes onto the canonical suffix form."""
    assert _normalize_symbol(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("分析港股 HK.06693 的走势", {"06693.HK"}),
        ("持仓 US.AAPL 与 HK.00700", {"AAPL.US", "00700.HK"}),
        ("对比 SH.600519 和 SZ.000001", {"600519.SH", "000001.SZ"}),
        # Negatives: prose and URLs must not become symbols. The US branch is
        # case-sensitive precisely so a "…/us.reuters/…" host cannot.
        ("Revenue grew in the US. Apple led the pack.", set()),
        ("Listed in the U.S. AAPL is the largest.", set()),
        ("see https://example.com/us.quotes for details", set()),
    ],
)
def test_scan_symbols_detects_venue_prefixed_symbols(
    text: str, expected: set[str]
) -> None:
    """A pasted connector code is locked as an identity, prose is not."""
    assert _scan_symbols(text) == expected


def test_crypto_pair_tables_match_the_resolver() -> None:
    """The grounding copies of the crypto pair tables must not drift.

    ``src.tools.symbol_search_tool`` is the resolver; it imports this module,
    so the tables are duplicated rather than shared. A venue inferred here
    that disagrees with the identity the resolver locks is a contradictory
    identity, which outranks every later lock and blocks all market tools —
    so the duplication needs a guard, not a comment.
    """
    from src.agent import grounding as g
    from src.tools import symbol_search_tool as ss

    assert set(g._CRYPTO_USD_BASES) == set(ss._CRYPTO_USD_BASES)
    # ``USD`` is the one quote the resolver accepts that is ambiguous (spot
    # gold and forex are quoted in it too); grounding decides it by the base
    # whitelist instead, so it is the only permitted difference.
    assert set(g._CRYPTO_QUOTE_ASSETS) | {"USD"} == set(ss._CRYPTO_QUOTE_ASSETS)


def _multi_metric_ledger(tmp_path: Path) -> GroundingLedger:
    """A ledger whose backtest holds both volatility and drawdown evidence."""
    run_dir = tmp_path / "runs" / "multi"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifacts" / "metrics.csv").write_text(
        "annualized_vol,max_drawdown\n0.23,-0.05\n",
        encoding="utf-8",
    )
    ledger = GroundingLedger(run_dir=tmp_path, user_message="回测策略的风险指标")
    ledger.ingest_tool_result(
        tool_name="backtest",
        arguments={"run_dir": str(run_dir)},
        result=json.dumps(
            {
                "status": "ok",
                "exit_code": 0,
                "run_dir": str(run_dir),
                "artifacts": {
                    "metrics.csv": str(run_dir / "artifacts" / "metrics.csv")
                },
            }
        ),
        call_id="bt-multi",
        success=True,
    )
    return ledger


def test_multi_metric_clause_validates_each_value_against_its_own_kind(
    tmp_path: Path,
) -> None:
    """#1421: one clause, two metrics — each number is checked against the
    metric it belongs to, not against a single clause-wide kind."""
    ledger = _multi_metric_ledger(tmp_path)

    good = ledger.validate_final_answer(
        "Annualized volatility was 23% and max drawdown was -5%."
    )
    assert good.valid is True, good.issues

    reversed_order = ledger.validate_final_answer(
        "Max drawdown was -5% and annualized volatility was 23%."
    )
    assert reversed_order.valid is True, reversed_order.issues


def test_multi_metric_clause_still_rejects_the_wrong_value(tmp_path: Path) -> None:
    """Per-value kinds must not launder an unsupported figure either."""
    ledger = _multi_metric_ledger(tmp_path)

    bad = ledger.validate_final_answer(
        "Annualized volatility was 23% and max drawdown was -9%."
    )
    assert bad.valid is False
    by_value = {issue.get("value"): issue for issue in bad.issues}
    assert "-9%" in by_value
    assert by_value["-9%"]["kind"] == "drawdown"


def test_single_metric_clause_behavior_is_unchanged(tmp_path: Path) -> None:
    ledger = _multi_metric_ledger(tmp_path)

    assert ledger.validate_final_answer("Annualized volatility was 23%.").valid is True
    bad = ledger.validate_final_answer("Annualized volatility was 24%.")
    assert bad.valid is False
