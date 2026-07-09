from __future__ import annotations

import ast
import importlib
import logging
import socket
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
AGS_SOURCE_DIRS = (
    ROOT / "agent" / "src" / "alpha_foundry",
    ROOT / "agent" / "src" / "alpha_quality",
    ROOT / "agent" / "src" / "research_ledger",
)
FORBIDDEN_IMPORT_ROOTS = (
    "src.agent",
    "src.governance",
    "src.live",
    "src.providers",
    "src.session",
    "src.tools",
    "src.trading",
    "api_server",
    "backtest",
)
FORBIDDEN_RUNTIME_NAMES = (
    "AgentContext",
    "AgentLoop",
    "SessionService",
    "ToolRegistry",
    "broker",
    "kill_switch",
    "mandate",
    "order_gate",
)
IMPORT_SMOKE_MODULES = (
    "src.alpha_foundry.artifacts",
    "src.alpha_foundry.dsl.operators",
    "src.alpha_foundry.forward.model",
    "src.alpha_foundry.forward.store",
    "src.alpha_foundry.reports.builder",
    "src.alpha_quality.forward_returns",
    "src.alpha_quality.ic_metrics",
    "src.alpha_quality.scorecard",
    "src.research_ledger.data_snapshot",
    "src.research_ledger.trial_ledger",
)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for source_dir in AGS_SOURCE_DIRS:
        files.extend(sorted(source_dir.rglob("*.py")))
    return files


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_ags_modules_do_not_import_live_runtime_or_tool_registry() -> None:
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_modules(tree):
            if module.startswith(FORBIDDEN_IMPORT_ROOTS):
                offenders.append(f"{path.relative_to(ROOT)} imports {module}")
        source = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_RUNTIME_NAMES:
            if name in source:
                offenders.append(f"{path.relative_to(ROOT)} references {name}")

    assert offenders == []


def test_ags_imports_have_no_network_or_logging_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_socket(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("AGS import attempted to create a network socket")

    monkeypatch.setattr(socket, "socket", fail_socket)
    before_handlers = tuple(logging.getLogger().handlers)

    for module_name in IMPORT_SMOKE_MODULES:
        importlib.import_module(module_name)

    assert tuple(logging.getLogger().handlers) == before_handlers


def test_ags_modules_do_not_install_process_global_hooks() -> None:
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in {"basicConfig", "register"}:
                    receiver = ast.unparse(func.value)
                    if receiver in {"logging", "atexit"}:
                        offenders.append(f"{path.relative_to(ROOT)} calls {receiver}.{func.attr}")

    assert offenders == []
