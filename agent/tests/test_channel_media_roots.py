"""Inbound IM media must be saved where the agent's read tools can open it (#465)."""

from __future__ import annotations

from pathlib import Path


def test_media_dir_lives_under_uploads_root(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path), raising=False)

    from src.channels.utils import get_media_dir

    media = get_media_dir("napcat")
    assert media == tmp_path / ".vibe-trading" / "uploads" / "napcat"
    assert media.is_dir()


def test_media_dir_is_within_allowed_file_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path), raising=False)

    from src.channels.utils import get_media_dir
    from src.tools.path_utils import allowed_file_roots

    media = get_media_dir("weixin").resolve()
    assert any(root == media or root in media.parents for root in allowed_file_roots()), (
        f"{media} is not readable under any allowed file root"
    )
