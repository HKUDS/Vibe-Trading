"""Security regression tests for run_dir-based file tools."""

from __future__ import annotations

from src.tools.path_utils import FileRoots
from src.config.accessor import get_env_config


import json
from pathlib import Path
import pytest

from src.tools.backtest_tool import run_backtest
from src.tools.edit_file_tool import EditFileTool
from src.tools.read_file_tool import ReadFileTool
from src.tools.write_file_tool import WriteFileTool
from src.tools.path_utils import allowed_write_roots, resolve_safe_path


def _body(raw: str) -> dict:
    """Parse a JSON tool response."""
    return json.loads(raw)


def test_write_file_accepts_model_argument_aliases(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))

    body = _body(
        WriteFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(
            file_path="handoff.md",
            text="verified alias content",
            run_dir=str(tmp_path),
        )
    )

    assert body["status"] == "ok"
    assert (tmp_path / "handoff.md").read_text(encoding="utf-8") == "verified alias content"


def test_write_file_returns_recoverable_errors_for_missing_arguments() -> None:
    missing_path = _body(WriteFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(content="payload"))
    missing_content = _body(WriteFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path="handoff.md"))

    assert missing_path["status"] == "error"
    assert "missing required argument 'path'" in missing_path["error"]
    assert missing_content["status"] == "error"
    assert "missing required argument 'content'" in missing_content["error"]


def test_write_file_rejects_unconfigured_absolute_run_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", raising=False)

    body = _body(WriteFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(
        path="code/signal_engine.py",
        content="print('nope')",
        run_dir=str(tmp_path),
    ))

    assert body["status"] == "error"
    assert "outside allowed run roots" in body["error"]
    assert not (tmp_path / "code" / "signal_engine.py").exists()


def test_read_and_edit_file_accept_configured_run_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    target = tmp_path / "run" / "notes.md"
    target.parent.mkdir(parents=True)
    target.write_text("alpha beta", encoding="utf-8")

    read_body = _body(ReadFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path="notes.md", run_dir=str(target.parent)))
    edit_body = _body(EditFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(
        path="notes.md",
        old_text="beta",
        new_text="gamma",
        run_dir=str(target.parent),
    ))

    assert read_body["status"] == "ok"
    assert "alpha beta" in read_body["content"]
    assert edit_body["status"] == "ok"
    assert target.read_text(encoding="utf-8") == "alpha gamma"


def test_read_file_skill_prefix_is_not_shadowed_by_run_dir(
    tmp_path: Path, monkeypatch
) -> None:
    """`skills/` binds to the bundled skills root, never to a run_dir decoy."""
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    decoy = tmp_path / "skills" / "data-routing" / "SKILL.md"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("DECOY CONTENT", encoding="utf-8")

    body = _body(
        ReadFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path="skills/data-routing/SKILL.md", run_dir=str(tmp_path))
    )

    assert body["status"] == "ok"
    assert "DECOY CONTENT" not in body["content"]
    assert "data-routing" in body["content"]


def test_read_file_skill_prefix_cannot_escape_skills_root() -> None:
    """Traversal out of the skills namespace must be rejected, not redirected.

    Binding the prefix to one root would be worthless if `skills/../x` walked
    back out of it.
    """
    body = _body(ReadFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path="skills/../agent.json"))

    assert body["status"] == "error"


def test_backtest_rejects_unconfigured_absolute_run_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", raising=False)
    (tmp_path / "code").mkdir()
    (tmp_path / "config.json").write_text('{"source":"auto","codes":["AAPL"]}', encoding="utf-8")
    (tmp_path / "code" / "signal_engine.py").write_text(
        "class SignalEngine:\n    def generate(self, data_map):\n        return {}\n",
        encoding="utf-8",
    )

    body = _body(run_backtest(str(tmp_path), roots=FileRoots.from_config(get_env_config().api)))

    assert body["status"] == "error"
    assert "outside allowed run roots" in body["error"]


def test_tilde_expansion_resolves_to_mock_home(tmp_path: Path, monkeypatch) -> None:
    # Mock user home directory
    mock_home = tmp_path / "home_user"
    mock_home.mkdir()
    monkeypatch.setenv("HOME", str(mock_home))
    monkeypatch.setenv("USERPROFILE", str(mock_home))

    # Configure mock home as allowed write root
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(mock_home / ".vibe-trading"))
    allowed_write = allowed_write_roots(roots=FileRoots.from_config(get_env_config().api))
    assert any(p.is_relative_to(mock_home) for p in allowed_write)

    # Resolve safe path using tilde
    resolved = resolve_safe_path("~/.vibe-trading/scripts/strat.py", None, allowed_write, purpose="write", roots=FileRoots.from_config(get_env_config().api))
    assert resolved == mock_home / ".vibe-trading" / "scripts" / "strat.py"


def test_read_write_separation_prevent_cross_escalation(tmp_path: Path, monkeypatch) -> None:
    read_only_dir = tmp_path / "read_only"
    write_only_dir = tmp_path / "write_only"
    read_only_dir.mkdir()
    write_only_dir.mkdir()

    # Configure separate environment variables
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(read_only_dir))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(write_only_dir))

    # Setup read-only file
    ro_file = read_only_dir / "conf.json"
    ro_file.write_text('{"key": "val"}', encoding="utf-8")

    # 1. Read should succeed on read-only root
    read_res = _body(ReadFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path=str(ro_file)))
    assert read_res["status"] == "ok"
    assert "val" in read_res["content"]

    # 2. Write/Edit should FAIL on read-only root (write isolation)
    write_res = _body(WriteFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path=str(ro_file), content="poison"))
    assert write_res["status"] == "error"
    assert "run_dir is required" in write_res["error"] or "escapes" in write_res["error"]
    assert ro_file.read_text(encoding="utf-8") == '{"key": "val"}' # Intact

    # 3. Write should succeed on write-only root
    wo_file = write_only_dir / "output.txt"
    write_ok = _body(WriteFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path=str(wo_file), content="success_write"))
    assert write_ok["status"] == "ok"
    assert wo_file.read_text(encoding="utf-8") == "success_write"


def test_resolve_safe_path_run_dir_escapes_fallback(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "runs" / "run_1"
    run_dir.mkdir(parents=True)
    extra_write_dir = tmp_path / "extra_write"
    extra_write_dir.mkdir()

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(extra_write_dir))

    # 1. Inside run_dir -> resolves to run_dir
    resolved_1 = resolve_safe_path("script.py", str(run_dir), allowed_write_roots(roots=FileRoots.from_config(get_env_config().api)), purpose="write", roots=FileRoots.from_config(get_env_config().api))
    assert resolved_1 == run_dir / "script.py"

    # 2. Escapes run_dir but inside extra_write -> resolves to extra_write (fallback)
    resolved_2 = resolve_safe_path(str(extra_write_dir / "tool.py"), str(run_dir), allowed_write_roots(roots=FileRoots.from_config(get_env_config().api)), purpose="write", roots=FileRoots.from_config(get_env_config().api))
    assert resolved_2 == extra_write_dir / "tool.py"

    # 3. Escapes run_dir and not in extra_write -> raises ValueError
    with pytest.raises(ValueError) as excinfo:
        resolve_safe_path("/etc/passwd", str(run_dir), allowed_write_roots(roots=FileRoots.from_config(get_env_config().api)), purpose="write", roots=FileRoots.from_config(get_env_config().api))
    assert "escapes run_dir" in str(excinfo.value)


def test_confined_write_roots_only_narrow_and_leave_the_parent_policy_intact(tmp_path: Path, monkeypatch) -> None:
    from dataclasses import replace

    runs = tmp_path / "runs"
    parent = runs / "parent"
    child = parent / "subagents" / "child"
    child.mkdir(parents=True)
    extra_write_dir = tmp_path / "extra_write"
    extra_write_dir.mkdir()
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(runs))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", f"{extra_write_dir},{runs}")

    parent_roots = FileRoots.from_config(get_env_config().api)
    child_roots = replace(parent_roots, confined_writes=child.resolve())
    allowed_child_roots = allowed_write_roots(roots=child_roots)
    assert allowed_child_roots == [child.resolve()]
    assert resolve_safe_path(
        "notes.md", str(child), allowed_child_roots, purpose="write", roots=child_roots,
    ) == child / "notes.md"
    for escape in ("../../req.json", str(parent / "req.json"), str(extra_write_dir / "tool.py")):
        with pytest.raises(ValueError) as excinfo:
            resolve_safe_path(escape, str(child), allowed_child_roots, purpose="write", roots=child_roots)
        assert "VIBE_TRADING_ALLOWED_WRITE_ROOTS" not in str(excinfo.value)

    allowed_parent_roots = allowed_write_roots(roots=parent_roots)
    assert extra_write_dir.resolve() in allowed_parent_roots
    assert resolve_safe_path(
        "../../req.json", str(child), allowed_parent_roots, purpose="write", roots=parent_roots,
    ) == parent / "req.json"


def test_write_rejection_names_the_write_roots_env(tmp_path: Path, monkeypatch) -> None:
    # The escape hatch must be discoverable from the error itself: a model
    # told only "escapes the workspace" cannot tell the user how to allow
    # ~/Documents (#1677).
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))

    body = _body(WriteFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path="/etc/poison.txt", content="x"))

    assert body["status"] == "error"
    assert "VIBE_TRADING_ALLOWED_WRITE_ROOTS" in body["error"]


def test_write_rejection_inside_run_dir_fallback_also_names_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_WRITE_ROOTS", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))
    run_dir = tmp_path / "runs" / "run_1"
    run_dir.mkdir(parents=True)

    body = _body(
        WriteFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path="/etc/poison.txt", content="x", run_dir=str(run_dir))
    )

    assert body["status"] == "error"
    assert "escapes run_dir" in body["error"]
    assert "VIBE_TRADING_ALLOWED_WRITE_ROOTS" in body["error"]


def test_read_purpose_rejection_names_the_file_roots_env(tmp_path: Path, monkeypatch) -> None:
    # purpose="file" is the read side (image_vision); it must point at the
    # read widening knob, not the write one.
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path / "elsewhere"))

    with pytest.raises(ValueError) as excinfo:
        resolve_safe_path("/etc/passwd", None, allowed_write_roots(roots=FileRoots.from_config(get_env_config().api)), purpose="file", roots=FileRoots.from_config(get_env_config().api))

    assert "VIBE_TRADING_ALLOWED_FILE_ROOTS" in str(excinfo.value)
    assert "VIBE_TRADING_ALLOWED_WRITE_ROOTS" not in str(excinfo.value)


@pytest.mark.parametrize("allowed_run", [True, False])
def test_relative_fallback_uses_run_dir_not_cwd(tmp_path, monkeypatch, allowed_run):
    run_dir = tmp_path / "runs" / "one"
    run_dir.mkdir(parents=True)
    allowed = tmp_path / "allowed"
    cwd = allowed / "nested" / "cwd"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(run_dir if allowed_run else tmp_path / "other"))
    with pytest.raises(ValueError):
        resolve_safe_path("../../outside.txt", str(run_dir), [allowed], roots=FileRoots.from_config(get_env_config().api))
    # An explicitly allowed sibling remains reachable through the same base.
    assert resolve_safe_path("../../allowed/ok.txt", str(run_dir), [allowed], roots=FileRoots.from_config(get_env_config().api)) == allowed / "ok.txt"


@pytest.mark.parametrize("run_dir", ["//server/share", r"\\server\share"])
def test_unc_run_dir_is_rejected_before_any_resolution(run_dir, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("UNC rejection must precede filesystem resolution")

    monkeypatch.setattr(Path, "resolve", forbidden)
    with pytest.raises(ValueError, match="UNC"):
        resolve_safe_path("result.txt", run_dir, [], roots=FileRoots.from_config(get_env_config().api))


def test_relative_fallback_cannot_escape_through_symlink(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / "one"
    run_dir.mkdir(parents=True)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (allowed / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(run_dir))
    with pytest.raises(ValueError):
        resolve_safe_path("../../allowed/link/out.txt", str(run_dir), [allowed], roots=FileRoots.from_config(get_env_config().api))
