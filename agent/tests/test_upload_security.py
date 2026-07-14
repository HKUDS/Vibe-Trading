"""Security regression tests for upload file type restrictions."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api_server, "UPLOADS_DIR", tmp_path)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


@pytest.mark.parametrize(
    "filename",
    [
        "payload.py",
        "run.sh",
        "config.yaml",
        "config.yml",
        "template.j2",
        "Dockerfile",
    ],
)
def test_upload_blocks_executable_adjacent_files(
    client: TestClient,
    tmp_path: Path,
    filename: str,
) -> None:
    response = client.post(
        "/upload",
        files={"file": (filename, b"content", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_upload_sanitizes_null_byte_in_reflected_filename(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """Null bytes / control chars must be stripped before the filename is echoed.

    httpx URL-encodes a raw ``\\x00`` in the multipart Content-Disposition, so we
    unit-test the sanitizer directly (that's what guards the reflection) and also
    assert the endpoint response never carries a raw control byte.
    """
    from src.api.uploads_routes import _sanitize_filename

    assert _sanitize_filename("evil\x00name.txt") == "evilname.txt"
    assert _sanitize_filename("a\x1fb\x7fc.txt") == "abc.txt"
    assert "\x00" not in _sanitize_filename("\x00\x00.txt")

    response = client.post(
        "/upload",
        files={"file": ("safe-name.txt", b"content", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["filename"] == "safe-name.txt"
    assert "\x00" not in response.text

