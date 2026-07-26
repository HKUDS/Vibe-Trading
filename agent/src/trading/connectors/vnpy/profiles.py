"""Built-in VeighNa (vn.py) RPC bridge connector profiles.

All four profiles reach the same remote vn.py RpcService over ZeroMQ (default
``tcp://127.0.0.1:2014`` req / ``tcp://127.0.0.1:4102`` pub); "paper" vs. "live"
is a label only here, not a runtime-verifiable discriminator — see
``src/trading/connectors/vnpy/sdk.py`` for why order placement fails closed
until the operator manually sets ``assume_environment_verified``.
"""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

VNPY_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="vnpy-paper-rpc",
        connector="vnpy",
        label="VeighNa Paper · RPC Bridge",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "paper"},
        notes=(
            "Reads a running vn.py Trader over its RpcService (default "
            "127.0.0.1:2014/4102). Requires the RPC Service app started in that "
            "Trader instance, with a gateway already connected and logged into a "
            "demo/simulated account. Vibe-Trading cannot verify this from the "
            "client side — it trusts the operator's own vn.py setup."
        ),
    ),
    TradingProfile(
        id="vnpy-paper-trade",
        connector="vnpy",
        label="VeighNa Paper · RPC Bridge Trading",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place",),
        readonly=False,
        config={"profile": "paper"},
        notes=(
            "Places orders through a running vn.py Trader's RpcService against "
            "whichever gateway is connected there. Set gateway_name to that "
            "gateway's key (e.g. 'CTP', 'XTP', 'FUTU') and set "
            "assume_environment_verified=true after confirming by hand that the "
            "remote Trader is logged into a demo/simulated account."
        ),
    ),
    TradingProfile(
        id="vnpy-live-rpc",
        connector="vnpy",
        label="VeighNa Live · RPC Bridge Read-Only",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live"},
        notes="Read-only view of a running vn.py Trader's RpcService. Order placement is not exposed in this profile.",
    ),
    TradingProfile(
        id="vnpy-live-trade",
        connector="vnpy",
        label="VeighNa Live · RPC Bridge Trading",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place.requires_mandate",),
        readonly=False,
        config={"profile": "live"},
        notes=(
            "Places real orders through a running vn.py Trader's RpcService. "
            "Gates on the user mandate and on assume_environment_verified=true — "
            "there is no structural paper/live discriminator on this transport, "
            "unlike Futu's OpenD trd_env guard, so this is weaker isolation than "
            "the other live-capable connectors. Confirm the remote Trader's "
            "gateway session by hand before enabling."
        ),
    ),
)
