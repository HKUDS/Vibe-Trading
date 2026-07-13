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
