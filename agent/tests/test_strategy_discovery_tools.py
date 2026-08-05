"""Frozen-contract tests for ``src.tools.strategy_discovery_tool`` — issue #969.

AC1 (tools callable at runtime): the module must expose exactly three
``BaseTool`` classes whose ``name`` attributes are ``list_strategies`` /
``query_strategies`` / ``get_strategy_evidence``, all read-only, returning
strict-JSON envelopes with ``status`` ok/error and never raising on invalid
parameter types.

The sibling-built ``StrategyDiscoveryFacade`` construction is intercepted at
module level (patching ``sdt.StrategyDiscoveryFacade``) so a ``FakeFacade``
records calls and canned envelopes — no real store, no filesystem state.
"""

from __future__ import annotations

import json

import pytest

from src.agent.tools import BaseTool

try:
    from src.tools import strategy_discovery_tool as sdt

    TOOLS_AVAILABLE = True
except ImportError:
    sdt = None
    TOOLS_AVAILABLE = False

requires_tools = pytest.mark.skipif(
    not TOOLS_AVAILABLE,
    reason="waiting on sibling B: src.tools.strategy_discovery_tool not landed yet (issue #969)",
)

EXPECTED_NAMES = {"list_strategies", "query_strategies", "get_strategy_evidence"}


def _strict_json_loads(text: str) -> dict:
    def _reject(constant):
        raise ValueError(f"non-strict constant {constant!r} in tool output")

    payload = json.loads(text, parse_constant=_reject)
    assert isinstance(
        payload, dict
    ), f"tool output must be a JSON object, got {type(payload)}"
    return payload


class FakeFacade:
    """Canned stand-in for StrategyDiscoveryFacade; records every call."""

    instances: list = []

    def __init__(self, *args, **kwargs):
        self.init_args = args
        self.init_kwargs = kwargs
        self.calls = []
        FakeFacade.instances.append(self)

    def list_strategies(self, *args, **kwargs):
        self.calls.append(("list_strategies", args, kwargs))
        return {"status": "ok", "total": 0, "returned": 0, "offset": 0, "items": []}

    def query_strategies(self, *args, **kwargs):
        self.calls.append(("query_strategies", args, kwargs))
        return {"status": "ok", "regime": None, "returned": 0, "items": []}

    def get_strategy_evidence(self, *args, **kwargs):
        self.calls.append(("get_strategy_evidence", args, kwargs))
        strategy_id = kwargs.get("strategy_id") or (args[0] if args else "")
        return {
            "status": "ok",
            "strategy_id": strategy_id,
            "regime": kwargs.get("regime"),
            "found": False,
            "rows": [],
            "note": "no evidence computed for this strategy yet",
        }


@pytest.fixture
def fake_facade(monkeypatch):
    """Intercept StrategyDiscoveryFacade construction.

    The tool module imports the facade lazily inside execute() via
    ``from src.strategy_discovery import StrategyDiscoveryFacade``, which is a
    module-attribute lookup at call time — patching the package attribute (and
    a module-level binding if present) keeps every real store untouched.
    """
    import src.strategy_discovery as sd_package

    FakeFacade.instances.clear()
    monkeypatch.setattr(sd_package, "StrategyDiscoveryFacade", FakeFacade, raising=True)
    if getattr(sdt, "StrategyDiscoveryFacade", None) is not None:
        monkeypatch.setattr(sdt, "StrategyDiscoveryFacade", FakeFacade, raising=True)
    return FakeFacade


def _discover_tool_classes():
    return [
        value
        for value in vars(sdt).values()
        if isinstance(value, type)
        and issubclass(value, BaseTool)
        and value is not BaseTool
        and getattr(value, "__module__", "") == sdt.__name__
    ]


def _instantiate_tools() -> dict:
    classes = _discover_tool_classes()
    assert len(classes) == 3, (
        f"expected exactly 3 BaseTool classes in strategy_discovery_tool, found "
        f"{[c.__name__ for c in classes]}"
    )
    tools = {cls().name: cls() for cls in classes}
    assert (
        set(tools) == EXPECTED_NAMES
    ), f"tool .name attributes must be {sorted(EXPECTED_NAMES)}, got {sorted(tools)}"
    return tools


@requires_tools
class TestToolClasses:
    def test_three_tools_with_exact_names_all_read_only(self, fake_facade) -> None:
        tools = _instantiate_tools()
        for name in EXPECTED_NAMES:
            tool = tools[name]
            assert isinstance(tool, BaseTool)
            assert (
                tool.parameters
            ), f"{name} must declare a JSON-schema parameters block"
            assert tool.is_readonly is True, f"{name} must be read-only"


@requires_tools
class TestExecuteEnvelopes:
    def test_list_strategies_returns_canned_ok_envelope(self, fake_facade) -> None:
        tool = _instantiate_tools()["list_strategies"]
        payload = _strict_json_loads(tool.execute(limit=5, offset=0))
        assert payload["status"] == "ok"
        assert payload["items"] == []
        facade = fake_facade.instances[-1]
        assert facade.calls and facade.calls[-1][0] == "list_strategies"
        _, args, kwargs = facade.calls[-1]
        forwarded = {**kwargs}
        if args:
            forwarded.setdefault("args", args)
        assert ("limit" in forwarded and forwarded["limit"] == 5) or (
            5 in args
        ), f"limit=5 was not forwarded to the facade: args={args} kwargs={kwargs}"

    def test_query_strategies_forwards_arguments(self, fake_facade) -> None:
        tool = _instantiate_tools()["query_strategies"]
        payload = _strict_json_loads(
            tool.execute(regime="bear_market", min_evidence_quality="marginal", limit=3)
        )
        assert payload["status"] == "ok"
        _, args, kwargs = fake_facade.instances[-1].calls[-1]
        combined = json.dumps({"args": list(args), "kwargs": kwargs})
        assert "bear_market" in combined
        assert "marginal" in combined

    def test_get_strategy_evidence_forwards_strategy_id(self, fake_facade) -> None:
        tool = _instantiate_tools()["get_strategy_evidence"]
        payload = _strict_json_loads(tool.execute(strategy_id="alpha_zoo:a1"))
        assert payload["status"] == "ok"
        assert payload["strategy_id"] == "alpha_zoo:a1"


@requires_tools
class TestInvalidParameters:
    """Invalid types must yield an error envelope — never an exception."""

    def test_list_strategies_rejects_string_limit(self, fake_facade) -> None:
        tool = _instantiate_tools()["list_strategies"]
        payload = _strict_json_loads(tool.execute(limit="ten"))
        assert payload["status"] == "error"
        assert payload.get("error")

    def test_query_strategies_rejects_string_min_trades(self, fake_facade) -> None:
        tool = _instantiate_tools()["query_strategies"]
        payload = _strict_json_loads(tool.execute(min_trades="many"))
        assert payload["status"] == "error"
        assert payload.get("error")

    def test_query_strategies_rejects_unparseable_cost_feasible(
        self, fake_facade
    ) -> None:
        # "yes"/"no" are documented LLM-tolerant boolean forms; "maybe" is not.
        tool = _instantiate_tools()["query_strategies"]
        payload = _strict_json_loads(tool.execute(cost_feasible="maybe"))
        assert payload["status"] == "error"
        assert payload.get("error")

    def test_get_strategy_evidence_rejects_non_string_strategy_id(
        self, fake_facade
    ) -> None:
        tool = _instantiate_tools()["get_strategy_evidence"]
        payload = _strict_json_loads(tool.execute(strategy_id=12345))
        assert payload["status"] == "error"
        assert payload.get("error")


@requires_tools
class TestStringLengthCap:
    """Free-text params are identifiers; over-long values are rejected at the
    tool boundary via the standard error envelope, before any facade call."""

    def test_overlong_strategy_id_is_rejected_with_clear_message(
        self, fake_facade
    ) -> None:
        tool = _instantiate_tools()["get_strategy_evidence"]
        payload = _strict_json_loads(tool.execute(strategy_id="a" * 501))
        assert payload["status"] == "error"
        error = payload.get("error", "")
        assert error, "cap rejection must carry a message"
        assert "too long" in error.lower(), f"expected a length message: {error!r}"
        assert (
            not fake_facade.instances or not fake_facade.instances[-1].calls
        ), "an over-long parameter must not reach the facade"

    def test_exactly_500_chars_is_accepted(self, fake_facade) -> None:
        tool = _instantiate_tools()["get_strategy_evidence"]
        payload = _strict_json_loads(tool.execute(strategy_id="a" * 500))
        assert payload["status"] == "ok"
        assert payload["strategy_id"] == "a" * 500

    def test_overlong_regime_and_source_are_rejected(self, fake_facade) -> None:
        query = _instantiate_tools()["query_strategies"]
        listed = _instantiate_tools()["list_strategies"]
        bad = "r" * 700
        for payload in (
            _strict_json_loads(query.execute(regime=bad)),
            _strict_json_loads(listed.execute(source=bad)),
        ):
            assert payload["status"] == "error"
            assert "too long" in payload.get("error", "").lower()


@requires_tools
class TestGenericErrorEnvelope:
    """Unexpected facade failures must surface as a generic error envelope —
    raw exception text (file paths, internals) belongs to server logs only."""

    class ExplodingFacade:
        _SECRET = "traceback-canary /Users/x/.vibe-trading/secrets/token"

        def __init__(self, *args, **kwargs):
            pass

        def list_strategies(self, *args, **kwargs):
            raise RuntimeError(self._SECRET)

        def query_strategies(self, *args, **kwargs):
            raise RuntimeError(self._SECRET)

        def get_strategy_evidence(self, *args, **kwargs):
            raise RuntimeError(self._SECRET)

    def test_facade_exception_yields_generic_message_without_leak(
        self, monkeypatch
    ) -> None:
        import src.strategy_discovery as sd_package

        monkeypatch.setattr(
            sd_package, "StrategyDiscoveryFacade", self.ExplodingFacade, raising=True
        )
        if getattr(sdt, "StrategyDiscoveryFacade", None) is not None:
            monkeypatch.setattr(
                sdt, "StrategyDiscoveryFacade", self.ExplodingFacade, raising=True
            )
        tools = _instantiate_tools()
        for name, call in (
            ("list_strategies", lambda t: t.execute(limit=1)),
            ("query_strategies", lambda t: t.execute()),
            ("get_strategy_evidence", lambda t: t.execute(strategy_id="alpha_zoo:a1")),
        ):
            payload = _strict_json_loads(call(tools[name]))
            assert payload["status"] == "error", f"{name}: expected error envelope"
            error = payload.get("error", "")
            assert error, f"{name}: error envelope must carry a message"
            assert (
                self.ExplodingFacade._SECRET not in error
            ), f"{name}: raw exception text leaked into the envelope: {error!r}"
            assert (
                "failed internally" in error
            ), f"{name}: expected the generic 'failed internally' wording: {error!r}"
