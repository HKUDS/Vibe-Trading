"""Base backtest engine with shared bar-by-bar execution loop.

All market engines inherit from BaseEngine and override market-rule methods.
The shared run_backtest() handles: data loading → signal generation →
pre-compute target weights (with optimizer) → bar-by-bar execution with
market rule enforcement → metrics → artifacts.
"""

from __future__ import annotations

import importlib
import json
import logging
import math
import re as _re
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.constraints import apply_constraints_frame, load_constraints
from backtest.loaders.rsshub_events import (
    FeedSpec,
    RSSHubEventProvider,
    enrich_price_frames_with_events,
    feed_specs_from_config,
)
from backtest.loaders.tushare_fundamentals import (
    TushareFundamentalProvider,
    enrich_price_frames_with_fundamentals,
)
from backtest.metrics import (
    bar_returns,
    by_exit_reason_stats,
    by_symbol_stats,
    calc_fill_turnover_series,
    calc_metrics,
)
from backtest.models import EquitySnapshot, FillRecord, Position, TradeRecord


def _json_safe_scalar_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Scalar metrics for stdout JSON; non-finite floats become null."""
    return {
        k: (None if isinstance(v, float) and not math.isfinite(v) else v)
        for k, v in metrics.items()
        if not isinstance(v, dict)
    }

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _OpenOrder:
    """A fully priced opening order that can be committed atomically."""

    symbol: str
    direction: int
    price: float
    size: float
    leverage: float
    margin: float
    commission: float

    @property
    def cost(self) -> float:
        """Cash consumed by the fill."""
        return self.margin + self.commission


@dataclass(frozen=True)
class _ReductionOrder:
    before: Position
    target_size: float
    price: float
    released_margin: float
    realized_pnl: float
    exit_commission: float

    @property
    def capital_credit(self) -> float:
        return self.released_margin + self.realized_pnl - self.exit_commission


def _run_card_data_sources(config: Dict[str, Any], loader: Any) -> List[str]:
    """Return source names for run-card evidence."""
    configured = config.get("_run_card_effective_sources")
    if isinstance(configured, list):
        return [str(source) for source in configured if str(source).strip()]
    if isinstance(configured, str) and configured.strip():
        return [configured.strip()]

    loader_name = getattr(loader, "name", None)
    if loader_name:
        return [str(loader_name)]

    source = config.get("source")
    return [str(source)] if source else []


# ─── Market detection (lightweight, for signal alignment only) ───

_CRYPTO_RE = _re.compile(r"^[A-Z]+-USDT$|^[A-Z]+/USDT$", _re.I)
_FOREX_RE = _re.compile(r"^[A-Z]{3}/[A-Z]{3}$|^[A-Z]{6}\.FX$")


def _detect_market_for_align(code: str) -> str:
    """Lightweight market detection for ffill_limit calculation."""
    if _CRYPTO_RE.match(code):
        return "crypto"
    if _FOREX_RE.match(code):
        return "forex"
    return "equity"


# ─── Forward-fill helpers (numpy, avoid pandas overhead) ───


def _ffill_1d(col: np.ndarray, limit: int) -> None:
    """In-place forward-fill a 1D array with limit."""
    count = 0
    last_valid = np.nan
    for i in range(len(col)):
        if np.isnan(col[i]):
            count += 1
            if count <= limit and not np.isnan(last_valid):
                col[i] = last_valid
        else:
            last_valid = col[i]
            count = 0


def _ffill_2d(arr: np.ndarray, limit: int = 5) -> np.ndarray:
    """Forward-fill NaN values column-wise with limit."""
    out = arr.copy()
    for col in range(out.shape[1]):
        _ffill_1d(out[:, col], limit)
    return out


# ─── Signal alignment (reused from daily_portfolio logic) ───


def _align(
    data_map: Dict[str, pd.DataFrame],
    signal_map: Dict[str, pd.Series],
    codes: List[str],
    optimizer: Optional[Callable] = None,
) -> tuple:
    """Build aligned date index, close matrix, target-position matrix, return matrix.

    Signal is shifted by 1 bar (next-bar-open semantics) then normalised so
    ``sum(abs(weights)) <= 1.0``.

    Args:
        data_map: code -> OHLCV DataFrame.
        signal_map: code -> signal Series.
        codes: Valid instrument codes.
        optimizer: Optional weight optimiser ``(ret, pos, dates) -> pos``.

    Returns:
        (dates, close_df, positions_df, returns_df)
    """
    # Build unified sorted date index from all symbols' trading calendars
    indexes = [data_map[c].index for c in codes]
    merged = np.unique(np.concatenate([index.asi8 for index in indexes]))
    common_tz = indexes[0].tz
    if all(index.tz == common_tz for index in indexes) and common_tz is not None:
        dates = pd.DatetimeIndex(pd.to_datetime(merged, utc=True).tz_convert(common_tz))
    else:
        dates = pd.DatetimeIndex(merged)

    n_dates = len(dates)
    n_codes = len(codes)

    # Use int64 view for O(log n) searchsorted lookups
    dates_i8 = dates.values.view("i8")

    # ffill with limit to avoid masking long suspensions (e.g. 3-week halt)
    # Cross-market needs larger limit (Chinese New Year can be 9-10 bars)
    ffill_limit = 10 if len({_detect_market_for_align(c) for c in codes}) > 1 else 5

    # Build close matrix via numpy direct fill + searchsorted index mapping
    close_arr = np.full((n_dates, n_codes), np.nan)
    for j, c in enumerate(codes):
        series = data_map[c]["close"]
        row_idx = np.searchsorted(dates_i8, series.index.values.view("i8"))
        close_arr[row_idx, j] = series.values

    # Vectorized ffill with limit using pandas (C-optimized internals)
    _tmp = pd.DataFrame(close_arr)
    close_arr = _tmp.ffill(limit=ffill_limit).values

    # Drop symbols that are entirely NaN (no data overlap with date range)
    all_nan_mask = np.all(np.isnan(close_arr), axis=0)
    all_nan_cols = [codes[j] for j in range(n_codes) if all_nan_mask[j]]
    if all_nan_cols:
        logger.warning("Symbols dropped (no usable price data): %s", all_nan_cols)
        keep_mask = ~all_nan_mask
        codes = [codes[j] for j in range(n_codes) if keep_mask[j]]
        if not codes:
            raise ValueError("All symbols have no data in the requested date range")
        close_arr = close_arr[:, keep_mask]
        n_codes = len(codes)

    # Build position matrix: shift on each symbol's OWN calendar, then fill
    pos_arr = np.full((n_dates, n_codes), np.nan)
    for j, c in enumerate(codes):
        # Get signal values aligned to own trading calendar.
        # copy=True guarantees a writable array: with copy=False, an already
        # float64 source returns a read-only view (e.g. pandas copy-on-write),
        # which the in-place nan_to_num/clip below would reject.
        own_idx = data_map[c].index
        sig_vals = signal_map[c].reindex(own_idx).values.astype(np.float64, copy=True)
        # fillna(0) + clip in numpy
        np.nan_to_num(sig_vals, copy=False, nan=0.0)
        np.clip(sig_vals, -1.0, 1.0, out=sig_vals)
        # shift(1) + fillna(0): prepend 0, drop last
        shifted_vals = np.empty_like(sig_vals)
        shifted_vals[0] = 0.0
        shifted_vals[1:] = sig_vals[:-1]
        # Place into unified grid via searchsorted
        row_idx = np.searchsorted(dates_i8, own_idx.values.view("i8"))
        pos_arr[row_idx, j] = shifted_vals

    # Vectorized ffill with limit using pandas (C-optimized)
    _tmp = pd.DataFrame(pos_arr)
    # ``.values`` may be a read-only view under pandas copy-on-write; take the
    # copy-returning nan_to_num (not in-place) so the fill never writes a
    # read-only destination.
    pos_arr = np.nan_to_num(_tmp.ffill(limit=ffill_limit).values, nan=0.0)

    # Construct DataFrames for return
    close = pd.DataFrame(close_arr, index=dates, columns=codes)
    pos = pd.DataFrame(pos_arr, index=dates, columns=codes)
    ret = bar_returns(close, label="engine per-symbol returns")

    if optimizer is not None:
        pos = optimizer(ret, pos, dates)

    scale = pos.abs().sum(axis=1).clip(lower=1.0)
    pos = pos.div(scale, axis=0)

    return dates, close, pos, ret


def _load_optimizer(config: Dict[str, Any]) -> Optional[Callable]:
    """Dynamically load an optimizer function from config.

    Args:
        config: Backtest configuration.

    Returns:
        Optimizer callable, or None.
    """
    opt_name = config.get("optimizer")
    constraints = load_constraints(config)
    if not opt_name:
        if constraints:
            print("[WARN] 'constraints' only act on optimizer output, "
                  "set 'optimizer' to use them; ignoring")
        return None
    opt_params = config.get("optimizer_params") or {}
    try:
        mod = importlib.import_module(f"backtest.optimizers.{opt_name}")
    except (ImportError, AttributeError) as e:
        print(f"[WARN] Failed to load optimizer '{opt_name}': {e}, falling back to equal weight")
        return None

    def optimize(ret: pd.DataFrame, pos: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
        out = mod.optimize(ret, pos, dates, **opt_params)
        return apply_constraints_frame(out, constraints)

    return optimize


def _normalise_fundamental_fields(config: Dict[str, Any]) -> dict[str, list[str]]:
    """Read the optional statement-table field map from backtest config."""
    raw_fields = config.get("fundamental_fields")
    if raw_fields in (None, {}):
        return {}
    if not isinstance(raw_fields, dict):
        raise ValueError("fundamental_fields must map table names to field-name lists")

    normalized: dict[str, list[str]] = {}
    for table, fields in raw_fields.items():
        if not isinstance(table, str) or not table.strip():
            raise ValueError("fundamental_fields table names must be non-empty strings")
        if fields is None:
            continue
        if isinstance(fields, str) or not isinstance(fields, Iterable):
            raise ValueError(f"fundamental_fields[{table!r}] must be a list of field names")

        field_list = list(fields)
        if not field_list:
            continue
        invalid = [field for field in field_list if not isinstance(field, str) or not field.strip()]
        if invalid:
            raise ValueError(f"fundamental_fields[{table!r}] contains invalid field names")
        normalized[table.strip()] = field_list
    return normalized


def _maybe_enrich_fundamentals(
    data_map: Dict[str, pd.DataFrame],
    config: Dict[str, Any],
) -> Dict[str, pd.DataFrame]:
    """Attach configured Tushare statement fields before signal generation."""
    fields_by_table = _normalise_fundamental_fields(config)
    if not fields_by_table:
        return data_map

    try:
        provider = TushareFundamentalProvider()
        return enrich_price_frames_with_fundamentals(
            data_map,
            provider,
            fields_by_table,
            as_of=config.get("end_date", ""),
            periods=config.get("fundamental_periods"),
        )
    except Exception as exc:
        raise RuntimeError(
            f"fundamental_fields requested but Tushare enrichment failed: {exc}"
        ) from exc


def _event_feed_specs(config: Dict[str, Any]) -> List[FeedSpec]:
    """Parse the optional ``event_feeds`` feed definitions from backtest config.

    ``event_feeds`` is a list of feed-definition dicts (there is no built-in
    catalogue) — each with ``name``/``route_template``/``event_type`` and an
    optional ``code_style``. An empty/absent value means "no event enrichment".
    """
    raw_feeds = config.get("event_feeds")
    if raw_feeds in (None, [], {}):
        return []
    if not isinstance(raw_feeds, (list, tuple)):
        raise ValueError("event_feeds must be a list of feed definitions")
    return feed_specs_from_config(raw_feeds)


def _maybe_enrich_events(
    data_map: Dict[str, pd.DataFrame],
    config: Dict[str, Any],
) -> Dict[str, pd.DataFrame]:
    """Attach a point-in-time-safe ``event_score`` column before signal generation."""
    specs = _event_feed_specs(config)
    if not specs:
        return data_map

    try:
        provider = RSSHubEventProvider(feeds=specs)
        if not provider.is_available():
            raise RuntimeError(f"RSSHub base URL not configured (set ${'RSSHUB_BASE_URL'})")
        return enrich_price_frames_with_events(
            data_map,
            provider,
            as_of=config.get("end_date", ""),
            decay_lambda=float(config.get("event_decay_lambda", 0.1)),
            lookback=int(config.get("event_lookback", 30)),
        )
    except Exception as exc:
        raise RuntimeError(
            f"event_feeds requested but RSSHub enrichment failed: {exc}"
        ) from exc


# ─── Base Engine ───


class BaseEngine(ABC):
    """Abstract base for all market engines.

    Subclasses override market-rule methods:
      - can_execute: whether a trade is allowed by market rules
      - round_size: lot-size rounding
      - calc_commission: fee structure
      - apply_slippage: slippage model
      - on_bar: per-bar hooks (funding fees, liquidation, etc.)
    """

    def __init__(self, config: dict):
        self.config = config
        self.initial_capital: float = config.get("initial_cash", 1_000_000)
        self.default_leverage: float = config.get("leverage", 1.0)
        self.position_adjustment = str(config.get("position_adjustment", "hold")).lower()
        if self.position_adjustment not in {"hold", "rebalance"}:
            raise ValueError("position_adjustment must be 'hold' or 'rebalance'")
        # Markets that clear at or below zero (e.g. EU day-ahead power) opt in
        # to opening on negative-price bars. Default False preserves the legacy
        # "reject any open_price <= 0" behavior. An exactly-zero open is always
        # rejected (undefined size = notional / price); negatives are handled by
        # abs()-based sizing and margin below.
        self.allow_nonpositive_prices: bool = bool(
            config.get("allow_nonpositive_prices", False)
        )
        #: Bar fields consulted, in order, for the price-limit base price.
        #: Futures engines put ``pre_settle`` first: exchanges set the band off
        #: the previous settlement, not the previous close.
        self.base_price_fields: tuple[str, ...] = ("pre_close",)
        self.capital: float = self.initial_capital
        self.positions: Dict[str, Position] = {}
        self.fill_records: List[FillRecord] = []
        self.trades: List[TradeRecord] = []
        self.equity_snapshots: List[EquitySnapshot] = []
        self._bar_idx: int = 0
        self._active_symbol: str = ""  # set by _rebalance/_close_position for subclass use

    # ── Market rule interface (subclass must implement) ──

    @abstractmethod
    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Whether market rules allow this trade.

        Args:
            symbol: Instrument identifier.
            direction: 1 (long), -1 (short), 0 (close).
            bar: Current bar data (OHLCV + extras).

        Returns:
            True if allowed.
        """

    @abstractmethod
    def round_size(self, raw_size: float, price: float) -> float:
        """Round position size per market lot rules.

        Args:
            raw_size: Desired size.
            price: Current price.

        Returns:
            Rounded size.
        """

    @abstractmethod
    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """Calculate commission for a trade.

        Args:
            size: Trade size.
            price: Execution price.
            direction: 1 or -1.
            is_open: True for opening, False for closing.

        Returns:
            Commission amount.
        """

    @abstractmethod
    def apply_slippage(self, price: float, direction: int) -> float:
        """Apply slippage to execution price.

        Args:
            price: Raw price.
            direction: 1 (buying / covering short) or -1 (selling / shorting).

        Returns:
            Slipped price.
        """

    def historical_base_price(self, symbol: str, bar: pd.Series) -> Optional[float]:
        """Return a reference price that is known before this bar's fill.

        Price-limit bands must be derived from a base price the market already
        knew when the order was placed. ``can_execute`` runs before the fill,
        and this engine fills at the CURRENT bar's open, so the current bar's
        close is not available information: using it is lookahead.

        Both sources here are strictly historical:
          1. the first field of :attr:`base_price_fields` present on the bar —
             ``pre_close`` for cash equity, ``pre_settle`` first for futures,
             whose exchanges set the band off the previous settlement;
          2. the previous row of the close panel the run pre-extracts, which is
             absent in a cross-market composite run (its sub-engines are
             stateless rule books with no panel of their own).

        Args:
            symbol: Symbol whose base price is wanted.
            bar: Current bar.

        Returns:
            The base price, or None when no historical close is reachable
            (first bar of a run, or a composite sub-engine).
        """
        for field in self.base_price_fields:
            if field in bar.index:
                raw = bar[field]
                if pd.notna(raw) and float(raw) > 0:
                    return float(raw)

        close_arr = getattr(self, "_close_arr", None)
        col = getattr(self, "_code_to_col", {}).get(symbol)
        row = getattr(self, "_bar_idx", 0) - 1
        if close_arr is not None and col is not None and row >= 0:
            value = close_arr[row, col]
            if pd.notna(value) and float(value) > 0:
                return float(value)

        # Last resort: reconstruct the prior close from tushare's pct_chg, which
        # is in percentage points. Both inputs sit on the current bar, but their
        # ratio is the PREVIOUS close, so the result is still historical.
        if "pct_chg" in bar.index and "close" in bar.index:
            pct, close = bar["pct_chg"], bar["close"]
            if pd.notna(pct) and pd.notna(close) and float(close) > 0:
                denominator = 1.0 + float(pct) / 100.0
                if denominator > 0:
                    return float(close) / denominator
        return None

    def prospective_fill_price(self, bar: pd.Series, direction: int) -> Optional[float]:
        """Return the price this engine would fill at on this bar.

        Mirrors the sizing path: the bar's open, with slippage applied in the
        trade direction. Comparing THIS against a price-limit band keeps the
        simulation from ever transacting outside the exchange's legal range.

        Args:
            bar: Current bar.
            direction: 1 (buy / cover), -1 (sell / short), 0 (close).

        Returns:
            The prospective fill price, or None when the bar has no usable open.
        """
        raw = bar.get("open", bar.get("close"))
        if raw is None or pd.isna(raw):
            return None
        price = float(raw)
        if price <= 0 and not self.allow_nonpositive_prices:
            return None
        return self.apply_slippage(price, direction)

    def limit_band(
        self, symbol: str, bar: pd.Series, limit: float
    ) -> Optional[tuple[float, float]]:
        """Return the (lower, upper) legal price band for this bar.

        Args:
            symbol: Symbol whose band is wanted.
            bar: Current bar.
            limit: Band half-width as a fraction (0.1 for +/-10%).

        Returns:
            The (lower, upper) band, or None when no historical base price is
            reachable — in which case the caller must not fabricate a block.
        """
        base = self.historical_base_price(symbol, bar)
        if base is None or base <= 0 or not limit:
            return None
        return base * (1.0 - float(limit)), base * (1.0 + float(limit))

    def on_bar(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """Per-bar market-rule hook (funding fees, liquidation, etc.).

        Default: no-op. Override in subclass as needed.
        """

    def before_rebalance_bar(
        self,
        timestamp: pd.Timestamp,
        data_map: Dict[str, pd.DataFrame],
        codes: List[str],
    ) -> bool:
        """Run pre-execution hooks; return True to stop after this snapshot."""
        return False

    def after_rebalance_bar(
        self,
        timestamp: pd.Timestamp,
        data_map: Dict[str, pd.DataFrame],
        codes: List[str],
    ) -> bool:
        """Run the legacy post-fill bar hooks; return True to stop."""
        for code in codes:
            if timestamp in data_map[code].index:
                self.on_bar(code, data_map[code].loc[timestamp], timestamp)
        return False

    def after_position_adjustment(
        self,
        *,
        action: str,
        timestamp: pd.Timestamp,
        before: Position,
        after: Position,
        execution_price: float,
        trading_fee: float,
        realized_pnl: float = 0.0,
        released_margin: float = 0.0,
    ) -> None:
        """Allow engines to update risk state/evidence after a committed delta fill."""
        return None

    def execution_open(self, bar: pd.Series) -> float:
        """Return the normal market-fill price for a bar."""
        return float(bar.get("open", bar.get("close", 0)))

    def valuation_open(self, bar: pd.Series) -> float:
        """Return the price observable when open orders are sized."""
        return float(bar.get("open", bar.get("close", 0)))

    # ── PnL / margin calculation hooks ──
    # Override in FuturesBaseEngine to inject contract multiplier.

    def _calc_pnl(
        self, symbol: str, direction: int, size: float,
        entry_price: float, exit_price: float,
    ) -> float:
        """Realised PnL for a closed position."""
        return direction * size * (exit_price - entry_price)

    def _calc_margin(
        self, symbol: str, size: float, price: float, leverage: float,
    ) -> float:
        """Margin (collateral) required for a position.

        ``abs(price)`` so collateral stays positive when the entry price is
        negative; for the usual positive price this is unchanged.
        """
        return size * abs(price) / leverage

    def _calc_raw_size(
        self, symbol: str, target_notional: float, price: float,
    ) -> float:
        """Convert target notional exposure to number of units/contracts.

        Size is a positive magnitude — direction carries the sign elsewhere —
        so divide by ``abs(price)``; a negative entry price must not flip the
        size negative (which the ``size <= 0`` guard would then reject). For a
        positive price this is unchanged.
        """
        return target_notional / abs(price)

    def _leverage_for_symbol(self, symbol: str) -> float:
        """Return leverage used to size and margin one symbol."""
        del symbol
        return self.default_leverage

    # ── Main entry ──

    def run_backtest(
        self,
        config: Dict[str, Any],
        loader: Any,
        signal_engine: Any,
        run_dir: Path,
        bars_per_year: int = 252,
    ) -> Dict[str, Any]:
        """Full backtest pipeline.

        Signature matches ``daily_portfolio.run_backtest`` for drop-in replacement.

        Args:
            config: Backtest configuration dict.
            loader: DataLoader with ``fetch()`` method.
            signal_engine: SignalEngine with ``generate()`` method.
            run_dir: Artifacts output directory.
            bars_per_year: Annualisation factor.

        Returns:
            Metrics dictionary.
        """
        codes = config.get("codes", [])
        interval = config.get("interval", "1D")
        extra_fields = config.get("extra_fields") or None

        # 1. Load data
        data_map = loader.fetch(
            codes,
            config.get("start_date", ""),
            config.get("end_date", ""),
            fields=extra_fields,
            interval=interval,
        )
        if not data_map:
            print(json.dumps({"error": "No data fetched"}))
            sys.exit(1)
        data_map = _maybe_enrich_fundamentals(data_map, config)
        data_map = _maybe_enrich_events(data_map, config)

        # 2. Generate signals
        signal_map = signal_engine.generate(data_map)
        if not isinstance(signal_map, dict):
            print(json.dumps({"error": (
                f"SignalEngine.generate() must return Dict[str, pd.Series], "
                f"got {type(signal_map).__name__}. "
                "Return a dict mapping symbol codes to pandas Series of signals."
            )}))
            sys.exit(1)
        for _code, _sig in signal_map.items():
            if not isinstance(_sig, pd.Series):
                print(json.dumps({"error": (
                    f"SignalEngine.generate() returned {type(_sig).__name__} for '{_code}', "
                    "expected pd.Series. Each value must be a pandas Series with DatetimeIndex."
                )}))
                sys.exit(1)
        valid_codes = sorted(c for c in signal_map if c in data_map)
        if not valid_codes:
            print(json.dumps({"error": "No valid signals generated"}))
            sys.exit(1)

        # 3. Pre-compute target weights (with optimizer)
        opt_fn = _load_optimizer(config)
        dates, close_df, target_pos, ret_df = _align(
            data_map, signal_map, valid_codes, optimizer=opt_fn,
        )

        # Sync codes after _align may have dropped all-NaN symbols
        valid_codes = [c for c in valid_codes if c in target_pos.columns]

        # 4. Bar-by-bar execution
        self._execute_bars(dates, data_map, close_df, target_pos, valid_codes)

        # 5. Build output series
        equity_series = pd.Series(
            [s.equity for s in self.equity_snapshots],
            index=[s.timestamp for s in self.equity_snapshots],
        )
        bench_ret = ret_df.mean(axis=1) if ret_df.shape[1] > 0 else pd.Series(0.0, index=dates)
        benchmark_metadata = {}

        # ── External benchmark fetch ──────────────────────────────────────────
        bench_ticker = config.get("benchmark")
        if bench_ticker and bench_ticker != "auto":
            from backtest.benchmark import resolve_benchmark
            bench_source = config.get("source", "yfinance")
            bench_result = resolve_benchmark(
                strategy_codes=codes,
                source=bench_source,
                start_date=config.get("start_date", ""),
                end_date=config.get("end_date", ""),
                interval=interval,
                explicit=bench_ticker,
                # Explicit source: fetch the benchmark through its own loader
                # (keeps e.g. source=local offline). Auto keeps the yfinance
                # default — its loader only wraps the preloaded strategy data.
                loader=loader if bench_source != "auto" else None,
            )
            if bench_result is not None:
                bench_ret = bench_result.ret_series.reindex(dates).fillna(0.0)
                benchmark_metadata = {
                    "benchmark_ticker": bench_result.ticker,
                    "benchmark_return": bench_result.total_ret,
                }
        # ── External benchmark fetch ──────────────────────────────────────────

        bench_equity = self.initial_capital * (1 + bench_ret).cumprod()

        # 6. Metrics
        realized_turnover = calc_fill_turnover_series(self.fill_records, equity_series)
        m = calc_metrics(
            equity_series,
            self.trades,
            self.initial_capital,
            bars_per_year,
            bench_ret,
            target_pos,
            turnover_series=realized_turnover,
        )
        m.update(benchmark_metadata)
        m["by_symbol"] = by_symbol_stats(self.trades)
        m["by_exit_reason"] = by_exit_reason_stats(self.trades)

        # Portfolio Studio: per-rebalance weight-drift notes from the target
        # positions. Optimizer-agnostic, so they land for the baseline too.
        from backtest.rebalance_notes import (
            compute_rebalance_notes,
            render_rebalance_notes_markdown,
            write_rebalance_notes,
        )
        rebalance_notes = compute_rebalance_notes(target_pos)
        write_rebalance_notes(run_dir / "artifacts" / "rebalance_notes.json", rebalance_notes)
        (run_dir / "artifacts" / "rebalance_notes.md").write_text(
            render_rebalance_notes_markdown(rebalance_notes), encoding="utf-8"
        )
        m["rebalance_count"] = rebalance_notes["summary"]["rebalance_count"]
        m["rebalance_turnover_mean"] = rebalance_notes["summary"]["turnover_mean"]
        m["rebalance_turnover_max"] = rebalance_notes["summary"]["turnover_max"]

        # Portfolio Studio: risk x-ray over the strategy's average basket.
        # Short runs and never-invested strategies raise ValueError in the
        # derivation and simply get no x-ray artifact.
        from backtest.risk_xray import (
            average_invested_weights,
            compute_risk_xray,
            render_risk_xray_markdown,
            write_risk_xray,
        )
        try:
            basket_weights, avg_invested = average_invested_weights(target_pos)
            risk_xray = compute_risk_xray(
                close_df, basket_weights, periods_per_year=bars_per_year,
            )
        except ValueError:
            pass
        else:
            write_risk_xray(run_dir / "artifacts" / "risk_xray.json", risk_xray)
            (run_dir / "artifacts" / "risk_xray.md").write_text(
                render_risk_xray_markdown(risk_xray), encoding="utf-8"
            )
            m["risk_xray_hhi"] = risk_xray["concentration"]["hhi"]
            m["risk_xray_effective_n"] = risk_xray["concentration"]["effective_n"]
            m["risk_xray_annualized_vol"] = risk_xray["volatility"]["annualized_vol"]
            m["risk_xray_max_drawdown"] = risk_xray["drawdown"]["max_drawdown"]
            m["risk_xray_avg_invested"] = avg_invested

        # 7. Validation (optional — triggered by config["validation"])
        if config.get("validation"):
            from backtest.validation import run_validation, write_validation_json
            v_results = run_validation(
                config, equity_series, self.trades, self.initial_capital, bars_per_year,
            )
            m["validation"] = v_results
            # Write validation.json through the shared strict writer so a
            # non-finite validation metric is serialized as null rather than an
            # invalid bare NaN/Infinity token (matching the standalone
            # `python -m backtest.validation` path and run_card). The writer
            # also creates the artifacts dir, which step 8 otherwise creates.
            write_validation_json(run_dir / "artifacts" / "validation.json", v_results)

        # 8. Artifacts
        self._write_artifacts(
            run_dir, data_map, dates, equity_series, bench_equity, bench_ret,
            target_pos, m, valid_codes,
        )

        # 9. Trust Layer run card
        from backtest.run_card import write_run_card
        write_run_card(
            run_dir,
            config,
            m,
            data_sources=_run_card_data_sources(config, loader),
            strategy_path=run_dir / "code" / "signal_engine.py",
            warnings=config.get("content_filter_warnings") or None,
        )

        # Print scalar metrics (skip nested dicts for JSON compat).
        # Explosive annual_return may be +inf; match options/run_card and emit
        # null instead of a bare Infinity token (invalid RFC-8259 JSON).
        print(json.dumps(_json_safe_scalar_metrics(m), indent=2, allow_nan=False))
        return m

    # ── Execution loop ──

    def _execute_bars(
        self,
        dates: pd.DatetimeIndex,
        data_map: Dict[str, pd.DataFrame],
        close_df: pd.DataFrame,
        target_pos: pd.DataFrame,
        codes: List[str],
    ) -> None:
        """Bar-by-bar execution with market rule enforcement."""
        # Pre-extract numpy arrays for O(1) indexed access instead of DataFrame.at[]
        # Explicit column reindex ensures array column order matches codes parameter,
        # regardless of DataFrame internal column ordering (which may be alphabetical).
        _target_arr = target_pos[codes].values  # (n_dates, n_codes) ndarray
        _close_arr = close_df[codes].values  # (n_dates, n_codes) ndarray
        _code_to_col = {c: j for j, c in enumerate(codes)}
        # Store as instance attrs for use in _calc_equity / _safe_price
        self._close_arr = _close_arr
        self._code_to_col = _code_to_col

        for i, ts in enumerate(dates):
            self._bar_idx = i

            stop_run = self.before_rebalance_bar(ts, data_map, codes)

            # a. Value the book at prices observable when orders execute.
            # Rebalances happen at the bar open, so using close_df[ts] here
            # would let the yet-unknown decision-bar close affect order size.
            equity = self._calc_open_equity(data_map, close_df, ts)
            target_weights: Dict[str, Optional[float]] = {}
            for c in codes:
                try:
                    val = _target_arr[i, _code_to_col[c]]
                    target_weights[c] = (
                        None if stop_run else (float(val) if not np.isnan(val) else 0.0)
                    )
                except Exception as exc:
                    target_weights[c] = None
                    logger.warning("Target weight failed for %s at %s: %s", c, ts, exc)

            if self.position_adjustment == "rebalance":
                self._execute_target_rebalance(target_weights, data_map, ts, equity, codes)
                target_weights = {}

            # b. Release capital before opening replacement positions.  A
            # single mixed close/open pass makes rotations depend on symbol
            # iteration order when the new name is visited before the old one.
            for c in codes:
                target_w = target_weights.get(c)
                current_pos = self.positions.get(c)
                if target_w is None or current_pos is None:
                    continue
                target_dir = 1 if target_w > 1e-9 else (-1 if target_w < -1e-9 else 0)
                if target_dir == 0 or target_dir != current_pos.direction:
                    try:
                        self._rebalance(c, 0.0, data_map.get(c), ts, equity)
                    except Exception as exc:
                        logger.warning(
                            "Rebalance close failed for %s at %s: %s", c, ts, exc
                        )

            # c. Price every opening order before committing any of them.  If
            # the requested basket does not fit after fees/lot rounding, apply
            # one common scale factor to all target weights.  This preserves
            # portfolio proportions and makes fills independent of input code
            # order; sequential cash clipping would privilege the first name.
            open_targets: list[tuple[str, float, Optional[pd.DataFrame]]] = []
            for c in sorted(codes):
                target_w = target_weights.get(c)
                if target_w is None:
                    continue
                target_dir = 1 if target_w > 1e-9 else (-1 if target_w < -1e-9 else 0)
                current_pos = self.positions.get(c)
                if current_pos is not None and (
                    target_dir == 0 or target_dir != current_pos.direction
                ):
                    continue
                if current_pos is None and target_dir != 0:
                    open_targets.append((c, target_w, data_map.get(c)))

            def _plans(scale: float) -> list[_OpenOrder]:
                result: list[_OpenOrder] = []
                for c, target_w, frame in open_targets:
                    try:
                        order = self._plan_open_order(
                            c, target_w * scale, frame, ts, equity
                        )
                    except Exception as exc:
                        logger.warning(
                            "Rebalance open plan failed for %s at %s: %s",
                            c,
                            ts,
                            exc,
                        )
                        continue
                    if order is not None:
                        result.append(order)
                return result

            planned = _plans(1.0)
            if sum(order.cost for order in planned) > self.capital + 1e-9:
                low, high = 0.0, 1.0
                for _ in range(50):
                    mid = (low + high) / 2.0
                    candidate = _plans(mid)
                    if sum(order.cost for order in candidate) <= self.capital + 1e-9:
                        low, planned = mid, candidate
                    else:
                        high = mid

            for order in planned:
                self._execute_open_order(order, ts)

            # d. Apply post-execution hooks after all normal market fills.
            if not stop_run:
                stop_run = self.after_rebalance_bar(ts, data_map, codes)

            # e. Record equity snapshot
            snap_equity = self._calc_equity(close_df, ts)
            if self.positions and type(self)._calc_pnl is BaseEngine._calc_pnl:
                _syms = list(self.positions.keys())
                _eps = np.array([p.entry_price for p in self.positions.values()])
                _dirs = np.array([p.direction for p in self.positions.values()])
                _sizes = np.array([p.size for p in self.positions.values()])
                _cps = np.array([
                    self._safe_price(
                        close_df, ts, s, ep,
                        _arr=_close_arr, _row=i, _col=_code_to_col.get(s),
                    )
                    for s, ep in zip(_syms, _eps)
                ])
                total_unrealized = float(np.sum(_dirs * _sizes * (_cps - _eps)))
            else:
                total_unrealized = 0.0
                for p in self.positions.values():
                    cp = self._safe_price(
                        close_df, ts, p.symbol, p.entry_price,
                        _arr=_close_arr, _row=i, _col=_code_to_col.get(p.symbol),
                    )
                    total_unrealized += self._calc_pnl(p.symbol, p.direction, p.size, p.entry_price, cp)
            self.equity_snapshots.append(EquitySnapshot(
                timestamp=ts,
                capital=self.capital,
                unrealized=total_unrealized,
                equity=snap_equity,
                positions=len(self.positions),
            ))

            if stop_run:
                break

        # f. Force close all remaining positions
        if len(dates) > 0:
            _last_row = min(self._bar_idx, len(dates) - 1)
            last_ts = dates[_last_row]
            for c in list(self.positions.keys()):
                pos = self.positions[c]
                mark_price = self._safe_price(
                    close_df, last_ts, c, pos.entry_price,
                    _arr=_close_arr, _row=_last_row, _col=_code_to_col.get(c),
                )
                self._active_symbol = c
                exit_price = self.apply_slippage(mark_price, -pos.direction)
                self._close_position(c, exit_price, last_ts, "end_of_backtest")

            # The final snapshot feeds metrics and artifacts.  Replace its
            # pre-liquidation mark with post-liquidation cash so terminal
            # slippage and exit commission are reflected in reported equity.
            if self.equity_snapshots:
                self.equity_snapshots[-1] = EquitySnapshot(
                    timestamp=last_ts,
                    capital=self.capital,
                    unrealized=0.0,
                    equity=self.capital,
                    positions=0,
                )

        # Clean up temporary instance attributes
        self._close_arr = None
        self._code_to_col = None

    def _calc_open_equity(
        self,
        data_map: Dict[str, pd.DataFrame],
        close_df: pd.DataFrame,
        ts: pd.Timestamp,
    ) -> float:
        """Value current positions at the execution bar's observable open.

        For a symbol that has a bar at ``ts``, its open is the mark available
        when next-bar-open orders execute.  Symbols without a bar on the
        unified calendar retain the aligned close fallback, which is the most
        recent price carried by ``_align``.
        """
        if not self.positions:
            return self.capital

        equity = self.capital
        for sym, pos in self.positions.items():
            _arr = getattr(self, "_close_arr", None)
            _row = getattr(self, "_bar_idx", None)
            _c2c = getattr(self, "_code_to_col", None)
            current_price = self._safe_price(
                close_df, ts, sym, pos.entry_price,
                _arr=_arr, _row=_row, _col=(_c2c.get(sym) if _c2c else None),
            )
            frame = data_map.get(sym)
            if frame is not None and ts in frame.index:
                open_price = self.valuation_open(frame.loc[ts])
                if (
                    pd.notna(open_price)
                    and float(open_price) > 0
                ):
                    current_price = float(open_price)

            margin = self._calc_margin(sym, pos.size, pos.entry_price, pos.leverage)
            unrealized = self._calc_pnl(
                sym, pos.direction, pos.size, pos.entry_price, current_price
            )
            equity += margin + unrealized
        return equity

    def _calc_equity(self, close_df: pd.DataFrame, ts: pd.Timestamp) -> float:
        """Total equity = free cash + sum(margin + unrealised) per position.

        Uses vectorized numpy path when _calc_pnl/_calc_margin are not
        overridden by a subclass (FuturesBaseEngine, CompositeEngine).
        """
        if not self.positions:
            return self.capital

        _base_pnl = type(self)._calc_pnl is BaseEngine._calc_pnl
        _base_margin = type(self)._calc_margin is BaseEngine._calc_margin

        # Use array fast-path when available
        _arr = getattr(self, "_close_arr", None)
        _row = getattr(self, "_bar_idx", None)
        _c2c = getattr(self, "_code_to_col", None)

        if _base_pnl and _base_margin:
            syms = list(self.positions.keys())
            sizes = np.array([p.size for p in self.positions.values()])
            entry_prices = np.array([p.entry_price for p in self.positions.values()])
            directions = np.array([p.direction for p in self.positions.values()])
            leverages = np.array([p.leverage for p in self.positions.values()])

            current_prices = np.array([
                self._safe_price(
                    close_df, ts, s, ep,
                    _arr=_arr, _row=_row, _col=(_c2c.get(s) if _c2c else None),
                )
                for s, ep in zip(syms, entry_prices)
            ])

            margins = sizes * entry_prices / leverages
            pnls = directions * sizes * (current_prices - entry_prices)
            return self.capital + float(np.sum(margins + pnls))

        equity = self.capital
        for sym, pos in self.positions.items():
            cp = self._safe_price(
                close_df, ts, sym, pos.entry_price,
                _arr=_arr, _row=_row, _col=(_c2c.get(sym) if _c2c else None),
            )
            margin = self._calc_margin(sym, pos.size, pos.entry_price, pos.leverage)
            unrealized = self._calc_pnl(sym, pos.direction, pos.size, pos.entry_price, cp)
            equity += margin + unrealized
        return equity

    def _rebalance(
        self,
        symbol: str,
        target_weight: float,
        df: Optional[pd.DataFrame],
        ts: pd.Timestamp,
        equity: float,
    ) -> None:
        """Adjust position for *symbol* toward *target_weight*."""
        self._active_symbol = symbol
        target_dir = 1 if target_weight > 1e-9 else (-1 if target_weight < -1e-9 else 0)
        current_pos = self.positions.get(symbol)

        # Nothing to do
        if current_pos is None and target_dir == 0:
            return
        if df is None or ts not in df.index:
            return

        bar = df.loc[ts]

        # Close if target is flat or direction changed
        if current_pos is not None:
            need_close = target_dir == 0 or target_dir != current_pos.direction
            if need_close:
                if self.can_execute(symbol, 0, bar):
                    open_price = self.execution_open(bar)
                    price = self.apply_slippage(open_price, -current_pos.direction)
                    self._close_position(symbol, price, ts, "signal")
                else:
                    return  # blocked (e.g. limit-down can't sell)

        if target_dir != 0 and symbol not in self.positions:
            order = self._plan_open_order(symbol, target_weight, df, ts, equity)
            if order is not None and order.cost <= self.capital + 1e-9:
                self._execute_open_order(order, ts)

    def _plan_open_order(
        self,
        symbol: str,
        target_weight: float,
        df: Optional[pd.DataFrame],
        ts: pd.Timestamp,
        equity: float,
        *,
        allow_existing: bool = False, require_positive_price: bool = False,
    ) -> Optional[_OpenOrder]:
        """Price an opening order without mutating portfolio state."""
        self._active_symbol = symbol
        direction = 1 if target_weight > 1e-9 else (-1 if target_weight < -1e-9 else 0)
        if (
            direction == 0
            or (symbol in self.positions and not allow_existing)
            or df is None
            or ts not in df.index
        ):
            return None
        bar = df.loc[ts]
        if not self.can_execute(symbol, direction, bar):
            return None
        open_price = self.execution_open(bar)
        if require_positive_price:
            self._validate_rebalance_values(open_price, positive=True)
        # Zero is always rejected (size = notional / price is undefined);
        # negatives are rejected unless this engine opted into non-positive
        # prices, in which case abs()-based sizing/margin below handle them.
        elif open_price == 0 or (open_price < 0 and not self.allow_nonpositive_prices):
            return None
        price = self.apply_slippage(open_price, direction)
        if require_positive_price:
            self._validate_rebalance_values(price, positive=True)
        leverage = self._leverage_for_symbol(symbol)
        target_notional = abs(target_weight) * equity * leverage
        size = self.round_size(
            self._calc_raw_size(symbol, target_notional, price), price
        )
        if size <= 0:
            return None
        margin = self._calc_margin(symbol, size, price, leverage)
        commission = self.calc_commission(
            size, price, direction, is_open=True
        )
        return _OpenOrder(
            symbol=symbol,
            direction=direction,
            price=price,
            size=size,
            leverage=leverage,
            margin=margin,
            commission=commission,
        )

    def _execute_target_rebalance(
        self,
        target_weights: Dict[str, Optional[float]], data_map: Dict[str, pd.DataFrame],
        ts: pd.Timestamp, equity: float, codes: List[str],
    ) -> None:
        """Plan every target delta, preflight capital, then commit the basket."""
        reductions: list[_ReductionOrder] = []
        opens: list[_OpenOrder] = []

        for symbol in sorted(codes):
            target_weight = target_weights.get(symbol)
            if target_weight is None:
                continue
            self._validate_rebalance_values(target_weight)

            self._active_symbol = symbol
            before = self.positions.get(symbol)
            target_direction = 1 if target_weight > 1e-9 else (-1 if target_weight < -1e-9 else 0)
            frame = data_map.get(symbol)
            if frame is None or ts not in frame.index:
                continue
            bar = frame.loc[ts]

            if before is None or target_direction != before.direction:
                if before is not None:
                    if not self.can_execute(symbol, 0, bar):
                        continue
                    raw_price = self.execution_open(bar)
                    self._validate_rebalance_values(raw_price, positive=True)
                    price = self.apply_slippage(raw_price, -before.direction)
                    self._validate_rebalance_values(price, positive=True)
                    reductions.append(self._plan_reduction(before, 0.0, price))
                    if target_direction == 0:
                        continue
                order = self._plan_open_order(
                    symbol,
                    target_weight,
                    frame,
                    ts,
                    equity,
                    allow_existing=before is not None,
                    require_positive_price=True,
                )
                if order is not None:
                    self._validate_rebalance_values(
                        order.price, order.leverage, order.size, order.margin, order.commission
                    )
                    opens.append(order)
                continue

            raw_price = self.execution_open(bar)
            self._validate_rebalance_values(raw_price, positive=True)
            leverage = self._leverage_for_symbol(symbol)
            self._validate_rebalance_values(raw_price, before.leverage, leverage)
            target_notional = abs(target_weight) * equity * before.leverage
            prices = (
                self.apply_slippage(raw_price, before.direction),
                self.apply_slippage(raw_price, -before.direction),
            )
            self._validate_rebalance_values(*prices, positive=True)
            sizes = tuple(
                self.round_size(
                    self._calc_raw_size(symbol, target_notional, price), price
                )
                for price in prices
            )
            self._validate_rebalance_values(*prices, *sizes)
            increase = sizes[0] > before.size + 1e-9
            reduction = sizes[1] < before.size - 1e-9
            # Both or neither means the target lies inside the fill-price band.
            if increase == reduction:
                continue
            target_size, price = (sizes[0], prices[0]) if increase else (sizes[1], prices[1])
            if not math.isclose(leverage, before.leverage, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError("cannot rebalance a position with changed leverage")
            if increase:
                if not self.can_execute(symbol, target_direction, bar):
                    continue
                size = target_size - before.size
                order = _OpenOrder(
                    symbol=symbol,
                    direction=before.direction,
                    price=price,
                    size=size,
                    leverage=leverage,
                    margin=self._calc_margin(symbol, size, price, leverage),
                    commission=self.calc_commission(
                        size, price, before.direction, is_open=True
                    ),
                )
                self._validate_rebalance_values(
                    order.price, order.leverage, order.size, order.margin, order.commission
                )
                opens.append(order)
            elif self.can_execute(symbol, 0, bar):
                reductions.append(self._plan_reduction(before, target_size, price))

        projected_capital = (
            self.capital
            + sum(order.capital_credit for order in reductions)
            - sum(order.cost for order in opens)
        )
        self._validate_rebalance_values(projected_capital)
        if projected_capital < -1e-9:
            raise ValueError("insufficient capital for position rebalance")

        for order in reductions:
            if order.target_size <= 1e-9:
                self._close_position(order.before.symbol, order.price, ts, "signal")
            else:
                self._execute_partial_reduction(order, ts)
        for order in opens:
            if order.symbol in self.positions:
                self._execute_position_increase(order, ts)
            else:
                self._execute_open_order(order, ts)

    @staticmethod
    def _validate_rebalance_values(*values: float, positive: bool = False) -> None:
        if all(
            math.isfinite(float(value)) and (not positive or float(value) > 0)
            for value in values
        ):
            return
        raise ValueError(
            "rebalance requires a finite positive execution price"
            if positive
            else "non-finite position rebalance value"
        )

    def _plan_reduction(self, before: Position, target_size: float, price: float) -> _ReductionOrder:
        closed_size = before.size - target_size
        released_margin = self._calc_margin(
            before.symbol, closed_size, before.entry_price, before.leverage
        )
        realized_pnl = self._calc_pnl(
            before.symbol, before.direction, closed_size, before.entry_price, price
        )
        exit_commission = self.calc_commission(
            closed_size, price, before.direction, is_open=False
        )
        self._validate_rebalance_values(
            target_size,
            price,
            released_margin,
            realized_pnl,
            exit_commission,
        )
        return _ReductionOrder(before, target_size, price, released_margin, realized_pnl, exit_commission)

    def _execute_position_increase(self, order: _OpenOrder, ts: pd.Timestamp) -> None:
        """Commit a same-direction opening delta."""
        before = self.positions[order.symbol]
        if order.direction != before.direction:
            raise ValueError("position increase direction must match the open position")
        if order.cost > self.capital + 1e-7:
            raise RuntimeError(
                f"planned order for {order.symbol} exceeds available capital"
            )
        new_size = before.size + order.size
        after = replace(
            before,
            entry_price=(before.size * before.entry_price + order.size * order.price) / new_size,
            size=new_size,
            entry_commission=before.entry_commission + order.commission,
        )
        self.capital -= order.cost
        self.positions[order.symbol] = after
        self._record_fill(
            symbol=order.symbol,
            timestamp=ts,
            action="increase",
            signed_quantity=order.direction * order.size,
            execution_price=order.price,
            fee=order.commission,
            margin=order.margin,
            leverage=order.leverage,
            reason="target_rebalance",
        )
        self.after_position_adjustment(
            action="increase",
            timestamp=ts,
            before=before,
            after=after,
            execution_price=order.price,
            trading_fee=order.commission,
        )

    def _execute_partial_reduction(self, order: _ReductionOrder, ts: pd.Timestamp) -> None:
        """Commit a same-direction closing delta."""
        before = self.positions[order.before.symbol]
        closed_size = before.size - order.target_size
        entry_commission = before.entry_commission * closed_size / before.size
        after = replace(
            before,
            size=order.target_size,
            entry_commission=before.entry_commission - entry_commission,
        )
        exit_margin = self._calc_margin(
            before.symbol, closed_size, order.price, before.leverage
        )
        pnl_pct = (
            order.realized_pnl / order.released_margin * 100
            if order.released_margin > 1e-9
            else 0.0
        )
        holding_bars = self._weighted_holding_bars(before)
        self.capital += order.capital_credit
        self.positions[before.symbol] = after
        self.trades.append(TradeRecord(
            symbol=before.symbol,
            direction=before.direction,
            entry_price=before.entry_price,
            exit_price=order.price,
            entry_time=before.entry_time,
            exit_time=ts,
            size=closed_size,
            leverage=before.leverage,
            pnl=order.realized_pnl,
            pnl_pct=pnl_pct,
            exit_reason="target_rebalance",
            holding_bars=holding_bars,
            commission=entry_commission + order.exit_commission,
            entry_margin=order.released_margin,
            exit_margin=exit_margin,
        ))
        self._record_fill(
            symbol=before.symbol,
            timestamp=ts,
            action="reduce",
            signed_quantity=-before.direction * closed_size,
            execution_price=order.price,
            fee=order.exit_commission,
            margin=exit_margin,
            leverage=before.leverage,
            reason="target_rebalance",
            holding_bars=holding_bars,
        )
        self.after_position_adjustment(
            action="partial_reduction",
            timestamp=ts,
            before=before,
            after=after,
            execution_price=order.price,
            trading_fee=order.exit_commission,
            realized_pnl=order.realized_pnl,
            released_margin=order.released_margin,
        )

    def _execute_open_order(self, order: _OpenOrder, ts: pd.Timestamp) -> None:
        """Commit a previously priced opening order."""
        if order.cost > self.capital + 1e-7:
            raise RuntimeError(
                f"planned order for {order.symbol} exceeds available capital"
            )
        self.capital -= order.cost
        self.positions[order.symbol] = Position(
            symbol=order.symbol,
            direction=order.direction,
            entry_price=order.price,
            entry_time=ts,
            size=order.size,
            leverage=order.leverage,
            entry_bar_idx=self._bar_idx,
            entry_commission=order.commission,
        )
        self._record_fill(
            symbol=order.symbol,
            timestamp=ts,
            action="open",
            signed_quantity=order.direction * order.size,
            execution_price=order.price,
            fee=order.commission,
            margin=order.margin,
            leverage=order.leverage,
            reason="signal",
        )

    def _close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_time: pd.Timestamp,
        reason: str,
    ) -> None:
        """Close position, record trade, return capital."""
        self._active_symbol = symbol
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return

        pnl = self._calc_pnl(symbol, pos.direction, pos.size, pos.entry_price, exit_price)
        margin = self._calc_margin(symbol, pos.size, pos.entry_price, pos.leverage)
        exit_margin = self._calc_margin(symbol, pos.size, exit_price, pos.leverage)
        pnl_pct = pnl / margin * 100 if margin > 1e-9 else 0.0
        exit_comm = self.calc_commission(pos.size, exit_price, pos.direction, is_open=False)

        self.capital += margin + pnl - exit_comm

        holding_bars = self._weighted_holding_bars(pos)

        self.trades.append(TradeRecord(
            symbol=symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            size=pos.size,
            leverage=pos.leverage,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            holding_bars=holding_bars,
            commission=pos.entry_commission + exit_comm,
            entry_margin=margin,
            exit_margin=exit_margin,
        ))
        self._record_fill(
            symbol=symbol,
            timestamp=exit_time,
            action="close",
            signed_quantity=-pos.direction * pos.size,
            execution_price=exit_price,
            fee=exit_comm,
            margin=exit_margin,
            leverage=pos.leverage,
            reason=reason,
            holding_bars=holding_bars,
        )

    def _record_fill(
        self,
        *,
        symbol: str,
        timestamp: pd.Timestamp,
        action: str,
        signed_quantity: float,
        execution_price: float,
        fee: float,
        margin: float,
        leverage: float,
        reason: str,
        holding_bars: float | None = None,
    ) -> None:
        """Append execution evidence without making it account state."""
        self.fill_records.append(FillRecord(
            symbol=symbol,
            timestamp=timestamp,
            bar_idx=self._bar_idx,
            action=action,
            signed_quantity=signed_quantity,
            notional=margin * leverage,
            execution_price=execution_price,
            fee=fee,
            margin=margin,
            reason=reason,
            holding_bars=holding_bars,
        ))

    def _weighted_holding_bars(self, position: Position) -> float:
        """Derive compressed-position age from immutable fill evidence.

        Reductions consume every accumulated opening delta proportionally,
        matching the weighted-average entry accounting used by this engine.
        Only the active position lifecycle matters; stopping at its preceding
        full close avoids rescanning the entire fill ledger on every exit.
        """
        active_fills: list[FillRecord] = []
        for fill in reversed(self.fill_records):
            if fill.symbol != position.symbol:
                continue
            if fill.action == "close":
                break
            active_fills.append(fill)

        lots: list[list[float]] = []
        for fill in reversed(active_fills):
            quantity = abs(fill.signed_quantity)
            if fill.action in {"open", "increase"}:
                lots.append([quantity, float(fill.bar_idx)])
                continue
            if fill.action not in {"reduce", "close"}:
                continue
            total = sum(lot[0] for lot in lots)
            if total <= 1e-12 or quantity >= total - 1e-12:
                lots.clear()
                continue
            remaining_ratio = (total - quantity) / total
            for lot in lots:
                lot[0] *= remaining_ratio

        total = sum(lot[0] for lot in lots)
        if total <= 1e-12:
            return float(max(self._bar_idx - position.entry_bar_idx, 0))
        return sum(
            quantity * max(self._bar_idx - int(bar_idx), 0)
            for quantity, bar_idx in lots
        ) / total

    # ── Artifacts ──

    def _write_artifacts(
        self,
        run_dir: Path,
        data_map: Dict[str, pd.DataFrame],
        dates: pd.DatetimeIndex,
        equity_series: pd.Series,
        bench_equity: pd.Series,
        bench_ret: pd.Series,
        target_pos: pd.DataFrame,
        metrics: dict,
        codes: List[str],
    ) -> None:
        """Write CSV artifacts compatible with daily_portfolio format."""
        out = run_dir / "artifacts"
        out.mkdir(parents=True, exist_ok=True)

        # OHLCV per symbol
        for code, df in data_map.items():
            df.to_csv(out / f"ohlcv_{code}.csv")

        # Equity curve
        port_ret = equity_series.pct_change().fillna(0.0)
        peak = equity_series.cummax()
        dd = (equity_series - peak) / peak.replace(0, 1)
        eq_df = pd.DataFrame({
            "ret": port_ret,
            "equity": equity_series,
            "drawdown": dd,
            "benchmark_equity": bench_equity.reindex(dates),
            "active_ret": port_ret - bench_ret.reindex(dates).fillna(0.0),
        }, index=dates)
        eq_df.index.name = "timestamp"
        eq_df.to_csv(out / "equity.csv")

        # Position weights (target, for compatibility)
        target_pos.index.name = "timestamp"
        target_pos.to_csv(out / "positions.csv")

        # Trades (compatible format)
        trade_rows = []
        for t in self.trades:
            # Entry event
            trade_rows.append({
                "timestamp": str(t.entry_time.date()) if hasattr(t.entry_time, "date") else str(t.entry_time),
                "code": t.symbol,
                "side": "buy" if t.direction == 1 else "sell",
                "price": round(t.entry_price, 4),
                "qty": round(t.size, 6),
                "reason": "signal",
                "pnl": 0.0,
                "holding_days": 0,
                "holding_bars": 0.0,
                "return_pct": 0.0,
            })
            # Exit event
            try:
                hold_days = (t.exit_time - t.entry_time).days
            except Exception:
                hold_days = 0
            trade_rows.append({
                "timestamp": str(t.exit_time.date()) if hasattr(t.exit_time, "date") else str(t.exit_time),
                "code": t.symbol,
                "side": "sell" if t.direction == 1 else "buy",
                "price": round(t.exit_price, 4),
                "qty": round(t.size, 6),
                "reason": t.exit_reason,
                "pnl": round(t.pnl, 4),
                "holding_days": hold_days,
                "holding_bars": t.holding_bars,
                "return_pct": round(t.pnl_pct, 2),
            })

        trade_cols = [
            "timestamp", "code", "side", "price", "qty", "reason", "pnl",
            "holding_days", "holding_bars", "return_pct",
        ]
        pd.DataFrame(trade_rows or [], columns=trade_cols).to_csv(out / "trades.csv", index=False)

        # Immutable execution evidence. JSONL keeps each delta self-contained
        # and avoids treating this append-only audit trail as mutable position
        # or account state.
        with (out / "fills.jsonl").open("w", encoding="utf-8") as handle:
            for fill in self.fill_records:
                handle.write(json.dumps({
                    "symbol": fill.symbol,
                    "timestamp": fill.timestamp.isoformat(),
                    "bar_idx": fill.bar_idx,
                    "action": fill.action,
                    "signed_quantity": fill.signed_quantity,
                    "notional": fill.notional,
                    "execution_price": fill.execution_price,
                    "fee": fill.fee,
                    "margin": fill.margin,
                    "reason": fill.reason,
                    "holding_bars": fill.holding_bars,
                }, allow_nan=False) + "\n")

        # Metrics
        flat_metrics = {k: v for k, v in metrics.items() if not isinstance(v, dict)}
        pd.DataFrame([flat_metrics]).to_csv(out / "metrics.csv", index=False)

    # ── Helpers ──

    @staticmethod
    def _safe_price(
        close_df: pd.DataFrame,
        ts: pd.Timestamp,
        symbol: str,
        fallback: float,
        *,
        _arr: "np.ndarray | None" = None,
        _row: "int | None" = None,
        _col: "int | None" = None,
    ) -> float:
        """Get close price with fallback. Uses array fast-path when available."""
        # Fast path: pre-computed array indexing (O(1) vs DataFrame.at hash lookup)
        if _arr is not None and _row is not None and _col is not None:
            val = _arr[_row, _col]
            return float(val) if not np.isnan(val) else fallback
        # Original path (backward compatible for subclasses)
        if ts in close_df.index and symbol in close_df.columns:
            val = close_df.at[ts, symbol]
            if pd.notna(val):
                return float(val)
        return fallback
