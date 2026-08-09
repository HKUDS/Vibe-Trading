"""Browser-driven personal WeChat QR login contracts."""

from __future__ import annotations

import asyncio
import json

from src.channels.bus.queue import MessageBus
from src.channels.weixin import WeixinChannel


def test_qr_login_persists_token_without_returning_it(tmp_path, monkeypatch) -> None:
    channel = WeixinChannel(
        {"enabled": True, "state_dir": str(tmp_path)},
        MessageBus(),
    )

    async def fetch_qr_code():
        return "private-qrcode-id", "https://weixin.example/scan"

    async def get_status(**_kwargs):
        return {
            "status": "confirmed",
            "bot_token": "server-only-token",
            "baseurl": "https://weixin.example/api",
        }

    monkeypatch.setattr(channel, "_fetch_qr_code", fetch_qr_code)
    monkeypatch.setattr(channel, "_api_get_with_base", get_status)

    async def run_login():
        started = await channel.begin_qr_login()
        completed = await channel.poll_qr_login()
        return started, completed

    started, completed = asyncio.run(run_login())

    assert started == {"status": "waiting", "qr_content": "https://weixin.example/scan"}
    assert completed == {"status": "authenticated"}
    assert "token" not in json.dumps(started).lower()
    assert "token" not in json.dumps(completed).lower()
    assert json.loads((tmp_path / "account.json").read_text())["token"] == "server-only-token"


def test_expired_qr_login_refreshes_the_browser_challenge(tmp_path, monkeypatch) -> None:
    channel = WeixinChannel(
        {"enabled": True, "state_dir": str(tmp_path)},
        MessageBus(),
    )
    challenges = iter(
        [
            ("first-id", "https://weixin.example/first"),
            ("second-id", "https://weixin.example/second"),
        ]
    )

    async def fetch_qr_code():
        return next(challenges)

    async def get_status(**_kwargs):
        return {"status": "expired"}

    monkeypatch.setattr(channel, "_fetch_qr_code", fetch_qr_code)
    monkeypatch.setattr(channel, "_api_get_with_base", get_status)

    async def run_login():
        started = await channel.begin_qr_login()
        refreshed = await channel.poll_qr_login()
        await channel.cancel_qr_login()
        return started, refreshed

    started, refreshed = asyncio.run(run_login())

    assert started["qr_content"] == "https://weixin.example/first"
    assert refreshed == {"status": "waiting", "qr_content": "https://weixin.example/second"}
