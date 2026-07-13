"""Fixed backtest entrypoint: read config.json, select loader by source, import signal_engine, run engine.

Supports ``source="auto"`` to route codes to loaders by symbol format.
Supports ``interval`` for bar size (1m/5m/15m/30m/1H/4H/1D, default 1D).
Supports ``engine`` for backtest engine (daily/options, default daily).

Usage: ``python -m backtest.runner <run_dir>``
"""

import ast
import importlib.util
import inspect
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

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
    VALID_SOURCES,
    get_loader_cls_with_fallback,
    resolve_loader,
)
from backtest.loaders.base import NoAvailableSourceError, validate_ohlc
# Symbol classification lives in ``_market_hooks`` so runner.py and
# composite.py share a single source of truth (audit-2026-05-18 B1+C1+C2).
# ``_detect_market`` is also re-exported here for back-compat with
# ``agent/src/swarm/grounding.py`` and existing tests that import it
# from ``backtest.runner``.
from backtest.engines._market_hooks import (  # noqa: F401  (re-exported)
    _detect_market,
    _detect_submarket,
    _is_china_futures,
)

logger = logging.getLogger(__name__)

_VALID_INTERVALS = {"1m", "5m", "15m", "30m", "1H", "4H", "1D"}
_VALID_ENGINES = {"daily", "options"}
_PRICE_PANEL_COLUMNS = ("open", "high", "low", "close", "volume", "vwap", "amount")
_FUND_PREFIX = "fund:"


class BacktestConfigSchema(BaseModel):
    """Validates backtest config.json before execution."""

    model_config = ConfigDict(extra="allow")

    codes: List[str]
    start_date: str
    end_date: str
    source: str = "tushare"
    interval: str = "1D"
    engine: str = "daily"
    fundamental_fields: Optional[Dict[str, List[str]]] = None
    event_feeds: Optional[List[Dict[str, Any]]] = None

    @field_validator("codes")
    @classmethod
    def codes_not_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("codes must be a non-empty list")
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
        if v not in VALID_SOURCES:
            raise ValueError(f"unsupported source {v!r}, must be one of {VALID_SOURCES}")
        return v

    @field_validator("fundamental_fields")
    @classmethod
    def valid_fundamental_fields(
        cls,
        v: Optional[Dict[str, List[str]]],
    ) -> Optional[Dict[str, List[str]]]:
        if v is None:
            return v
        for table, fields in v.items():
            if not table.strip():
                raise ValueError("fundamental_fields table names must be non-empty strings")
            if any(not field.strip() for field in fields):
                raise ValueError("fundamental_fields field names must be non-empty strings")
        return v

    @field_validator("event_feeds")
    @classmethod
    def valid_event_feeds(cls, v: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        if v is None:
            return v
        for entry in v:
            if not isinstance(entry, dict):
                raise ValueError(
                    "each event_feeds entry must be an object with name/route_template/event_type"
                )
            for key in ("name", "route_template", "event_type"):
                if not str(entry.get(key, "")).strip():
                    raise ValueError(f"event_feeds entry missing required field: {key}")
        return v

    @model_validator(mode="after")
    def start_before_end(self) -> "BacktestConfigSchema":
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


# --- Runtime-reachable operation scrubber (VT-001 defense-in-depth) ---
#
# The structural checks above only reject *import-time* execution. The real
# exposure is that once ``SignalEngine`` is instantiated and ``.generate()`` is
# called, arbitrary code inside its method bodies runs with no runtime sandbox.
# This scrubber walks the code that actually executes during a backtest — every
# ``SignalEngine`` method plus any module-level helper transitively called from
# one — and rejects network / process-spawn / dynamic-exec / filesystem-write
# operations there.
#
# It is deliberately scoped to *reachable* code, not the whole file: the bundled
# skill examples (agent/src/skills/*/example_signal_engine.py) legitimately carry
# ``import requests`` + ``requests.get`` inside standalone ``_fetch_okx`` helpers
# and ``if __name__ == "__main__"`` demo blocks that the runner never executes
# (it does ``import module; SignalEngine().generate(data_map)``). Blocking those
# imports file-wide would reject strategies generated from ~12 shipped skills, so
# we block the dangerous *use* along the executed path instead of a harmless
# unused top-level import. Transitive reach via ``getattr``/indirection is a
# documented residual — see the VT-001 note; this is not a kernel-level guarantee.
_FORBIDDEN_IMPORT_MODULES = frozenset(
    {
        "socket",
        "socketserver",
        "subprocess",
        "urllib",
        "urllib2",
        "urllib3",
        "http",
        "requests",
        "httpx",
        "aiohttp",
        "ftplib",
        "smtplib",
        "telnetlib",
        "multiprocessing",
        "ctypes",
    }
)
# ``os`` itself is allowed (os.path etc.), but these attributes shell out, spawn,
# or read the process environment — none has a place in a signal engine.
_FORBIDDEN_OS_ATTRS = frozenset(
    {
        "system",
        "popen",
        "popen2",
        "popen3",
        "popen4",
        "fork",
        "forkpty",
        "putenv",
        "unsetenv",
        "getenv",
        "environ",
        "environb",
        "startfile",
    }
)
_FORBIDDEN_BUILTINS = frozenset(
    {"eval", "exec", "compile", "__import__", "globals", "locals", "vars", "breakpoint"}
)
_OPEN_WRITE_MODE_CHARS = frozenset("wax+")
_SCRUB_MSG = "is not allowed inside generated strategy code"


def _is_forbidden_os_attr(attr: str) -> bool:
    """Return whether ``os.<attr>`` shells out, spawns, execs, or reads env."""
    return attr in _FORBIDDEN_OS_ATTRS or attr.startswith(("spawn", "exec"))


def _attribute_root_name(node: ast.Attribute) -> str | None:
    """Return the leftmost ``Name`` id of an attribute chain (``a.b.c`` -> ``a``)."""
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _reject_forbidden_open(node: ast.Call) -> None:
    """Reject ``open()`` used to write files or read a non-relative-literal path."""
    func = node.func
    is_builtin_open = isinstance(func, ast.Name) and func.id == "open"
    is_io_os_open = (
        isinstance(func, ast.Attribute)
        and func.attr == "open"
        and isinstance(func.value, ast.Name)
        and func.value.id in {"io", "os"}
    )
    if not (is_builtin_open or is_io_os_open):
        return

    mode_node: ast.AST | None = node.args[1] if len(node.args) >= 2 else None
    for kw in node.keywords:
        if kw.arg == "mode":
            mode_node = kw.value
    if mode_node is not None:
        if not (isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str)):
            raise ValueError(f"open() with a non-literal mode {_SCRUB_MSG}")
        if any(ch in _OPEN_WRITE_MODE_CHARS for ch in mode_node.value):
            raise ValueError(f"Writing files via open(mode={mode_node.value!r}) {_SCRUB_MSG}")

    path_node = node.args[0] if node.args else None
    if not (isinstance(path_node, ast.Constant) and isinstance(path_node.value, str)):
        raise ValueError(f"open() with a non-literal path {_SCRUB_MSG}")
    path = path_node.value
    if path.startswith(("/", "~", "\\")) or ".." in path or (len(path) > 1 and path[1] == ":"):
        raise ValueError(f"open() with a non-relative path {path!r} {_SCRUB_MSG}")


def _reject_forbidden_node(node: ast.AST) -> None:
    """Raise ``ValueError`` if a single AST node performs a forbidden operation."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split(".")[0] in _FORBIDDEN_IMPORT_MODULES:
                raise ValueError(f"Import of {alias.name!r} {_SCRUB_MSG}")
    elif isinstance(node, ast.ImportFrom):
        root = (node.module or "").split(".")[0]
        if root in _FORBIDDEN_IMPORT_MODULES:
            raise ValueError(f"Import from {node.module!r} {_SCRUB_MSG}")
        if root == "os":
            for alias in node.names:
                if _is_forbidden_os_attr(alias.name):
                    raise ValueError(f"Import of os.{alias.name} {_SCRUB_MSG}")
    elif isinstance(node, ast.Attribute):
        root = _attribute_root_name(node)
        if root in _FORBIDDEN_IMPORT_MODULES:
            raise ValueError(f"Use of {root}.{node.attr} {_SCRUB_MSG}")
        if root == "os" and _is_forbidden_os_attr(node.attr):
            raise ValueError(f"Use of os.{node.attr} {_SCRUB_MSG}")
    elif isinstance(node, ast.Name):
        if node.id in _FORBIDDEN_BUILTINS:
            raise ValueError(f"Use of {node.id!r} {_SCRUB_MSG}")
    elif isinstance(node, ast.Call):
        _reject_forbidden_open(node)


def _scan_runtime_reachable(tree: ast.Module) -> None:
    """Reject forbidden ops in ``SignalEngine`` methods + their transitive callees.

    Entry points are every method defined directly on the ``SignalEngine`` class.
    From there, any bare-name call that resolves to a module-level function is
    followed and scanned too, so a payload hidden in a helper that ``generate()``
    calls is still caught. Module-level functions never reached from a
    ``SignalEngine`` method (standalone data-fetch helpers, ``__main__`` demos)
    are intentionally left unscanned.
    """
    engine_cls = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SignalEngine"),
        None,
    )
    if engine_cls is None:
        return

    module_funcs = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    worklist: list[ast.AST] = [
        m for m in engine_cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    visited: set[int] = set()
    while worklist:
        fn = worklist.pop()
        if id(fn) in visited:
            continue
        visited.add(id(fn))
        for node in ast.walk(fn):
            _reject_forbidden_node(node)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                target = module_funcs.get(node.func.id)
                if target is not None:
                    worklist.append(target)


def _validate_signal_engine_source(file_path: Path) -> None:
    """Reject import-time executable statements before loading signal_engine.py."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except SyntaxError as exc:
        raise ValueError(f"Invalid signal_engine.py syntax: {exc}") from exc

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "signal_engine":
            raise ValueError(
                "Circular import: 'from signal_engine import ...' imports the file from itself. "
                "Remove this import — SignalEngine is defined in this same file."
            )
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

    # Deep pass: the structural loop above only guards import-time execution;
    # this walks the code that runs on SignalEngine().generate() (VT-001).
    _scan_runtime_reachable(tree)


def _validate_signal_engine_class(engine_cls) -> None:
    """Pre-flight check: SignalEngine can be instantiated with no args and has generate()."""
    sig = inspect.signature(engine_cls.__init__)
    required = [
        p.name for p in sig.parameters.values()
        if p.name != "self" and p.default is inspect.Parameter.empty
        and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]
    if required:
        raise ValueError(
            f"SignalEngine.__init__() has required arguments {required}. "
            "All parameters must have default values so the runner can call SignalEngine()."
        )
    if not callable(getattr(engine_cls, "generate", None)):
        raise ValueError(
            "SignalEngine must have a callable 'generate' method. "
            "Expected: def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]"
        )


# --- Market detection ---
# ``_MARKET_PATTERNS``, ``_detect_market``, ``_is_china_futures``,
# ``_detect_submarket`` are imported from ``_market_hooks`` above and
# re-exported here for back-compat (swarm/grounding.py, tests).

# Back-compat: market type -> legacy source name (for engine selection & metrics)
_MARKET_TO_SOURCE = {
    "a_share": "tushare",
    "us_equity": "yfinance",
    "hk_equity": "yfinance",
    "india_equity": "yahoo",
    "crypto": "okx",
    "futures": "tushare",
    "fund": "tushare",
    "macro": "akshare",
    "forex": "akshare",
}


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


def _columns_required_from_factor_spec(spec: Any) -> list[str]:
    """Extract ``columns_required`` from supported factor spec shapes.

    Args:
        spec: Factor metadata as a dict, an Alpha-like object with ``meta``, an
            object with ``columns_required``, or a raw string alpha id.

    Returns:
        Declared panel columns, or an empty list when the shape has none.
    """
    if isinstance(spec, dict):
        meta = spec.get("meta")
        if isinstance(meta, dict):
            return [str(c) for c in meta.get("columns_required", [])]
        return [str(c) for c in spec.get("columns_required", [])]
    meta = getattr(spec, "meta", None)
    if isinstance(meta, dict):
        return [str(c) for c in meta.get("columns_required", [])]
    columns = getattr(spec, "columns_required", None)
    if columns is not None:
        return [str(c) for c in columns]
    return []


def _selected_factor_specs(config: dict) -> list[Any]:
    """Return selected factor metadata configured for the run.

    The current runner has no dedicated factor-zoo execution path, so this
    accepts the shapes used by callers that already know factor metadata
    (``selected_factors``/``factors``/``alpha_metas``) and alpha-id lists that
    can be resolved through the registry.

    Args:
        config: Backtest config.

    Returns:
        Factor specs or metadata dictionaries.
    """
    specs: list[Any] = []
    for key in ("selected_factors", "factors", "alpha_metas"):
        raw = config.get(key)
        if isinstance(raw, list):
            specs.extend(raw)
        elif raw:
            specs.append(raw)

    alpha_ids: list[str] = []
    for key in ("alpha_ids", "factor_ids", "alphas"):
        raw = config.get(key)
        if raw is None:
            continue
        if isinstance(raw, str):
            alpha_ids.append(raw)
        else:
            alpha_ids.extend(str(item) for item in raw)

    if alpha_ids:
        from src.factors.registry import get_default_registry

        registry = get_default_registry()
        for alpha_id in alpha_ids:
            try:
                specs.append(registry.get(alpha_id).meta)
            except KeyError:
                logger.warning("selected alpha_id %r is not registered; skipping", alpha_id)
    return specs


def _fund_columns_required(selected_factors: Iterable[Any]) -> list[str]:
    """Collect requested ``fund:*`` panel columns from selected factors.

    Args:
        selected_factors: Factor metadata/spec objects.

    Returns:
        Stable, de-duplicated ``fund:*`` column names.
    """
    seen: set[str] = set()
    out: list[str] = []
    for spec in selected_factors:
        for column in _columns_required_from_factor_spec(spec):
            if not column.startswith(_FUND_PREFIX) or column in seen:
                continue
            seen.add(column)
            out.append(column)
    return out


def _build_price_panel(data_map: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Convert ``code -> OHLCV frame`` rows into the factor panel shape.

    Args:
        data_map: Backtest loader output.

    Returns:
        ``column -> dates x symbols`` panel for price columns present in the
        data map.
    """
    panel: dict[str, pd.DataFrame] = {}
    for column in _PRICE_PANEL_COLUMNS:
        series_by_symbol = {
            symbol: frame[column]
            for symbol, frame in data_map.items()
            if column in frame.columns
        }
        if series_by_symbol:
            panel[column] = pd.DataFrame(series_by_symbol)
    return panel


def _nan_fundamental_frame(
    index: pd.DatetimeIndex,
    symbols: list[str],
) -> pd.DataFrame:
    """Build an all-NaN fundamental panel frame."""
    return pd.DataFrame(float("nan"), index=index, columns=symbols)


def _inject_fundamental_panel(
    panel: dict[str, pd.DataFrame],
    *,
    symbols: list[str],
    fund_columns: Iterable[str],
    start: str,
    end: str,
    freq: str = "ttm",
    pit: bool = True,
    source: str = "auto",
    index: pd.DatetimeIndex | None = None,
) -> dict[str, pd.DataFrame]:
    """Inject required fundamental fields into a factor panel.

    Args:
        panel: Existing factor panel keyed by column name.
        symbols: Symbols to load.
        fund_columns: Requested ``fund:*`` columns.
        start: Start date string.
        end: End date string.
        freq: Fundamental frequency. Defaults to ``ttm``.
        pit: Whether point-in-time loading is enforced.
        source: Fundamental data source route.
        index: Optional price index to align to. Defaults to ``panel["close"]``.

    Returns:
        The same panel dictionary with ``fund:<field>`` frames added.
    """
    fields = [column[len(_FUND_PREFIX):] for column in fund_columns if column.startswith(_FUND_PREFIX)]
    fields = list(dict.fromkeys(fields))
    if not fields:
        return panel

    price_index = index
    if price_index is None:
        close = panel.get("close")
        price_index = close.index if close is not None else pd.DatetimeIndex([])

    try:
        from backtest.loaders.fundamentals_loader import load_fundamental_panel

        loaded = load_fundamental_panel(
            symbols=symbols,
            fields=fields,
            start=start,
            end=end,
            freq=freq,
            pit=pit,
            source=source,
            index=price_index,
        )
    except Exception as exc:  # noqa: BLE001 - data-source failure must not kill backtest
        logger.warning(
            "fundamental panel load failed for fields=%s symbols=%s: %s; injecting NaN frames",
            fields,
            symbols,
            exc,
            exc_info=True,
        )
        loaded = {}

    for field in fields:
        frame = loaded.get(field)
        if not isinstance(frame, pd.DataFrame):
            frame = _nan_fundamental_frame(price_index, symbols)
        else:
            frame = frame.reindex(index=price_index, columns=symbols)
        panel[f"{_FUND_PREFIX}{field}"] = frame
    return panel


def _project_panel_fields_to_data_map(
    data_map: dict[str, pd.DataFrame],
    panel: dict[str, pd.DataFrame],
    fund_columns: Iterable[str],
) -> dict[str, pd.DataFrame]:
    """Copy injected panel fields back to per-symbol backtest frames."""
    out = {symbol: frame.copy() for symbol, frame in data_map.items()}
    for column in fund_columns:
        frame = panel.get(column)
        if frame is None:
            continue
        for symbol, symbol_frame in out.items():
            if symbol in frame.columns:
                symbol_frame[column] = frame[symbol].reindex(symbol_frame.index)
            else:
                symbol_frame[column] = float("nan")
    return out


def _maybe_inject_fundamentals_for_factor_panel(
    data_map: dict[str, pd.DataFrame],
    config: dict,
) -> dict[str, pd.DataFrame]:
    """Inject ``fund:*`` factor dependencies when selected factors request them."""
    selected_factors = _selected_factor_specs(config)
    fund_columns = _fund_columns_required(selected_factors)
    if not fund_columns:
        return data_map

    panel = _build_price_panel(data_map)
    close = panel.get("close")
    price_index = close.index if close is not None else pd.DatetimeIndex([])
    symbols = list(data_map)
    _inject_fundamental_panel(
        panel,
        symbols=symbols,
        fund_columns=fund_columns,
        start=config.get("start_date", ""),
        end=config.get("end_date", ""),
        freq="ttm",
        pit=True,
        source="auto",
        index=price_index,
    )
    return _project_panel_fields_to_data_map(data_map, panel, fund_columns)


# --- Main entry ---

def main(run_dir: Path) -> None:
    """Load config, fetch data, run the selected backtest engine.

    With ``source="auto"``, routes each code through the appropriate loader.

    Args:
        run_dir: Run directory containing ``config.json`` and ``code/signal_engine.py``.
            The path is validated against the allowed run roots
            (``VIBE_TRADING_ALLOWED_RUN_ROOTS`` plus the defaults) before any
            file is read so an arbitrary filesystem location cannot be used
            to source ``code/signal_engine.py``.
    """
    # Guard the CLI entry point with the same root whitelist the MCP
    # ``backtest`` tool already uses (src/tools/backtest_tool.py:23). Without
    # this, ``python -m backtest.runner /tmp/attacker_path`` would happily
    # import ``signal_engine.py`` from anywhere on disk; the AST scrubber
    # below blocks executable top-level statements but a method body still
    # runs on instantiation. See ``safe_run_dir`` for the policy.
    from src.tools.path_utils import safe_run_dir
    try:
        run_dir = safe_run_dir(str(run_dir))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)

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
    source = config.get("source", "tushare")
    codes = config.get("codes", [])

    # Load signal engine
    signal_path = run_dir / "code" / "signal_engine.py"
    if not signal_path.exists():
        print(json.dumps({"error": "code/signal_engine.py not found"}))
        sys.exit(1)

    try:
        signal_module = _load_module_from_file(signal_path, "signal_engine")
    except ValueError as exc:
        # Source-level AST validation (circular self-import, unsafe imports,
        # decorators, top-level statements) raises ValueError. Surface it as a
        # clean JSON envelope instead of a raw traceback so the agent gets an
        # actionable message.
        print(json.dumps({"error": f"SignalEngine source error: {exc}"}))
        sys.exit(1)
    engine_cls = getattr(signal_module, "SignalEngine", None)
    if engine_cls is None:
        print(json.dumps({"error": "SignalEngine class not found in signal_engine.py"}))
        sys.exit(1)

    try:
        _validate_signal_engine_class(engine_cls)
    except ValueError as exc:
        print(json.dumps({"error": f"SignalEngine interface error: {exc}"}))
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
        if data_map and len(data_map) < len(codes):
            missing = set(codes) - set(data_map.keys())
            logger.warning(
                "source=%s returned data for %d/%d symbols; missing: %s",
                source, len(data_map), len(codes), missing,
            )
        # Runtime fallback: try next sources in chain when primary returns empty
        if not data_map and codes:
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

    # Loader-boundary OHLC sanity for every source, centralized at the one
    # point all fetch paths converge (auto / single / runtime fallback).
    data_map = _sanitize_data_map(data_map)
    if not data_map:
        print(json.dumps({"error": "No data fetched"}))
        sys.exit(1)
    data_map = _maybe_inject_fundamentals_for_factor_panel(data_map, config)

    if source == "auto":
        config["_run_card_effective_sources"] = sorted(_group_codes_by_source(codes))
    else:
        config["_run_card_effective_sources"] = [source]

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
    if source == "auto":
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

    # India equity routing — must precede source-based routing because India's
    # effective source is ``yahoo``, which has no Wave-1 branch and would
    # otherwise fall through to the crypto default.
    if "india_equity" in markets:
        from backtest.engines.india_equity import IndiaEquityEngine
        return IndiaEquityEngine(config)

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


def _sanitize_data_map(data_map: dict) -> dict:
    """Drop structurally-invalid OHLC bars from every fetched frame.

    Each loader only drops NaN rows, so a bar that violates the OHLC
    invariants (``high < low``, a non-positive price, or a high/low that fails
    to bracket open/close) can still reach the backtest and surface as NaN/inf
    metrics. Applying :func:`validate_ohlc` here — the single point every
    fetched map converges through — guards every source uniformly (``auto``,
    single-source, runtime fallback, and any future loader), so the per-loader
    checks no longer have to be added one at a time.

    Args:
        data_map: ``code -> DataFrame`` map as returned by a loader fetch.

    Returns:
        The same mapping with each frame's invalid bars removed.
    """
    return {code: validate_ohlc(frame) for code, frame in data_map.items()}


class _AutoLoader:
    """Dummy loader for auto mode: returns pre-fetched data maps."""

    def __init__(self, data_map: dict):
        self._data = data_map

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        """Return preloaded rows for requested codes."""
        return {c: df for c, df in self._data.items() if c in codes}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m backtest.runner <run_dir>")
        sys.exit(1)
    main(Path(sys.argv[1]))
