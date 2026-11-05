"""Whole-module strategy scanner (P0.3): bypass corpus and legitimate-code corpus.

Each bypass reached a forbidden capability (shell, env secrets, network,
module object graph, file I/O outside the run dir) past the old
reachable-code-only scanner. Payloads are only parsed, never executed.
"""

from __future__ import annotations

import uuid

import pytest

from backtest.runner import _load_module_from_file


def _load(tmp_path, source: str):
    path = tmp_path / "signal_engine.py"
    path.write_text('"""Generated signal engine."""\n' + source, encoding="utf-8")
    return _load_module_from_file(path, f"se_{uuid.uuid4().hex}")


_ENGINE = "class SignalEngine:\n    def generate(self, data_map):\n"

_BYPASSES = {
    # Reachability gaps
    "helper_class_method": (
        "import os\n"
        "class _H:\n    def go(self):\n        return os.system('id')\n"
        + _ENGINE + "        return _H().go()\n"
    ),
    "function_passed_by_reference": (
        "import os\n"
        "def _h(x):\n    return os.system('id')\n"
        + _ENGINE + "        return {k: v.apply(_h) for k, v in data_map.items()}\n"
    ),
    "function_alias_variable": (
        "import os\n"
        "def _h():\n    return os.system('id')\n"
        + _ENGINE + "        f = _h\n        return f()\n"
    ),
    "unused_toplevel_requests": "import requests\n" + _ENGINE + "        return {}\n",
    # os renamed or passed around
    "import_os_as": "import os as o\n" + _ENGINE + "        return o.system('id')\n",
    "os_assigned_to_variable": "import os\n" + _ENGINE + "        m = os\n        return m.system('id')\n",
    "os_passed_to_function": "import os\n" + _ENGINE + "        return getter(os)\n",
    # Modules reached through other objects
    "pandas_reexported_os": "import pandas as pd\n" + _ENGINE + "        return pd.io.common.os.environ\n",
    "os_sys_modules": "import os\n" + _ENGINE + "        return os.sys.modules\n",
    "os_dunder_dict": "import os\n" + _ENGINE + "        return os.__dict__['system']('id')\n",
    "operator_attrgetter": (
        "import os\nimport operator\n" + _ENGINE + "        return operator.attrgetter('system')(os)\n"
    ),
    "inspect_frames": "import inspect\n" + _ENGINE + "        return inspect.currentframe()\n",
    "generator_frame_globals": (
        _ENGINE + "        g = (x for x in ())\n        return g.gi_frame.f_back.f_globals\n"
    ),
    # Process control
    "os_execv": "import os\n" + _ENGINE + "        return os.execv('/bin/sh', ['sh'])\n",
    "os_posix_spawn": "import os\n" + _ENGINE + "        return os.posix_spawn('/bin/sh', ['sh'], {})\n",
    "os_kill": "import os\n" + _ENGINE + "        return os.kill(1, 9)\n",
    "asyncio_import": "import asyncio\n" + _ENGINE + "        return {}\n",
    # Data libraries fetching on their own
    "yfinance_import": "import yfinance as yf\n" + _ENGINE + "        return yf.download('AAPL')\n",
    "ccxt_import": "import ccxt\n" + _ENGINE + "        return {}\n",
    "pandas_url_read": (
        "import pandas as pd\n" + _ENGINE + "        return pd.read_csv('https://attacker.example/x.csv')\n"
    ),
    "pandas_absolute_read": "import pandas as pd\n" + _ENGINE + "        return pd.read_csv('/etc/passwd')\n",
    "pandas_variable_read": "import pandas as pd\n" + _ENGINE + "        p = 'x'\n        return pd.read_json(p)\n",
    "pandas_read_sql": "import pandas as pd\n" + _ENGINE + "        return pd.read_sql('select 1', None)\n",
    "numpy_absolute_load": "import numpy as np\n" + _ENGINE + "        return np.load('/tmp/x.npy')\n",
    "to_csv_with_path": _ENGINE + "        data_map['a'].to_csv('/tmp/x.csv')\n        return {}\n",
    "to_pickle_relative": _ENGINE + "        data_map['a'].to_pickle('x.pkl')\n        return {}\n",
    "numpy_save": "import numpy as np\n" + _ENGINE + "        np.save('x.npy', 1)\n        return {}\n",
    "open_url_literal": _ENGINE + "        return open('https://attacker.example')\n",
}


@pytest.mark.parametrize("source", list(_BYPASSES.values()), ids=list(_BYPASSES))
def test_bypass_is_rejected(tmp_path, source) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        _load(tmp_path, source)


_LEGITIMATE = {
    "relative_csv_read": "import pandas as pd\n" + _ENGINE + "        return pd.read_csv('data/prices.csv')\n",
    "to_json_returns_string": _ENGINE + "        return {k: v.to_json() for k, v in data_map.items()}\n",
    "to_csv_without_target": _ENGINE + "        s = data_map['a'].to_csv(index=False)\n        return {}\n",
    "os_path_join": "import os\n" + _ENGINE + "        return os.path.join('a', 'b')\n",
    "numpy_math": "import numpy as np\n" + _ENGINE + "        return np.where(np.zeros(3) > 0, 1, -1)\n",
    "clean_helper_class": (
        "class _Helper:\n    def score(self, df):\n        return df['close'].pct_change()\n"
        + _ENGINE + "        return {k: _Helper().score(v) for k, v in data_map.items()}\n"
    ),
    "lambda_apply": _ENGINE + "        return {k: v['close'].apply(lambda x: x * 2) for k, v in data_map.items()}\n",
    "signal_attribute_names": (
        _ENGINE + "        self.signal = 1\n        out = {}\n"
        "        for k, v in data_map.items():\n            out[k] = v.assign(signal=self.signal)['signal']\n"
        "        return out\n"
    ),
    "json_loads": "import json\n" + _ENGINE + "        return json.loads('{}')\n",
    "typing_and_math": "import math\nfrom typing import Dict\n" + _ENGINE + "        return {'x': math.sqrt(4)}\n",
}


@pytest.mark.parametrize("source", list(_LEGITIMATE.values()), ids=list(_LEGITIMATE))
def test_legitimate_strategy_code_still_loads(tmp_path, source) -> None:
    assert hasattr(_load(tmp_path, source), "SignalEngine")
