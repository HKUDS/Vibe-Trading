"""The Landlock backend: Linux's sandbox when bwrap cannot create namespaces (a Docker container).

The ruleset itself only exists on Linux; on such a host the node tests in
``test_swarm_shell_sandbox.py`` run through it for real. These tests pin what is granted, when the
backend is chosen, and that the launcher never starts a command it could not confine.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import src.tools.sandbox as sandbox
from src.tools.sandbox import LANDLOCK_EXEC, SandboxSettings, SandboxUnavailableError, landlock_grants


@pytest.fixture
def linux(monkeypatch):
    """A Linux host where bwrap cannot run (a container) and Landlock can."""
    monkeypatch.setattr(sandbox.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandbox, "_probe_backend", lambda backend, network: f"{backend} cannot run here (test)")
    monkeypatch.setattr(sandbox, "_probe_landlock", lambda network: None)


def _node(tmp_path: Path, **overrides) -> SandboxSettings:
    return SandboxSettings(runtime_root=tmp_path / "home", **{"swarm_mode": "auto", **overrides})


def test_grants_hide_only_the_hidden_paths_and_list_the_way_to_them(tmp_path):
    root = tmp_path / "home"
    (root / "auth").mkdir(parents=True)
    (root / "auth" / "token.json").write_text("{}")
    (root / "swarm" / "runs").mkdir(parents=True)
    (root / "sessions.db").write_text("")
    (tmp_path / "other").mkdir()
    (tmp_path / "to-auth").symlink_to(root / "auth")
    (tmp_path / "to-other").symlink_to(tmp_path / "other")

    read, listed = landlock_grants({root / "auth"}, top=tmp_path)

    assert str(root / "auth") not in read and str(root / "auth" / "token.json") not in read
    assert {str(root / "swarm"), str(root / "sessions.db"), str(tmp_path / "other")} <= set(read)
    assert listed == [str(tmp_path), str(root)], "only the way down to a hidden path is list-only"
    assert str(tmp_path / "to-auth") not in read, "a grant follows a symlink, so one into a hidden path is left out"
    assert str(tmp_path / "to-other") in read


def test_a_node_uses_landlock_when_bwrap_cannot_run(tmp_path, linux):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    node = _node(tmp_path).for_workspace(workspace)

    argv, profile = node.command_argv("echo hi", workspace)

    assert node.backend == "landlock" and profile is None
    assert argv[:3] == [sys.executable, "-I", str(LANDLOCK_EXEC)] and argv[-3:] == ["/bin/sh", "-c", "echo hi"]
    spec = json.loads(argv[3])
    assert str(workspace.resolve()) in spec["write"] and spec["net"] is False


def test_the_spec_hides_the_runtime_roots_credentials(tmp_path, linux):
    root = tmp_path / "home"
    (root / "auth").mkdir(parents=True)
    (root / "connections.json").write_text("{}")
    (root / "swarm").mkdir()

    spec = _node(tmp_path).landlock_spec(tmp_path / "ws")

    readable = set(spec["read"])
    assert str((root / "auth").resolve()) not in readable
    assert str((root / "connections.json").resolve()) not in readable
    assert str((root / "swarm").resolve()) in readable


def test_a_named_backend_is_never_swapped_for_landlock(tmp_path, linux):
    node = _node(tmp_path, backend="bwrap").for_workspace(tmp_path / "ws")

    assert not node.enabled and node.unconfined_fallback


def test_without_either_backend_auto_reports_both_reasons(tmp_path, linux, monkeypatch):
    monkeypatch.setattr(sandbox, "_probe_landlock", lambda network: "Landlock ABI 3 cannot refuse TCP (test)")

    node = _node(tmp_path).for_workspace(tmp_path / "ws")

    assert node.unconfined_fallback
    assert "bwrap cannot run here" in node.unavailable and "Landlock ABI 3" in node.unavailable


def test_the_main_sandbox_falls_back_to_landlock_on_linux(tmp_path, linux):
    assert SandboxSettings(runtime_root=tmp_path, enabled=True).resolved_backend() == "landlock"


def test_the_main_sandbox_refuses_when_neither_linux_backend_works(tmp_path, linux, monkeypatch):
    monkeypatch.setattr(sandbox, "_probe_landlock", lambda network: "Landlock is not available (test)")

    with pytest.raises(SandboxUnavailableError, match="bwrap cannot run here.*Landlock is not available"):
        SandboxSettings(runtime_root=tmp_path, enabled=True).resolved_backend()


@pytest.mark.skipif(sys.platform.startswith("linux"), reason="checks the refusal on a non-Linux kernel")
def test_the_launcher_refuses_off_linux_before_starting_anything(tmp_path):
    marker = tmp_path / "ran"
    spec = json.dumps({"write": [str(tmp_path)], "net": True})

    done = subprocess.run([sys.executable, "-I", str(LANDLOCK_EXEC), spec, "/bin/sh", "-c", f"touch {marker}"],
                          capture_output=True, text=True, timeout=30)

    assert done.returncode == 125 and "Linux-only" in done.stderr
    assert not marker.exists()


def test_bwrap_keeps_dev_and_tmp_writable_and_covers_credential_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")
    root = tmp_path / "home"
    (root / "auth").mkdir(parents=True)
    (root / "connections.json").write_text("{}")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    argv, _ = SandboxSettings(runtime_root=root, enabled=True, backend="bwrap").command_argv(":", workspace)

    pairs = list(zip(argv, argv[1:]))
    tmp = str(sandbox.SHARED_TMP.resolve())
    assert ("--dev", "/dev") in pairs and ("--bind", tmp) in pairs
    assert ("--tmpfs", str((root / "auth").resolve())) in pairs or ("--tmpfs", str(root / "auth")) in pairs
    covered = argv[argv.index("/dev/null", argv.index("--dev") + 2) + 1]
    assert Path(covered).name == "connections.json", "a credential file cannot take --tmpfs (bwrap aborts)"


def test_a_runtime_root_inside_tmp_keeps_tmp_ungranted(tmp_path, linux, monkeypatch):
    # Landlock cannot subtract the credentials from a /tmp grant, so /tmp is withheld instead.
    monkeypatch.setattr(sandbox, "SHARED_TMP", tmp_path)
    (tmp_path / "home" / "auth").mkdir(parents=True)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    spec = _node(tmp_path).landlock_spec(workspace)

    assert str(tmp_path.resolve()) not in spec["write"] and str(workspace.resolve()) in spec["write"]
    assert spec["env"] == {"TMPDIR": str(workspace.resolve() / ".tmp")}


def test_a_runtime_root_outside_tmp_shares_tmp(tmp_path, linux, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(sandbox, "SHARED_TMP", shared)

    spec = _node(tmp_path).landlock_spec(tmp_path)

    assert str(shared.resolve()) in spec["write"] and spec["env"] == {}
