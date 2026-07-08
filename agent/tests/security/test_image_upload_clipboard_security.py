from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.channels import weixin
from src.channels.websocket import _IMAGE_MIME_ALLOWED, _extract_data_url_mime


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api_server, "UPLOADS_DIR", tmp_path)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_upload_blocks_svg_active_content(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/upload",
        files={"file": ("evil.svg", b'<svg><script>alert(1)</script></svg>', "image/svg+xml")},
    )

    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_upload_still_allows_safe_png(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/upload",
        files={"file": ("chart.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["file_path"].startswith("uploads/")
    assert len(list(tmp_path.iterdir())) == 1


def test_clipboard_data_url_svg_is_not_an_allowed_websocket_image() -> None:
    mime = _extract_data_url_mime("data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=")

    assert mime == "image/svg+xml"
    assert mime not in _IMAGE_MIME_ALLOWED


def test_weixin_outbound_media_does_not_classify_svg_as_image() -> None:
    assert ".svg" not in weixin._IMAGE_EXTS
