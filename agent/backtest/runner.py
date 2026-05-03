"""Fixed backtest entrypoint: read config.json, select loader by source, import signal_engine, run engine.

Supports ``source="auto"`` to route codes to loaders by symbol format.
Supports ``interval`` for bar size (1m/5m/15m/30m/1H/4H/1D, default 1D).
Supports ``engine`` for backtest engine (daily/options, default daily).

Usage: ``python -m backtest.runner <run_dir>``
"""

import ast
import importlib.util
from dataclasses import dataclass
from functools import lru_cache
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator, field_validator

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from backtest.loaders.registry import (
    FALLBACK_CHAINS,
    LOADER_REGISTRY,
    get_loader_cls_with_fallback,
    resolve_loader,
)
from backtest.loaders.base import NoAvailableSourceError
from backtest.financials.ashare import get_ashare_financial_runtime
from backtest.financials.ashare.field_registry import (
    SUPPORTED_FINANCIAL_TABLES,
)
from backtest.financials.contracts import MarketFinancialRuntime

logger = logging.getLogger(__name__)

_VALID_INTERVALS = {"1m", "5m", "15m", "30m", "1H", "4H", "1D"}
_VALID_ENGINES = {"daily", "options"}
_VALID_SOURCES = {"tushare", "okx", "yfinance", "akshare", "ccxt", "auto"}
_VALID_FINANCIAL_AVAILABILITY = {"ann_date_next_trade_day"}
_VALID_UNIVERSE_MARKETS = {"a_share"}
_VALID_UNIVERSE_SCOPES = {"all_active"}
_TUSHARE_TOKEN_PLACEHOLDERS = {"", "your-tushare-token"}
_DEFAULT_FINANCIAL_PERIOD_LOOKBACK_QUARTERS = 4
_TUSHARE_POINTS_COLUMNS = ("到期积分", "points", "expire_points", "积分")


def _get_ashare_financial_runtime() -> MarketFinancialRuntime:
    """Return the market-scoped A-share financial implementation bundle."""
    return get_ashare_financial_runtime()


@dataclass(frozen=True)
class FinancialFetchPlan:
    """Runtime fetch mode for financial raw tables."""

    mode: str
    periods: tuple[str, ...] = ()


class FinancialsConfigSchema(BaseModel):
    """Validates the optional financial-statement request block."""

    model_config = ConfigDict(extra="allow")

    required: bool = False
    tables: List[str] = []
    fields: List[str] = []
    availability: str = "ann_date_next_trade_day"
    strict_source: str = "tushare"

    @field_validator("tables")
    @classmethod
    def valid_tables(cls, value: List[str]) -> List[str]:
        unknown = sorted(set(value) - set(SUPPORTED_FINANCIAL_TABLES))
        if unknown:
            raise ValueError(
                f"unsupported financial tables {unknown!r}, must be chosen from {SUPPORTED_FINANCIAL_TABLES}"
            )
        return value

    @field_validator("fields")
    @classmethod
    def valid_fields(cls, value: List[str]) -> List[str]:
        registry = _get_ashare_financial_runtime().registry
        unknown = [field_name for field_name in value if not registry.has_field(field_name)]
        if unknown:
            raise ValueError(f"unknown financial fields: {unknown!r}")
        return value

    @field_validator("availability")
    @classmethod
    def valid_availability(cls, value: str) -> str:
        if value not in _VALID_FINANCIAL_AVAILABILITY:
            raise ValueError(
                "unsupported financial availability "
                f"{value!r}, must be one of {_VALID_FINANCIAL_AVAILABILITY}"
            )
        return value

    @field_validator("strict_source")
    @classmethod
    def valid_strict_source(cls, value: str) -> str:
        if value != "tushare":
            raise ValueError("financials.strict_source must be 'tushare'")
        return value

    @model_validator(mode="after")
    def has_query_shape(self) -> "FinancialsConfigSchema":
        if self.required and not self.tables and not self.fields:
            raise ValueError("financials.required=true requires at least one table or field")
        return self


class UniverseConfigSchema(BaseModel):
    """Validates the optional runtime universe selector."""

    model_config = ConfigDict(extra="allow")

    market: str
    scope: str = "all_active"

    @field_validator("market")
    @classmethod
    def valid_market(cls, value: str) -> str:
        if value not in _VALID_UNIVERSE_MARKETS:
            raise ValueError(
                f"unsupported universe market {value!r}, must be one of {_VALID_UNIVERSE_MARKETS}"
            )
        return value

    @field_validator("scope")
    @classmethod
    def valid_scope(cls, value: str) -> str:
        if value not in _VALID_UNIVERSE_SCOPES:
            raise ValueError(
                f"unsupported universe scope {value!r}, must be one of {_VALID_UNIVERSE_SCOPES}"
            )
        return value


class BacktestConfigSchema(BaseModel):
    """Validates backtest config.json before execution."""

    model_config = ConfigDict(extra="allow")

    codes: List[str] = []
    start_date: str
    end_date: str
    source: str = "tushare"
    interval: str = "1D"
    engine: str = "daily"
    financials: Optional[FinancialsConfigSchema] = None
    universe: Optional[UniverseConfigSchema] = None

    @field_validator("codes")
    @classmethod
    def codes_not_empty(cls, v: List[str]) -> List[str]:
        if any(not c.strip() for c in v):
            raise ValueError("codes must not contain empty strings")
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def valid_date(cls, v: str) -> str:
        try:
            pd.Timestamp(v)
        except Exception:
            raise ValueError(f"invalid date format: {v!r} (expected YYYY-MM-DD)")
        return v

    @field_validator("interval")
    @classmethod
    def valid_interval(cls, v: str) -> str:
        if v not in _VALID_INTERVALS:
            raise ValueError(f"unsupported interval {v!r}, must be one of {_VALID_INTERVALS}")
        return v

    @field_validator("engine")
    @classmethod
    def valid_engine(cls, v: str) -> str:
        if v not in _VALID_ENGINES:
            raise ValueError(f"unsupported engine {v!r}, must be one of {_VALID_ENGINES}")
        return v

    @field_validator("source")
    @classmethod
    def valid_source(cls, v: str) -> str:
        if v not in _VALID_SOURCES:
            raise ValueError(f"unsupported source {v!r}, must be one of {_VALID_SOURCES}")
        return v

    @model_validator(mode="after")
    def start_before_end(self) -> "BacktestConfigSchema":
        if not self.codes and self.universe is None:
            raise ValueError("codes must be a non-empty list")
        if pd.Timestamp(self.start_date) > pd.Timestamp(self.end_date):
            raise ValueError(
                f"start_date ({self.start_date}) must be <= end_date ({self.end_date})"
            )
        return self


def _load_module_from_file(file_path: Path, module_name: str):
    """Load a Python module from a file path via importlib.

    Args:
        file_path: Path to the ``.py`` file.
        module_name: Logical module name.

    Returns:
        Loaded module object.
    """
    _validate_signal_engine_source(file_path)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _is_literal_node(node: ast.AST) -> bool:
    """Return whether an AST node is made only from literal values."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal_node(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            (key is None or _is_literal_node(key)) and _is_literal_node(value)
            for key, value in zip(node.keys, node.values)
        )
    return False


def _is_safe_constant_assignment(node: ast.AST) -> bool:
    """Return whether a top-level assignment is literal-only."""
    if isinstance(node, ast.Assign):
        return _is_literal_node(node.value)
    if isinstance(node, ast.AnnAssign):
        return node.value is None or _is_literal_node(node.value)
    return False


def _is_safe_reference(node: ast.AST | None) -> bool:
    """Return whether an annotation/base expression cannot call code."""
    if node is None:
        return True
    if isinstance(node, (ast.Name, ast.Attribute, ast.Constant)):
        return True
    if isinstance(node, ast.Subscript):
        return _is_safe_reference(node.value) and _is_safe_reference(node.slice)
    if isinstance(node, ast.Tuple):
        return all(_is_safe_reference(item) for item in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_safe_reference(node.left) and _is_safe_reference(node.right)
    return False


def _validate_function_def(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    """Reject import-time execution in function definitions."""
    if node.decorator_list:
        raise ValueError(f"Decorators are not allowed on function {node.name!r}")
    for default in [*node.args.defaults, *[d for d in node.args.kw_defaults if d]]:
        if not _is_literal_node(default):
            raise ValueError(f"Non-literal default is not allowed on function {node.name!r}")
    annotations = [node.returns]
    annotations.extend(arg.annotation for arg in node.args.posonlyargs)
    annotations.extend(arg.annotation for arg in node.args.args)
    annotations.extend(arg.annotation for arg in node.args.kwonlyargs)
    annotations.append(node.args.vararg.annotation if node.args.vararg else None)
    annotations.append(node.args.kwarg.annotation if node.args.kwarg else None)
    for annotation in annotations:
        if not _is_safe_reference(annotation):
            raise ValueError(f"Unsafe annotation is not allowed on function {node.name!r}")


def _validate_class_body(node: ast.ClassDef) -> None:
    """Reject import-time execution inside class bodies."""
    if node.decorator_list:
        raise ValueError(f"Decorators are not allowed on class {node.name!r}")
    for base in node.bases:
        if not _is_safe_reference(base):
            raise ValueError(f"Unsafe base class is not allowed on class {node.name!r}")
    if node.keywords:
        raise ValueError(f"Class keywords are not allowed on class {node.name!r}")
    for child in node.body:
        if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant):
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _validate_function_def(child)
            continue
        if _is_safe_constant_assignment(child):
            continue
        if isinstance(child, ast.Pass):
            continue
        raise ValueError(
            f"Executable class-level statement {type(child).__name__} is not allowed"
        )


def _validate_signal_engine_source(file_path: Path) -> None:
    """Reject import-time executable statements before loading signal_engine.py."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except SyntaxError as exc:
        raise ValueError(f"Invalid signal_engine.py syntax: {exc}") from exc

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _validate_function_def(node)
            continue
        if isinstance(node, ast.ClassDef):
            _validate_class_body(node)
            continue
        if _is_safe_constant_assignment(node):
            continue
        raise ValueError(
            f"Executable top-level statement {type(node).__name__} is not allowed"
        )


# --- Market detection (returns market type, NOT source name) ---

_MARKET_PATTERNS = [
    (re.compile(r"^\d{6}\.(SZ|SH|BJ)$", re.I), "a_share"),
    (re.compile(r"^(51|15|56)\d{4}\.(SZ|SH)$", re.I), "a_share"),
    (re.compile(r"^[A-Z]+\.US$", re.I), "us_equity"),
    (re.compile(r"^\d{3,5}\.HK$", re.I), "hk_equity"),
    (re.compile(r"^[A-Z]+-USDT$", re.I), "crypto"),
    (re.compile(r"^[A-Z]+/USDT$", re.I), "crypto"),
    # China futures: product+delivery.exchange (e.g. IF2406.CFFEX, rb2410.SHFE)
    (re.compile(r"^[A-Za-z]{1,2}\d{3,4}\.(ZCE|DCE|SHFE|INE|CFFEX|GFEX)$", re.I), "futures"),
    # Global futures: product+month-code (e.g. ESZ4, CLF25, GCM2025)
    (re.compile(r"^[A-Z]{2,4}[FGHJKMNQUVXZ]\d{1,2}$", re.I), "futures"),
    # Global futures: product+YYMM (e.g. CL2412, ES2503)
    (re.compile(r"^[A-Z]{2,4}\d{4}$", re.I), "futures"),
    # Global futures: bare product code with exchange (e.g. ES.CME)
    (re.compile(r"^[A-Z]{2,4}\.(CME|CBOT|NYMEX|COMEX|ICE|EUREX)$", re.I), "futures"),
    # Forex pairs: XXX/YYY or XXXXXX.FX
    (re.compile(r"^[A-Z]{3}/[A-Z]{3}$"), "forex"),
    (re.compile(r"^[A-Z]{6}\.FX$"), "forex"),
]

# Back-compat: market type -> legacy source name (for engine selection & metrics)
_MARKET_TO_SOURCE = {
    "a_share": "tushare",
    "us_equity": "yfinance",
    "hk_equity": "yfinance",
    "crypto": "okx",
    "futures": "tushare",
    "fund": "tushare",
    "macro": "akshare",
    "forex": "akshare",
}


def _detect_market(code: str) -> str:
    """Infer market type from symbol format.

    Args:
        code: Ticker / symbol string.

    Returns:
        Market type (a_share/us_equity/hk_equity/crypto/futures/forex);
        unknown defaults to ``a_share``.
    """
    for pattern, market in _MARKET_PATTERNS:
        if pattern.match(code):
            return market
    return "a_share"


def _detect_source(code: str) -> str:
    """Infer legacy source name from symbol (back-compat for metrics/engine).

    Args:
        code: Ticker / symbol string.

    Returns:
        Source name (tushare/okx/yfinance/akshare).
    """
    market = _detect_market(code)
    return _MARKET_TO_SOURCE.get(market, "tushare")


def _group_codes_by_market(codes: List[str]) -> Dict[str, List[str]]:
    """Group symbols by detected market type.

    Args:
        codes: List of symbol strings.

    Returns:
        Mapping market_type -> list of codes.
    """
    groups: Dict[str, List[str]] = {}
    for code in codes:
        market = _detect_market(code)
        groups.setdefault(market, []).append(code)
    return groups


def _group_codes_by_source(codes: List[str]) -> Dict[str, List[str]]:
    """Group symbols by inferred source (back-compat).

    Args:
        codes: List of symbol strings.

    Returns:
        Mapping source -> list of codes.
    """
    groups: Dict[str, List[str]] = {}
    for code in codes:
        src = _detect_source(code)
        groups.setdefault(src, []).append(code)
    return groups


def _get_loader(source: str):
    """Return a DataLoader class for a source name, with fallback.

    Args:
        source: Source name (tushare/okx/yfinance/akshare/ccxt).

    Returns:
        DataLoader class.
    """
    try:
        return get_loader_cls_with_fallback(source)
    except NoAvailableSourceError:
        # Ultimate fallback for unknown sources
        if "tushare" in LOADER_REGISTRY:
            return LOADER_REGISTRY["tushare"]
        raise


def _normalize_codes(codes: List[str], source: str) -> List[str]:
    """Normalize symbol strings for a source.

    Args:
        codes: Raw code list.
        source: Data source.

    Returns:
        Normalized codes.
    """
    if source in ("okx", "ccxt"):
        return [c.replace("/", "-").upper() for c in codes]
    return codes


def _financials_requested(config: dict) -> bool:
    """Whether the config explicitly requests statement-style financial data."""
    financials = config.get("financials") or {}
    return bool(
        financials
        and (
            financials.get("required")
            or financials.get("tables")
            or financials.get("fields")
        )
    )


def _uses_runtime_a_share_universe(config: dict) -> bool:
    """Whether codes were resolved from the runtime A-share all-active universe."""
    universe = config.get("universe") or {}
    return bool(
        config.get("_resolved_codes_from_universe")
        and universe.get("market") == "a_share"
        and universe.get("scope", "all_active") == "all_active"
    )


def _format_financial_table_list(table_names: List[str] | tuple[str, ...]) -> str:
    """Render requested financial tables for user-facing errors."""
    return ", ".join(sorted(dict.fromkeys(str(name) for name in table_names if name))) or "<none>"


def _format_required_points_by_table(required_points_by_table: Dict[str, int]) -> str:
    """Render per-table VIP point requirements for user-facing errors."""
    if not required_points_by_table:
        return "<none>"
    return ", ".join(
        f"{table_name}={points}"
        for table_name, points in sorted(required_points_by_table.items())
    )


def _parse_explicit_tushare_points(config: dict) -> int | None:
    """Parse an explicit Tushare points override for compatibility fallbacks."""
    financials = config.get("financials") or {}
    raw_value = financials.get("tushare_points", os.getenv("TUSHARE_POINTS", "")).strip() if isinstance(financials.get("tushare_points", os.getenv("TUSHARE_POINTS", "")), str) else financials.get("tushare_points", os.getenv("TUSHARE_POINTS", ""))
    if raw_value in (None, ""):
        return None
    try:
        points = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("financials.tushare_points or TUSHARE_POINTS must be an integer") from exc
    if points < 0:
        raise ValueError("financials.tushare_points or TUSHARE_POINTS must be >= 0")
    return points


def _extract_tushare_points_from_user_frame(user_frame: pd.DataFrame) -> int:
    """Extract current account points from the Tushare user endpoint result."""
    if user_frame is None or user_frame.empty:
        raise ValueError("Tushare user endpoint returned no rows")

    points_column = next(
        (column for column in _TUSHARE_POINTS_COLUMNS if column in user_frame.columns),
        None,
    )
    if points_column is None:
        raise ValueError(
            "Tushare user endpoint returned no recognized points column; "
            f"columns={list(user_frame.columns)!r}"
        )

    series = pd.to_numeric(user_frame[points_column], errors="coerce")
    numeric_points = series[series.notna()]
    if numeric_points.empty:
        raise ValueError("Tushare user endpoint returned no numeric points")

    total_points = int(numeric_points.sum())
    if total_points < 0:
        raise ValueError("Tushare user endpoint returned negative points")
    return total_points


def _resolve_financial_points_by_table(query_plan, *, use_vip_points: bool) -> Dict[str, int]:
    """Resolve per-table Tushare point requirements for a query plan."""
    runtime = _get_ashare_financial_runtime()
    required_points_by_table: Dict[str, int] = {}
    for table_name in query_plan.query_fields:
        table = runtime.registry.get_table(table_name)
        if use_vip_points and table.vip_min_points is not None:
            required_points_by_table[table_name] = table.vip_min_points
            continue
        required_points_by_table[table_name] = table.min_points or 0
    return required_points_by_table


@lru_cache(maxsize=4)
def _query_tushare_points_from_account(token: str) -> int:
    """Query Tushare account capability and return currently available points."""
    import tushare as ts

    api = ts.pro_api(token)
    user_frame = api.user(token=token)
    return _extract_tushare_points_from_user_frame(user_frame)


def _resolve_tushare_points(config: dict) -> int | None:
    """Resolve Tushare points for VIP capability checks.

    The primary path queries the account capability from Tushare directly so
    full-market runtime requests do not require hand-filled point settings.
    Explicit config or env values remain as a compatibility fallback when the
    automatic query cannot be completed.
    """
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if token and token not in _TUSHARE_TOKEN_PLACEHOLDERS:
        try:
            return _query_tushare_points_from_account(token)
        except Exception as exc:
            fallback_points = _parse_explicit_tushare_points(config)
            if fallback_points is not None:
                logger.warning(
                    "Falling back to explicit Tushare points override after automatic query failed: %s",
                    exc,
                )
                return fallback_points
            raise ValueError(
                "unable to query Tushare account points automatically via Tushare user(token=...); "
                f"reason={type(exc).__name__}: {exc}"
            ) from exc

    return _parse_explicit_tushare_points(config)


def _last_completed_quarter(as_of: pd.Timestamp) -> pd.Period:
    """Return the latest completed fiscal quarter as of a trade date."""
    timestamp = pd.Timestamp(as_of).normalize()
    quarter = timestamp.to_period("Q")
    if pd.Timestamp(quarter.end_time).normalize() > timestamp:
        return quarter - 1
    return quarter


def _derive_cross_sectional_financial_periods(
    start_date: str,
    end_date: str,
    *,
    lookback_quarters: int = _DEFAULT_FINANCIAL_PERIOD_LOOKBACK_QUARTERS,
) -> tuple[str, ...]:
    """Derive completed fiscal report periods needed for PIT enrichment."""
    if lookback_quarters < 1:
        raise ValueError("financials.period_lookback_quarters must be >= 1")

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    if end_ts < start_ts:
        raise ValueError("end_date must be >= start_date for financial period planning")

    start_anchor = _last_completed_quarter(start_ts)
    end_anchor = _last_completed_quarter(end_ts)
    first_period = start_anchor - (lookback_quarters - 1)
    periods = pd.period_range(start=first_period, end=end_anchor, freq="Q")
    return tuple(pd.Timestamp(period.end_time).strftime("%Y%m%d") for period in periods)


def _has_tushare_token() -> bool:
    """Return whether a usable TUSHARE_TOKEN is configured."""
    return os.getenv("TUSHARE_TOKEN", "").strip() not in _TUSHARE_TOKEN_PLACEHOLDERS


def _resolve_a_share_universe_codes() -> List[str]:
    """Resolve the active A-share universe through Tushare stock_basic."""
    if not _has_tushare_token():
        raise ValueError("a_share universe resolution requires TUSHARE_TOKEN")

    import tushare as ts

    api = ts.pro_api(os.getenv("TUSHARE_TOKEN", ""))
    universe = api.stock_basic(exchange="", list_status="L", fields="ts_code")
    if universe is None or universe.empty or "ts_code" not in universe.columns:
        raise ValueError("a_share universe resolved to no codes")

    codes = sorted(
        {
            code
            for raw_code in universe["ts_code"].dropna().tolist()
            for code in [str(raw_code).strip().upper()]
            if code and _detect_market(code) == "a_share"
        }
    )
    if not codes:
        raise ValueError("a_share universe resolved to no codes")
    return codes


def _resolve_codes_from_config(config: dict, source: str) -> List[str]:
    """Resolve the effective code list from explicit codes or a runtime universe."""
    codes = list(config.get("codes") or [])
    if codes:
        return codes

    universe = config.get("universe") or {}
    if not universe:
        return []

    if universe.get("market") != "a_share":
        raise ValueError("runtime universe currently supports only universe.market='a_share'")
    if source not in {"tushare", "auto"}:
        raise ValueError("a_share runtime universe currently requires source='tushare' or 'auto'")
    return _resolve_a_share_universe_codes()


def _validate_financials_request(config: dict, source: str, codes: List[str]) -> str:
    """Validate a strict A-share financial request and normalize the source.

    This gate intentionally fails fast until the dedicated runtime financial
    loader/assembler is wired into the runner.
    """
    if not _financials_requested(config):
        return source

    markets = {_detect_market(code) for code in codes}
    if markets != {"a_share"}:
        raise ValueError(
            "financials currently support only A-share strategies; "
            f"detected markets={sorted(markets)}"
        )

    if source not in {"tushare", "auto"}:
        raise ValueError(
            "financials require strict Tushare mode; "
            f"source must be 'tushare' or 'auto', got {source!r}"
        )

    if not _has_tushare_token():
        raise ValueError("financials require TUSHARE_TOKEN")

    if config.get("interval", "1D") != "1D":
        raise ValueError("financials currently support only interval='1D'")

    return "tushare"


def _build_financial_query_plan_from_config(config: dict):
    """Build the strict financial query plan declared in config."""
    if not _financials_requested(config):
        return None

    runtime = _get_ashare_financial_runtime()
    financials = config.get("financials") or {}
    fields = tuple(financials.get("fields") or ())
    if not fields:
        raise ValueError("financials runtime currently requires explicit financials.fields")

    preferred_tables = financials.get("preferred_tables") or {}
    query_plan = runtime.registry.build_query_plan(
        fields,
        preferred_tables=preferred_tables,
        include_key_columns=True,
        strict=True,
    )

    declared_tables = set(financials.get("tables") or ())
    unexpected_tables = set(query_plan.requested_fields) - declared_tables
    if declared_tables and unexpected_tables:
        raise ValueError(
            "financials.tables does not cover all requested field owners: "
            f"{sorted(unexpected_tables)}"
        )

    return query_plan


def _build_financial_fetch_plan(config: dict, query_plan) -> FinancialFetchPlan | None:
    """Plan whether financial raw tables should use per-code or VIP period fetches."""
    if query_plan is None:
        return None
    if not _uses_runtime_a_share_universe(config):
        return FinancialFetchPlan(mode="per_code")

    runtime = _get_ashare_financial_runtime()
    capability = runtime.registry.assess_cross_sectional_query(query_plan)
    requested_tables = tuple(query_plan.query_fields)
    requested_tables_text = _format_financial_table_list(requested_tables)
    if not capability.supported:
        raise ValueError(
            "financials full-market cross-section requires VIP period endpoints for every requested table; "
            f"requested tables={requested_tables_text}; "
            f"unsupported tables={_format_financial_table_list(capability.unsupported_tables)}; "
            f"supported tables={_format_financial_table_list(capability.supported_tables)}"
        )

    ordinary_required_points_by_table = _resolve_financial_points_by_table(
        query_plan,
        use_vip_points=False,
    )
    ordinary_required_points = max(ordinary_required_points_by_table.values(), default=0)
    ordinary_required_points_text = _format_required_points_by_table(ordinary_required_points_by_table)
    vip_required_points_text = _format_required_points_by_table(capability.required_points_by_table)

    available_points = _resolve_tushare_points(config)
    if available_points is None:
        raise ValueError(
            "financials full-market cross-section could not determine Tushare account points; "
            f"requested tables={requested_tables_text}; "
            f"required points by table={vip_required_points_text}"
        )
    if available_points < ordinary_required_points:
        raise ValueError(
            "financials require at least 2000 Tushare points for requested tables; "
            f"requested tables={requested_tables_text}; "
            f"current account points={available_points}; "
            f"ordinary required points={ordinary_required_points}; "
            f"ordinary required points by table={ordinary_required_points_text}"
        )
    if available_points < capability.required_points:
        logger.warning(
            "financials full-market cross-section falling back to slower per-code Tushare fetch; "
            "requested tables=%s; current account points=%s; VIP required points=%s; ordinary required points=%s",
            requested_tables_text,
            available_points,
            capability.required_points,
            ordinary_required_points,
        )
        return FinancialFetchPlan(mode="per_code")

    financials = config.get("financials") or {}
    raw_lookback = financials.get(
        "period_lookback_quarters",
        _DEFAULT_FINANCIAL_PERIOD_LOOKBACK_QUARTERS,
    )
    try:
        lookback_quarters = int(raw_lookback)
    except (TypeError, ValueError) as exc:
        raise ValueError("financials.period_lookback_quarters must be an integer") from exc

    return FinancialFetchPlan(
        mode="cross_section",
        periods=_derive_cross_sectional_financial_periods(
            config.get("start_date", ""),
            config.get("end_date", ""),
            lookback_quarters=lookback_quarters,
        ),
    )


def _fetch_cross_sectional_financial_tables(
    raw_loader,
    query_plan,
    *,
    periods: tuple[str, ...],
    table_params: dict,
) -> dict[str, pd.DataFrame]:
    """Fetch and concatenate VIP period cross-sections for requested tables."""
    frames_by_table: dict[str, list[pd.DataFrame]] = {
        table_name: [] for table_name in query_plan.query_fields
    }
    for period in periods:
        period_tables = raw_loader.fetch_for_period(
            query_plan,
            period=period,
            table_params=table_params,
        )
        for table_name, frame in period_tables.items():
            if frame is not None and not frame.empty:
                frames_by_table.setdefault(table_name, []).append(frame)

    result: dict[str, pd.DataFrame] = {}
    for table_name, fields in query_plan.query_fields.items():
        frames = frames_by_table.get(table_name) or []
        if frames:
            result[table_name] = pd.concat(frames, ignore_index=True)
        else:
            result[table_name] = pd.DataFrame(columns=list(fields))
    return result


def _enrich_price_data_map_with_financials(
    config: dict,
    data_map: dict,
    query_plan,
    fetch_plan: FinancialFetchPlan | None,
) -> dict:
    """Attach PIT financial statement columns to the fetched price data."""
    if query_plan is None or not data_map:
        return data_map

    runtime = _get_ashare_financial_runtime()
    financials = config.get("financials") or {}
    raw_loader = runtime.loader_factory()
    table_params = financials.get("table_params") or {}
    if fetch_plan is not None and fetch_plan.mode == "cross_section":
        raw_tables = _fetch_cross_sectional_financial_tables(
            raw_loader,
            query_plan,
            periods=fetch_plan.periods,
            table_params=table_params,
        )
    else:
        raw_tables = raw_loader.fetch_for_codes(
            query_plan,
            codes=list(data_map.keys()),
            start_date=config.get("start_date", ""),
            end_date=config.get("end_date", ""),
            table_params=table_params,
        )
    return runtime.enrich_data_map(
        data_map,
        raw_tables,
        query_plan,
        report_type_priorities=financials.get("report_type_priorities") or {},
    )


# --- Main entry ---

def main(run_dir: Path) -> None:
    """Load config, fetch data, run the selected backtest engine.

    With ``source="auto"``, routes each code through the appropriate loader.

    Args:
        run_dir: Run directory containing ``config.json`` and ``code/signal_engine.py``.
    """
    config_path = run_dir / "config.json"
    if not config_path.exists():
        print(json.dumps({"error": "config.json not found"}))
        sys.exit(1)

    raw_config = json.loads(config_path.read_text(encoding="utf-8"))

    # Validate config schema
    try:
        BacktestConfigSchema(**raw_config)
    except Exception as exc:
        errors = str(exc)
        print(json.dumps({"error": f"Invalid config: {errors}"}))
        sys.exit(1)

    config = raw_config
    config["_resolved_codes_from_universe"] = not bool(raw_config.get("codes")) and bool(
        raw_config.get("universe")
    )
    source = config.get("source", "tushare")
    try:
        codes = _resolve_codes_from_config(config, source)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    config["codes"] = codes

    # Load signal engine
    signal_path = run_dir / "code" / "signal_engine.py"
    if not signal_path.exists():
        print(json.dumps({"error": "code/signal_engine.py not found"}))
        sys.exit(1)

    signal_module = _load_module_from_file(signal_path, "signal_engine")
    engine_cls = getattr(signal_module, "SignalEngine", None)
    if engine_cls is None:
        print(json.dumps({"error": "SignalEngine class not found in signal_engine.py"}))
        sys.exit(1)

    try:
        source = _validate_financials_request(config, source, codes)
        financial_query_plan = _build_financial_query_plan_from_config(config)
        financial_fetch_plan = _build_financial_fetch_plan(config, financial_query_plan)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)

    # Data: auto split vs single loader
    interval = config.get("interval", "1D")

    if source == "auto":
        data_map = _fetch_auto(codes, config, interval)
    else:
        codes = _normalize_codes(codes, source)
        config["codes"] = codes
        LoaderCls = _get_loader(source)
        loader = LoaderCls()
        data_map = loader.fetch(
            codes,
            config.get("start_date", ""),
            config.get("end_date", ""),
            fields=config.get("extra_fields") or None,
            interval=interval,
        )
        # Runtime fallback: try next sources in chain when primary returns empty
        if not data_map and codes and not _financials_requested(config):
            market = _detect_market(codes[0])
            for fb_name in FALLBACK_CHAINS.get(market, []):
                if fb_name == source or fb_name not in LOADER_REGISTRY:
                    continue
                fb_loader = LOADER_REGISTRY[fb_name]()
                if not fb_loader.is_available():
                    continue
                fb_codes = _normalize_codes(codes, fb_name)
                data_map = fb_loader.fetch(
                    fb_codes, config.get("start_date", ""),
                    config.get("end_date", ""), interval=interval,
                )
                if data_map:
                    logger.info("Runtime fallback: %s -> %s", source, fb_name)
                    source = fb_name
                    loader = fb_loader
                    break
    data_map = _enrich_price_data_map_with_financials(
        config,
        data_map,
        financial_query_plan,
        financial_fetch_plan,
    )
    if not data_map:
        print(json.dumps({"error": "No data fetched"}))
        sys.exit(1)

    # Engine
    engine_type = config.get("engine", "daily")
    signal_engine = engine_cls()

    # Annualization bars
    effective_source = _detect_primary_source(codes, source)
    from backtest.metrics import calc_bars_per_year
    # Cross-market: use calendar-day annualization (bars_per_year=None)
    market_types = {_detect_market(c) for c in codes}
    if len(market_types) > 1:
        bars_per_year = None
    else:
        bars_per_year = calc_bars_per_year(interval, effective_source)

    # Auto mode: wrap preloaded data in a dummy loader
    if source == "auto" or financial_query_plan is not None:
        loader = _AutoLoader(data_map)

    if engine_type == "options":
        from backtest.engines.options_portfolio import run_options_backtest
        run_options_backtest(config, loader, signal_engine, run_dir, bars_per_year=bars_per_year)
    else:
        market_engine = _create_market_engine(effective_source, config, codes)
        market_engine.run_backtest(config, loader, signal_engine, run_dir, bars_per_year=bars_per_year)


def _create_market_engine(source: str, config: dict, codes: List[str]):
    """Create the appropriate market engine based on data source and market type.

    Routing priority:
      1. Detect market type from symbol patterns (futures, forex, etc.)
      2. Fall back to source-based routing (okx->crypto, tushare->china_a, etc.)

    Args:
        source: Data source (okx/ccxt/tushare/akshare/yfinance).
        config: Backtest configuration.
        codes: Instrument codes.

    Returns:
        BaseEngine subclass instance.
    """
    # Detect dominant market type from codes
    markets = {_detect_market(c) for c in codes} if codes else set()

    # Cross-market -> CompositeEngine
    if len(markets) > 1:
        from backtest.engines.composite import CompositeEngine
        return CompositeEngine(config, codes)

    # Futures routing (Wave 2)
    if "futures" in markets:
        # Distinguish China vs global futures by exchange suffix
        if any(_is_china_futures(c) for c in codes):
            from backtest.engines.china_futures import ChinaFuturesEngine
            return ChinaFuturesEngine(config)
        from backtest.engines.global_futures import GlobalFuturesEngine
        return GlobalFuturesEngine(config)

    # Forex routing (Wave 2)
    if "forex" in markets:
        from backtest.engines.forex import ForexEngine
        return ForexEngine(config)

    # Original routing (Wave 1)
    if source in ("okx", "ccxt"):
        from backtest.engines.crypto import CryptoEngine
        return CryptoEngine(config)
    elif source in ("tushare", "akshare"):
        if markets & {"us_equity", "hk_equity"}:
            from backtest.engines.global_equity import GlobalEquityEngine
            market = _detect_submarket(codes)
            return GlobalEquityEngine(config, market=market)
        from backtest.engines.china_a import ChinaAEngine
        return ChinaAEngine(config)
    elif source == "yfinance":
        from backtest.engines.global_equity import GlobalEquityEngine
        market = _detect_submarket(codes)
        return GlobalEquityEngine(config, market=market)
    else:
        from backtest.engines.crypto import CryptoEngine
        return CryptoEngine(config)


def _is_china_futures(code: str) -> bool:
    """Check if a futures code belongs to a Chinese exchange.

    Args:
        code: Symbol string (e.g. 'IF2406.CFFEX', 'rb2410.SHFE').

    Returns:
        True if it matches a Chinese futures exchange suffix.
    """
    china_exchanges = {"CFFEX", "SHFE", "DCE", "ZCE", "INE", "GFEX"}
    parts = code.upper().split(".")
    if len(parts) == 2 and parts[1] in china_exchanges:
        return True
    # Heuristic: Chinese futures product codes
    m = re.match(r"([A-Za-z]+)\d+", parts[0])
    if m:
        product = m.group(1)
        # Known Chinese futures products (partial list)
        cn_products = {
            "IF", "IC", "IH", "IM", "T", "TF", "TS", "TL",
            "au", "ag", "cu", "al", "zn", "pb", "ni", "sn", "ss",
            "rb", "hc", "i", "j", "jm",
            "sc", "fu", "lu", "bu", "nr",
            "c", "cs", "m", "y", "a", "p", "jd", "lh",
            "CF", "SR", "TA", "MA", "AP", "RM", "OI",
            "pp", "l", "v", "eg", "eb", "PF", "SA", "FG", "UR",
            "si", "lc",
        }
        if product in cn_products:
            return True
    return False


def _detect_submarket(codes: List[str]) -> str:
    """Detect US vs HK from symbol suffixes.

    Args:
        codes: Instrument codes.

    Returns:
        "hk" if any code ends with .HK, else "us".
    """
    for code in codes:
        if code.upper().endswith(".HK"):
            return "hk"
    return "us"


def _detect_primary_source(codes: List[str], source: str) -> str:
    """Pick primary source for annualization (e.g. bars per year).

    Args:
        codes: All symbols.
        source: Config ``source`` field.

    Returns:
        Dominant source name.
    """
    if source != "auto":
        return source
    groups = _group_codes_by_source(codes)
    if len(groups) == 1:
        return list(groups.keys())[0]
    # Mixed: use the source with the most symbols
    return max(groups, key=lambda s: len(groups[s]))


def _fetch_auto(codes: List[str], config: dict, interval: str = "1D") -> dict:
    """Auto mode: route each market group through fallback chain.

    Args:
        codes: All symbols.
        config: Backtest config dict.
        interval: Bar interval string.

    Returns:
        Merged ``code -> DataFrame`` map.
    """
    market_groups = _group_codes_by_market(codes)
    merged = {}
    start_date = config.get("start_date", "")
    end_date = config.get("end_date", "")

    for market, market_codes in market_groups.items():
        try:
            loader = resolve_loader(market)
        except NoAvailableSourceError as exc:
            # Fallback: try legacy source mapping
            legacy_src = _MARKET_TO_SOURCE.get(market, "tushare")
            logger.warning("Fallback chain failed for %s: %s — trying %s", market, exc, legacy_src)
            LoaderCls = _get_loader(legacy_src)
            loader = LoaderCls()

        src_name = getattr(loader, "name", "unknown")
        normalized_codes = _normalize_codes(market_codes, src_name)
        fields = config.get("extra_fields") if src_name == "tushare" else None
        result = loader.fetch(normalized_codes, start_date, end_date, fields=fields, interval=interval)

        # Runtime fallback: try remaining sources when primary returns empty
        if not result:
            for fb_name in FALLBACK_CHAINS.get(market, []):
                if fb_name == src_name or fb_name not in LOADER_REGISTRY:
                    continue
                fb_loader = LOADER_REGISTRY[fb_name]()
                if not fb_loader.is_available():
                    continue
                fb_codes = _normalize_codes(market_codes, fb_name)
                result = fb_loader.fetch(fb_codes, start_date, end_date, interval=interval)
                if result:
                    logger.info("Runtime fallback: %s -> %s for %s", src_name, fb_name, market)
                    break

        merged.update(result)

    return merged


class _AutoLoader:
    """Dummy loader for auto mode: returns pre-fetched data maps."""

    def __init__(self, data_map: dict):
        self._data = data_map

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        """Return preloaded rows for requested codes."""
        return {c: df for c, df in self._data.items() if c in codes}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python -m backtest.runner <run_dir>")
        sys.exit(1)
    main(Path(sys.argv[1]))
