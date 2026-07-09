from __future__ import annotations

import json

import pytest

from src.alpha_foundry.artifacts import (
    PathTraversalError,
    safe_artifact_path,
    safe_artifact_write_json,
)


@pytest.mark.parametrize(
    "requested",
    [
        "../../.env",
        "../../../etc/passwd",
        "..\\..\\windows\\system32",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        ".././.././.env",
        "../../.env\x00.json",
        "\u2025/etc/passwd",
        "\u2026/etc/passwd",
    ],
)
def test_safe_artifact_path_blocks_traversal(tmp_path, requested: str) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()

    with pytest.raises(PathTraversalError):
        safe_artifact_path(root, requested)


def test_safe_artifact_write_json_rejects_symlink_escape(tmp_path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = root / "link.json"
    link.symlink_to(outside)

    with pytest.raises(PathTraversalError):
        safe_artifact_write_json(root, "link.json", {"schema_version": "x"})


def test_safe_artifact_write_json_is_strict_and_atomic(tmp_path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()

    path = safe_artifact_write_json(root, "report.json", {"schema_version": "x", "value": 1.0})

    assert path == root / "report.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"schema_version": "x", "value": 1.0}
    assert not list(root.glob("*.tmp"))
