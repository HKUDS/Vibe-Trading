"""Importing the backtest runner must not touch the process environment.

``load_dotenv()`` used to run at import scope. pytest imports test modules
during *collection*, which happens before any per-test ``os.environ`` snapshot
exists, so a developer's own ``LANGCHAIN_MODEL_NAME`` entered the environment
and no fixture could undo it — seven redaction tests failed on a machine with
an ``agent/.env`` while CI, which checks one out, stayed green.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]

_PROBE = (
    "import json, os\n"
    "before = dict(os.environ)\n"
    "import backtest.runner\n"
    "print(json.dumps({k: os.environ[k] for k in set(os.environ) - set(before)}))\n"
)


def test_importing_the_runner_adds_no_environment_variables(tmp_path: Path) -> None:
    """A `.env` beside the working directory must stay unread on import."""
    (tmp_path / ".env").write_text(
        "VIBE_TRADING_IMPORT_PROBE=leaked\nLANGCHAIN_MODEL_NAME=leaked-model\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    # The suite sandboxes HOME, which also hides the user site-packages this
    # interpreter's numpy lives in. Hand the child exactly what the parent can
    # already import rather than making it rediscover any of it.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(AGENT_DIR), str(AGENT_DIR / "src"), *(p for p in sys.path if p)]
    )
    env.pop("VIBE_TRADING_IMPORT_PROBE", None)

    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    added = json.loads(result.stdout.strip().splitlines()[-1])
    assert added == {}, f"importing backtest.runner set {sorted(added)}"
