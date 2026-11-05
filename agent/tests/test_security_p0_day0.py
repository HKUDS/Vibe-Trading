"""Regression tests for the P0 day-0 security fixes.

Covers: no ``.env`` reload in the backtest child (F3), pathlib reads confined
to the run dir, broker host pinning and the agent/MCP local-gateway rule (N1),
paper profiles refusing a live config (F7), and child->parent paper IPC that
never unpickles (M4) with a scrubbed child environment.

Every credential here is a dummy canary; nothing touches a network or broker.
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import pickle
import subprocess
import textwrap
import uuid
from pathlib import Path

import pytest

from backtest import runner as bt_runner
from backtest.runner import _load_module_from_file
from src.trading.endpoint_policy import is_broker_url, is_local_gateway_host

CANARY = "CANARY-" + uuid.uuid4().hex


def _write_engine(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "signal_engine.py"
    path.write_text(
        "\n".join(
            [
                '"""Generated signal engine."""',
                "from pathlib import Path",
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                body,
            ]
        ),
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------- #
# F3: the backtest child must never re-read agent/.env
# --------------------------------------------------------------------------- #


def test_runner_main_never_calls_load_dotenv() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(bt_runner.main)))
    calls = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "load_dotenv" not in calls


def test_backtest_tool_runs_child_in_run_dir_not_agent_root() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "tools" / "backtest_tool.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    execute_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "runner"
    ]
    assert len(execute_calls) == 1
    keywords = {kw.arg: ast.unparse(kw.value) for kw in execute_calls[0].keywords}
    assert keywords["cwd"] == "run_path"
    assert keywords["pythonpath"] == "agent_root"


def test_runner_child_cannot_see_dotenv_by_relative_path(tmp_path: Path) -> None:
    pytest.importorskip("rich")
    from src.core.runner import Runner

    # A fake agent root holding a canary .env and an importable module, and a
    # run dir elsewhere: the child must import from pythonpath but run in run_dir.
    agent_root = tmp_path / "agent"
    (agent_root / "probe_pkg").mkdir(parents=True)
    (agent_root / "probe_pkg" / "__init__.py").write_text("VALUE = 7\n", encoding="utf-8")
    (agent_root / ".env").write_text(f"OPENAI_API_KEY={CANARY}\n", encoding="utf-8")
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    entry = tmp_path / "probe.py"
    entry.write_text(
        "import json, os, probe_pkg\n"
        "print(json.dumps({'cwd': os.getcwd(), 'dotenv_visible': os.path.exists('.env'),"
        " 'value': probe_pkg.VALUE, 'canary_in_env': any("
        f"{CANARY!r} in v for v in os.environ.values())}}))\n",
        encoding="utf-8",
    )

    result = Runner(timeout=60).execute(entry, run_dir, cwd=run_dir, pythonpath=agent_root)

    assert result.success, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert Path(report["cwd"]).resolve() == run_dir.resolve()
    assert report == {**report, "dotenv_visible": False, "value": 7, "canary_in_env": False}


def test_runtime_env_allowlist_keeps_source_order_drops_secrets() -> None:
    pytest.importorskip("rich")
    from src.core.runner import _is_runtime_env_key_allowed

    assert _is_runtime_env_key_allowed("MARKET_DATA_ORDER_A_SHARE")
    for secret in ("OPENAI_API_KEY", "API_AUTH_KEY", "TAP_AGENT_KEY", "ETORO_API_KEY", "LONGBRIDGE_APP_SECRET"):
        assert not _is_runtime_env_key_allowed(secret)


# --------------------------------------------------------------------------- #
# Scanner: pathlib reads confined to Path("<relative literal>")
# --------------------------------------------------------------------------- #

_FORBIDDEN_READS = [
    ("dunder_file_dotenv", "        Path(__file__).parents[2].joinpath('.env').read_text()\n        return []"),
    ("absolute_read_text", "        Path('/etc/passwd').read_text()\n        return []"),
    ("home_read_bytes", "        Path('~/.vibe-trading/okx.json').read_bytes()\n        return []"),
    ("parent_open", "        Path('../.env').open()\n        return []"),
    ("variable_receiver", "        p = Path('x')\n        p.read_text()\n        return []"),
    ("windows_drive", "        Path('C:/Users/x/.env').read_text()\n        return []"),
]


@pytest.mark.parametrize("case_id,body", _FORBIDDEN_READS, ids=[c[0] for c in _FORBIDDEN_READS])
def test_scanner_rejects_pathlib_reads_outside_run_dir(tmp_path, case_id, body) -> None:
    with pytest.raises(ValueError, match="not allowed inside generated strategy code"):
        _load_module_from_file(_write_engine(tmp_path, body), f"se_{uuid.uuid4().hex}")


@pytest.mark.parametrize(
    "body",
    [
        "        Path('data.csv').read_text()\n        return []",
        "        Path('inputs/prices.bin').read_bytes()\n        return []",
        "        Path('data.csv').open()\n        return []",
    ],
)
def test_scanner_allows_relative_literal_reads(tmp_path, body) -> None:
    _load_module_from_file(_write_engine(tmp_path, body), f"se_{uuid.uuid4().hex}")


# --------------------------------------------------------------------------- #
# N1: broker hosts pinned; agent/MCP host override only for local gateways
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://www.okx.com", True),
        ("https://my.okx.com:443", True),
        ("https://okx.com", True),
        ("http://www.okx.com", False),
        ("https://attacker.example", False),
        ("https://www.okx.com.attacker.example", False),
        ("https://evilokx.com", False),
        ("https://user:pw@www.okx.com", False),
        ("https://www.okx.com@attacker.example", False),
        ("www.okx.com", False),
        ("", False),
    ],
)
def test_is_broker_url(url, ok) -> None:
    assert is_broker_url(url, ("okx.com",)) is ok


@pytest.mark.parametrize(
    "host,ok",
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("[::1]", True),
        ("192.168.1.20", True),
        ("10.0.0.5", True),
        ("host.docker.internal", True),
        ("opend.local", True),
        ("169.254.169.254", False),
        ("0.0.0.0", False),
        ("8.8.8.8", False),
        ("attacker.example", False),
        ("https://attacker.example", False),
        ("localhost.attacker.example", False),
    ],
)
def test_is_local_gateway_host(host, ok) -> None:
    assert is_local_gateway_host(host) is ok


def test_agent_host_override_rejects_remote_hosts() -> None:
    from src.tools.trading_connector_tool import InvalidTradingArgument, _overrides

    for bad in ("https://attacker.example", "attacker.example", "169.254.169.254"):
        with pytest.raises(InvalidTradingArgument):
            _overrides({"host": bad})
    for good in ("127.0.0.1", "opend.local", "host.docker.internal", None, ""):
        assert _overrides({"host": good})["host"] in {good, None}


def test_okx_config_refuses_foreign_host() -> None:
    from src.trading.connectors.okx.sdk import OKXConfig, OKXConfigError, build_config

    assert OKXConfig.from_mapping({}).host == "https://www.okx.com"
    for bad in ("https://attacker.example", "http://www.okx.com", "https://www.okx.com.attacker.example"):
        with pytest.raises(OKXConfigError):
            OKXConfig.from_mapping({"host": bad, "api_key": "TEST-KEY-CANARY"})
        with pytest.raises(OKXConfigError):
            build_config({"profile": "paper"}, {"host": bad})


def test_other_cloud_broker_urls_are_pinned() -> None:
    from src.trading.connectors.binance.sdk import BinanceConfig, BinanceConfigError
    from src.trading.connectors.toss.sdk import TossConfig, TossConfigError
    from src.trading.connectors.trading212.sdk import Trading212Config, Trading212ConfigError

    assert BinanceConfig.from_mapping({"testnet_host": "https://testnet.binancefuture.com"})
    with pytest.raises(BinanceConfigError):
        BinanceConfig.from_mapping({"testnet_host": "https://attacker.example"})
    assert TossConfig.from_mapping({})
    with pytest.raises(TossConfigError):
        TossConfig.from_mapping({"base_url": "http://127.0.0.1:9"})
    assert Trading212Config.from_mapping({"profile": "paper", "base_url": "https://demo.trading212.com"})
    with pytest.raises(Trading212ConfigError):
        Trading212Config.from_mapping({"base_url": "https://attacker.example"})


# --------------------------------------------------------------------------- #
# F7: a paper profile can never resolve to a live connector config
# --------------------------------------------------------------------------- #


def test_paper_profile_refuses_live_profile_override(monkeypatch, tmp_path) -> None:
    from src.trading import service
    from src.trading.connectors.alpaca import sdk as alpaca_sdk
    from src.trading.profiles import profile_by_id

    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    placed: list[dict] = []
    monkeypatch.setattr(alpaca_sdk, "place_order", lambda cfg, **kw: placed.append(kw) or {"status": "ok"})

    profile = profile_by_id("alpaca-paper-trade")
    assert service._sdk_config(profile, alpaca_sdk, {}).environment == "paper"
    with pytest.raises(ValueError, match="refusing"):
        service._sdk_config(profile, alpaca_sdk, {"profile": "live"})
    with pytest.raises(ValueError, match="refusing"):
        service.place_order("AAPL", "alpaca-paper-trade", side="buy", quantity=1, profile="live")
    assert placed == []


# --------------------------------------------------------------------------- #
# M4: child->parent paper IPC is JSON lines, never pickle
# --------------------------------------------------------------------------- #

_UNPICKLED: list[str] = []


def _mark_unpickled() -> None:
    _UNPICKLED.append("ran")


class _Payload:
    def __reduce__(self):
        return (_mark_unpickled, ())


@pytest.fixture
def sp():
    """The IPC module; its package __init__ imports defusedxml (a base dependency)."""
    pytest.importorskip("defusedxml")
    from src.tools.paper_trade import strategy_process

    return strategy_process


def _parent_conn(sp, data: bytes):
    return sp.StrategyConnection(io.BytesIO(data), io.BytesIO(), parent=True)


def test_parent_never_unpickles_child_output(sp) -> None:
    conn = _parent_conn(sp, pickle.dumps(_Payload()) + b"\n")
    assert conn.poll(5)
    with pytest.raises(EOFError):
        conn.recv()
    conn.close()
    assert _UNPICKLED == []


@pytest.mark.parametrize(
    "line",
    [b'{"tag": "ready"}\n', b"[]\n", b"[1]\n", b'["ready"]', b"not json\n"],
    ids=["object", "empty", "untagged", "no_newline", "garbage"],
)
def test_decode_child_message_rejects_malformed(sp, line) -> None:
    with pytest.raises(ValueError):
        sp.decode_child_message(line)


def test_child_message_round_trip_and_size_cap(sp, monkeypatch) -> None:
    order = {"symbol": "600519.SH", "side": "buy", "qty": 100.0, "limit": None, "reason": "x"}
    line = sp.encode_child_message(("day", "2026-01-05", [order]))
    assert sp.decode_child_message(line) == ("day", "2026-01-05", [order])
    with pytest.raises(ValueError):
        sp.encode_child_message(("day", "2026-01-05", [{"qty": float("nan")}]))

    monkeypatch.setattr(sp, "_MAX_CHILD_MESSAGE_BYTES", 32)
    conn = _parent_conn(sp, sp.encode_child_message(("day", "d", ["x" * 100])))
    assert conn.poll(5)
    with pytest.raises(EOFError):
        conn.recv()
    conn.close()


def test_malformed_child_error_is_a_protocol_failure() -> None:
    pytest.importorskip("defusedxml")
    from src.tools.paper_trade.strategy_exec import StrategyProcessError, _child_failure

    assert _child_failure(("error",), "2026-01-05").class_name == StrategyProcessError.__name__
    assert _child_failure(("error", 1, 2), "2026-01-05").class_name == StrategyProcessError.__name__
    failure = _child_failure(("error", "2026-01-06", "ZeroDivisionError"), "2026-01-05")
    assert (failure.day, failure.class_name) == ("2026-01-06", "ZeroDivisionError")


def test_paper_strategy_child_gets_scrubbed_env_and_private_cwd(sp, monkeypatch) -> None:
    pytest.importorskip("rich")
    monkeypatch.setenv("OPENAI_API_KEY", CANARY)
    captured: dict = {}

    class _FakeProcess:
        def __init__(self, args, **kwargs):
            captured.update(kwargs)
            self.stdin, self.stdout = io.BytesIO(), io.BytesIO()

    monkeypatch.setattr(subprocess, "Popen", _FakeProcess)
    _, conn = sp.start_strategy_process({"source": "", "filename": "x.py", "days": (), "symbols": ()})
    workdir = Path(captured["cwd"])
    assert workdir.is_dir() and not any(workdir.iterdir())
    assert CANARY not in captured["env"].values()
    assert "OPENAI_API_KEY" not in captured["env"]
    conn.close()
    assert not workdir.exists()
