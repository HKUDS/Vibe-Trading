"""Composite cross-market backtest engine.

Manages a shared capital pool across multiple market engines.
Sub-engines are used as stateless "rule books" for market-specific
calculations (commission, slippage, lot rounding, etc.).
All state (capital, positions, trades) lives in CompositeEngine.
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd

from backtest.engines.base import BaseEngine
from backtest.engines._market_hooks import (
    _detect_market,
    _interval_span_hours,
    _is_china_futures,
    _liquidation_mark,
    code_currency,
    calc_crypto_funding_fee,
    check_crypto_liquidation,
    calc_forex_swap,
)


def _build_rule_engines(config: dict, codes: List[str]) -> Dict[str, BaseEngine]:
    """Instantiate one sub-engine per market type detected in codes."""
    markets = {_detect_market(c) for c in codes}
    engines: Dict[str, BaseEngine] = {}

    for market in markets:
        if market == "a_share":
            from backtest.engines.china_a import ChinaAEngine
            engines["a_share"] = ChinaAEngine(config)
        elif market == "us_equity":
            from backtest.engines.global_equity import GlobalEquityEngine
            engines["us_equity"] = GlobalEquityEngine(config, market="us")
        elif market == "hk_equity":
            from backtest.engines.global_equity import GlobalEquityEngine
            engines["hk_equity"] = GlobalEquityEngine(config, market="hk")
        elif market == "india_equity":
            from backtest.engines.india_equity import IndiaEquityEngine
            engines["india_equity"] = IndiaEquityEngine(config)
        elif market == "kr_equity":
            from backtest.engines.korea_equity import KoreaEquityEngine
            engines["kr_equity"] = KoreaEquityEngine(config)
        elif market == "vietnam_equity":
            from backtest.engines.vietnam_equity import VietnamEquityEngine
            engines["vietnam_equity"] = VietnamEquityEngine(config)
        elif market == "ca_equity":
            from backtest.engines.global_equity import GlobalEquityEngine
            engines["ca_equity"] = GlobalEquityEngine(config, market="ca")
        elif market == "uk_equity":
            from backtest.engines.global_equity import GlobalEquityEngine
            engines["uk_equity"] = GlobalEquityEngine(config, market="uk")
        elif market == "crypto":
            from backtest.engines.crypto import CryptoEngine
            engines["crypto"] = CryptoEngine(config)
        elif market == "index":
            from backtest.engines.global_equity import GlobalEquityEngine
            engines["index"] = GlobalEquityEngine(config, market="us")
        elif market == "forex":
            from backtest.engines.forex import ForexEngine
            engines["forex"] = ForexEngine(config)
        elif market == "futures":
            futures_codes = [c for c in codes if _detect_market(c) == "futures"]
            if any(_is_china_futures(c) for c in futures_codes):
                from backtest.engines.china_futures import ChinaFuturesEngine
                engines["china_futures"] = ChinaFuturesEngine(config)
            if any(not _is_china_futures(c) for c in futures_codes):
                from backtest.engines.global_futures import GlobalFuturesEngine
                engines["global_futures"] = GlobalFuturesEngine(config)

    return engines


def _reject_mixed_currency(codes: List[str]) -> None:
    """Refuse a code set whose members do not settle in one currency.

    The shared capital pool holds a single scalar of cash and sums position
    values into a single equity curve. With codes from two currency zones that
    curve adds CNY to USD to KRW as if the units matched, and every metric
    derived from it — return, Sharpe, drawdown — is meaningless. There is no FX
    translation layer yet, so this fails closed rather than reporting a number
    that looks fine.

    Args:
        codes: Instrument codes for the backtest.

    Raises:
        ValueError: If the codes span more than one settlement currency.
    """
    by_currency: Dict[str, List[str]] = {}
    for code in codes:
        by_currency.setdefault(code_currency(code), []).append(code)
    if len(by_currency) <= 1:
        return
    breakdown = "; ".join(
        f"{currency}: {', '.join(sorted(members))}"
        for currency, members in sorted(by_currency.items())
    )
    raise ValueError(
        "composite backtest requires one settlement currency across all codes, "
        f"but got {len(by_currency)} — {breakdown}. The shared capital pool has "
        "no FX translation, so a mixed-currency equity curve would sum "
        "different units. Split the run by currency, or convert the inputs "
        "to one currency before loading."
    )


class CompositeEngine(BaseEngine):
    """Cross-market engine with shared capital pool.

    Sub-engines are stateless rule providers. All positions, capital,
    and trades live here (inherited from BaseEngine).

    Args:
        config: Backtest configuration dict.
        codes: List of instrument codes spanning multiple markets.
    """

    def __init__(self, config: dict, codes: List[str]):
        super().__init__(config)

        # Build symbol -> market mapping
        self._symbol_market: Dict[str, str] = {c: _detect_market(c) for c in codes}

        # Build sub-engines (one per market type)
        self._rule_engines = _build_rule_engines(config, codes)

        # Crypto dedup state (owned by CompositeEngine, not sub-engine)
        self._funding_applied: set = set()
        self._funding_daily_done: set = set()

        # Forex dedup state
        self._last_swap_dates: dict = {}

        self._run_interval = str(config.get("interval", "1D"))

    def run_backtest(self, config: dict, *args, **kwargs):
        """Run the pipeline, refusing a code set that spans currencies.

        The check lives here rather than in ``__init__`` because the damage is
        in the shared equity curve, not in constructing the rule-book engines.

        Args:
            config: Backtest configuration dict.
            *args: Forwarded to :meth:`BaseEngine.run_backtest`.
            **kwargs: Forwarded to :meth:`BaseEngine.run_backtest`.

        Returns:
            The metrics dictionary from :meth:`BaseEngine.run_backtest`.

        Raises:
            ValueError: If the codes span more than one settlement currency.
        """
        _reject_mixed_currency(config.get("codes") or list(self._symbol_market))
        # The run config, not the construction config, is authoritative for the
        # bar span — same convention as CryptoEngine.run_backtest.
        self._run_interval = str(config.get("interval", "1D"))
        return super().run_backtest(config, *args, **kwargs)

    def _rule_for(self, symbol: str) -> BaseEngine:
        """Get the sub-engine that provides rules for this symbol."""
        market = self._symbol_market.get(symbol, "a_share")
        if market == "futures":
            market = "china_futures" if _is_china_futures(symbol) else "global_futures"
        engine = self._rule_engines.get(market)
        if engine is None:
            if not self._rule_engines:
                raise ValueError("No sub-engines available for composite backtest")
            engine = next(iter(self._rule_engines.values()))
        return engine

    # ── Stateless method dispatch ──

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Market-rule check with state/rules split helpers for HOSE, A-share, India."""
        market = self._symbol_market.get(symbol, "a_share")

        # HOSE, A-share and India all read run state a stateless rule book
        # does not have: positions for T+1/T+2 and the close panel for the
        # band reference price. Each market's module-level helper takes the
        # composite as the state side and the sub-engine as the parameter
        # side, so the shared state is what the rules are evaluated against.
        if market == "vietnam_equity":
            sub = self._rule_engines.get("vietnam_equity")
            if sub is not None:
                from backtest.engines.vietnam_equity import hose_can_execute

                return hose_can_execute(self, sub, symbol, direction, bar)

        if market == "a_share":
            sub = self._rule_engines.get("a_share")
            if sub is not None:
                from backtest.engines.china_a import china_a_can_execute

                return china_a_can_execute(self, sub, symbol, direction, bar)

        if market == "india_equity":
            sub = self._rule_engines.get("india_equity")
            if sub is not None:
                from backtest.engines.india_equity import india_can_execute

                return india_can_execute(self, sub, symbol, direction, bar)

        # Delegate remaining checks (price limits, short-sell block, etc.)
        return self._rule_for(symbol).can_execute(symbol, direction, bar)

    def round_size(self, raw_size: float, price: float) -> float:
        """Delegate to active symbol's sub-engine."""
        return self._rule_for(self._active_symbol).round_size(raw_size, price)

    def calc_commission(
        self, size: float, price: float, direction: int, is_open: bool,
    ) -> float:
        """Delegate to active symbol's sub-engine."""
        return self._rule_for(self._active_symbol).calc_commission(
            size, price, direction, is_open,
        )

    def apply_slippage(self, price: float, direction: int) -> float:
        """Delegate to active symbol's sub-engine."""
        sub = self._rule_for(self._active_symbol)
        # ForexEngine needs _active_symbol set on the sub-engine
        sub._active_symbol = self._active_symbol
        return sub.apply_slippage(price, direction)

    # ── PnL / margin dispatch (route by symbol, not _active_symbol) ──

    def _calc_pnl(
        self, symbol: str, direction: int, size: float,
        entry_price: float, exit_price: float,
    ) -> float:
        return self._rule_for(symbol)._calc_pnl(
            symbol, direction, size, entry_price, exit_price,
        )

    def _calc_margin(
        self, symbol: str, size: float, price: float, leverage: float,
    ) -> float:
        return self._rule_for(symbol)._calc_margin(symbol, size, price, leverage)

    def _calc_raw_size(
        self, symbol: str, target_notional: float, price: float,
    ) -> float:
        return self._rule_for(symbol)._calc_raw_size(symbol, target_notional, price)

    def _leverage_for_symbol(self, symbol: str) -> float:
        return self._rule_for(symbol)._leverage_for_symbol(symbol)

    # ── Stateful hooks (implemented directly, NO delegation) ──

    def on_bar(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """Per-bar hooks dispatched by market type."""
        market = self._symbol_market.get(symbol)

        if market == "crypto":
            crypto_sub = self._rule_engines["crypto"]
            fee = calc_crypto_funding_fee(
                symbol, bar, timestamp, self.positions,
                crypto_sub.funding_rate,
                self._funding_applied, self._funding_daily_done,
                _interval_span_hours(self._run_interval),
            )
            self.capital -= fee

            if check_crypto_liquidation(symbol, bar, self.positions):
                pos = self.positions.get(symbol)
                if pos is not None:
                    # Fill at the same adverse mark the hook used for the check so
                    # a wick trigger never exits at a better price than the venue.
                    liq_price = crypto_sub.apply_slippage(_liquidation_mark(bar, pos), -pos.direction)
                    self._close_position(symbol, liq_price, timestamp, "liquidation")

        elif market == "forex":
            forex_sub = self._rule_engines["forex"]
            if forex_sub.swap_enabled:
                swap = calc_forex_swap(
                    symbol, timestamp, self.positions,
                    forex_sub.lot_size, self._last_swap_dates,
                )
                self.capital += swap
