"""The repo-root .gitignore must cover every file the runtime writes at its root.

The owner's shell exports ``VIBE_TRADING_HOME`` as the checkout, so anything
``get_runtime_root()`` creates lands in the working tree. The .gitignore block
for those paths says it is kept "closed against the connector CONFIG_FILENAME
sites", but nothing checked that, and fourteen broker config files — API keys
and secrets among them — were missing from it. This test derives the set from
the code instead of from the list.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _AGENT_ROOT.parent
_FILENAME_CONSTANT = re.compile(r"(^|_)(CONFIG_FILENAME|DB_FILENAME)$")
# A tuple of candidate names, e.g. ``paths._DEFAULT_FILENAMES`` for agent.json
# and its YAML twins, which the single-name pattern above never saw.
_FILENAMES_CONSTANT = re.compile(r"(^|_)FILENAMES$")


def _runtime_root_filenames() -> dict[str, str]:
    """Map each root-level filename constant to the module that defines it."""
    found: dict[str, str] = {}
    for path in sorted((_AGENT_ROOT / "src").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "get_runtime_root()" not in source:
            continue
        for node in ast.parse(source).body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            module = str(path.relative_to(_REPO_ROOT))
            if (
                _FILENAME_CONSTANT.search(target.id)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                found[node.value.value] = module
            elif _FILENAMES_CONSTANT.search(target.id) and isinstance(
                node.value, (ast.Tuple, ast.List)
            ):
                for element in node.value.elts:
                    if isinstance(element, ast.Constant) and isinstance(
                        element.value, str
                    ):
                        found[element.value] = module
    return found


def _ignored_root_entries() -> set[str]:
    lines = (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip().startswith("/")}


def test_discovery_sees_the_broker_config_files() -> None:
    """Guard the guard: an empty scan would pass the coverage test vacuously."""
    names = _runtime_root_filenames()

    assert {"alpaca.json", "zerodha.json", "connections.json"} <= set(names)
    assert {"agent.json", "agent.yaml", "agent.yml"} <= set(names)
    assert len(names) >= 20


def test_every_runtime_root_file_is_gitignored() -> None:
    ignored = _ignored_root_entries()

    missing = {
        name: module
        for name, module in _runtime_root_filenames().items()
        if f"/{name}" not in ignored
    }

    assert not missing, (
        "runtime-root files not covered by .gitignore (add a '/<name>' line to "
        f"the runtime block): {missing}"
    )
