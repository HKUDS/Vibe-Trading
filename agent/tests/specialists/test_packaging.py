"""Packaging pins for bundled specialist definitions.

Mirrors ``test_swarm_presets_packaging.py`` (issue #55 regression guard): the
definitions must ship inside the ``src.specialists`` package so wheels and
editable installs see the same roster.
"""

from __future__ import annotations

from pathlib import Path

from src.specialists.loader import DEFINITIONS_DIR, load_specialists

EXPECTED_SPECIALIST_COUNT = 12

# DEC-5 safety anchor: the trading-connector specialist is read-only by
# construction. Order-writing tools must never enter its whitelist.
TRADING_CONNECTOR_READONLY_TOOLS = {
    "trading_connections",
    "trading_select_connection",
    "trading_check",
    "trading_account",
    "trading_positions",
    "trading_orders",
    "trading_quote",
    "trading_history",
}


def test_definitions_dir_lives_inside_the_package() -> None:
    import src.specialists as package

    module_dir = Path(package.__file__).resolve().parent
    assert DEFINITIONS_DIR == module_dir / "definitions"
    assert DEFINITIONS_DIR.is_dir()


def test_bundled_roster_count_is_pinned() -> None:
    bundled = [p.stem for p in DEFINITIONS_DIR.glob("*.yaml")]
    assert len(bundled) == EXPECTED_SPECIALIST_COUNT, (
        f"expected {EXPECTED_SPECIALIST_COUNT} bundled specialists, found "
        f"{len(bundled)} — check pyproject package-data for dropped YAMLs"
    )


def test_trading_connector_whitelist_is_exactly_read_only() -> None:
    spec = load_specialists()["trading-connector-agent"]
    assert set(spec.tools) == TRADING_CONNECTOR_READONLY_TOOLS
    assert "trading_place_order" not in spec.tools
    assert "trading_cancel_order" not in spec.tools
