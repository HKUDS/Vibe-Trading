"""Regression tests for /upload streaming + size enforcement.

Pinned by PR #53 (fix: stream uploads while enforcing API size limit). The previous
implementation read the entire file into memory before checking MAX_UPLOAD_SIZE, so
oversized payloads could exhaust server memory before being rejected. These tests
shrink the limit so they exercise the streaming/cleanup paths without allocating 50 MB.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api_server, "UPLOADS_DIR", tmp_path)
    monkeypatch.setattr(api_server, "MAX_UPLOAD_SIZE", 4 * 1024)  # 4 KB
    monkeypatch.setattr(api_server, "_UPLOAD_CHUNK_SIZE", 1024)  # 1 KB
    return TestClient(api_server.app)


def _existing_uploads(uploads_dir: Path) -> list[Path]:
    return [p for p in uploads_dir.iterdir() if p.is_file()]


def test_upload_under_limit_succeeds(client: TestClient, tmp_path: Path) -> None:
    payload = b"x" * (2 * 1024)  # 2 KB, well under the 4 KB limit
    response = client.post(
        "/upload",
        files={"file": ("note.txt", payload, "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["filename"] == "note.txt"

    saved = Path(body["file_path"])
    assert saved.exists()
    assert saved.read_bytes() == payload
    assert saved.parent == tmp_path.resolve()


def test_upload_exactly_at_limit_succeeds(client: TestClient) -> None:
    payload = b"y" * (4 * 1024)
    response = client.post(
        "/upload",
        files={"file": ("ok.txt", payload, "text/plain")},
    )
    assert response.status_code == 200


def test_upload_over_limit_returns_413_and_cleans_partial_file(
    client: TestClient, tmp_path: Path
) -> None:
    payload = b"z" * (4 * 1024 + 1)  # one byte over
    response = client.post(
        "/upload",
        files={"file": ("big.txt", payload, "text/plain")},
    )

    assert response.status_code == 413
    assert "limit" in response.json()["detail"].lower()
    # Streaming path must remove the partially-written file.
    assert _existing_uploads(tmp_path) == []


def test_upload_blocked_extension_returns_400(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/upload",
        files={"file": ("malware.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert _existing_uploads(tmp_path) == []


