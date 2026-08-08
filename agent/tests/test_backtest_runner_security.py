"""Security regression tests for backtest signal_engine loading."""

from __future__ import annotations

import uuid

import pytest

from backtest.runner import _load_module_from_file


def _module_name() -> str:
    """Return a unique module name for import tests."""
    return f"signal_engine_test_{uuid.uuid4().hex}"


def test_signal_engine_rejects_top_level_execution(tmp_path) -> None:
    artifact = tmp_path / "top_level_rce"
    # ``Path.as_posix()`` so the embedded path uses forward slashes; the raw
    # Windows form ``C:\Users\...`` looks like ``\U`` (a unicode escape) when
    # interpolated into Python source and breaks ``ast.parse`` before the
    # security scrubber under test ever runs.
    artifact_str = artifact.as_posix()
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                "import os",
                f"os.system('touch {artifact_str}')",
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                "        return []",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Executable top-level statement"):
        _load_module_from_file(signal_file, _module_name())

    assert not artifact.exists()


def test_signal_engine_rejects_class_level_execution(tmp_path) -> None:
    artifact = tmp_path / "class_level_rce"
    artifact_str = artifact.as_posix()  # see top_level test for rationale
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                "import os",
                "class SignalEngine:",
                f"    os.system('touch {artifact_str}')",
                "    def generate(self, *args, **kwargs):",
                "        return []",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Executable class-level statement"):
        _load_module_from_file(signal_file, _module_name())

    assert not artifact.exists()


def test_signal_engine_allows_minimal_valid_strategy(tmp_path) -> None:
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Generated signal engine."""',
                "THRESHOLD = 3",
                "class SignalEngine:",
                "    lookback = 20",
                "    def generate(self, *args, **kwargs):",
                "        return []",
            ]
        ),
        encoding="utf-8",
    )

    module = _load_module_from_file(signal_file, _module_name())

    assert module.SignalEngine().generate() == []


# --------------------------------------------------------------------------- #
# VT-001: forbidden operations hidden INSIDE method bodies.
#
# Every fixture below is structurally valid (valid class + method defs, only
# import-time-safe top-level statements) and therefore passed the pre-VT-001
# validator, which never walked into function bodies. They must now be rejected
# because the danger lives on the code path that runs on SignalEngine().generate().
# --------------------------------------------------------------------------- #

# Each entry: (id, body_lines) — spliced into SignalEngine.generate().
_FORBIDDEN_IN_METHOD_BODY = [
    ("import_socket", ["        import socket", "        return socket.gethostname()"]),
    (
        "subprocess_call",
        ["        import subprocess", "        return subprocess.run(['id'])"],
    ),
    ("os_system", ["        import os", "        return os.system('id')"]),
    ("os_environ_read", ["        import os", "        return os.environ['SECRET']"]),
    ("os_getenv", ["        import os", "        return os.getenv('SECRET')"]),
    ("eval_call", ["        return eval('1+1')"]),
    ("exec_call", ["        exec('x = 1')", "        return []"]),
    ("dunder_import", ["        return __import__('os').getcwd()"]),
    ("requests_get", ["        import requests", "        return requests.get('http://x')"]),
    ("urllib_urlopen", ["        import urllib.request as u", "        return u.urlopen('http://x')"]),
    ("open_write", ["        open('evil.txt', 'w').write('x')", "        return []"]),
    ("open_abs_read", ["        return open('/etc/passwd').read()"]),
    # The red line: no research or backtest path may reach a connector's
    # place_order. The subprocess is handed the agent root on PYTHONPATH, so
    # the separation has to be enforced by the scanner, not by hoping the
    # module is unimportable.
    (
        "import_trading_service",
        ["        import src.trading.service", "        return []"],
    ),
    (
        "from_trading_service_import_place_order",
        ["        from src.trading.service import place_order", "        return []"],
    ),
    (
        "from_trading_import_service",
        ["        from src.trading import service", "        return []"],
    ),
    (
        "import_broker_connector",
        ["        import src.trading.connectors.okx.sdk", "        return []"],
    ),
    (
        "import_live_order_gate",
        ["        from src.live.sdk_order_gate import check", "        return []"],
    ),
    (
        "trading_attribute_chain",
        ["        import src", "        return src.trading.service.place_order(1)"],
    ),
    (
        "getattr_indirection_onto_trading",
        [
            "        import src",
            "        return getattr(src.trading.service, 'place_order')(1)",
        ],
    ),
]


@pytest.mark.parametrize(
    "case_id,body",
    _FORBIDDEN_IN_METHOD_BODY,
    ids=[c[0] for c in _FORBIDDEN_IN_METHOD_BODY],
)
def test_signal_engine_rejects_forbidden_op_in_method_body(tmp_path, case_id, body) -> None:
    signal_file = tmp_path / "signal_engine.py"
    lines = [
        '"""Generated signal engine."""',
        "class SignalEngine:",
        "    def generate(self, *args, **kwargs):",
        *body,
    ]
    signal_file.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(ValueError, match="not allowed inside generated strategy code"):
        _load_module_from_file(signal_file, _module_name())


@pytest.mark.parametrize(
    "import_line",
    [
        "        from src.quantlib.fixedincome import bond_price",
        "        import src.quantlib.credit",
        "        from src.factors.registry import get_factor",
    ],
    ids=["quantlib_from", "quantlib_import", "factors_registry"],
)
def test_signal_engine_still_allows_project_math_imports(tmp_path, import_line) -> None:
    """Blocking the broker subtree must not cost strategies the math layer.

    ``src.trading`` and ``src.quantlib`` share a root package, so a root-level
    block would close the red-line gap by taking away the finance-math layer
    strategies are explicitly meant to import. The prefix match keeps them
    apart; this pins that it stays that way.
    """
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Generated signal engine."""',
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                import_line,
                "        return []",
            ]
        ),
        encoding="utf-8",
    )

    _load_module_from_file(signal_file, _module_name())


# Module-level imports are deliberately left unrejected so an unused
# ``import requests`` beside an unreachable helper does not fail the shipped
# skill examples; the compensating check is on the *use* along the executed
# path. That check matches dotted chains rooted in the module's own name, so
# every binding below renamed the root and reached the payload anyway — the
# aliasing half of the VT-001 residual.
_MODULE_LEVEL_ALIAS_BYPASSES = [
    ("from_socket_alias", "from socket import socket as S", "        return S()"),
    ("from_subprocess_alias", "from subprocess import run as R", "        return R(['ls'])"),
    ("from_os_system", "from os import system", "        return system('id')"),
    ("from_ctypes", "from ctypes import CDLL", "        return CDLL('x')"),
    ("import_socket_alias", "import socket as sk", "        return sk.socket()"),
    ("import_subprocess_alias", "import subprocess as sp", "        return sp.run(['ls'])"),
    (
        "from_trading_place_order",
        "from src.trading.service import place_order",
        "        return place_order(1)",
    ),
    (
        "from_live_order_gate",
        "from src.live.sdk_order_gate import check",
        "        return check()",
    ),
    (
        "from_trading_submodule_alias",
        "from src.trading import service as sv",
        "        return sv.place_order(1)",
    ),
    (
        "import_trading_alias",
        "import src.trading.service as t",
        "        return t.place_order(1)",
    ),
]


@pytest.mark.parametrize(
    "case_id,import_line,call_line",
    _MODULE_LEVEL_ALIAS_BYPASSES,
    ids=[c[0] for c in _MODULE_LEVEL_ALIAS_BYPASSES],
)
def test_signal_engine_rejects_module_level_alias_of_forbidden_module(
    tmp_path, case_id, import_line, call_line,
) -> None:
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Generated signal engine."""',
                import_line,
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                call_line,
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not allowed inside generated strategy code"):
        _load_module_from_file(signal_file, _module_name())


@pytest.mark.parametrize(
    "import_line,body_line",
    [
        # The reason module-level imports are not rejected outright: the shipped
        # skill examples carry these beside helpers the runner never reaches.
        ("import requests", "        return []"),
        ("from requests import get", "        return []"),
        # Ordinary strategy imports, used on the executed path.
        ("import pandas as pd", "        return pd.DataFrame()"),
        ("from src.quantlib.options import bs_price", "        return bs_price(1, 1, 1, 1, 1)"),
        ("from os import path", "        return path.join('a', 'b')"),
    ],
    ids=["unused_requests", "unused_from_requests", "pandas_alias", "quantlib", "os_path"],
)
def test_signal_engine_alias_check_leaves_legitimate_imports_alone(
    tmp_path, import_line, body_line,
) -> None:
    """The alias check must cost neither the unused import nor the math layer."""
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Generated signal engine."""',
                import_line,
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                body_line,
            ]
        ),
        encoding="utf-8",
    )

    _load_module_from_file(signal_file, _module_name())


# Blocking the ``src.trading`` prefix buys nothing while a module can be fetched
# by NAME instead of named in an import statement. Every case below was measured
# ACCEPTED against the live scanner before this list existed — the red line was
# one string away from being reachable in each of them.
_DYNAMIC_MODULE_REACH = [
    ("importlib_import_module", "import importlib", "        return importlib.import_module('src.trading.service')"),
    ("importlib_alias", "import importlib as il", "        return il.import_module('src.trading.service')"),
    (
        "importlib_from_alias",
        "from importlib import import_module as imp",
        "        return imp('src.trading.service')",
    ),
    ("importlib_util", "import importlib.util", "        return importlib.util.spec_from_file_location('x', 'y.py')"),
    (
        "importlib_inside_method",
        "import pandas as pd",
        "        import importlib\n        return importlib.import_module('src.trading.service')",
    ),
    ("builtins_dunder_import", "import builtins", "        return builtins.__import__('src.trading.service')"),
    ("builtins_eval", "import builtins", "        return builtins.eval('1+1')"),
    ("builtins_alias", "import builtins as b", "        return b.__import__('src.trading.service')"),
    (
        "builtins_from_alias",
        "from builtins import __import__ as bi",
        "        return bi('src.trading.service')",
    ),
    ("sys_modules", "import sys", "        return sys.modules['src.trading.service']"),
    ("sys_path_injection", "import sys", "        sys.path.insert(0, '/tmp/evil')\n        return []"),
    ("pkgutil_resolve_name", "import pkgutil", "        return pkgutil.resolve_name('src.trading.service:place_order')"),
    ("runpy_run_module", "import runpy", "        return runpy.run_module('src.trading.service')"),
    # pickle/marshal never name the module in the source at all.
    ("pickle_loads", "import pickle", "        return pickle.loads(b'payload')"),
    ("marshal_loads", "import marshal", "        return marshal.loads(b'payload')"),
    ("shutil_copy", "import shutil", "        return shutil.copy('/etc/passwd', '/tmp/x')"),
    ("webbrowser_open", "import webbrowser", "        return webbrowser.open('http://x')"),
    ("gc_get_objects", "import gc", "        return gc.get_objects()"),
]


@pytest.mark.parametrize(
    "case_id,import_line,body",
    _DYNAMIC_MODULE_REACH,
    ids=[c[0] for c in _DYNAMIC_MODULE_REACH],
)
def test_signal_engine_rejects_module_reached_by_name(
    tmp_path, case_id, import_line, body,
) -> None:
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Generated signal engine."""',
                import_line,
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                body,
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not allowed inside generated strategy code"):
        _load_module_from_file(signal_file, _module_name())


# ``open(path, "w")`` is refused, but the same write reached disk through the
# pathlib spellings, which the bare-open check cannot see. Measured ACCEPTED
# before this guard.
_PATHLIB_WRITES = [
    ("write_text", "        Path('evil.txt').write_text('x')\n        return []"),
    ("write_bytes", "        Path('evil.bin').write_bytes(b'x')\n        return []"),
    ("open_positional_mode", "        Path('evil.txt').open('w')\n        return []"),
    ("open_append_mode", "        Path('evil.txt').open('a+')\n        return []"),
    ("open_keyword_mode", "        Path('evil.txt').open(mode='w')\n        return []"),
]


@pytest.mark.parametrize("case_id,body", _PATHLIB_WRITES, ids=[c[0] for c in _PATHLIB_WRITES])
def test_signal_engine_rejects_pathlib_file_writes(tmp_path, case_id, body) -> None:
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
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

    with pytest.raises(ValueError, match="not allowed inside generated strategy code"):
        _load_module_from_file(signal_file, _module_name())


@pytest.mark.parametrize(
    "body",
    [
        # Reading a relative file is what a strategy legitimately does.
        "        fh = Path('data.csv').open()\n        return []",
        "        fh = Path('data.csv').open('r')\n        return []",
        "        return [] if Path('data.csv').exists() else []",
    ],
    ids=["open_no_mode", "open_read_mode", "exists"],
)
def test_pathlib_write_guard_leaves_reads_alone(tmp_path, body) -> None:
    """The write guard must not cost a strategy its read path."""
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
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

    _load_module_from_file(signal_file, _module_name())


# The object graph is the last structural route to a module the import checks
# refuse: it reaches every loaded class without naming one. Both were measured
# ACCEPTED before _FORBIDDEN_DUNDER_ATTRS existed.
_OBJECT_GRAPH_REACH = [
    ("mro_subclasses", "        return ().__class__.__mro__[1].__subclasses__()"),
    ("globals_builtins", "        return (lambda: 0).__globals__['__builtins__']"),
    ("class_base", "        return data_map.__class__.__base__"),
    ("reduce", "        return data_map.__reduce__()"),
    ("code_object", "        return (lambda: 0).__code__"),
]


@pytest.mark.parametrize("case_id,body", _OBJECT_GRAPH_REACH, ids=[c[0] for c in _OBJECT_GRAPH_REACH])
def test_signal_engine_rejects_object_graph_traversal(tmp_path, case_id, body) -> None:
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Generated signal engine."""',
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                body,
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not allowed inside generated strategy code"):
        _load_module_from_file(signal_file, _module_name())


_OS_FILESYSTEM_MUTATION = [
    ("remove", "        os.remove('x')\n        return []"),
    ("unlink", "        os.unlink('x')\n        return []"),
    ("rename", "        os.rename('a', 'b')\n        return []"),
    ("chmod", "        os.chmod('a', 511)\n        return []"),
]


@pytest.mark.parametrize(
    "case_id,body", _OS_FILESYSTEM_MUTATION, ids=[c[0] for c in _OS_FILESYSTEM_MUTATION]
)
def test_signal_engine_rejects_os_filesystem_mutation(tmp_path, case_id, body) -> None:
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Generated signal engine."""',
                "import os",
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                body,
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not allowed inside generated strategy code"):
        _load_module_from_file(signal_file, _module_name())


@pytest.mark.parametrize(
    "body",
    [
        # Ordinary strategy code must survive all of the guards above.
        "        return data_map['X'].close.rolling(20).mean()",
        "        return data_map['X'].open.iloc[-1] + data_map['X'].high.max()",
        "        return os.path.join('a', 'b')",
        "        return self.lookback if hasattr(self, 'lookback') else 20",
    ],
    ids=["rolling_mean", "ohlc_columns", "os_path_join", "self_attr"],
)
def test_hardening_leaves_ordinary_strategy_code_alone(tmp_path, body) -> None:
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Generated signal engine."""',
                "import os",
                "import pandas as pd",
                "class SignalEngine:",
                "    lookback = 20",
                "    def generate(self, *args, **kwargs):",
                body,
            ]
        ),
        encoding="utf-8",
    )

    _load_module_from_file(signal_file, _module_name())


def test_signal_engine_rejects_forbidden_op_in_transitively_called_helper(tmp_path) -> None:
    # Payload hidden in a module-level helper that generate() calls — the
    # reachability walk must follow the call and reject it.
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Generated signal engine."""',
                "def _exfiltrate():",
                "    import socket",
                "    return socket.socket()",
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                "        return _exfiltrate()",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not allowed inside generated strategy code"):
        _load_module_from_file(signal_file, _module_name())


def test_signal_engine_allows_realistic_pandas_strategy(tmp_path) -> None:
    # A representative generated strategy: numpy/pandas math, a for-loop, an if,
    # a module-level pure helper called from generate(), and a private method.
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Momentum strategy."""',
                "from typing import Dict",
                "import numpy as np",
                "import pandas as pd",
                "",
                "def _zscore(s: pd.Series) -> pd.Series:",
                "    return (s - s.rolling(20).mean()) / s.rolling(20).std()",
                "",
                "class SignalEngine:",
                "    def __init__(self, lookback: int = 20):",
                "        self.lookback = lookback",
                "    def generate(self, data_map: Dict[str, pd.DataFrame]):",
                "        out = {}",
                "        for code, df in data_map.items():",
                "            z = _zscore(df['close'])",
                "            sig = pd.Series(0.0, index=df.index)",
                "            if len(df) > self.lookback:",
                "                sig = np.sign(z).fillna(0.0)",
                "            out[code] = self._clip(sig)",
                "        return out",
                "    def _clip(self, s):",
                "        return s.clip(-1, 1)",
            ]
        ),
        encoding="utf-8",
    )

    module = _load_module_from_file(signal_file, _module_name())
    assert hasattr(module, "SignalEngine")


@pytest.mark.parametrize(
    "expr",
    [
        "getattr(os, 'system')('id')",
        "getattr(os, 'sys' + 'tem')('id')",  # computed attr name; target-keyed check still catches it
        "getattr(os, 'popen')('id')",
        "setattr(os, 'x', 1)",
    ],
    ids=["getattr_system", "getattr_computed", "getattr_popen", "setattr_os"],
)
def test_signal_engine_rejects_getattr_indirection_onto_os(tmp_path, expr) -> None:
    # GHSA-jqmf F8 residual: `import os` is allowed and the attribute scanner
    # never sees ".system", so getattr(os, "system")("id") previously slipped
    # through. The target-keyed getattr/setattr/delattr guard must reject it.
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""x."""',
                "import os",
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                f"        return {expr}",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not allowed inside generated strategy code"):
        _load_module_from_file(signal_file, _module_name())


def test_signal_engine_allows_getattr_on_user_objects(tmp_path) -> None:
    # Dynamic attribute access on ordinary user objects (self, a DataFrame, an
    # indicator object) is legitimate and common — the bundled harmonic example
    # uses getattr(tech, name, None) — so the F8 guard must NOT reject it.
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Strategy using dynamic attribute access on user objects."""',
                "from typing import Dict",
                "import pandas as pd",
                "class SignalEngine:",
                "    def __init__(self, lookback: int = 20):",
                "        self.lookback = lookback",
                "    def generate(self, data_map: Dict[str, pd.DataFrame]):",
                "        out = {}",
                "        window = getattr(self, 'lookback', 20)",
                "        for code, df in data_map.items():",
                "            close = getattr(df, 'close', None)",
                "            out[code] = close.rolling(window).mean() if close is not None else df",
                "        return out",
            ]
        ),
        encoding="utf-8",
    )

    module = _load_module_from_file(signal_file, _module_name())
    assert hasattr(module, "SignalEngine")


def test_signal_engine_allows_unreachable_network_helper(tmp_path) -> None:
    # Mirrors the bundled skill examples: a top-level ``import requests`` plus a
    # standalone ``_fetch_okx`` data-fetch helper that generate() never calls.
    # Because it is unreachable from any SignalEngine method it must NOT trip the
    # scrubber — blocking it would reject strategies generated from ~12 skills.
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Strategy with an unused standalone fetch helper."""',
                "from typing import Dict",
                "import pandas as pd",
                "import requests",
                "",
                "def _fetch_okx(inst_id):",
                "    resp = requests.get('https://www.okx.com/api/v5/market/candles')",
                "    return resp.json()",
                "",
                "class SignalEngine:",
                "    def generate(self, data_map: Dict[str, pd.DataFrame]):",
                "        return {c: df['close'] * 0.0 for c, df in data_map.items()}",
            ]
        ),
        encoding="utf-8",
    )

    module = _load_module_from_file(signal_file, _module_name())
    assert hasattr(module, "SignalEngine")


def test_signal_engine_allows_signed_numeric_literal_assignment(tmp_path) -> None:
    # A negative threshold (e.g. a mined ``prior_5d_return`` bound) parses as
    # ``UnaryOp(USub, Constant)`` rather than a bare ``Constant``. It is still a
    # compile-time constant that executes nothing at import, so it must be treated
    # as a safe literal assignment (issue #985 second rejection path).
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Strategy with signed numeric thresholds."""',
                "THRESHOLD = -0.08",
                "BOUNDS = [{'min': -0.08, 'max': 0.02}]",
                "class SignalEngine:",
                "    def generate(self, *args, **kwargs):",
                "        return []",
            ]
        ),
        encoding="utf-8",
    )

    module = _load_module_from_file(signal_file, _module_name())

    assert module.THRESHOLD == -0.08
    assert module.BOUNDS == [{"min": -0.08, "max": 0.02}]


@pytest.mark.parametrize(
    "decorator_line",
    ["    @staticmethod", "    @classmethod", "    @some_decorator"],
    ids=["staticmethod", "classmethod", "custom"],
)
def test_signal_engine_still_rejects_decorators(tmp_path, decorator_line) -> None:
    # The issue #985 fix removes decorators from the generated template instead of
    # loosening this validator, so every decorator must stay rejected.
    signal_file = tmp_path / "signal_engine.py"
    signal_file.write_text(
        "\n".join(
            [
                '"""Strategy with a decorated method."""',
                "class SignalEngine:",
                decorator_line,
                "    def helper(cls):",
                "        return []",
                "    def generate(self, *args, **kwargs):",
                "        return []",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Decorators are not allowed"):
        _load_module_from_file(signal_file, _module_name())
