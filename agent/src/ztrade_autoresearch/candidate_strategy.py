"""Deterministic ztrade V47 candidate strategy.

This module is intentionally self-contained so rendered Vibe-Trading
``SignalEngine`` files can depend on one local class while preserving the
behavioral core of ztrade's ``v47_weak_guard_62_70`` profile:

* BrickChartV32Selector entry eligibility.
* S1 bear-volume exclusion.
* Daily composite candidate ranking and slot selection.
* V47 early-failure market, weak-breadth, gap, and capitulation guards.
* Brick-color pending sells with next-close confirmation.

Vibe-Trading shifts target signals by one bar, so signals emitted on a signal
date are the target positions for the next tradable bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np
import pandas as pd


@dataclass
class _Position:
    code: str
    buy_i: int
    buy_price: float
    entry_score: float
    buy_trade_i: int = 0
    red_count: int = 0


@dataclass
class _PendingSell:
    code: str
    detect_i: int
    stored_red_count: int


class ZTradeV47SignalEngine:
    """ztrade ``v47_weak_guard_62_70`` expressed as a Vibe SignalEngine."""

    def __init__(
        self,
        *,
        # v47 profile params
        s1_window: int = 7,
        s1_volume_ratio_min: float = 1.2,
        s1_max_age: int = 2,
        s1_stale_age_min: int | None = None,
        s1_stale_volume_ratio_min: float | None = None,
        early_failure_exit_enable: bool = True,
        early_failure_max_hold_days: int = 2,
        early_failure_loss_pct: float = 1.0,
        early_failure_market_weak_enable: bool = True,
        early_failure_market_ma_window: int = 20,
        early_failure_market_min_coverage: int = 2000,
        early_failure_market_below_ma_ratio_min: float = 0.55,
        early_failure_market_down_ratio_min: float = 0.50,
        early_failure_gap_guard_pct: float = 3.0,
        early_failure_gap_guard_capitulation_pct: float = 6.0,
        early_failure_gap_guard_capitulation_below_ma_ratio_max: float = 0.65,
        early_failure_gap_guard_capitulation_down_ratio_max: float = 0.75,
        early_failure_weak_breadth_guard_enable: bool = True,
        early_failure_weak_breadth_below_ma_ratio_max: float = 0.62,
        early_failure_weak_breadth_down_ratio_max: float = 0.70,
        # selector/backtest defaults used by ztrade V3
        max_positions: int = 4,
        max_hold_days: int = 20,
        brick_min_value: float = 3.0,
        max_window: int = 60,
        volume_window: int = 20,
        volume_ratio_min: float = 1.0,
        red_vs_prev_green_ratio_min: float = 2.0 / 3.0,
        max_red_day_gain_pct: float = 9.0,
        near_line_tolerance_pct: float = 1.5,
        red_day_gain_vol_window: int = 20,
        red_day_gain_vol_multiplier: float = 1.6,
        red_day_gain_floor_pct: float = 2.5,
        enable_reversal_repair_filter: bool = True,
        reversal_max_range_pct: float = 0.06,
        reversal_max_body_pct: float = 0.04,
        reversal_close_pos_min: float = 0.60,
        reversal_no_breakout_lookback: int = 15,
        enable_volume_confirmation: bool = True,
        enable_dif_confirmation: bool = True,
        dif_min_value: float = 0.0,
        active_start_date: str | None = None,
    ) -> None:
        self.s1_window = int(s1_window)
        self.s1_volume_ratio_min = float(s1_volume_ratio_min)
        self.s1_max_age = int(s1_max_age)
        self.s1_stale_age_min = None if s1_stale_age_min is None else int(s1_stale_age_min)
        self.s1_stale_volume_ratio_min = (
            None if s1_stale_volume_ratio_min is None else float(s1_stale_volume_ratio_min)
        )
        self.early_failure_exit_enable = bool(early_failure_exit_enable)
        self.early_failure_max_hold_days = int(early_failure_max_hold_days)
        self.early_failure_loss_pct = float(early_failure_loss_pct)
        self.early_failure_market_weak_enable = bool(early_failure_market_weak_enable)
        self.early_failure_market_ma_window = int(early_failure_market_ma_window)
        self.early_failure_market_min_coverage = int(early_failure_market_min_coverage)
        self.early_failure_market_below_ma_ratio_min = float(early_failure_market_below_ma_ratio_min)
        self.early_failure_market_down_ratio_min = float(early_failure_market_down_ratio_min)
        self.early_failure_gap_guard_pct = float(early_failure_gap_guard_pct)
        self.early_failure_gap_guard_capitulation_pct = float(early_failure_gap_guard_capitulation_pct)
        self.early_failure_gap_guard_capitulation_below_ma_ratio_max = float(
            early_failure_gap_guard_capitulation_below_ma_ratio_max
        )
        self.early_failure_gap_guard_capitulation_down_ratio_max = float(
            early_failure_gap_guard_capitulation_down_ratio_max
        )
        self.early_failure_weak_breadth_guard_enable = bool(early_failure_weak_breadth_guard_enable)
        self.early_failure_weak_breadth_below_ma_ratio_max = float(early_failure_weak_breadth_below_ma_ratio_max)
        self.early_failure_weak_breadth_down_ratio_max = float(early_failure_weak_breadth_down_ratio_max)

        self.max_positions = int(max_positions)
        self.max_hold_days = int(max_hold_days)
        self.brick_min_value = float(brick_min_value)
        self.max_window = int(max_window)
        self.volume_window = int(volume_window)
        self.volume_ratio_min = float(volume_ratio_min)
        self.red_vs_prev_green_ratio_min = float(red_vs_prev_green_ratio_min)
        self.max_red_day_gain_pct = float(max_red_day_gain_pct)
        self.near_line_tolerance_pct = float(near_line_tolerance_pct)
        self.red_day_gain_vol_window = int(red_day_gain_vol_window)
        self.red_day_gain_vol_multiplier = float(red_day_gain_vol_multiplier)
        self.red_day_gain_floor_pct = float(red_day_gain_floor_pct)
        self.enable_reversal_repair_filter = bool(enable_reversal_repair_filter)
        self.reversal_max_range_pct = float(reversal_max_range_pct)
        self.reversal_max_body_pct = float(reversal_max_body_pct)
        self.reversal_close_pos_min = float(reversal_close_pos_min)
        self.reversal_no_breakout_lookback = int(reversal_no_breakout_lookback)
        self.enable_volume_confirmation = bool(enable_volume_confirmation)
        self.enable_dif_confirmation = bool(enable_dif_confirmation)
        self.dif_min_value = float(dif_min_value)
        self.active_start_date = pd.Timestamp(active_start_date) if active_start_date else None

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Return per-symbol target weights for the reference V47 portfolio."""
        frames = {code: _with_indicators(_normalize_ohlcv(df)) for code, df in data_map.items()}
        if not frames:
            return {}
        dates = pd.DatetimeIndex(sorted(set().union(*(set(df.index) for df in frames.values()))))
        market_state = _market_breadth_state(frames, self)
        signals = {code: pd.Series(0.0, index=df.index, dtype=float) for code, df in frames.items()}
        positions: dict[str, _Position] = {}
        pending: dict[str, _PendingSell] = {}

        for i, ts in enumerate(dates):
            active = self.active_start_date is None or ts >= self.active_start_date
            if not active:
                continue

            self._execute_pending(ts, i, frames, positions, pending)
            self._detect_exits(ts, i, frames, market_state, positions, pending)
            self._select_buys(ts, i, dates, frames, positions, pending)

            weight_sum = sum(max(0.1, self._position_weight(pos)) for pos in positions.values())
            for code, pos in positions.items():
                if ts in signals[code].index:
                    signals[code].at[ts] = max(0.1, self._position_weight(pos)) / (weight_sum or 1.0)

        return {code: series.fillna(0.0).clip(0.0, 1.0) for code, series in signals.items()}

    def _execute_pending(
        self,
        ts: pd.Timestamp,
        i: int,
        frames: dict[str, pd.DataFrame],
        positions: dict[str, _Position],
        pending: dict[str, _PendingSell],
    ) -> None:
        for code, order in list(pending.items()):
            frame = frames.get(code)
            if frame is None or ts not in frame.index:
                continue
            current_i = frame.index.get_loc(ts)
            if isinstance(current_i, slice) or int(current_i) <= order.detect_i:
                continue
            row = frame.loc[ts]
            if bool(row.get("绿柱", False)):
                positions.pop(code, None)
                pending.pop(code, None)
            elif bool(row.get("红柱", False)):
                pos = positions.get(code)
                if pos:
                    pos.red_count = _count_consecutive_red(frame, ts, pos.buy_i)
                pending.pop(code, None)

    def _detect_exits(
        self,
        ts: pd.Timestamp,
        i: int,
        frames: dict[str, pd.DataFrame],
        market_state: pd.DataFrame,
        positions: dict[str, _Position],
        pending: dict[str, _PendingSell],
    ) -> None:
        for code, pos in list(positions.items()):
            if code in pending:
                continue
            frame = frames.get(code)
            if frame is None or ts not in frame.index:
                continue
            current_i = frame.index.get_loc(ts)
            if isinstance(current_i, slice):
                continue
            current_i = int(current_i)
            row = frame.loc[ts]
            stored_red_count = pos.red_count
            current_red_count = _count_consecutive_red(frame, ts, pos.buy_i)
            if current_red_count > 0:
                pos.red_count = current_red_count
            if self.max_hold_days > 0 and current_i - pos.buy_i >= self.max_hold_days:
                positions.pop(code, None)
                continue
            if not bool(row.get("绿柱", False)):
                continue
            close = float(row["close"])
            change_pct = (close / pos.buy_price - 1.0) * 100.0 if pos.buy_price > 0 else 0.0
            if stored_red_count >= 4:
                positions.pop(code, None)
                continue
            if self._early_failure_should_exit(ts, current_i, change_pct, pos, market_state):
                positions.pop(code, None)
                continue
            pending[code] = _PendingSell(code=code, detect_i=current_i, stored_red_count=stored_red_count)

    def _select_buys(
        self,
        ts: pd.Timestamp,
        i: int,
        dates: pd.DatetimeIndex,
        frames: dict[str, pd.DataFrame],
        positions: dict[str, _Position],
        pending: dict[str, _PendingSell],
    ) -> None:
        del i
        del dates
        available = max(0, self.max_positions - len(positions))
        if available <= 0:
            return
        factors: dict[str, dict[str, float]] = {}
        for code, frame in frames.items():
            if code in positions or code in pending or ts not in frame.index:
                continue
            hist = frame.loc[:ts].tail(max(self.max_window + 120, 200))
            passed, data = self._passes_filters(hist)
            if passed and data is not None:
                factors[code] = data
        composite = _compute_composite_score(factors)
        ranked = sorted(composite.items(), key=lambda item: item[1], reverse=True)
        opened = 0
        for code, score in ranked:
            frame = frames[code]
            buy_i = int(frame.index.searchsorted(ts, side="right"))
            if buy_i >= len(frame.index):
                continue
            buy_ts = frame.index[buy_i]
            buy_price = _price_at(frame, buy_ts, "open") or _price_at(frame, buy_ts, "close")
            if buy_price <= 0:
                continue
            positions[code] = _Position(
                code=code,
                buy_i=buy_i,
                buy_price=buy_price,
                entry_score=float(score),
                buy_trade_i=buy_i,
            )
            opened += 1
            if opened >= available:
                break

    def _passes_filters(self, hist: pd.DataFrame) -> tuple[bool, dict[str, float] | None]:
        if hist.empty or len(hist) < 12:
            return False, None
        if not self._passes_backtest_prefilter(hist):
            return False, None
        if self._has_s1_bear_volume(hist):
            return False, None
        passed, factors = self._passes_brick_chart(hist)
        if not passed or factors is None:
            return False, None
        daily_ok, near_score = self._passes_daily_zx_lines(hist)
        if not daily_ok:
            return False, None
        if not _weekly_short_line_ok(hist):
            return False, None
        factors["near_score"] = near_score
        return True, factors

    def _passes_backtest_prefilter(self, hist: pd.DataFrame) -> bool:
        """Mirror ztrade V3's mandatory fast prefilter before full selector scoring."""
        if len(hist) < 21:
            return False
        close = pd.to_numeric(hist["close"], errors="coerce")
        volume = pd.to_numeric(hist["volume"], errors="coerce")
        signal_pos = len(hist) - 1
        current_close = float(close.iloc[signal_pos])
        if pd.isna(current_close) or current_close < 2.0:
            return False
        prev_close = float(close.iloc[signal_pos - 1]) if signal_pos > 0 else current_close
        if pd.isna(prev_close) or prev_close <= 0:
            return False
        change_pct = (current_close - prev_close) / prev_close * 100.0
        if change_pct < -10.0 or change_pct > 15.0:
            return False
        lookback = min(6, signal_pos)
        if lookback >= 3:
            recent_closes = close.iloc[signal_pos - lookback : signal_pos + 1].to_numpy(dtype=float)
            has_decline = any(recent_closes[j] < recent_closes[j - 1] for j in range(1, len(recent_closes)))
            if not has_decline:
                return False
        volume_window = volume.iloc[max(0, signal_pos - 20) : signal_pos]
        if volume_window.empty:
            return False
        avg_volume = float(volume_window.mean())
        signal_volume = float(volume.iloc[signal_pos])
        if pd.isna(avg_volume) or avg_volume <= 0 or pd.isna(signal_volume):
            return False
        if signal_volume / avg_volume < 0.2:
            return False

        if {"红柱", "绿柱"}.issubset(hist.columns):
            brick_hist = hist
        else:
            brick_hist = _compute_brick_chart(hist.copy())
        if len(brick_hist) < 3:
            return False
        curr = brick_hist.iloc[-1]
        prev = brick_hist.iloc[-2]
        prev_prev = brick_hist.iloc[-3]
        return bool(curr.get("红柱", False)) and bool(prev.get("绿柱", False)) and bool(prev_prev.get("绿柱", False))

    def _has_s1_bear_volume(self, hist: pd.DataFrame) -> bool:
        window = hist.tail(self.s1_window).copy()
        if len(window) < 2:
            return False
        close = pd.to_numeric(window["close"], errors="coerce")
        volume = pd.to_numeric(window["volume"], errors="coerce")
        prev_close = close.shift(1)
        up_volumes = volume[close > prev_close].dropna()
        down_volumes = volume[close < prev_close].dropna()
        if up_volumes.empty or down_volumes.empty:
            return False
        down_idx = down_volumes.idxmax()
        down_pos = window.index.get_loc(down_idx)
        days_since_down = len(window) - 1 - down_pos
        if days_since_down > self.s1_max_age:
            return False
        up_max = float(up_volumes.max())
        if up_max <= 0:
            return False
        ratio_min = self.s1_volume_ratio_min
        if (
            self.s1_stale_age_min is not None
            and self.s1_stale_volume_ratio_min is not None
            and days_since_down >= self.s1_stale_age_min
        ):
            ratio_min = self.s1_stale_volume_ratio_min
        return float(down_volumes.loc[down_idx]) / up_max > ratio_min

    def _passes_brick_chart(self, hist: pd.DataFrame) -> tuple[bool, dict[str, float] | None]:
        if len(hist) < 12:
            return False, None
        brick_hist = _compute_brick_chart(hist.tail(max(self.max_window, 60)).copy())
        try:
            dif_series = _compute_dif(brick_hist) if self.enable_dif_confirmation else None
            curr_idx = len(brick_hist) - 1
            curr = brick_hist.iloc[curr_idx]
            prev = brick_hist.iloc[curr_idx - 1]
            prev_prev = brick_hist.iloc[curr_idx - 2]
        except (KeyError, ValueError, TypeError, IndexError):
            return False, None
        if not (bool(curr["红柱"]) and bool(prev["绿柱"]) and bool(prev_prev["绿柱"])):
            return False, None
        prev_green_height = float(prev_prev["砖型图"]) - float(prev["砖型图"])
        red_height = float(curr["砖型图"]) - float(prev["砖型图"])
        if prev_green_height <= 0 or red_height <= 0:
            return False, None
        if red_height < prev_green_height * self.red_vs_prev_green_ratio_min:
            return False, None
        prev_close = float(prev["close"])
        curr_close = float(curr["close"])
        if prev_close <= 0:
            return False, None
        red_day_gain_pct = (curr_close / prev_close - 1.0) * 100.0
        dynamic_limit = self._dynamic_red_day_gain_limit(brick_hist, curr_idx)
        if red_day_gain_pct > dynamic_limit:
            return False, None
        if self.enable_reversal_repair_filter and not self._passes_reversal_repair_candle_at(brick_hist, curr_idx):
            return False, None
        if self.enable_volume_confirmation and not self._passes_volume_confirmation_at(brick_hist, curr_idx):
            return False, None
        dif_val = 0.0
        if self.enable_dif_confirmation and dif_series is not None:
            dif_val = float(dif_series.iloc[curr_idx])
            if pd.isna(dif_val) or dif_val < self.dif_min_value:
                return False, None
        if float(curr["砖型图"]) < self.brick_min_value:
            return False, None
        vol_today = float(brick_hist["volume"].iloc[curr_idx])
        prev_vol = brick_hist["volume"].iloc[max(0, curr_idx - self.volume_window) : curr_idx]
        vol_avg = float(prev_vol.mean()) if not prev_vol.empty else 1.0
        return True, {
            "brick_ratio": red_height / prev_green_height,
            "vol_ratio": vol_today / vol_avg if vol_avg > 0 else 0.0,
            "dif_val": dif_val,
            "gain_margin": max(0.0, dynamic_limit - red_day_gain_pct),
        }

    def _dynamic_red_day_gain_limit(self, hist: pd.DataFrame, curr_idx: int) -> float:
        abs_ret = hist["close"].pct_change().abs() * 100.0
        start_idx = max(1, curr_idx - self.red_day_gain_vol_window)
        vol_window = abs_ret.iloc[start_idx:curr_idx].dropna()
        if vol_window.empty:
            return self.red_day_gain_floor_pct
        recent_vol = float(vol_window.median())
        return min(max(recent_vol * self.red_day_gain_vol_multiplier, self.red_day_gain_floor_pct), self.max_red_day_gain_pct)

    def _passes_reversal_repair_candle_at(self, hist: pd.DataFrame, curr_idx: int) -> bool:
        if curr_idx < 1:
            return False
        latest = hist.iloc[curr_idx]
        prev = hist.iloc[curr_idx - 1]
        prev_close = float(prev["close"])
        if prev_close <= 0:
            return False
        high = float(latest["high"])
        low = float(latest["low"])
        open_ = float(latest["open"])
        close = float(latest["close"])
        candle_range = high - low
        if candle_range <= 0:
            return False
        if candle_range / prev_close > self.reversal_max_range_pct:
            return False
        if abs(close - open_) / prev_close > self.reversal_max_body_pct:
            return False
        if close < open_:
            return False
        if (close - low) / (candle_range + 1e-9) < self.reversal_close_pos_min:
            return False
        start_idx = max(0, curr_idx - max(1, self.reversal_no_breakout_lookback))
        prev_high = float(hist["high"].iloc[start_idx:curr_idx].max())
        return not pd.isna(prev_high) and high <= prev_high

    def _passes_volume_confirmation_at(self, hist: pd.DataFrame, curr_idx: int) -> bool:
        if curr_idx < 1:
            return False
        volume_today = float(hist["volume"].iloc[curr_idx])
        if volume_today <= 0:
            return False
        prev_window = hist["volume"].iloc[max(0, curr_idx - self.volume_window) : curr_idx]
        if prev_window.empty:
            return False
        avg_volume = float(prev_window.mean())
        return avg_volume > 0 and volume_today >= avg_volume * self.volume_ratio_min

    def _passes_daily_zx_lines(self, hist: pd.DataFrame) -> tuple[bool, float]:
        window = hist.tail(max(self.max_window, 120))
        if window.empty:
            return False, 0.0
        latest_close = float(window["close"].iloc[-1])
        if latest_close <= 0:
            return False, 0.0
        short_line = _short_line(window["close"])
        multi_line = _zx_multi_line(window["close"])
        short_val = float(short_line.iloc[-1])
        multi_val = float(multi_line.iloc[-1])
        if pd.isna(short_val) or pd.isna(multi_val) or multi_val <= 0:
            return False, 0.0
        if short_val <= multi_val or latest_close <= multi_val:
            return False, 0.0
        dist_short_pct = abs(latest_close / short_val - 1.0) * 100.0
        dist_multi_pct = abs(latest_close / multi_val - 1.0) * 100.0
        near_score = 1.0 if min(dist_short_pct, dist_multi_pct) <= self.near_line_tolerance_pct else 0.0
        return True, near_score

    def _early_failure_should_exit(
        self,
        ts: pd.Timestamp,
        i: int,
        change_pct: float,
        pos: _Position,
        market_state: pd.DataFrame,
    ) -> bool:
        if not self.early_failure_exit_enable:
            return False
        hold_days = i - pos.buy_i
        if hold_days > self.early_failure_max_hold_days or change_pct > -self.early_failure_loss_pct:
            return False
        state = _state_at(market_state, ts)
        market_weak = bool(state.get("is_weak", False)) if state else False
        return self._early_failure_skip_reason(change_pct, market_weak, state) == ""

    def _early_failure_skip_reason(self, change_pct: float, market_weak: bool, state: dict[str, Any]) -> str:
        if self.early_failure_market_weak_enable and market_weak is not True:
            return "market_not_weak"
        below = float(state.get("below_ma_ratio", 0.0))
        down = float(state.get("down_ratio", 0.0))
        if self.early_failure_weak_breadth_guard_enable:
            if (
                below > self.early_failure_weak_breadth_below_ma_ratio_max
                or down > self.early_failure_weak_breadth_down_ratio_max
            ):
                return "market_too_weak"
        if self.early_failure_gap_guard_pct > 0 and change_pct <= -self.early_failure_gap_guard_pct:
            if (
                self.early_failure_gap_guard_capitulation_pct > self.early_failure_gap_guard_pct
                and change_pct <= -self.early_failure_gap_guard_capitulation_pct
                and below <= self.early_failure_gap_guard_capitulation_below_ma_ratio_max
                and down <= self.early_failure_gap_guard_capitulation_down_ratio_max
            ):
                return ""
            return "gap_guard"
        return ""

    def _position_weight(self, pos: _Position) -> float:
        del pos
        return 1.0


class SignalEngine(ZTradeV47SignalEngine):
    """Default V47 baseline SignalEngine for Vibe-Trading backtests."""


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        if "date" in out.columns:
            out.index = pd.to_datetime(out["date"])
        else:
            out.index = pd.to_datetime(out.index)
    if "volume" not in out.columns and "vol" in out.columns:
        out["volume"] = out["vol"]
    for col in ("open", "high", "low", "close", "volume"):
        if col not in out.columns:
            raise ValueError(f"missing required OHLCV column: {col}")
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.sort_index()
    out["date"] = out.index
    return out


def _with_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = _compute_brick_chart(df)
    out["dif"] = _compute_dif(out)
    out["short_line"] = _short_line(out["close"])
    out["multi_line"] = _zx_multi_line(out["close"])
    return out


def _sma(series: pd.Series, n: int, m: int) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    result = np.full(len(values), np.nan, dtype=float)
    if len(values) < n:
        return pd.Series(result, index=series.index, dtype=float)
    result[n - 1] = np.nanmean(values[:n])
    alpha = m / n
    beta = 1.0 - alpha
    for i in range(n, len(values)):
        result[i] = alpha * values[i] + beta * result[i - 1]
    return pd.Series(result, index=series.index, dtype=float)


def _compute_brick_chart(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty or len(out) < 10:
        out["砖型图"] = 0.0
        out["红柱"] = False
        out["绿柱"] = False
        return out
    hhv_high = out["high"].rolling(window=4, min_periods=1).max()
    llv_low = out["low"].rolling(window=4, min_periods=1).min()
    denom = hhv_high - llv_low
    var1a = (hhv_high - out["close"]) / (denom + 1e-9) * 100 - 90
    var2a = _sma(var1a, 4, 1) + 100
    var3a = (out["close"] - llv_low) / (denom + 1e-9) * 100
    var4a = _sma(var3a, 6, 1)
    var5a = _sma(var4a, 6, 1) + 100
    var6a = var5a - var2a
    out["砖型图"] = (var6a - 4).where(var6a > 4, 0)
    out["红柱"] = out["砖型图"].diff().gt(0)
    out["绿柱"] = out["砖型图"].diff().lt(0)
    return out


def _compute_dif(df: pd.DataFrame, fast: int = 12, slow: int = 26) -> pd.Series:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


def _short_line(close: pd.Series) -> pd.Series:
    ema10 = close.ewm(span=10, adjust=False).mean()
    return ema10.ewm(span=10, adjust=False).mean()


def _zx_multi_line(close: pd.Series) -> pd.Series:
    ma14 = close.rolling(window=14, min_periods=1).mean()
    ma20 = close.rolling(window=20, min_periods=1).mean()
    ma57 = close.rolling(window=57, min_periods=1).mean()
    ma114 = close.rolling(window=114, min_periods=1).mean() if len(close) >= 114 else ma57
    return (ma14 + ma20 + ma57 + ma114) / 4.0


def _weekly_short_line_ok(hist: pd.DataFrame) -> bool:
    frame = hist.tail(260).copy()
    if frame.empty:
        return False
    date_values = pd.Series(pd.to_datetime(frame["date"] if "date" in frame.columns else frame.index), index=frame.index)
    week_key = date_values.dt.isocalendar().week + date_values.dt.year * 100
    weekly = frame.assign(_week=week_key.to_numpy()).groupby("_week").agg({"close": "last"})
    if len(weekly) < 10:
        return False
    weekly_short = _short_line(weekly["close"])
    latest_close = float(weekly["close"].iloc[-1])
    latest_short = float(weekly_short.iloc[-1])
    return not pd.isna(latest_short) and latest_short > 0 and latest_close > latest_short


def _market_breadth_state(data_map: Dict[str, pd.DataFrame], engine: ZTradeV47SignalEngine) -> pd.DataFrame:
    rows = []
    all_dates = pd.DatetimeIndex(sorted(set().union(*(set(df.index) for df in data_map.values()))))
    for ts in all_dates:
        covered = below_ma = down = 0
        for df in data_map.values():
            if ts not in df.index:
                continue
            idx = df.index.get_loc(ts)
            if isinstance(idx, slice) or idx <= 0 or idx + 1 < engine.early_failure_market_ma_window:
                continue
            close = pd.to_numeric(df["close"], errors="coerce")
            current = float(close.iloc[idx])
            previous = float(close.iloc[idx - 1])
            ma_value = float(close.iloc[idx - engine.early_failure_market_ma_window + 1 : idx + 1].mean())
            if any(pd.isna(v) for v in (current, previous, ma_value)) or current <= 0 or previous <= 0:
                continue
            covered += 1
            below_ma += int(current < ma_value)
            down += int(current < previous)
        below_ratio = below_ma / covered if covered else 0.0
        down_ratio = down / covered if covered else 0.0
        is_weak = (
            covered >= engine.early_failure_market_min_coverage
            and below_ratio >= engine.early_failure_market_below_ma_ratio_min
            and down_ratio >= engine.early_failure_market_down_ratio_min
        )
        rows.append(
            {
                "date": ts,
                "covered": covered,
                "below_ma_ratio": below_ratio,
                "down_ratio": down_ratio,
                "is_weak": is_weak,
            }
        )
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def _state_at(market_state: pd.DataFrame, ts: pd.Timestamp) -> dict[str, Any]:
    if market_state.empty:
        return {}
    if ts in market_state.index:
        return dict(market_state.loc[ts])
    idx = market_state.index.searchsorted(ts, side="right") - 1
    if idx < 0:
        return {}
    return dict(market_state.iloc[idx])


def _compute_composite_score(factor_data: dict[str, dict[str, float]]) -> dict[str, float]:
    if not factor_data:
        return {}
    codes = list(factor_data)
    brick = _percentile_rank([factor_data[c]["brick_ratio"] for c in codes])
    vol = _percentile_rank([factor_data[c]["vol_ratio"] for c in codes])
    dif = _percentile_rank([factor_data[c]["dif_val"] for c in codes])
    gain = _percentile_rank([factor_data[c]["gain_margin"] for c in codes])
    result = {}
    for i, code in enumerate(codes):
        near = float(factor_data[code].get("near_score", 0.0))
        result[code] = near * 0.30 + brick[i] * 0.35 + vol[i] * 0.15 + dif[i] * 0.15 + gain[i] * 0.05
    return result


def _percentile_rank(values: list[float]) -> list[float]:
    if not values:
        return []
    sorted_vals = sorted(values)
    n = len(values)
    return [sum(1 for item in sorted_vals if item <= value) / n for value in values]


def _count_consecutive_red(frame: pd.DataFrame, ts: pd.Timestamp, buy_i: int) -> int:
    if ts not in frame.index:
        return 0
    idx = frame.index.get_loc(ts)
    if isinstance(idx, slice):
        return 0
    count = 0
    for pos in range(int(idx), max(-1, buy_i - 1), -1):
        if bool(frame["红柱"].iloc[pos]):
            count += 1
        else:
            break
    return count


def _price_at(frame: pd.DataFrame, ts: pd.Timestamp, col: str) -> float:
    if ts not in frame.index or col not in frame.columns:
        return 0.0
    value = float(frame.at[ts, col])
    return 0.0 if pd.isna(value) else value
