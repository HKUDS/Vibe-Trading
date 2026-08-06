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
