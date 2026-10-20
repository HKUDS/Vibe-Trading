"""T9 gate — zero side effects / zero credentials / zero live connectors + G1 ledger closure.

Four surfaces (plan §T8, REQUIREMENTS §7 T9, §9 red lines):

1. FILE-TREE PURITY (dynamic): real ``run_paper_trade_step`` calls — orders
   mode (us single-leg AND the cn_a federated path) and strategy_path mode
   (real spawned child) — leave the sandboxed runtime root
   (``get_runtime_root()``, the conftest-redirected ``~/.vibe-trading``) and
   a controlled cwd byte-identical: same relative paths, same content
   sha256, nothing created or deleted (directories and symlinks included).
2. ZERO CREDENTIALS (static): the paper-trade source surface performs no
   direct environment read and names no RM credential constant/env name.
   The ONLY sanctioned secret path is the pre-existing ``CLICKHOUSE_*`` env
   config (``acs_ro`` read-only user, REQUIREMENTS §3-6) consumed through
   the EXISTING ``get_env_config()``/``ClickHouseConnector`` layer — the
   lowercase ``cfg.clickhouse_*`` attribute reads in data.py are that path,
   not an RM credential surface, and no module here reads env itself.
3. ZERO LIVE CONNECTORS (static): no scoped ``trading_*`` connector call
   surface and no order-placement verb anywhere in the package.  The scan
   is the SCOPED regex — a bare ``trading_`` grep is a KNOWN FALSE RED:
   the frozen pt-v1.1 vocabulary (``non_trading_day``/``trading_day``) and
   the calendar helpers (``is_trading_day``/``trading_days_in_range``) are
   contract words, never connector calls, and must not be "fixed".
4. G1 LEDGER CLOSED (static): zero residual STEP1 ledger markers across the
   ledger scan surface (package source, ``agent/tests``, the pt-v1.1
   contract JSON).  The marker literal is assembled by a runtime join, so
   this file — source AND compiled ``.pyc`` constant table — never contains
   it and the scan never self-matches (CPython constant-folds a plain
   ``"a" + "b"`` BinOp into the code object; ``"".join`` cannot be folded).

Offline: injected fake loaders/clients, zero network (``--disable-socket``
hard gate).  The strategy child spawns through ``multiprocessing`` pipes —
POSIX socketpair at the C layer, which pytest-socket does not intercept.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from src.config.paths import get_runtime_root
from src.tools.paper_trade import tool as tool_module
from src.tools.paper_trade.tool import run_paper_trade_step

_PACKAGE_DIR = Path(tool_module.__file__).resolve().parent
_TESTS_DIR = Path(__file__).resolve().parent
_CONTRACT_JSON = _TESTS_DIR.parents[1] / "schema" / "tool_contracts" / "paper_trade_step-v1.1.json"

# Runtime-assembled so the contiguous literal exists in neither this file's
# source nor its .pyc (see module docstring §4) — the acceptance grep over
# agent/tests/ must not self-match on the scanner itself.
_LEDGER_MARKER = "".join(("TODO-", "G1"))

_US_DAY = "2026-03-06"  # Friday
_CN_A_DAY = "2026-03-06"
_CN_A_PREV = "2026-03-05"
_US_FEES = {"commission_per_share": 0.0049, "commission_min": 0.99, "sec_fee_rate": 0.0}
_CN_A_FEES = {
    "commission_rate": 0.00025, "commission_min": 5.0,
    "stamp_tax_sell": 0.0005, "transfer_fee": 0.00001,
}


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "sina") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self._frames[c] for c in codes if c in self._frames}


class FakeChClient:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._frames.get(ts_code, pd.DataFrame())


class FakeCalendarClient:
    def __init__(self, open_days: tuple[str, ...]) -> None:
        self._open = set(open_days)

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {"exchange": "SSE", "cal_date": day.strftime("%Y-%m-%d"),
             "is_open": int(day.strftime("%Y-%m-%d") in self._open), "pretrade_date": ""}
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _frame(day: str, close: float) -> pd.DataFrame:
    record = {"trade_date": day, "open": close, "high": close, "low": close,
              "close": close, "volume": 1000.0}
    frame = pd.DataFrame([record])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


def _snapshot_tree(root: Path) -> dict[str, str]:
    """Byte-level tree snapshot: relative path → sha256 (file) / "dir" / link target.

    Directories are recorded so a created/removed EMPTY directory is a diff;
    symlinks are recorded by target (never followed into foreign trees).
    """
    tree: dict[str, str] = {}
    if not root.exists():
        return tree
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            tree[rel] = f"link:{path.readlink().as_posix()}"
        elif path.is_dir():
            tree[rel] = "dir"
        elif path.is_file():
            tree[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return tree


@pytest.fixture()
def controlled_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """chdir into a seeded sentinel directory and return it for snapshotting."""
    (tmp_path / "sentinel.txt").write_text("paper-trade purity sentinel\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "data.json").write_text('{"untouched": true}\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _assert_trees_frozen(runtime_before: dict[str, str], cwd_before: dict[str, str],
                         cwd: Path) -> None:
    assert _snapshot_tree(get_runtime_root()) == runtime_before
    assert _snapshot_tree(cwd) == cwd_before


# ── 1. file-tree purity (dynamic, real tool calls) ──


def test_orders_mode_us_leaves_runtime_root_and_cwd_byte_identical(controlled_cwd: Path) -> None:
    payload = {
        "account_id": "pa_purity", "market": "us",
        "account_state": {"cash": 50000.0, "positions": []},
        "orders": [{"symbol": "PUR.US", "side": "buy", "qty": 10}],
        "from_date": _US_DAY, "to_date": _US_DAY, "fee_model": dict(_US_FEES),
    }
    loader = FakeLoader({"PUR.US": _frame(_US_DAY, 100.0)})
    runtime_before = _snapshot_tree(get_runtime_root())
    cwd_before = _snapshot_tree(controlled_cwd)

    doc = json.loads(run_paper_trade_step(payload, loader=loader))

    assert "status" not in doc, doc  # the guarded call really succeeded
    assert doc["fills"][0]["fee"] == 0.99
    _assert_trees_frozen(runtime_before, cwd_before, controlled_cwd)


def test_orders_mode_cn_a_federated_leaves_runtime_root_and_cwd_byte_identical(
    controlled_cwd: Path,
) -> None:
    # The cn_a two-leg federation (AM-9) with every seam injected: no
    # ClickHouse connector is built, no env config is read, nothing writes.
    payload = {
        "account_id": "pa_purity", "market": "cn_a",
        "account_state": {"cash": 200000.0, "positions": []},
        "orders": [{"symbol": "600519.SH", "side": "buy", "qty": 100}],
        "from_date": _CN_A_DAY, "to_date": _CN_A_DAY, "fee_model": dict(_CN_A_FEES),
    }
    loader = FakeLoader({"600519.SH": _frame(_CN_A_DAY, 1421.0)}, "tencent")
    ch_client = FakeChClient({"600519.SH": _frame(_CN_A_PREV, 1418.0)})
    calendar_client = FakeCalendarClient((_CN_A_DAY,))
    runtime_before = _snapshot_tree(get_runtime_root())
    cwd_before = _snapshot_tree(controlled_cwd)

    doc = json.loads(run_paper_trade_step(
        payload, loader=loader, ch_client=ch_client,
        calendar_client=calendar_client, limits_client=None))

    assert "status" not in doc, doc
    assert doc["fills"][0]["fee"] == 36.95  # the cn_a golden cents
    assert doc["data_provenance"]["source"] == "clickhouse+tencent(merged)"
    _assert_trees_frozen(runtime_before, cwd_before, controlled_cwd)


_STRATEGY_SOURCE = '''"""Purity probe strategy: one buy, zero I/O."""

UNIVERSE = ("PUR.US",)


class SignalEngine:
    def generate_signals(self, ctx, trade_date):
        return [{"symbol": "PUR.US", "side": "buy", "qty": 10, "reason": "purity probe"}]
'''


def test_strategy_path_mode_leaves_runtime_root_and_cwd_byte_identical(controlled_cwd: Path) -> None:
    # The strategy install is SETUP and happens BEFORE the snapshot: the
    # guarded surface is the tool call (which spawns the real T7 child),
    # not the test's own fixture writes.
    root = get_runtime_root() / "strategies"
    root.mkdir(parents=True, exist_ok=True)
    strategy = root / "purity_probe.py"
    strategy.write_text(_STRATEGY_SOURCE, encoding="utf-8")

    payload = {
        "account_id": "pa_purity", "market": "us",
        "account_state": {"cash": 50000.0, "positions": []},
        "strategy_path": str(strategy),
        "from_date": _US_DAY, "to_date": _US_DAY, "fee_model": dict(_US_FEES),
    }
    loader = FakeLoader({"PUR.US": _frame(_US_DAY, 100.0)})
    runtime_before = _snapshot_tree(get_runtime_root())
    cwd_before = _snapshot_tree(controlled_cwd)

    doc = json.loads(run_paper_trade_step(payload, loader=loader))

    assert "status" not in doc, doc
    assert [f["reason"] for f in doc["fills"]] == ["purity probe"]
    _assert_trees_frozen(runtime_before, cwd_before, controlled_cwd)


# ── 2/3. zero credentials, zero live connectors (static source scans) ──


def _package_sources() -> list[Path]:
    return sorted(
        path for path in _PACKAGE_DIR.rglob("*.py") if "__pycache__" not in path.parts
    )


def _scan(pattern: re.Pattern[str], paths: list[Path]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            hits.append(f"{path.name}:{line}:{match.group(0)}")
    return hits


def test_source_surface_reads_no_environment_and_names_no_rm_credentials() -> None:
    # Zero-credential red line (REQUIREMENTS §3-6/§9): the package itself
    # never reads env and never names a credential constant.  Uppercase
    # CLICKHOUSE_* env names are included: even the sanctioned acs_ro secret
    # must flow through the pre-existing config layer (lowercase cfg.*
    # attribute reads in data.py), never a direct env read in this package.
    env_read = re.compile(r"os\.environ|os\.getenv|environ\.get\(")
    credential = re.compile(
        r"API_KEY|SECRET|PASSWORD|PASSWD|PRIVATE_KEY|ACCESS_KEY|CREDENTIAL"
        r"|BEARER|KEYRING|AUTH_TOKEN|RM_TOKEN|RM_API|RM_SECRET|RM_KEY"
        r"|CLICKHOUSE_USER|CLICKHOUSE_PASSWORD|CLICKHOUSE_HOST|CLICKHOUSE_LLM"
    )
    sources = _package_sources()
    assert sources, "the paper_trade package must contain source files"
    assert _scan(env_read, sources) == []
    assert _scan(credential, sources) == []


def test_source_surface_calls_no_live_trading_connector() -> None:
    # Zero-live red line (REQUIREMENTS R1/§9), package-wide: the SCOPED
    # connector regex (a bare "trading_" grep false-reds on the frozen
    # non_trading_day/trading_day vocabulary — see module docstring §3),
    # plus the order-placement verbs and the broker-layer import root.
    scoped = re.compile(
        r"trading_(account|orders|positions|quote|history|check|connections|select|place|cancel)"
    )
    broker_surface = re.compile(r"place_order|cancel_order|src\.trading")
    sources = _package_sources()
    assert _scan(scoped, sources) == []
    assert _scan(broker_surface, sources) == []


# ── 4. G1 ledger closure (static scan) ──


def _ledger_scan_surface() -> list[Path]:
    # Mirrors the plan's acceptance grep surface (package source +
    # agent/tests + the contract JSON), restricted to TEXT files with
    # __pycache__ excluded — binary .pyc hits are the known grep pitfall,
    # and comments never compile into .pyc anyway.
    text_files = [
        path
        for root in (_PACKAGE_DIR, _TESTS_DIR)
        for path in root.rglob("*")
        if path.suffix in {".py", ".json"} and path.is_file() and "__pycache__" not in path.parts
    ]
    return [*sorted(text_files), _CONTRACT_JSON]


def test_g1_ledger_has_zero_residual_markers() -> None:
    # STEP1 ledger closure (18 markers / 8 files): each task removed its own
    # surface at the frozen pt-v1.1 value (T2 calendar×2, T5 schema×5 +
    # state_hash×3 + contract JSON×4 + tests×2, T6 __init__×1, T8
    # limits_cn_a×1 — the provenance token comment, now FROZEN).  Zero
    # residual anywhere on the ledger surface.
    surface = _ledger_scan_surface()
    assert _CONTRACT_JSON in surface
    assert len(surface) > 20, "scan surface must cover the package, the tests and the contract"
    hits = [
        str(path) for path in surface
        if _LEDGER_MARKER in path.read_text(encoding="utf-8")
    ]
    assert hits == []
