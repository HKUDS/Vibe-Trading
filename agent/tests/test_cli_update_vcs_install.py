"""A Git-installed build must not be replaced with a PyPI wheel on update."""

from __future__ import annotations

import json
from importlib.metadata import Distribution
from subprocess import CompletedProcess

import pytest

from cli.commands import update


@pytest.fixture
def install_metadata(tmp_path, monkeypatch):
    def install(direct_url: dict) -> None:
        metadata = tmp_path / "vibe_trading_ai-0.1.dist-info"
        metadata.mkdir(exist_ok=True)
        (metadata / "METADATA").write_text("Name: vibe-trading-ai\nVersion: 0.1\n")
        (metadata / "direct_url.json").write_text(json.dumps(direct_url))
        monkeypatch.setattr(update, "distribution", lambda _: Distribution.at(metadata))

    return install


def test_update_preserves_git_install_provenance(install_metadata, monkeypatch, capsys):
    install_metadata(
        {
            "url": "https://example.org/project.git",
            "vcs_info": {
                "vcs": "git",
                "commit_id": "a" * 40,
                "requested_revision": "feature",
            },
        }
    )
    monkeypatch.setattr(update, "fetch_latest_version", lambda: "99.0.0")
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return CompletedProcess(args[0], returncode=1)

    monkeypatch.setattr(update.subprocess, "run", fake_run)
    result = update.cmd_update()
    assert calls == []
    assert result == update.EXIT_OK
    output = capsys.readouterr().out
    assert "source" in output.lower()
    assert "original" in output.lower()


@pytest.mark.parametrize(
    "direct_url,kind",
    [
        (
            {"url": "https://example.org/package.whl", "archive_info": {}},
            update.KIND_WHEEL,
        ),
        (
            {"url": "file:///fixture", "dir_info": {"editable": True}},
            update.KIND_EDITABLE,
        ),
    ],
)
def test_existing_wheel_and_editable_detection(install_metadata, direct_url, kind):
    install_metadata(direct_url)
    assert update.detect_install_kind() == kind
