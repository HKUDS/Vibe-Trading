"""Candidate options strategies for ``backtest.engines.options_portfolio``.

Five ``OptionsSignalEngine`` implementations (see SKILL.md for the instruction
format): covered call, cash-secured put, short iron condor, vol-gated short
strangle and protective put. ``SignalEngine`` defaults to the iron condor.

The engine calls ``generate`` once with the whole history, so trade management
(profit targets, DTE exits, compounding size) is decided here by re-pricing
each leg with the engine's own model -- trailing historical vol, the same
smile, Black-Scholes -- using only bars up to the decision date. Pass the run's
``options_config`` values (``risk_free_rate``, ``iv_skew``, ``iv_curvature``,
``default_iv``) and ``commission`` so both sides price identically.

Stock legs: the engine trades options only, so the share position of the
covered call and protective put is a long call struck at ~0 that expires after
the data ends (price ~= spot, delta 1). The engine's margin model cannot see
that it covers the short call, so run those two with ``margin_enabled: false``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.engines.options_portfolio import historical_volatility, leg_iv
from src.quantlib.options import bs_greeks, bs_price

Leg = Dict[str, Any]


class _OptionsBook:
    """Shared pricing, strike selection and per-underlying trade loop."""

    def __init__(self, risk_free_rate: float = 0.02, iv_skew: float = 0.0,
                 iv_curvature: float = 0.0, default_iv: float = 0.3,
                 commission: float = 0.0, capital: float = 100_000.0,
                 start_date: Optional[str] = None) -> None:
        self.r = risk_free_rate
        self.skew = iv_skew
        self.curvature = iv_curvature
        self.default_iv = default_iv
        self.commission = commission
        self.capital = capital
        # No entries before this date: the warm-up bars only feed vol and gates.
        self.start = pd.Timestamp(start_date) if start_date else None

    # --- pricing (mirrors the engine) ---

    def _price(self, S: float, hv: float, ts: pd.Timestamp, leg: Leg) -> float:
        T = max((pd.Timestamp(leg["expiry"]) - ts).days / 365.0, 0.0)
        iv = leg_iv(S, leg["strike"], hv, self.skew, self.curvature)
        return bs_price(S, leg["strike"], T, self.r, iv, leg["type"])

    def _value(self, S: float, hv: float, ts: pd.Timestamp, legs: List[Leg]) -> float:
        return sum(self._price(S, hv, ts, leg) * leg["qty"] for leg in legs)

    def _strike(self, S: float, hv: float, ts: pd.Timestamp, expiry: str,
                option_type: str, delta: float) -> float:
        """Listed-style strike (1% of spot grid) whose |delta| is closest to target."""
        step = 10 ** np.floor(np.log10(S / 100)) if S >= 100 else 0.5
        T = max((pd.Timestamp(expiry) - ts).days / 365.0, 1e-3)
        best, best_err = S, np.inf
        for K in np.arange(np.floor(S * 0.6 / step), np.ceil(S * 1.4 / step) + 1) * step:
            iv = leg_iv(S, K, hv, self.skew, self.curvature)
            err = abs(abs(bs_greeks(S, K, T, self.r, iv, option_type)["delta"]) - delta)
            if err < best_err:
                best, best_err = float(K), err
        return best

    @staticmethod
    def _expiry(index: pd.DatetimeIndex, i: int, dte: int) -> Optional[str]:
        """First trading date at least ``dte`` calendar days after bar ``i``."""
        target = index[i] + pd.Timedelta(days=dte)
        j = index.searchsorted(target)
        return str(index[j].date()) if j < len(index) else None

    # --- driver ---

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        for code, df in data_map.items():
            close = df["close"].astype(float)
            hv = historical_volatility(close, default_iv=self.default_iv)
            signals += self._run(code, close, hv, self.capital / len(data_map))
        return signals

    def _run(self, code: str, close: pd.Series, hv: pd.Series,
             capital: float) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @staticmethod
    def _signal(ts: pd.Timestamp, action: str, code: str, legs: List[Leg]) -> Dict[str, Any]:
        return {"date": str(ts.date()), "action": action, "underlying": code,
                "legs": [dict(leg) for leg in legs]}

    def _stock_legs(self, close: pd.Series, qty: float) -> List[Leg]:
        """Share replica: call struck near zero, expiring after the data ends."""
        expiry = close.index[-1] + pd.Timedelta(days=400)
        return [{"type": "call", "strike": 0.01, "expiry": str(expiry.date()), "qty": qty}]


class _ShortPremium(_OptionsBook):
    """Open a structure, manage it to a profit target / DTE floor, repeat.

    Subclasses define ``_build`` (legs for one unit plus max loss per unit, or
    ``None`` to skip) and may override ``_gate``. Size compounds on the
    strategy's own realized P&L, so a drawdown shrinks the next trade.
    """

    dte = 45
    take_profit: Optional[float] = 0.5   # fraction of entry credit captured
    exit_dte: Optional[int] = 21         # close when this few days remain
    risk_fraction = 1.0                  # capital per trade / max-loss-or-notional per unit

    def _build(self, S: float, hv: float, ts: pd.Timestamp, expiry: str):
        raise NotImplementedError

    def _gate(self, close: pd.Series, hv: pd.Series, i: int) -> bool:
        return True

    def _run(self, code, close, hv, capital):
        idx = close.index
        out: List[Dict[str, Any]] = []
        legs: Optional[List[Leg]] = None
        credit = 0.0
        for i, ts in enumerate(idx):
            S, vol = float(close.iloc[i]), float(hv.iloc[i])
            if legs is not None:
                expiry = pd.Timestamp(legs[0]["expiry"])
                value = self._value(S, vol, ts, legs)  # negative for a short book
                if ts >= expiry:
                    # The engine settles at intrinsic; mirror it in our capital.
                    intrinsic = sum(max(0.0, (S - lg["strike"]) if lg["type"] == "call"
                                        else (lg["strike"] - S)) * lg["qty"] for lg in legs)
                    capital += credit + intrinsic
                    legs = None
                elif ((self.take_profit is not None and credit > 0
                       and credit + value >= self.take_profit * credit)
                      or (self.exit_dte is not None and (expiry - ts).days <= self.exit_dte)):
                    out.append(self._signal(ts, "close", code, legs))
                    capital += credit + value - self.commission * sum(
                        abs(self._price(S, vol, ts, lg) * lg["qty"]) for lg in legs)
                    legs = None
                    continue  # re-enter on the next bar, after the close fills
            if legs is not None or (self.start is not None and ts < self.start):
                continue
            if i + 1 >= len(idx) or not self._gate(close, hv, i):
                continue
            expiry = self._expiry(idx, i, self.dte)
            if expiry is None:
                continue
            built = self._build(S, vol, ts, expiry)
            if built is None:
                continue
            unit_legs, unit_risk = built
            qty = float(np.floor(self.risk_fraction * max(capital, 0.0) / unit_risk))
            if qty <= 0:
                continue
            legs = [dict(lg, qty=lg["qty"] * qty) for lg in unit_legs]
            credit = -self._value(S, vol, ts, legs) - self.commission * sum(
                abs(self._price(S, vol, ts, lg) * lg["qty"]) for lg in legs)
            out.append(self._signal(ts, "open", code, legs))
        return out


class CashSecuredPutEngine(_ShortPremium):
    """Sell a ~0.30-delta put, ~35 DTE, sized so cash covers assignment.

    Held to expiry and cash-settled (the engine has no share delivery), which
    is a wheel whose assigned shares are sold at once instead of having calls
    written against them.
    """

    def __init__(self, delta: float = 0.30, dte: int = 35, **kw: Any) -> None:
        super().__init__(**kw)
        self.delta, self.dte = delta, dte
        self.take_profit = self.exit_dte = None

    def _build(self, S, hv, ts, expiry):
        K = self._strike(S, hv, ts, expiry, "put", self.delta)
        return [{"type": "put", "strike": K, "expiry": expiry, "qty": -1}], K


class IronCondorEngine(_ShortPremium):
    """Short ~16-delta strangle with ~5-delta wings, 45 DTE, managed at
    50% of credit or 21 DTE. Risks ``risk_fraction`` of capital per trade."""

    def __init__(self, short_delta: float = 0.16, wing_delta: float = 0.05,
                 risk_fraction: float = 0.10, **kw: Any) -> None:
        super().__init__(**kw)
        self.short_delta, self.wing_delta = short_delta, wing_delta
        self.risk_fraction = risk_fraction

    def _build(self, S, hv, ts, expiry):
        sp = self._strike(S, hv, ts, expiry, "put", self.short_delta)
        lp = self._strike(S, hv, ts, expiry, "put", self.wing_delta)
        sc = self._strike(S, hv, ts, expiry, "call", self.short_delta)
        lc = self._strike(S, hv, ts, expiry, "call", self.wing_delta)
        if not (lp < sp < sc < lc):
            return None
        legs = [
            {"type": "put", "strike": sp, "expiry": expiry, "qty": -1},
            {"type": "put", "strike": lp, "expiry": expiry, "qty": 1},
            {"type": "call", "strike": sc, "expiry": expiry, "qty": -1},
            {"type": "call", "strike": lc, "expiry": expiry, "qty": 1},
        ]
        # Max loss ignoring the credit: conservative and independent of fills.
        return legs, max(sp - lp, lc - sc)


class VolGatedStrangleEngine(_ShortPremium):
    """Short ~16-delta strangle, 45 DTE, managed at 50% / 21 DTE, entered only
    when the realized-vol regime allows.

    ``gate``: ``"none"``; ``"contracting"`` -- 10-day vol below 30-day vol (sell
    after a spike has started to fade, never into a rising one); ``"elevated"``
    -- 30-day vol above its trailing 1-year median.
    """

    def __init__(self, delta: float = 0.16, gate: str = "contracting",
                 notional_fraction: float = 1.0, **kw: Any) -> None:
        super().__init__(**kw)
        self.delta, self.gate = delta, gate
        self.risk_fraction = notional_fraction

    def generate(self, data_map):
        self._hv10 = {c: historical_volatility(df["close"].astype(float), window=10,
                                               default_iv=self.default_iv)
                      for c, df in data_map.items()}
        return super().generate(data_map)

    def _run(self, code, close, hv, capital):
        self._code = code
        return super()._run(code, close, hv, capital)

    def _gate(self, close, hv, i):
        if self.gate == "contracting":
            return float(self._hv10[self._code].iloc[i]) < float(hv.iloc[i])
        if self.gate == "elevated":
            return i >= 252 and float(hv.iloc[i]) > float(hv.iloc[i - 252:i].median())
        return True

    def _build(self, S, hv, ts, expiry):
        legs = [
            {"type": "put", "strike": self._strike(S, hv, ts, expiry, "put", self.delta),
             "expiry": expiry, "qty": -1},
            {"type": "call", "strike": self._strike(S, hv, ts, expiry, "call", self.delta),
             "expiry": expiry, "qty": -1},
        ]
        return legs, S


class _StockPlusOption(_OptionsBook):
    """Hold the share replica from the start date; ``_overlay`` adds one
    rolling option leg (short call or long put) sized to the shares."""

    option_type = "call"
    side = -1

    def __init__(self, delta: float, dte: int, roll_dte: Optional[int] = None,
                 stock_fraction: float = 1.0, **kw: Any) -> None:
        super().__init__(**kw)
        self.delta, self.dte, self.roll_dte = delta, dte, roll_dte
        self.stock_fraction = stock_fraction

    def _run(self, code, close, hv, capital):
        idx = close.index
        out: List[Dict[str, Any]] = []
        stock = self._stock_legs(close, 0.0)[0]
        lots: List[float] = []   # replica lots, FIFO: the engine closes the oldest match first
        cash = capital
        leg: Optional[Leg] = None
        c = self.commission
        for i, ts in enumerate(idx[:-1]):
            if self.start is not None and ts < self.start:
                continue
            S, vol = float(close.iloc[i]), float(hv.iloc[i])
            px = lambda lg: self._price(S, vol, ts, lg)  # noqa: E731
            if leg is not None:
                expiry = pd.Timestamp(leg["expiry"])
                if ts >= expiry:
                    intrinsic = max(0.0, (S - leg["strike"]) if leg["type"] == "call"
                                    else (leg["strike"] - S))
                    cash += intrinsic * leg["qty"]
                    leg = None
                elif self.roll_dte is not None and (expiry - ts).days <= self.roll_dte:
                    out.append(self._signal(ts, "close", code, [leg]))
                    cash += px(leg) * leg["qty"] - c * abs(px(leg) * leg["qty"])
                    leg = None
                    continue
            if leg is not None:
                continue
            expiry = self._expiry(idx, i, self.dte)
            if expiry is None:
                continue
            # Re-size the shares to equity each cycle, as assignment and
            # re-buying would; otherwise settled calls/puts drift cash and leverage.
            held = sum(lots)
            target = float(np.floor(self.stock_fraction * (cash + held * px(stock)) / S))
            diff = target - held
            if held == 0 or abs(diff) > 0.02 * held:
                if diff > 0:
                    lots.append(diff)
                    out.append(self._signal(ts, "open", code, [dict(stock, qty=diff)]))
                else:
                    legs, left = [], -diff
                    while left > 0:
                        take = min(left, lots[0])
                        legs.append(dict(stock, qty=take))
                        lots[0] -= take
                        left -= take
                        if lots[0] == 0:
                            lots.pop(0)
                    out.append(self._signal(ts, "close", code, legs))
                cash -= diff * px(stock) + c * abs(diff * px(stock))
            K = self._strike(S, vol, ts, expiry, self.option_type, self.delta)
            leg = {"type": self.option_type, "strike": K, "expiry": expiry,
                   "qty": self.side * sum(lots)}
            out.append(self._signal(ts, "open", code, [leg]))
            cash -= px(leg) * leg["qty"] + c * abs(px(leg) * leg["qty"])
        return out


class CoveredCallEngine(_StockPlusOption):
    """Long shares, short a ~0.30-delta call ~35 DTE, held to expiry. An ITM
    call cash-settles and the shares are re-sized to equity, which is what
    assignment followed by re-buying amounts to."""

    def __init__(self, delta: float = 0.30, dte: int = 35, **kw: Any) -> None:
        super().__init__(delta=delta, dte=dte, **kw)


class ProtectivePutEngine(_StockPlusOption):
    """Long shares plus a ~0.20-delta put ~60 DTE, rolled at 21 DTE.
    The long-vol / insurance baseline."""

    option_type = "put"
    side = 1

    def __init__(self, delta: float = 0.20, dte: int = 60, roll_dte: int = 21,
                 **kw: Any) -> None:
        super().__init__(delta=delta, dte=dte, roll_dte=roll_dte, **kw)


ENGINES: Dict[str, Callable[..., _OptionsBook]] = {
    "covered_call": CoveredCallEngine,
    "cash_secured_put": CashSecuredPutEngine,
    "iron_condor": IronCondorEngine,
    "vol_gated_strangle": VolGatedStrangleEngine,
    "protective_put": ProtectivePutEngine,
}

SignalEngine = IronCondorEngine
