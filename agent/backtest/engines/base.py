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
import re as _re
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

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
    by_exit_reason_stats,
    by_symbol_stats,
    calc_execution_metrics,
    calc_metrics,
    calc_turnover_series,
    calc_trade_turnover_series,
)
from backtest.models import (
    EquitySnapshot,
    FillRecord,
    OrderRecord,
    Position,
    TradeRecord,
)
from backtest.reporting import build_reporting_outputs, write_reporting_outputs

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _OpenOrder:
    """A priced opening order awaiting lifecycle-aware submission."""

    symbol: str
    direction: int
    decision_price: float
    price: float
    size: float
    leverage: float
    margin: float
    commission: float
    signal_time: pd.Timestamp | None = None

    @property
    def cost(self) -> float:
        """Maximum immediate cash consumed by the planned fill."""
        return self.margin + self.commission


def _safe_signal_time(df: pd.DataFrame, ts: pd.Timestamp) -> pd.Timestamp | None:
    """Return the prior symbol-local timestamp for a next-bar execution signal."""
    try:
        loc = df.index.get_loc(ts)
    except Exception:
        return None

    if isinstance(loc, slice):
        loc = loc.start
    elif isinstance(loc, np.ndarray):
        if len(loc) == 0:
            return None
        loc = int(loc[0])

    if not isinstance(loc, (int, np.integer)) or int(loc) <= 0:
        return None
    try:
        return pd.Timestamp(df.index[int(loc) - 1])
    except Exception:
        return None


def _safe_holding_days(entry_time: Any, exit_time: Any, fallback: int) -> int:
    """Compute holding days safely with a legacy-friendly fallback."""
    try:
        entry_ts = pd.Timestamp(entry_time)
        exit_ts = pd.Timestamp(exit_time)
        return max(int((exit_ts - entry_ts).days), 0)
    except Exception:
        return max(int(fallback), 0)


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
    all_dates: set = set()
    for c in codes:
        all_dates.update(data_map[c].index)
    dates = pd.DatetimeIndex(sorted(all_dates))

    close = pd.DataFrame(index=dates, columns=codes, dtype=float)
    for c in codes:
        close[c] = data_map[c]["close"].reindex(dates)

    # ffill with limit to avoid masking long suspensions (e.g. 3-week halt)
    # Cross-market needs larger limit (Chinese New Year can be 9-10 bars)
    ffill_limit = 10 if len({_detect_market_for_align(c) for c in codes}) > 1 else 5
    close = close.ffill(limit=ffill_limit)

    # Drop symbols that are entirely NaN (no data overlap with date range)
    all_nan_cols = [c for c in codes if close[c].isna().all()]
    if all_nan_cols:
        logger.warning("Symbols dropped (no usable price data): %s", all_nan_cols)
        codes = [c for c in codes if c not in all_nan_cols]
        if not codes:
            raise ValueError("All symbols have no data in the requested date range")
        close = close[codes]

    pos = pd.DataFrame(0.0, index=dates, columns=codes)
    for c in codes:
        # Shift on each symbol's OWN trading calendar, then ffill to unified
        own_dates = data_map[c].index
        raw = signal_map[c].reindex(own_dates).fillna(0.0).clip(-1.0, 1.0)
        shifted = raw.shift(1).fillna(0.0)
        pos[c] = shifted.reindex(dates).ffill(limit=ffill_limit).fillna(0.0)

    ret = close.pct_change().fillna(0.0)

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
    if not opt_name:
        return None
    opt_params = config.get("optimizer_params") or {}
    try:
        mod = importlib.import_module(f"backtest.optimizers.{opt_name}")
        return lambda ret, pos, dates: mod.optimize(ret, pos, dates, **opt_params)
    except (ImportError, AttributeError) as e:
        print(f"[WARN] Failed to load optimizer '{opt_name}': {e}, falling back to equal weight")
        return None


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
        self.capital: float = self.initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[TradeRecord] = []
        self.fills: List[FillRecord] = []
        self.orders: List[OrderRecord] = []
        self.pending_orders: Dict[str, OrderRecord] = {}
        self.equity_snapshots: List[EquitySnapshot] = []
        self.executed_position_weights: List[Dict[str, Any]] = []
        self._exit_accumulators: Dict[str, Dict[str, Any]] = {}
        self._order_sequence: int = 0
        self._volume_participation = self._normalize_volume_participation(
            config.get("volume_participation_rate")
        )
        self.volume_field: str = str(config.get("volume_field", "volume"))
        self._bar_volume_consumed: Dict[tuple[str, pd.Timestamp], float] = {}
        self.default_order_type = str(
            config.get("order_type", "market")
        ).lower()
        if self.default_order_type not in {"market", "limit"}:
            raise ValueError("order_type must be 'market' or 'limit'")
        self.default_time_in_force = str(
            config.get("time_in_force", "GTC")
        ).upper()
        if self.default_time_in_force not in {"GTC", "IOC", "FOK"}:
            raise ValueError("time_in_force must be GTC, IOC, or FOK")
        self._execution_latency_bars = self._normalize_bar_setting(
            config.get("execution_latency_bars", 0),
            "execution_latency_bars",
            allow_none=False,
        )
        self._order_expiry_bars = self._normalize_bar_setting(
            config.get("order_expiry_bars"),
            "order_expiry_bars",
            allow_none=True,
        )
        self._max_unfilled_bars = self._normalize_bar_setting(
            config.get("max_unfilled_bars"),
            "max_unfilled_bars",
            allow_none=True,
        )
        self._limit_price_offset_bps = self._normalize_nonnegative_setting(
            config.get("limit_price_offset_bps", 0.0),
            "limit_price_offset_bps",
        )
        self._venue_rejections = self._normalize_venue_rejections(
            config.get("venue_reject_symbols")
        )
        self._execution_dates = pd.DatetimeIndex([])
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

    def on_bar(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """Per-bar market-rule hook (funding fees, liquidation, etc.).

        Default: no-op. Override in subclass as needed.
        """

    def determine_fill_quantity(
        self,
        order: OrderRecord,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> float:
        """Return the quantity executable for ``order`` on this bar.

        The default preserves the legacy all-or-nothing behavior. Engines or
        tests can override this hook with venue liquidity/participation rules
        to produce partial or zero fills across successive bars.
        """
        return float(order.remaining_quantity or 0.0)

    @staticmethod
    def _normalize_volume_participation(
        raw: Any,
    ) -> float | Dict[str, float] | None:
        """Validate an optional global or per-symbol participation setting."""
        if raw is None:
            return None

        def validate(value: Any, label: str) -> float:
            if isinstance(value, bool):
                raise ValueError(f"{label} must be a number between 0 and 1")
            try:
                rate = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{label} must be a number between 0 and 1"
                ) from exc
            if not np.isfinite(rate) or rate < 0.0 or rate > 1.0:
                raise ValueError(f"{label} must be between 0 and 1 inclusive")
            return rate

        if isinstance(raw, dict):
            return {
                str(symbol): validate(value, f"volume_participation_rate[{symbol!r}]")
                for symbol, value in raw.items()
            }
        return validate(raw, "volume_participation_rate")

    def _participation_rate_for(self, symbol: str) -> float | None:
        """Resolve a symbol-specific rate, falling back to ``default``."""
        setting = self._volume_participation
        if setting is None:
            return None
        if isinstance(setting, dict):
            if symbol in setting:
                return setting[symbol]
            return setting.get("default")
        return setting

    def _volume_context(
        self,
        symbol: str,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> Dict[str, Any]:
        """Return cumulative per-symbol capacity available on this bar."""
        rate = self._participation_rate_for(symbol)
        if rate is None:
            return {
                "enabled": False,
                "bar_volume": None,
                "participation_rate": None,
                "bar_volume_capacity": None,
                "available_quantity": None,
                "volume_limit_exempt": False,
            }
        raw_volume = bar.get(self.volume_field, 0.0)
        try:
            bar_volume = float(raw_volume)
        except (TypeError, ValueError):
            bar_volume = 0.0
        if not np.isfinite(bar_volume) or bar_volume <= 0.0:
            bar_volume = 0.0
        capacity = max(bar_volume * rate, 0.0)
        key = (symbol, pd.Timestamp(timestamp))
        consumed = max(float(self._bar_volume_consumed.get(key, 0.0)), 0.0)
        return {
            "enabled": True,
            "bar_volume": bar_volume,
            "participation_rate": rate,
            "bar_volume_capacity": capacity,
            "available_quantity": max(capacity - consumed, 0.0),
            "volume_limit_exempt": False,
        }

    def _consume_bar_volume(
        self,
        symbol: str,
        timestamp: pd.Timestamp,
        quantity: float,
    ) -> None:
        """Record executed quantity against one symbol/bar capacity budget."""
        key = (symbol, pd.Timestamp(timestamp))
        self._bar_volume_consumed[key] = (
            float(self._bar_volume_consumed.get(key, 0.0)) + abs(float(quantity))
        )

    @staticmethod
    def _normalize_bar_setting(
        raw: Any,
        label: str,
        *,
        allow_none: bool,
    ) -> int | Dict[str, int | None] | None:
        """Validate a non-negative integer scalar or per-symbol mapping."""
        if raw is None:
            return None if allow_none else 0

        def validate(value: Any, value_label: str) -> int | None:
            if value is None and allow_none:
                return None
            if isinstance(value, bool):
                raise ValueError(f"{value_label} must be a non-negative integer")
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{value_label} must be a non-negative integer"
                ) from exc
            if (
                not np.isfinite(numeric)
                or numeric < 0.0
                or not numeric.is_integer()
            ):
                raise ValueError(
                    f"{value_label} must be a non-negative integer"
                )
            return int(numeric)

        if isinstance(raw, dict):
            return {
                str(symbol): validate(value, f"{label}[{symbol!r}]")
                for symbol, value in raw.items()
            }
        return validate(raw, label)

    @staticmethod
    def _normalize_nonnegative_setting(
        raw: Any,
        label: str,
    ) -> float | Dict[str, float]:
        """Validate a finite non-negative scalar or per-symbol mapping."""
        def validate(value: Any, value_label: str) -> float:
            if isinstance(value, bool):
                raise ValueError(f"{value_label} must be a non-negative number")
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{value_label} must be a non-negative number"
                ) from exc
            if not np.isfinite(numeric) or numeric < 0.0:
                raise ValueError(f"{value_label} must be a non-negative number")
            return numeric

        if isinstance(raw, dict):
            return {
                str(symbol): validate(value, f"{label}[{symbol!r}]")
                for symbol, value in raw.items()
            }
        return validate(raw, label)

    @staticmethod
    def _normalize_venue_rejections(raw: Any) -> Dict[str, str]:
        """Normalize deterministic per-symbol venue rejection reasons."""
        if raw in (None, [], {}):
            return {}
        if isinstance(raw, dict):
            return {
                str(symbol): str(reason or "venue_rejected")
                for symbol, reason in raw.items()
            }
        if isinstance(raw, (list, tuple, set)):
            return {str(symbol): "venue_rejected" for symbol in raw}
        raise ValueError("venue_reject_symbols must be a list or mapping")

    @staticmethod
    def _symbol_setting(
        setting: Any,
        symbol: str,
        default: Any,
    ) -> Any:
        """Resolve an exact symbol or ``default`` entry from a setting."""
        if isinstance(setting, dict):
            if symbol in setting:
                return setting[symbol]
            return setting.get("default", default)
        return setting if setting is not None else default

    def _bar_time(self, bar_index: int | None) -> pd.Timestamp | None:
        """Resolve a configured execution bar index to its actual timestamp."""
        if bar_index is None or len(self._execution_dates) == 0:
            return None
        if 0 <= int(bar_index) < len(self._execution_dates):
            return pd.Timestamp(self._execution_dates[int(bar_index)])
        return None

    def order_rejection_reason(
        self,
        order: OrderRecord,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> str | None:
        """Return a deterministic venue rejection reason, if any.

        Market engines may override this hook for venue-specific validation.
        Temporary market restrictions belong in :meth:`can_execute` and do
        not reject an otherwise valid persistent order.
        """
        return self._venue_rejections.get(order.symbol) or self._venue_rejections.get(
            "default"
        )

    def _limit_offset_for(self, symbol: str) -> float:
        return float(self._symbol_setting(
            self._limit_price_offset_bps, symbol, 0.0,
        ))

    def _configured_limit_price(
        self,
        symbol: str,
        side: str,
        decision_price: float,
    ) -> float:
        """Return a passive limit derived from the order decision price."""
        offset = self._limit_offset_for(symbol) / 10_000.0
        multiplier = 1.0 - offset if side == "buy" else 1.0 + offset
        return float(decision_price) * multiplier

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
        """Margin (collateral) required for a position."""
        return size * price / leverage

    def _calc_raw_size(
        self, symbol: str, target_notional: float, price: float,
    ) -> float:
        """Convert target notional exposure to number of units/contracts."""
        return target_notional / price

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
        executed_positions = self._executed_positions_frame(dates, valid_codes)
        daily_accounting = self._build_daily_accounting(
            equity_series,
            executed_positions,
            dates,
        )
        bench_ret = ret_df.mean(axis=1) if ret_df.shape[1] > 0 else pd.Series(0.0, index=dates)
        benchmark_metadata = {}

        # ── External benchmark fetch ──────────────────────────────────────────
        bench_ticker = config.get("benchmark")
        if bench_ticker and bench_ticker != "auto":
            from backtest.benchmark import resolve_benchmark
            bench_result = resolve_benchmark(
                strategy_codes=codes,
                source=config.get("source", "yfinance"),
                start_date=config.get("start_date", ""),
                end_date=config.get("end_date", ""),
                interval=interval,
                explicit=bench_ticker,
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
        realized_turnover = calc_trade_turnover_series(self.trades, equity_series)
        m = calc_metrics(
            equity_series,
            self.trades,
            self.initial_capital,
            bars_per_year,
            bench_ret,
            target_pos,
            turnover_series=realized_turnover,
        )
        m.update(calc_execution_metrics(
            executed_positions,
            self.fills,
            observation_count=len(equity_series),
            bars_per_year=bars_per_year,
            orders=self.orders,
        ))
        m.update(benchmark_metadata)
        m["by_symbol"] = by_symbol_stats(self.trades)
        m["by_exit_reason"] = by_exit_reason_stats(self.trades)

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
            target_pos, m, valid_codes, executed_positions, daily_accounting,
            bars_per_year=bars_per_year,
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

        # Print scalar metrics (skip nested dicts for JSON compat)
        print(json.dumps({k: v for k, v in m.items() if not isinstance(v, dict)}, indent=2))
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
        self._execution_dates = pd.DatetimeIndex(dates)
        for i, ts in enumerate(dates):
            self._bar_idx = i

            # a. Value the book at prices observable when orders execute.
            # Rebalances happen at the bar open, so using close_df[ts] here
            # would let the yet-unknown decision-bar close affect order size.
            equity = self._calc_open_equity(data_map, close_df, ts)
            target_weights: Dict[str, Optional[float]] = {}
            for c in codes:
                try:
                    target_weights[c] = (
                        float(target_pos.at[ts, c]) if ts in target_pos.index else 0.0
                    )
                except Exception as exc:
                    target_weights[c] = None
                    logger.warning("Target weight failed for %s at %s: %s", c, ts, exc)

            # b. Release capital before opening replacement positions.  A
            # single mixed close/open pass makes rotations depend on symbol
            # iteration order when the new name is visited before the old one.
            for c in codes:
                target_w = target_weights[c]
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
                target_w = target_weights[c]
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
                frame = data_map.get(order.symbol)
                if frame is None or ts not in frame.index:
                    continue
                self._execute_open_order(order, frame.loc[ts], ts)

            # d. Apply close/within-bar hooks after open execution.  Hooks use
            # the current bar's close for funding, swaps, and liquidation, so
            # running them first could liquidate a position that was scheduled
            # to exit at the open (or charge a position before it was opened).
            for c in codes:
                if ts in data_map[c].index:
                    self.on_bar(c, data_map[c].loc[ts], ts)

            # e. Record equity snapshot
            snap_equity = self._calc_equity(close_df, ts)
            if self.positions and type(self)._calc_pnl is BaseEngine._calc_pnl:
                _syms = list(self.positions.keys())
                _eps = np.array([p.entry_price for p in self.positions.values()])
                _dirs = np.array([p.direction for p in self.positions.values()])
                _sizes = np.array([p.size for p in self.positions.values()])
                _cps = np.array(
                    [self._safe_price(close_df, ts, s, ep) for s, ep in zip(_syms, _eps)]
                )
                total_unrealized = float(np.sum(_dirs * _sizes * (_cps - _eps)))
            else:
                total_unrealized = 0.0
                for p in self.positions.values():
                    cp = self._safe_price(close_df, ts, p.symbol, p.entry_price)
                    total_unrealized += self._calc_pnl(p.symbol, p.direction, p.size, p.entry_price, cp)
            self.equity_snapshots.append(EquitySnapshot(
                timestamp=ts,
                capital=self.capital,
                unrealized=total_unrealized,
                equity=snap_equity,
                positions=len(self.positions),
            ))
            self._record_executed_position_weights(
                ts,
                close_df,
                snap_equity,
                codes,
            )

        # f. Force close all remaining positions
        if len(dates) > 0:
            last_ts = dates[-1]
            # Pending residuals are cancelled before the terminal flattening
            # order. Any quantity already filled remains in the position and
            # is liquidated exactly once below.
            for order in list(self.pending_orders.values()):
                order.cancel(last_ts, "end_of_backtest")
            self.pending_orders.clear()

            for c in list(self.positions.keys()):
                self._active_symbol = c
                decision_price = self._safe_price(
                    close_df,
                    last_ts,
                    c,
                    self.positions[c].entry_price,
                )
                fill_price = self.apply_slippage(
                    decision_price,
                    -self.positions[c].direction,
                )
                self._close_position(
                    c,
                    fill_price,
                    last_ts,
                    "end_of_backtest",
                    exit_decision_price=decision_price,
                )

            # The backtest has a canonical flat terminal state. Forced exits
            # happen after the ordinary final-bar mark, so replace that mark
            # with post-liquidation cash equity. Metrics, validation, daily
            # accounting, and artifacts are all built from these snapshots.
            if self.equity_snapshots:
                self.equity_snapshots[-1] = EquitySnapshot(
                    timestamp=last_ts,
                    capital=self.capital,
                    unrealized=0.0,
                    equity=self.capital,
                    positions=0,
                )

            if self.executed_position_weights:
                self._record_executed_position_weights(
                    last_ts,
                    close_df,
                    self._calc_equity(close_df, last_ts),
                    codes,
                    replace_last=True,
                )

    def _calc_open_equity(
        self,
        data_map: Dict[str, pd.DataFrame],
        close_df: pd.DataFrame,
        ts: pd.Timestamp,
    ) -> float:
        """Value current positions at the execution bar's observable open.

        For a symbol that has a bar at ``ts``, its open is the mark available
        when next-bar-open orders execute. Symbols without a bar on the
        unified calendar retain the aligned close fallback, which is the most
        recent price carried by ``_align``.
        """
        if not self.positions:
            return self.capital

        equity = self.capital
        for sym, pos in self.positions.items():
            current_price = self._safe_price(close_df, ts, sym, pos.entry_price)
            frame = data_map.get(sym)
            if frame is not None and ts in frame.index:
                open_price = frame.loc[ts].get("open")
                if (
                    open_price is not None
                    and pd.notna(open_price)
                    and float(open_price) > 0
                ):
                    current_price = float(open_price)

            margin = self._calc_margin(
                sym, pos.size, pos.entry_price, pos.leverage
            )
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

        if _base_pnl and _base_margin:
            syms = list(self.positions.keys())
            sizes = np.array([p.size for p in self.positions.values()])
            entry_prices = np.array([p.entry_price for p in self.positions.values()])
            directions = np.array([p.direction for p in self.positions.values()])
            leverages = np.array([p.leverage for p in self.positions.values()])

            current_prices = np.array(
                [self._safe_price(close_df, ts, s, ep) for s, ep in zip(syms, entry_prices)]
            )

            margins = sizes * entry_prices / leverages
            pnls = directions * sizes * (current_prices - entry_prices)
            return self.capital + float(np.sum(margins + pnls))

        equity = self.capital
        for sym, pos in self.positions.items():
            cp = self._safe_price(close_df, ts, sym, pos.entry_price)
            margin = self._calc_margin(sym, pos.size, pos.entry_price, pos.leverage)
            unrealized = self._calc_pnl(sym, pos.direction, pos.size, pos.entry_price, cp)
            equity += margin + unrealized
        return equity

    def _record_executed_position_weights(
        self,
        ts: pd.Timestamp,
        close_df: pd.DataFrame,
        equity: float,
        codes: List[str],
        *,
        replace_last: bool = False,
    ) -> None:
        """Record signed post-execution weights using current marked prices."""
        row: Dict[str, Any] = {"timestamp": pd.Timestamp(ts)}
        row.update({code: 0.0 for code in codes})

        if np.isfinite(equity) and abs(equity) > 1e-12:
            for symbol, pos in self.positions.items():
                current_price = self._safe_price(close_df, ts, symbol, pos.entry_price)
                # Margin * leverage recovers current notional and respects
                # futures contract multipliers through the shared margin hook.
                notional = self._calc_margin(
                    symbol,
                    pos.size,
                    current_price,
                    pos.leverage,
                ) * pos.leverage
                row[symbol] = pos.direction * notional / equity

        if (
            replace_last
            and self.executed_position_weights
            and self.executed_position_weights[-1].get("timestamp") == pd.Timestamp(ts)
        ):
            self.executed_position_weights[-1] = row
        else:
            self.executed_position_weights.append(row)

    def _executed_positions_frame(
        self,
        dates: pd.DatetimeIndex,
        codes: List[str],
    ) -> pd.DataFrame:
        """Return execution-weight snapshots aligned to every backtest bar."""
        if not self.executed_position_weights:
            frame = pd.DataFrame(0.0, index=dates, columns=codes)
        else:
            frame = pd.DataFrame(self.executed_position_weights)
            frame["timestamp"] = pd.to_datetime(frame["timestamp"])
            frame = frame.drop_duplicates("timestamp", keep="last").set_index("timestamp")
            frame = frame.reindex(index=dates, columns=codes).fillna(0.0)
        frame.index.name = "timestamp"
        return frame.astype(float)

    def _build_daily_accounting(
        self,
        equity_series: pd.Series,
        executed_positions: pd.DataFrame,
        dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Build reconciled daily net/gross accounting from actual fills.

        ``gross_return`` is a cost-added reconciliation series:
        ``net_return + cost_rate``. It is not a separately simulated no-cost
        execution run. The first row uses initial capital as previous equity;
        later rows use the prior observed equity. A zero denominator produces
        a deterministic zero return/cost rate.
        """
        index = pd.DatetimeIndex(dates)
        equity = equity_series.reindex(index).astype(float)
        previous_equity = equity.shift(1)
        if len(previous_equity) > 0:
            previous_equity.iloc[0] = self.initial_capital
        safe_previous = previous_equity.where(previous_equity.abs() > 1e-12)
        net_return = ((equity - previous_equity) / safe_previous).fillna(0.0)

        daily_commission = pd.Series(0.0, index=index)
        daily_slippage = pd.Series(0.0, index=index)
        if self.fills:
            fill_costs = pd.DataFrame({
                "timestamp": [pd.Timestamp(fill.timestamp) for fill in self.fills],
                "commission": [float(fill.commission) for fill in self.fills],
                "slippage_cost": [float(fill.slippage_cost) for fill in self.fills],
            }).groupby("timestamp")[["commission", "slippage_cost"]].sum()
            daily_commission = fill_costs["commission"].reindex(index).fillna(0.0)
            daily_slippage = fill_costs["slippage_cost"].reindex(index).fillna(0.0)

        daily_total_cost = daily_commission + daily_slippage
        cost_rate = (daily_total_cost / safe_previous).fillna(0.0)
        gross_return = net_return + cost_rate
        gross_equity = self.initial_capital * (1.0 + gross_return).cumprod()

        positions = executed_positions.reindex(index=index).fillna(0.0)
        one_way_turnover = calc_turnover_series(positions).reindex(index).fillna(0.0)
        gross_exposure = positions.abs().sum(axis=1)
        net_exposure = positions.sum(axis=1)
        long_exposure = positions.clip(lower=0.0).sum(axis=1)
        short_exposure = -positions.clip(upper=0.0).sum(axis=1)

        accounting = pd.DataFrame({
            "net_return": net_return,
            "gross_return": gross_return,
            "daily_commission": daily_commission,
            "daily_slippage_cost": daily_slippage,
            "daily_total_cost": daily_total_cost,
            "cost_rate": cost_rate,
            "one_way_turnover": one_way_turnover,
            "gross_exposure": gross_exposure,
            "net_exposure": net_exposure,
            "long_exposure": long_exposure,
            "short_exposure": short_exposure,
            "equity": equity,
            "gross_equity": gross_equity,
        }, index=index)
        accounting.index.name = "timestamp"
        return accounting

    def _plan_open_order(
        self,
        symbol: str,
        target_weight: float,
        df: Optional[pd.DataFrame],
        ts: pd.Timestamp,
        equity: float,
    ) -> Optional[_OpenOrder]:
        """Price an opening order without mutating portfolio state."""
        self._active_symbol = symbol
        direction = (
            1 if target_weight > 1e-9 else -1 if target_weight < -1e-9 else 0
        )
        if (
            direction == 0
            or symbol in self.positions
            or df is None
            or ts not in df.index
        ):
            return None
        bar = df.loc[ts]
        decision_price = float(bar.get("open", bar.get("close", 0)))
        if decision_price <= 0:
            return None
        price = self.apply_slippage(decision_price, direction)
        leverage = self.default_leverage
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
            decision_price=decision_price,
            price=price,
            size=size,
            leverage=leverage,
            margin=margin,
            commission=commission,
            signal_time=_safe_signal_time(df, ts),
        )

    def _execute_open_order(
        self,
        plan: _OpenOrder,
        bar: pd.Series,
        ts: pd.Timestamp,
    ) -> None:
        """Submit a priced opening plan through the persistent order ledger."""
        self._active_symbol = plan.symbol
        order = self._create_order(
            symbol=plan.symbol,
            event_type="entry",
            direction=plan.direction,
            quantity=plan.size,
            timestamp=ts,
            decision_price=plan.decision_price,
            reason="signal",
            signal_time=plan.signal_time,
        )
        self._process_order(order, bar, ts)
        if order.status == "filled":
            self.pending_orders.pop(plan.symbol, None)

    def _rebalance(
        self,
        symbol: str,
        target_weight: float,
        df: Optional[pd.DataFrame],
        ts: pd.Timestamp,
        equity: float,
    ) -> None:
        """Adjust a symbol toward its target using persistent order state."""
        self._active_symbol = symbol
        target_dir = 1 if target_weight > 1e-9 else (-1 if target_weight < -1e-9 else 0)
        if df is None or ts not in df.index:
            return
        bar = df.loc[ts]

        pending = self.pending_orders.get(symbol)
        if pending is not None:
            current = self.positions.get(symbol)
            incompatible = (
                pending.event_type == "entry" and target_dir != pending.direction
            ) or (
                pending.event_type == "exit"
                and (current is None or target_dir == current.direction)
            )
            if incompatible:
                pending.cancel(ts, "signal_changed")
                self.pending_orders.pop(symbol, None)
            else:
                pending_event = pending.event_type
                self._process_order(pending, bar, ts)
                if pending.status in {"open", "partially_filled"}:
                    return
                self.pending_orders.pop(symbol, None)
                if pending_event == "entry":
                    return
                # A filled exit may open the opposite target below. Any other
                # terminal outcome must wait until the next bar instead of
                # immediately resubmitting a rejected/expired/cancelled exit.
                if pending.status != "filled":
                    return

        current_pos = self.positions.get(symbol)
        if current_pos is None and target_dir == 0:
            return

        # Close if target is flat or direction changed. A partial exit remains
        # pending and continues on later bars.
        if current_pos is not None:
            need_close = target_dir == 0 or target_dir != current_pos.direction
            if need_close:
                decision_price = float(bar.get("open", bar.get("close", 0)))
                if decision_price <= 0:
                    return
                order = self._create_order(
                    symbol=symbol,
                    event_type="exit",
                    direction=current_pos.direction,
                    quantity=current_pos.size,
                    timestamp=ts,
                    decision_price=decision_price,
                    reason="signal",
                    signal_time=current_pos.signal_time,
                )
                self._process_order(order, bar, ts)
                if order.status in {"open", "partially_filled"}:
                    return
                self.pending_orders.pop(symbol, None)

        if target_dir != 0 and symbol not in self.positions:
            decision_price = float(bar.get("open", bar.get("close", 0)))
            if decision_price <= 0:
                return
            fill_price = self.apply_slippage(decision_price, target_dir)
            signal_time = _safe_signal_time(df, ts)
            leverage = self.default_leverage
            target_notional = abs(target_weight) * equity * leverage
            raw_size = self._calc_raw_size(symbol, target_notional, fill_price)
            size = self.round_size(raw_size, fill_price)
            if size <= 0:
                return
            order = self._create_order(
                symbol=symbol,
                event_type="entry",
                direction=target_dir,
                quantity=size,
                timestamp=ts,
                decision_price=decision_price,
                reason="signal",
                signal_time=signal_time,
            )
            self._process_order(order, bar, ts)
            if order.status == "filled":
                self.pending_orders.pop(symbol, None)
            return

    def _next_order_id(self) -> str:
        """Return a deterministic identifier local to this engine run."""
        self._order_sequence += 1
        return f"order_{self._order_sequence:08d}"

    def _create_order(
        self,
        *,
        symbol: str,
        event_type: str,
        direction: int,
        quantity: float,
        timestamp: pd.Timestamp,
        decision_price: float,
        reason: str,
        signal_time: pd.Timestamp | None = None,
        order_type: str | None = None,
        limit_price: float | None = None,
        time_in_force: str | None = None,
        latency_bars: int | None = None,
        expiry_bars: int | None = None,
    ) -> OrderRecord:
        """Create and register a persistent entry or exit order."""
        if event_type not in {"entry", "exit"}:
            raise ValueError(f"unsupported order event type: {event_type!r}")
        side = (
            "buy"
            if (event_type == "entry" and direction == 1)
            or (event_type == "exit" and direction == -1)
            else "sell"
        )
        resolved_type = str(order_type or self.default_order_type).lower()
        if resolved_type not in {"market", "limit"}:
            raise ValueError(f"unsupported order type: {resolved_type!r}")
        resolved_tif = str(
            time_in_force or self.default_time_in_force
        ).upper()
        if resolved_tif not in {"GTC", "IOC", "FOK"}:
            raise ValueError(f"unsupported time in force: {resolved_tif!r}")

        configured_latency = self._symbol_setting(
            self._execution_latency_bars, symbol, 0,
        )
        latency_value = configured_latency if latency_bars is None else latency_bars
        resolved_latency = self._normalize_bar_setting(
            latency_value,
            "latency_bars",
            allow_none=False,
        )
        if isinstance(resolved_latency, dict) or resolved_latency is None:
            raise ValueError("latency_bars must resolve to a non-negative integer")
        configured_expiry = self._symbol_setting(
            self._order_expiry_bars, symbol, None,
        )
        expiry_value = configured_expiry if expiry_bars is None else expiry_bars
        resolved_expiry = self._normalize_bar_setting(
            expiry_value,
            "expiry_bars",
            allow_none=True,
        )
        if isinstance(resolved_expiry, dict):
            raise ValueError("expiry_bars must resolve to a non-negative integer")

        try:
            raw_quantity = float(quantity)
        except (TypeError, ValueError):
            raw_quantity = float("nan")
        try:
            raw_decision_price = float(decision_price)
        except (TypeError, ValueError):
            raw_decision_price = float("nan")
        safe_quantity = abs(raw_quantity) if np.isfinite(raw_quantity) else 0.0
        safe_decision_price = (
            raw_decision_price if np.isfinite(raw_decision_price) else 0.0
        )
        resolved_limit = limit_price
        if resolved_type == "limit" and resolved_limit is None:
            resolved_limit = self._configured_limit_price(
                symbol, side, safe_decision_price,
            )
        if resolved_limit is not None:
            try:
                resolved_limit = float(resolved_limit)
            except (TypeError, ValueError):
                resolved_limit = float("nan")

        rejection_reason = ""
        if direction not in {-1, 1}:
            rejection_reason = "invalid_direction"
        elif not np.isfinite(raw_quantity) or safe_quantity <= 0.0:
            rejection_reason = "invalid_quantity"
        elif not np.isfinite(raw_decision_price) or safe_decision_price <= 0.0:
            rejection_reason = "invalid_decision_price"
        elif resolved_type == "limit" and (
            resolved_limit is None
            or not np.isfinite(resolved_limit)
            or resolved_limit <= 0.0
        ):
            rejection_reason = "invalid_limit_price"

        created_bar_index = max(int(self._bar_idx), 0)
        eligible_bar_index = created_bar_index + resolved_latency
        expires_bar_index = (
            created_bar_index + resolved_expiry
            if resolved_expiry is not None else None
        )
        terminal = bool(rejection_reason)
        order = OrderRecord(
            order_id=self._next_order_id(),
            symbol=symbol,
            side=side,
            event_type=event_type,
            direction=direction,
            requested_quantity=safe_quantity,
            created_time=pd.Timestamp(timestamp),
            decision_price=safe_decision_price,
            reason=reason,
            remaining_quantity=0.0 if terminal else None,
            cancelled_quantity=safe_quantity if terminal else 0.0,
            status="rejected" if terminal else "open",
            updated_time=pd.Timestamp(timestamp) if terminal else None,
            signal_time=signal_time,
            order_type=resolved_type,
            limit_price=resolved_limit,
            time_in_force=resolved_tif,
            created_bar_index=created_bar_index,
            eligible_bar_index=eligible_bar_index,
            eligible_time=self._bar_time(eligible_bar_index),
            expires_bar_index=expires_bar_index,
            expires_time=self._bar_time(expires_bar_index),
            status_reason=rejection_reason,
        )
        self.orders.append(order)
        if not terminal:
            self.pending_orders[symbol] = order
        return order

    def _affordable_entry_quantity(
        self,
        order: OrderRecord,
        requested: float,
        fill_price: float,
    ) -> float:
        """Clamp an entry fill to capital available at execution time."""
        quantity = min(abs(float(requested)), float(order.remaining_quantity or 0.0))
        quantity = self.round_size(quantity, fill_price)
        if quantity <= 0:
            return 0.0
        leverage = self.default_leverage
        margin = self._calc_margin(order.symbol, quantity, fill_price, leverage)
        commission = self.calc_commission(
            quantity, fill_price, order.direction, is_open=True,
        )
        if margin + commission <= self.capital + 1e-9:
            return quantity

        available = max(self.capital, 0.0)
        raw = self._calc_raw_size(
            order.symbol, available * leverage, fill_price,
        )
        quantity = min(quantity, self.round_size(raw, fill_price))
        for _ in range(12):
            if quantity <= 0:
                return 0.0
            margin = self._calc_margin(order.symbol, quantity, fill_price, leverage)
            commission = self.calc_commission(
                quantity, fill_price, order.direction, is_open=True,
            )
            required = margin + commission
            if required <= self.capital + 1e-9:
                return quantity
            scale = max(self.capital / required, 0.0) if required > 0 else 0.0
            reduced = self.round_size(quantity * scale * (1.0 - 1e-9), fill_price)
            if reduced >= quantity:
                return 0.0
            quantity = reduced
        return 0.0

    @staticmethod
    def _finite_price(value: Any) -> float | None:
        """Return a positive finite price or ``None``."""
        try:
            price = float(value)
        except (TypeError, ValueError):
            return None
        return price if np.isfinite(price) and price > 0.0 else None

    def _execution_prices(
        self,
        order: OrderRecord,
        bar: pd.Series,
        execution_direction: int,
    ) -> tuple[float, float] | None:
        """Resolve an eligible decision/fill price for market or limit orders."""
        open_price = self._finite_price(bar.get("open", bar.get("close", 0.0)))
        if open_price is None:
            return None
        if order.order_type == "market":
            fill_price = self._finite_price(
                self.apply_slippage(open_price, execution_direction)
            )
            return (
                (open_price, fill_price) if fill_price is not None else None
            )

        limit_price = self._finite_price(order.limit_price)
        low_price = self._finite_price(bar.get("low"))
        high_price = self._finite_price(bar.get("high"))
        if limit_price is None or low_price is None or high_price is None:
            return None

        if order.side == "buy":
            if low_price > limit_price + 1e-12:
                return None
            decision_price = min(open_price, limit_price)
            slipped = self._finite_price(
                self.apply_slippage(decision_price, 1)
            )
            if slipped is None:
                return None
            fill_price = min(slipped, limit_price)
        else:
            if high_price < limit_price - 1e-12:
                return None
            decision_price = max(open_price, limit_price)
            slipped = self._finite_price(
                self.apply_slippage(decision_price, -1)
            )
            if slipped is None:
                return None
            fill_price = max(slipped, limit_price)
        return decision_price, fill_price

    def _record_unfilled_attempt(
        self,
        order: OrderRecord,
        timestamp: pd.Timestamp,
        reason: str,
    ) -> None:
        """Record a zero-fill attempt and apply deterministic cancellation."""
        order.record_unfilled(timestamp)
        if order.time_in_force in {"IOC", "FOK"}:
            order.cancel(timestamp, f"{order.time_in_force.lower()}_{reason}")
        else:
            max_unfilled = self._symbol_setting(
                self._max_unfilled_bars, order.symbol, None,
            )
            if (
                max_unfilled is not None
                and order.unfilled_eligible_bars >= int(max_unfilled)
            ):
                order.cancel(timestamp, f"max_unfilled_bars:{reason}")
        if order.status not in {"open", "partially_filled"}:
            self.pending_orders.pop(order.symbol, None)

    def _process_order(
        self,
        order: OrderRecord,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> float:
        """Execute at most one fill for an order on the current bar."""
        if order.status not in {"open", "partially_filled"}:
            return 0.0
        timestamp = pd.Timestamp(timestamp)
        if (
            order.expires_bar_index is not None
            and self._bar_idx > order.expires_bar_index
        ):
            order.expire(timestamp, "order_expiry_bars")
            self.pending_orders.pop(order.symbol, None)
            return 0.0
        if self._bar_idx < order.eligible_bar_index:
            order.record_deferred(timestamp)
            return 0.0
        order.set_eligible_time(timestamp)
        order.record_attempt(timestamp)

        rejection_reason = self.order_rejection_reason(order, bar, timestamp)
        if rejection_reason:
            order.reject(timestamp, rejection_reason)
            self.pending_orders.pop(order.symbol, None)
            return 0.0
        execution_direction = (
            order.direction if order.event_type == "entry" else -order.direction
        )
        market_rule_direction = (
            order.direction if order.event_type == "entry" else 0
        )
        if not self.can_execute(order.symbol, market_rule_direction, bar):
            self._record_unfilled_attempt(
                order, timestamp, "market_rule_blocked",
            )
            return 0.0
        prices = self._execution_prices(order, bar, execution_direction)
        if prices is None:
            self._record_unfilled_attempt(
                order,
                timestamp,
                "limit_not_touched" if order.order_type == "limit"
                else "invalid_market_price",
            )
            return 0.0
        decision_price, fill_price = prices
        remaining_before_fill = float(order.remaining_quantity or 0.0)
        try:
            requested_on_bar = float(self.determine_fill_quantity(
                order, bar, pd.Timestamp(timestamp)
            ))
        except (TypeError, ValueError):
            requested_on_bar = 0.0
        if not np.isfinite(requested_on_bar):
            requested_on_bar = 0.0
        requested_on_bar = min(
            max(requested_on_bar, 0.0),
            remaining_before_fill,
        )
        volume_context = self._volume_context(order.symbol, bar, timestamp)
        available_quantity = volume_context["available_quantity"]
        volume_constrained = (
            volume_context["enabled"]
            and requested_on_bar > float(available_quantity) + 1e-9
        )
        if volume_constrained:
            order.record_volume_constraint()
        quantity = (
            min(requested_on_bar, float(available_quantity))
            if volume_context["enabled"] else requested_on_bar
        )
        try:
            quantity = float(self.round_size(quantity, fill_price))
        except (TypeError, ValueError):
            quantity = 0.0
        if not np.isfinite(quantity) or quantity < 0.0:
            quantity = 0.0
        if volume_context["enabled"]:
            # A venue rounder may round to the nearest lot and therefore move
            # above the cap. Reject that sub-lot execution rather than emit an
            # impossible fill or manufacture an invalid fractional lot.
            if quantity > float(available_quantity) + 1e-9:
                quantity = 0.0
        full_liquidity = (
            not volume_constrained
            and requested_on_bar + 1e-9 >= remaining_before_fill
        )
        if order.event_type == "entry":
            quantity = self._affordable_entry_quantity(order, quantity, fill_price)
            # Preserve the legacy full-fill behavior when the only reduction
            # is the capital constraint. Liquidity-driven reductions remain
            # genuine partial fills and keep their original requested size.
            if (
                order.time_in_force == "GTC"
                and full_liquidity
                and 0 < quantity < remaining_before_fill
            ):
                order.requested_quantity = order.filled_quantity + quantity
                order.remaining_quantity = quantity
        else:
            position = self.positions.get(order.symbol)
            if position is None:
                order.cancel(timestamp, "position_missing")
                return 0.0
            quantity = min(quantity, abs(float(position.size)))
            try:
                quantity = float(self.round_size(quantity, fill_price))
            except (TypeError, ValueError):
                quantity = 0.0
            if not np.isfinite(quantity) or quantity < 0.0:
                quantity = 0.0
        if (
            volume_context["enabled"]
            and quantity > float(available_quantity) + 1e-9
        ):
            quantity = 0.0
        if (
            order.time_in_force == "FOK"
            and quantity + 1e-9 < remaining_before_fill
        ):
            self._record_unfilled_attempt(order, timestamp, "not_fully_fillable")
            return 0.0
        if quantity <= 0:
            self._record_unfilled_attempt(order, timestamp, "zero_fill_quantity")
            return 0.0

        order.record_fill(quantity, timestamp)
        if volume_context["enabled"]:
            self._consume_bar_volume(order.symbol, timestamp, quantity)
        if order.event_type == "entry":
            self._execute_entry_fill(
                order,
                quantity,
                decision_price,
                fill_price,
                pd.Timestamp(timestamp),
                volume_context=volume_context,
            )
        else:
            self._execute_exit_fill(
                order,
                quantity,
                decision_price,
                fill_price,
                pd.Timestamp(timestamp),
                volume_context=volume_context,
            )
        if order.time_in_force == "IOC" and order.status == "partially_filled":
            order.cancel(timestamp, "ioc_residual")
        if order.status not in {"open", "partially_filled"}:
            self.pending_orders.pop(order.symbol, None)
        return quantity

    def _execute_entry_fill(
        self,
        order: OrderRecord,
        quantity: float,
        decision_price: float,
        fill_price: float,
        timestamp: pd.Timestamp,
        volume_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Apply one entry fill and aggregate it into the position basis."""
        leverage = self.default_leverage
        commission = self.calc_commission(
            quantity, fill_price, order.direction, is_open=True,
        )
        margin = self._calc_margin(order.symbol, quantity, fill_price, leverage)
        slippage_cost = self._calc_pnl(
            order.symbol,
            order.direction,
            quantity,
            decision_price,
            fill_price,
        )
        self.capital -= margin + commission

        current = self.positions.get(order.symbol)
        if current is None:
            position = Position(
                symbol=order.symbol,
                direction=order.direction,
                entry_price=fill_price,
                entry_time=timestamp,
                size=quantity,
                leverage=leverage,
                entry_bar_idx=self._bar_idx,
                entry_commission=commission,
                entry_decision_price=decision_price,
                entry_slippage_cost=slippage_cost,
                signal_time=order.signal_time,
            )
        else:
            total_size = current.size + quantity
            current_decision = float(
                current.entry_decision_price
                if current.entry_decision_price is not None
                else current.entry_price
            )
            position = Position(
                symbol=current.symbol,
                direction=current.direction,
                entry_price=(current.entry_price * current.size + fill_price * quantity) / total_size,
                entry_time=current.entry_time,
                size=total_size,
                leverage=current.leverage,
                entry_bar_idx=current.entry_bar_idx,
                entry_commission=current.entry_commission + commission,
                entry_decision_price=(
                    current_decision * current.size + decision_price * quantity
                ) / total_size,
                entry_slippage_cost=current.entry_slippage_cost + slippage_cost,
                signal_time=current.signal_time,
            )
        self.positions[order.symbol] = position
        volume_context = volume_context or {}
        self.fills.append(FillRecord(
            timestamp=timestamp,
            symbol=order.symbol,
            side=order.side,
            event_type="entry",
            direction=order.direction,
            quantity=quantity,
            decision_price=decision_price,
            fill_price=fill_price,
            notional=quantity * fill_price,
            commission=commission,
            slippage_cost=slippage_cost,
            reason=order.reason,
            order_id=order.order_id,
            requested_quantity=order.requested_quantity,
            remaining_quantity=order.remaining_quantity,
            fill_status=order.status,
            bar_volume=volume_context.get("bar_volume"),
            participation_rate=volume_context.get("participation_rate"),
            bar_volume_capacity=volume_context.get("bar_volume_capacity"),
            volume_limit_exempt=bool(
                volume_context.get("volume_limit_exempt", False)
            ),
            order_type=order.order_type,
            limit_price=order.limit_price,
            eligible_time=order.eligible_time,
            eligible_bar_index=order.eligible_bar_index,
            execution_bar_index=self._bar_idx,
            time_in_force=order.time_in_force,
        ))

    def _start_exit_accumulator(self, position: Position) -> Dict[str, Any]:
        """Capture entry state for a sequence of partial exits."""
        accumulator = {
            "symbol": position.symbol,
            "direction": position.direction,
            "entry_price": position.entry_price,
            "entry_decision_price": float(
                position.entry_decision_price
                if position.entry_decision_price is not None
                else position.entry_price
            ),
            "entry_time": position.entry_time,
            "entry_bar_idx": position.entry_bar_idx,
            "entry_size": position.size,
            "leverage": position.leverage,
            "entry_commission": position.entry_commission,
            "signal_time": position.signal_time,
            "exit_quantity": 0.0,
            "exit_fill_notional": 0.0,
            "exit_decision_notional": 0.0,
            "execution_pnl": 0.0,
            "gross_pnl": 0.0,
            "exit_commission": 0.0,
            "last_exit_time": None,
            "last_reason": "signal",
        }
        self._exit_accumulators[position.symbol] = accumulator
        return accumulator

    def _execute_exit_fill(
        self,
        order: OrderRecord,
        quantity: float,
        decision_price: float,
        fill_price: float,
        timestamp: pd.Timestamp,
        volume_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Apply one exit fill and finalize one trade when flat."""
        position = self.positions.get(order.symbol)
        if position is None:
            return
        accumulator = self._exit_accumulators.get(order.symbol)
        if accumulator is None:
            accumulator = self._start_exit_accumulator(position)

        execution_pnl = self._calc_pnl(
            order.symbol, position.direction, quantity, position.entry_price, fill_price,
        )
        gross_pnl = self._calc_pnl(
            order.symbol,
            position.direction,
            quantity,
            accumulator["entry_decision_price"],
            decision_price,
        )
        exit_slippage_cost = self._calc_pnl(
            order.symbol,
            -position.direction,
            quantity,
            decision_price,
            fill_price,
        )
        exit_commission = self.calc_commission(
            quantity, fill_price, position.direction, is_open=False,
        )
        margin = self._calc_margin(
            order.symbol, quantity, position.entry_price, position.leverage,
        )
        self.capital += margin + execution_pnl - exit_commission

        accumulator["exit_quantity"] += quantity
        accumulator["exit_fill_notional"] += quantity * fill_price
        accumulator["exit_decision_notional"] += quantity * decision_price
        accumulator["execution_pnl"] += execution_pnl
        accumulator["gross_pnl"] += gross_pnl
        accumulator["exit_commission"] += exit_commission
        accumulator["last_exit_time"] = timestamp
        accumulator["last_reason"] = order.reason

        volume_context = volume_context or {}
        self.fills.append(FillRecord(
            timestamp=timestamp,
            symbol=order.symbol,
            side=order.side,
            event_type="exit",
            direction=position.direction,
            quantity=quantity,
            decision_price=decision_price,
            fill_price=fill_price,
            notional=quantity * fill_price,
            commission=exit_commission,
            slippage_cost=exit_slippage_cost,
            reason=order.reason,
            order_id=order.order_id,
            requested_quantity=order.requested_quantity,
            remaining_quantity=order.remaining_quantity,
            fill_status=order.status,
            bar_volume=volume_context.get("bar_volume"),
            participation_rate=volume_context.get("participation_rate"),
            bar_volume_capacity=volume_context.get("bar_volume_capacity"),
            volume_limit_exempt=bool(
                volume_context.get("volume_limit_exempt", False)
            ),
            order_type=order.order_type,
            limit_price=order.limit_price,
            eligible_time=order.eligible_time,
            eligible_bar_index=order.eligible_bar_index,
            execution_bar_index=self._bar_idx,
            time_in_force=order.time_in_force,
        ))

        remaining = max(position.size - quantity, 0.0)
        if remaining > 1e-9:
            fraction = remaining / position.size
            self.positions[order.symbol] = Position(
                symbol=position.symbol,
                direction=position.direction,
                entry_price=position.entry_price,
                entry_time=position.entry_time,
                size=remaining,
                leverage=position.leverage,
                entry_bar_idx=position.entry_bar_idx,
                entry_commission=position.entry_commission * fraction,
                entry_decision_price=position.entry_decision_price,
                entry_slippage_cost=position.entry_slippage_cost * fraction,
                signal_time=position.signal_time,
            )
            return

        self.positions.pop(order.symbol, None)
        self._finalize_trade(order.symbol)

    def _finalize_trade(self, symbol: str) -> None:
        """Build one completed trade from all fills in an exit sequence."""
        accumulator = self._exit_accumulators.pop(symbol, None)
        if accumulator is None or accumulator["exit_quantity"] <= 0:
            return
        quantity = float(accumulator["exit_quantity"])
        exit_price = accumulator["exit_fill_notional"] / quantity
        exit_decision_price = accumulator["exit_decision_notional"] / quantity
        execution_pnl = float(accumulator["execution_pnl"])
        gross_pnl = float(accumulator["gross_pnl"])
        slippage_cost = gross_pnl - execution_pnl
        total_commission = (
            float(accumulator["entry_commission"])
            + float(accumulator["exit_commission"])
        )
        net_pnl = gross_pnl - total_commission - slippage_cost
        margin = self._calc_margin(
            symbol,
            quantity,
            accumulator["entry_price"],
            accumulator["leverage"],
        )
        exit_margin = self._calc_margin(
            symbol,
            quantity,
            exit_price,
            accumulator["leverage"],
        )
        holding_bars = max(self._bar_idx - accumulator["entry_bar_idx"], 0)
        holding_days = _safe_holding_days(
            accumulator["entry_time"],
            accumulator["last_exit_time"],
            holding_bars,
        )
        self.trades.append(TradeRecord(
            symbol=symbol,
            direction=accumulator["direction"],
            entry_price=accumulator["entry_price"],
            exit_price=exit_price,
            entry_time=accumulator["entry_time"],
            exit_time=accumulator["last_exit_time"],
            size=quantity,
            leverage=accumulator["leverage"],
            pnl=execution_pnl,
            pnl_pct=execution_pnl / margin * 100 if margin > 1e-9 else 0.0,
            exit_reason=accumulator["last_reason"],
            holding_bars=holding_bars,
            commission=total_commission,
            entry_margin=margin,
            exit_margin=exit_margin,
            signal_time=accumulator["signal_time"],
            entry_decision_price=accumulator["entry_decision_price"],
            exit_decision_price=exit_decision_price,
            gross_pnl=gross_pnl,
            slippage_cost=slippage_cost,
            net_pnl=net_pnl,
            holding_days=holding_days,
        ))

    def _close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_time: pd.Timestamp,
        reason: str,
        exit_decision_price: float | None = None,
    ) -> None:
        """Immediately flatten the residual position through an auditable order."""
        self._active_symbol = symbol
        position = self.positions.get(symbol)
        if position is None:
            return
        pending = self.pending_orders.pop(symbol, None)
        if pending is not None:
            pending.cancel(exit_time, f"forced_close:{reason}")
        decision_price = (
            float(exit_decision_price)
            if exit_decision_price is not None
            else float(exit_price)
        )
        order = self._create_order(
            symbol=symbol,
            event_type="exit",
            direction=position.direction,
            quantity=position.size,
            timestamp=exit_time,
            decision_price=decision_price,
            reason=reason,
            signal_time=position.signal_time,
            order_type="market",
            time_in_force="GTC",
            latency_bars=0,
            expiry_bars=None,
        )
        order.expires_bar_index = None
        order.expires_time = None
        order.set_eligible_time(exit_time)
        order.record_attempt(exit_time)
        order.record_fill(position.size, exit_time)
        self.pending_orders.pop(symbol, None)
        participation_rate = self._participation_rate_for(symbol)
        self._execute_exit_fill(
            order,
            position.size,
            decision_price,
            float(exit_price),
            pd.Timestamp(exit_time),
            volume_context={
                "participation_rate": participation_rate,
                "volume_limit_exempt": participation_rate is not None,
            },
        )

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
        executed_positions: Optional[pd.DataFrame] = None,
        daily_accounting: Optional[pd.DataFrame] = None,
        bars_per_year: Optional[int] = 252,
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

        # Actual post-execution weights are separate from target weights.
        if executed_positions is None:
            executed_positions = self._executed_positions_frame(dates, codes)
        executed_positions = executed_positions.reindex(index=dates, columns=codes).fillna(0.0)
        executed_positions.index.name = "timestamp"
        executed_positions.to_csv(out / "executed_positions.csv")

        # Fill ledger is emitted even for a zero-fill backtest.
        fill_cols = [
            "timestamp",
            "order_id",
            "symbol",
            "side",
            "event_type",
            "direction",
            "quantity",
            "decision_price",
            "fill_price",
            "notional",
            "commission",
            "slippage_cost",
            "reason",
            "requested_quantity",
            "remaining_quantity",
            "fill_status",
            "bar_volume",
            "participation_rate",
            "bar_volume_capacity",
            "volume_limit_exempt",
            "order_type",
            "limit_price",
            "eligible_time",
            "eligible_bar_index",
            "execution_bar_index",
            "time_in_force",
        ]
        fill_rows = [{
            "timestamp": fill.timestamp,
            "order_id": fill.order_id,
            "symbol": fill.symbol,
            "side": fill.side,
            "event_type": fill.event_type,
            "direction": fill.direction,
            "quantity": fill.quantity,
            "decision_price": fill.decision_price,
            "fill_price": fill.fill_price,
            "notional": fill.notional,
            "commission": fill.commission,
            "slippage_cost": fill.slippage_cost,
            "reason": fill.reason,
            "requested_quantity": fill.requested_quantity,
            "remaining_quantity": fill.remaining_quantity,
            "fill_status": fill.fill_status,
            "bar_volume": fill.bar_volume,
            "participation_rate": fill.participation_rate,
            "bar_volume_capacity": fill.bar_volume_capacity,
            "volume_limit_exempt": fill.volume_limit_exempt,
            "order_type": fill.order_type,
            "limit_price": fill.limit_price,
            "eligible_time": fill.eligible_time,
            "eligible_bar_index": fill.eligible_bar_index,
            "execution_bar_index": fill.execution_bar_index,
            "time_in_force": fill.time_in_force,
        } for fill in self.fills]
        pd.DataFrame(fill_rows, columns=fill_cols).to_csv(out / "fills.csv", index=False)

        order_cols = [
            "order_id",
            "symbol",
            "side",
            "event_type",
            "direction",
            "requested_quantity",
            "filled_quantity",
            "remaining_quantity",
            "cancelled_quantity",
            "status",
            "created_time",
            "updated_time",
            "signal_time",
            "decision_price",
            "reason",
            "volume_constrained",
            "volume_constrained_bars",
            "order_type",
            "limit_price",
            "time_in_force",
            "created_bar_index",
            "eligible_bar_index",
            "eligible_time",
            "expires_bar_index",
            "expires_time",
            "attempt_count",
            "deferred_bars",
            "unfilled_eligible_bars",
            "first_fill_time",
            "last_fill_time",
            "status_reason",
        ]
        order_rows = [{
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side,
            "event_type": order.event_type,
            "direction": order.direction,
            "requested_quantity": order.requested_quantity,
            "filled_quantity": order.filled_quantity,
            "remaining_quantity": order.remaining_quantity,
            "cancelled_quantity": order.cancelled_quantity,
            "status": order.status,
            "created_time": order.created_time,
            "updated_time": order.updated_time,
            "signal_time": order.signal_time,
            "decision_price": order.decision_price,
            "reason": order.reason,
            "volume_constrained": order.volume_constrained,
            "volume_constrained_bars": order.volume_constrained_bars,
            "order_type": order.order_type,
            "limit_price": order.limit_price,
            "time_in_force": order.time_in_force,
            "created_bar_index": order.created_bar_index,
            "eligible_bar_index": order.eligible_bar_index,
            "eligible_time": order.eligible_time,
            "expires_bar_index": order.expires_bar_index,
            "expires_time": order.expires_time,
            "attempt_count": order.attempt_count,
            "deferred_bars": order.deferred_bars,
            "unfilled_eligible_bars": order.unfilled_eligible_bars,
            "first_fill_time": order.first_fill_time,
            "last_fill_time": order.last_fill_time,
            "status_reason": order.status_reason,
        } for order in self.orders]
        pd.DataFrame(order_rows, columns=order_cols).to_csv(
            out / "orders.csv", index=False,
        )

        if daily_accounting is None:
            daily_accounting = self._build_daily_accounting(
                equity_series,
                executed_positions,
                dates,
            )
        daily_accounting.index.name = "timestamp"
        daily_accounting.to_csv(out / "daily_accounting.csv")

        reporting_outputs = build_reporting_outputs(
            daily_accounting=daily_accounting,
            executed_positions=executed_positions,
            trades=self.trades,
            fills=self.fills,
            orders=self.orders,
            scalar_metrics=metrics,
            starting_capital=self.initial_capital,
            bars_per_year=bars_per_year,
            final_capital=self.capital,
            final_unrealized_pnl=(
                self.equity_snapshots[-1].unrealized
                if self.equity_snapshots else 0.0
            ),
            open_position_count=len(self.positions),
        )
        metrics.update(reporting_outputs["concentration_metrics"])
        write_reporting_outputs(out, reporting_outputs)

        # Trades (compatible format)
        trade_rows = []
        for t in self.trades:
            # Entry event
            trade_rows.append({
                "timestamp": str(t.entry_time.date()) if hasattr(t.entry_time, "date") else str(t.entry_time),
                "code": t.symbol,
                "side": "buy" if t.direction == 1 else "sell",
                "price": round(t.entry_price, 4),
                "signal_time": str(t.signal_time) if t.signal_time is not None else "",
                "decision_price": (
                    round(t.entry_decision_price, 4)
                    if t.entry_decision_price is not None else ""
                ),
                "fill_price": round(t.entry_price, 4),
                "qty": round(t.size, 6),
                "reason": "signal",
                "pnl": 0.0,
                "gross_pnl": 0.0,
                "commission": 0.0,
                "slippage_cost": 0.0,
                "net_pnl": 0.0,
                "holding_days": 0,
                "return_pct": 0.0,
            })
            # Exit event
            trade_rows.append({
                "timestamp": str(t.exit_time.date()) if hasattr(t.exit_time, "date") else str(t.exit_time),
                "code": t.symbol,
                "side": "sell" if t.direction == 1 else "buy",
                "price": round(t.exit_price, 4),
                "signal_time": str(t.signal_time) if t.signal_time is not None else "",
                "decision_price": (
                    round(t.exit_decision_price, 4)
                    if t.exit_decision_price is not None else ""
                ),
                "fill_price": round(t.exit_price, 4),
                "qty": round(t.size, 6),
                "reason": t.exit_reason,
                "pnl": round(t.pnl, 4),
                "gross_pnl": round(t.gross_pnl, 4) if t.gross_pnl is not None else "",
                "commission": round(t.commission, 4),
                "slippage_cost": round(t.slippage_cost, 4),
                "net_pnl": round(t.net_pnl, 4) if t.net_pnl is not None else "",
                "holding_days": t.holding_days if t.holding_days is not None else 0,
                "return_pct": round(t.pnl_pct, 2),
            })

        trade_cols = [
            "timestamp",
            "code",
            "side",
            "price",
            "signal_time",
            "decision_price",
            "fill_price",
            "qty",
            "reason",
            "pnl",
            "gross_pnl",
            "commission",
            "slippage_cost",
            "net_pnl",
            "holding_days",
            "return_pct",
        ]
        pd.DataFrame(trade_rows or [], columns=trade_cols).to_csv(out / "trades.csv", index=False)

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
    ) -> float:
        """Get close price with fallback."""
        if ts in close_df.index and symbol in close_df.columns:
            val = close_df.at[ts, symbol]
            if pd.notna(val):
                return float(val)
        return fallback
