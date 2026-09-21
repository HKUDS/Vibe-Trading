from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path

import pytest

from src.config.writer import ConfigNotWritableError, update_channel_section


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_update_channel_section_preserves_unrelated_and_sibling_keys(tmp_path):
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {"example": {"command": "example"}},
                "customTopLevel": {"keep": [1, 2, 3]},
                "channels": {
                    "replyTimeoutS": 1800,
                    "feishu": {"group_policy": "mention"},
                    "telegram": {"enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )

    saved = update_channel_section(
        "feishu",
        {"enabled": True, "app_id": "cli_app"},
        config_path=config_path,
    )

    assert saved == config_path
    payload = _read(saved)
    assert payload["mcpServers"]["example"]["command"] == "example"
    assert payload["customTopLevel"] == {"keep": [1, 2, 3]}
    assert payload["channels"]["replyTimeoutS"] == 1800
    assert payload["channels"]["telegram"] == {"enabled": False}
    assert payload["channels"]["feishu"] == {
        "group_policy": "mention",
        "enabled": True,
        "app_id": "cli_app",
    }


def test_update_channel_section_creates_file_and_parent_dirs(tmp_path):
    config_path = tmp_path / "nested" / "deep" / "agent.json"
    assert not config_path.exists()

    saved = update_channel_section("slack", {"enabled": True}, config_path=config_path)

    assert saved == config_path
    assert config_path.exists()
    assert _read(saved)["channels"]["slack"] == {"enabled": True}


def test_update_channel_section_rejects_non_json_config(tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text("channels: {}\n", encoding="utf-8")

    with pytest.raises(ConfigNotWritableError):
        update_channel_section("feishu", {"enabled": True}, config_path=config_path)

    missing = tmp_path / "agent.yml"
    with pytest.raises(ConfigNotWritableError):
        update_channel_section("feishu", {"enabled": True}, config_path=missing)


def test_update_channel_section_clears_listed_keys(tmp_path):
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        json.dumps(
            {
                "channels": {
                    "feishu": {
                        "app_secret": "old-secret",
                        "app_id": "old-app",
                        "enabled": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    update_channel_section(
        "feishu",
        {"enabled": True},
        clears=("app_secret", "not_present"),
        config_path=config_path,
    )

    section = _read(config_path)["channels"]["feishu"]
    assert "app_secret" not in section
    assert "not_present" not in section
    assert section["app_id"] == "old-app"
    assert section["enabled"] is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX file-mode semantics")
def test_update_channel_section_writes_owner_only_file(tmp_path):
    config_path = tmp_path / "agent.json"

    update_channel_section("feishu", {"enabled": True}, config_path=config_path)

    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_update_channel_section_sequential_writes_accumulate(tmp_path):
    config_path = tmp_path / "agent.json"

    update_channel_section(
        "feishu", {"enabled": True, "app_id": "cli_app"}, config_path=config_path
    )
    update_channel_section(
        "telegram", {"enabled": True, "token": "t"}, config_path=config_path
    )

    payload = _read(config_path)
    assert payload["channels"]["feishu"] == {"enabled": True, "app_id": "cli_app"}
    assert payload["channels"]["telegram"] == {"enabled": True, "token": "t"}


def test_concurrent_writes_to_different_channels_both_survive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two threads patching different channels at once must not lose a patch.

    The barrier forces both readers to overlap when the write lock is absent;
    with the lock, the first reader times out at the barrier and the second runs
    after the first write, so both sections land.
    """
    config_path = tmp_path / "agent.json"
    config_path.write_text(json.dumps({"channels": {}}), encoding="utf-8")

    import src.config.writer as writer

    real_read = writer._read_config_file
    barrier = threading.Barrier(2, timeout=1.0)

    def synchronized_read(path: Path) -> dict:
        payload = real_read(path)
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            # Expected when the write lock serialized the two readers.
            pass
        return payload

    monkeypatch.setattr(writer, "_read_config_file", synchronized_read)

    def patch_channel(channel: str) -> None:
        update_channel_section(
            channel, {"token": f"{channel}-token"}, config_path=config_path
        )

    threads = [
        threading.Thread(target=patch_channel, args=("feishu",)),
        threading.Thread(target=patch_channel, args=("telegram",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    payload = _read(config_path)
    assert payload["channels"]["feishu"] == {"token": "feishu-token"}
    assert payload["channels"]["telegram"] == {"token": "telegram-token"}
