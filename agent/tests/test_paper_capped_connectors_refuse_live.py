"""Structural gate: paper-capped connectors refuse a live order before anything else.

``docs/paper-trading/PLAN.md`` promised a CRITICAL grep gate called
``test_paper_adapters_no_live_endpoints.py`` over ``src/paper_trading/adapters/``.
That layer never shipped — the connector architecture replaced it — so the gate
was never written against anything real, while two other documents went on
citing it as though it existed. This is that gate, against what did ship.

The invariant under test is the red line in CLAUDE.md: a broker exposing no
runtime paper/live discriminator is capped at paper and its order entry points
refuse a non-paper config *before* reaching the broker SDK. Checking the refusal
happens early is the whole point — a guard placed after the network call would
still pass a behavioural test that only asserts "it raised".

The connector list is derived from the filesystem, so adding a broker fails this
test until someone classifies it. That is the anti-drift property; do not
replace the enumeration with a hardcoded list.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_CONNECTOR_ROOT = Path(__file__).resolve().parents[1] / "src" / "trading" / "connectors"

# Brokers with no runtime paper/live discriminator. Capped at paper; every
# order entry point must refuse a non-paper config up front.
_PAPER_CAPPED = frozenset({"longbridge", "dhan", "shoonya", "trading212", "zerodha"})

# Brokers with a structural discriminator (host separation, demo flag, account
# id format, trade environment). Live placement is allowed here, but only
# through the mandate gate — which `test_backtest_runner_security.py` and the
# order-guard suites cover; this gate deliberately does not re-assert it.
_LIVE_CAPABLE = frozenset(
    {
        "alpaca",
        "binance",
        "etoro",
        "futu",
        "okx",
        "tiger",
        "robinhood",
        "ibkr",
        "mt5",
    }
)

_ORDER_ENTRY_POINTS = ("place_order", "cancel_order")

# A guard is a paper/environment test. Matching on the source segment keeps this
# readable and independent of how each connector spells its config object.
_GUARD_MARKERS = ("is_paper", 'environment != "paper"', "environment != 'paper'")

# How many leading statements may precede the guard. One is needed because most
# connectors must resolve `config or load_config()` before they can inspect it.
_MAX_STATEMENTS_BEFORE_GUARD = 1


def _connector_names() -> list[str]:
    """Return every connector package name found on disk."""
    return sorted(path.name for path in _CONNECTOR_ROOT.iterdir() if path.is_dir() and not path.name.startswith("__"))


def _order_functions(sdk_path: Path) -> dict[str, tuple[ast.FunctionDef, str]]:
    """Return the order entry points defined in a connector's ``sdk.py``."""
    source = sdk_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    found: dict[str, tuple[ast.FunctionDef, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _ORDER_ENTRY_POINTS:
            found[node.name] = (node, source)
    return found


def _executable_body(func: ast.FunctionDef) -> list[ast.stmt]:
    """Return the function body with the docstring removed."""
    return [stmt for stmt in func.body if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))]


def test_every_connector_is_classified() -> None:
    """A new broker must be classified before it can ship.

    This is the drift alarm. If it fails, decide whether the new connector has
    a runtime paper/live discriminator and add it to exactly one set above.
    """
    unclassified = set(_connector_names()) - _PAPER_CAPPED - _LIVE_CAPABLE

    assert not unclassified, (
        f"Unclassified broker connector(s): {sorted(unclassified)}. Add each to "
        "_PAPER_CAPPED (no runtime paper/live discriminator) or _LIVE_CAPABLE "
        "(has one). Do not guess — check how the connector distinguishes paper "
        "from live at runtime."
    )


@pytest.mark.parametrize("broker", sorted(_PAPER_CAPPED))
def test_paper_capped_connector_refuses_non_paper_before_the_sdk(broker: str) -> None:
    """Each capped broker's order entry points guard on paper up front."""
    sdk_path = _CONNECTOR_ROOT / broker / "sdk.py"
    assert sdk_path.is_file(), f"{broker} has no sdk.py"

    functions = _order_functions(sdk_path)
    assert functions, f"{broker}/sdk.py defines no order entry point"

    for name, (func, source) in sorted(functions.items()):
        body = _executable_body(func)
        assert body, f"{broker}.{name} has an empty body"

        guard_index = None
        for index, stmt in enumerate(body):
            segment = ast.get_source_segment(source, stmt) or ""
            if any(marker in segment for marker in _GUARD_MARKERS):
                guard_index = index
                break

        assert guard_index is not None, (
            f"{broker}.{name} has no paper/environment guard. This broker is "
            "capped at paper because it exposes no runtime paper/live "
            "discriminator, so a non-paper config must be refused here."
        )
        assert guard_index <= _MAX_STATEMENTS_BEFORE_GUARD, (
            f"{broker}.{name} checks for paper at statement {guard_index + 1}, "
            f"after {guard_index} other statement(s). The guard must come first "
            "so nothing reaches the broker SDK before the refusal."
        )
