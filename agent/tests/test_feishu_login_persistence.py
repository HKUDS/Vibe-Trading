from __future__ import annotations

import json
import os
import stat

from src.channels.feishu import _persist_login_credentials


def test_persist_login_credentials_preserves_config_and_writes_private_file(tmp_path):
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {"example": {"command": "example"}},
                "channels": {
                    "replyTimeoutS": 1800,
                    "feishu": {"group_policy": "mention"},
                },
            }
        ),
        encoding="utf-8",
    )

    saved = _persist_login_credentials(
        "cli_test_app",
        "test-secret",
        "feishu",
        config_path=config_path,
    )

    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload["mcpServers"]["example"]["command"] == "example"
    assert payload["channels"]["replyTimeoutS"] == 1800
    assert payload["channels"]["feishu"] == {
        "group_policy": "mention",
        "enabled": True,
        "app_id": "cli_test_app",
        "app_secret": "test-secret",
        "domain": "feishu",
    }
    if os.name == "posix":
        assert stat.S_IMODE(saved.stat().st_mode) == 0o600
