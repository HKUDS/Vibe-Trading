"""The console CLI must use its own src package in shared editable environments."""

import os
from pathlib import Path
import subprocess
import sys


def test_cli_prefers_its_sibling_src_over_another_editable_project(tmp_path):
    conflicting = tmp_path / "another-project"
    (conflicting / "src").mkdir(parents=True)
    (conflicting / "src/__init__.py").write_text("raise RuntimeError('wrong project src imported')\n")
    home = tmp_path / "home"
    (home / ".vibe-trading").mkdir(parents=True)
    (home / ".vibe-trading/.env").write_text("")
    env = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        VIBE_TRADING_HOME=str(home / ".vibe-trading"),
        PYTHONPATH=str(conflicting),
    )
    script = "import cli; import src.config.accessor as own; print(own.__file__)"
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == (Path(__file__).parents[1] / "src/config/accessor.py").resolve()
