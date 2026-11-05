"""Regression tests: a caller cannot retarget a paper profile at a live broker.

``profile`` used to be an override key on eleven connectors, so a caller that
passed ``profile="live"`` to a paper profile reached the live host. The paper
branch of :func:`src.trading.service.place_order` skips the mandate gate, which
made that an ungated live-order path. The key is gone from every connector; the
environment check in :func:`src.trading.service._sdk_config` stays as depth, and
both layers are pinned here so neither can regress unnoticed.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.trading import service
from src.trading.connectors.alpaca import sdk as alpaca_sdk
from src.trading.types import TradingProfile

CONNECTOR_SDKS = sorted(
    (Path(__file__).resolve().parents[1] / "src" / "trading" / "connectors").glob("*/sdk.py")
)


@pytest.mark.parametrize("sdk_path", CONNECTOR_SDKS, ids=lambda path: path.parent.name)
def test_no_connector_accepts_a_profile_override(sdk_path: Path) -> None:
    """``profile`` selects paper vs live, so it must never be a caller override."""
    tree = ast.parse(sdk_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_OVERRIDE_KEYS" for t in node.targets)
        ):
            continue
        values = [element.value for element in node.value.elts if isinstance(element, ast.Constant)]
        assert "profile" not in values, f"{sdk_path.parent.name} still accepts profile="
        return
    pytest.skip("connector exposes no override surface")


def test_alpaca_paper_profile_ignores_a_live_profile_override() -> None:
    """A paper profile stays on the paper host even when the caller asks for live."""
    config = alpaca_sdk.build_config({"profile": "paper"}, {"profile": "live"})

    assert config.is_paper is True
    assert config.host == alpaca_sdk.PAPER_HOST


def test_sdk_config_refuses_a_config_that_changed_environment() -> None:
    """Depth: a connector that resolves to the other environment is refused."""
    profile = TradingProfile(
        id="alpaca-paper",
        connector="alpaca",
        label="Alpaca paper",
        environment="paper",
        transport="broker_sdk",
        capabilities=(),
        readonly=False,
        config={"profile": "paper"},
    )
    module = SimpleNamespace(
        build_config=lambda config, options: SimpleNamespace(environment="live")
    )

    with pytest.raises(ValueError, match="targets live"):
        service._sdk_config(profile, module, {})
