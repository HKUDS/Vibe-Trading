"""Deterministic ztrade V47-style candidate strategy.

The file is intentionally self-contained. Future agent edits in the "middle
version" are allowed to add helper functions here, but not new dependencies.

The implementation is a Vibe-Trading signal-engine adaptation of ztrade's
current best profile, ``v47_weak_guard_62_70``. It preserves the key research
intent instead of importing ztrade internals:

* S1-style recent reversal setup.
* Volume confirmation around the reversal.
* ZX multi-line trend confirmation.
* Weekly short-line confirmation.
* Early-failure exit guard.

Vibe-Trading's backtest engine shifts signals by one bar, so a signal at bar t
is executed at the next bar open.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


class ZTradeV47SignalEngine:
    """V47 weak-guard strategy expressed as a Vibe-Trading SignalEngine."""

    def __init__(
        self,
        s1_window: int = 7,
        s1_volume_ratio_min: float = 1.2,
        s1_max_age: int = 2,
        early_failure_exit_enable: bool = True,
        early_failure_max_hold_days: int = 2,
        early_failure_loss_pct: float = 1.0,
        early_failure_market_below_ma_ratio_min: float = 0.55,
        early_failure_market_down_ratio_min: float = 0.50,
        early_failure_weak_breadth_below_ma_ratio_max: float = 0.62,
        early_failure_weak_breadth_down_ratio_max: float = 0.70,
        trend_line_tolerance_pct: float = 1.5,
        active_start_date: str | None = None,
    ) -> None:
        self.s1_window = int(s1_window)
        self.s1_volume_ratio_min = float(s1_volume_ratio_min)
        self.s1_max_age = int(s1_max_age)
        self.early_failure_exit_enable = bool(early_failure_exit_enable)
        self.early_failure_max_hold_days = int(early_failure_max_hold_days)
        self.early_failure_loss_pct = float(early_failure_loss_pct)
        self.early_failure_market_below_ma_ratio_min = float(early_failure_market_below_ma_ratio_min)
        self.early_failure_market_down_ratio_min = float(early_failure_market_down_ratio_min)
        self.early_failure_weak_breadth_below_ma_ratio_max = float(early_failure_weak_breadth_below_ma_ratio_max)
        self.early_failure_weak_breadth_down_ratio_max = float(early_failure_weak_breadth_down_ratio_max)
        self.trend_line_tolerance_pct = float(trend_line_tolerance_pct)
        self.active_start_date = pd.Timestamp(active_start_date) if active_start_date else None

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Return per-symbol target signals: 1 for long, 0 for flat."""
        market_state = _market_breadth_state(data_map)
        return {code: self._generate_one(_normalize_ohlcv(df), market_state) for code, df in data_map.items()}

    def _generate_one(self, df: pd.DataFrame, market_state: pd.DataFrame) -> pd.Series:
        if len(df) < 30:
            return pd.Series(0.0, index=df.index)

        close = df["close"].astype(float)
        short_line = _short_line(close)
        multi_line = _zx_multi_line(close)
        volume_ratio = _volume_ratio(df["volume"].astype(float), 20)
        weekly_ok = _weekly_short_line_ok(df)
        setup = _recent_reversal_setup(
            df,
            short_line=short_line,
            multi_line=multi_line,
            volume_ratio=volume_ratio,
            s1_window=self.s1_window,
            s1_max_age=self.s1_max_age,
            volume_ratio_min=self.s1_volume_ratio_min,
            trend_line_tolerance_pct=self.trend_line_tolerance_pct,
            weekly_ok=weekly_ok,
        )

        signals = pd.Series(0.0, index=df.index)
        in_position = False
        entry_price = 0.0
        entry_i = -1
        for i, ts in enumerate(df.index):
            price = float(close.iloc[i])
            if price <= 0 or np.isnan(price):
                continue

            if not in_position:
                if bool(setup.iloc[i]):
                    in_position = True
                    entry_price = price
                    entry_i = i
                    signals.iloc[i] = 1.0
                continue

            hold_bars = i - entry_i
            ret_pct = (price / entry_price - 1.0) * 100.0 if entry_price > 0 else 0.0
            weak_market = _weak_market_at(ts, market_state, self)
            exit_signal = price < float(short_line.iloc[i]) or price < float(multi_line.iloc[i])
            if (
                self.early_failure_exit_enable
                and hold_bars <= self.early_failure_max_hold_days
                and ret_pct <= -self.early_failure_loss_pct
                and weak_market
            ):
                exit_signal = True

            if exit_signal:
                in_position = False
                entry_price = 0.0
                entry_i = -1
                signals.iloc[i] = 0.0
            else:
                signals.iloc[i] = 1.0

        signals = signals.fillna(0.0).clip(0.0, 1.0)
        if self.active_start_date is not None:
            signals.loc[signals.index < self.active_start_date] = 0.0
        return signals


class SignalEngine(ZTradeV47SignalEngine):
    """Default V47 baseline SignalEngine for Vibe-Trading backtests."""


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    if "volume" not in out.columns and "vol" in out.columns:
        out["volume"] = out["vol"]
    for col in ("open", "high", "low", "close", "volume"):
        if col not in out.columns:
            raise ValueError(f"missing required OHLCV column: {col}")
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.sort_index()


def _short_line(close: pd.Series) -> pd.Series:
    ema10 = close.ewm(span=10, adjust=False).mean()
    return ema10.ewm(span=10, adjust=False).mean()


def _zx_multi_line(close: pd.Series) -> pd.Series:
    ma14 = close.rolling(window=14, min_periods=1).mean()
    ma20 = close.rolling(window=20, min_periods=1).mean()
    ma57 = close.rolling(window=57, min_periods=1).mean()
    ma114 = close.rolling(window=114, min_periods=1).mean() if len(close) >= 114 else ma57
    return (ma14 + ma20 + ma57 + ma114) / 4.0


def _volume_ratio(volume: pd.Series, window: int) -> pd.Series:
    base = volume.rolling(window=window, min_periods=3).mean().shift(1)
    return volume / base.replace(0.0, np.nan)


def _weekly_short_line_ok(df: pd.DataFrame) -> pd.Series:
    weekly_close = df["close"].resample("W-FRI").last().dropna()
    if weekly_close.empty:
        return pd.Series(False, index=df.index)
    weekly_short = _short_line(weekly_close)
    ok = (weekly_close > weekly_short).reindex(df.index, method="ffill")
    return ok.fillna(False).astype(bool)


def _recent_reversal_setup(
    df: pd.DataFrame,
    *,
    short_line: pd.Series,
    multi_line: pd.Series,
    volume_ratio: pd.Series,
    s1_window: int,
    s1_max_age: int,
    volume_ratio_min: float,
    trend_line_tolerance_pct: float,
    weekly_ok: pd.Series,
) -> pd.Series:
    close = df["close"].astype(float)
    open_ = df["open"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = close.shift(1)

    crossed_short = (close > short_line) & (close.shift(1) <= short_line.shift(1))
    above_multi = close > multi_line
    near_line = ((close / short_line - 1.0).abs() * 100.0 <= trend_line_tolerance_pct) | (
        (close / multi_line - 1.0).abs() * 100.0 <= trend_line_tolerance_pct
    )
    repair_candle = (
        (close >= open_)
        & (((high - low) / prev_close.replace(0.0, np.nan)) <= 0.06)
        & (((close - open_).abs() / prev_close.replace(0.0, np.nan)) <= 0.04)
        & (((close - low) / (high - low).replace(0.0, np.nan)) >= 0.60)
    )
    recent_cross = crossed_short.rolling(window=max(1, s1_window), min_periods=1).max().astype(bool)
    fresh_cross = crossed_short.rolling(window=max(1, s1_max_age + 1), min_periods=1).max().astype(bool)
    volume_ok = volume_ratio >= volume_ratio_min
    return (recent_cross & fresh_cross & above_multi & near_line & repair_candle & volume_ok & weekly_ok).fillna(False)


def _market_breadth_state(data_map: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for df in data_map.values():
        norm = _normalize_ohlcv(df)
        close = norm["close"].astype(float)
        ma = close.rolling(window=20, min_periods=5).mean()
        frames.append(pd.DataFrame({"below_ma": close < ma, "down": close.pct_change() < 0}, index=norm.index))
    if not frames:
        return pd.DataFrame(columns=["below_ma_ratio", "down_ratio"])
    below = pd.concat([f["below_ma"] for f in frames], axis=1).mean(axis=1)
    down = pd.concat([f["down"] for f in frames], axis=1).mean(axis=1)
    return pd.DataFrame({"below_ma_ratio": below, "down_ratio": down})


def _weak_market_at(ts: pd.Timestamp, market_state: pd.DataFrame, engine: ZTradeV47SignalEngine) -> bool:
    if market_state.empty:
        return True
    if ts not in market_state.index:
        idx = market_state.index.searchsorted(ts, side="right") - 1
        if idx < 0:
            return True
        row = market_state.iloc[idx]
    else:
        row = market_state.loc[ts]
    below = float(row.get("below_ma_ratio", 0.0))
    down = float(row.get("down_ratio", 0.0))
    market_weak = below >= engine.early_failure_market_below_ma_ratio_min and down >= engine.early_failure_market_down_ratio_min
    not_extreme = below <= engine.early_failure_weak_breadth_below_ma_ratio_max and down <= engine.early_failure_weak_breadth_down_ratio_max
    return market_weak and not_extreme
