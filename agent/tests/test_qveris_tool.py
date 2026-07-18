from __future__ import annotations

import json
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.tools import qveris_tool as qt


@pytest.fixture(autouse=True)
def qveris_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(qt, "QVERIS_CONFIG_PATH", tmp_path / "qveris.json")
    monkeypatch.delenv("QVERIS_API_KEY", raising=False)
    monkeypatch.delenv("QVERIS_BASE_URL", raising=False)
    qt._SESSION_SPEND.clear()
    getattr(qt, "_SESSION_RESERVED", {}).clear()
    return tmp_path / "qveris.json"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def test_config_read_write_masks_key_and_uses_0600(qveris_config_path: Path):
    saved = qt.save_qveris_config(
        qt.QVerisConfig(
            enabled=True,
            base_url="https://example.test/api",
            api_key="sk-test-8TI",
            mode="paid",
            budget_credits_per_session=12.5,
        )
    )

    assert saved.enabled is True
    assert qt.load_qveris_config().api_key == "sk-test-8TI"
    assert qt.mask_api_key("sk-test-8TI") == "sk-t…8TI"
    assert stat.S_IMODE(qveris_config_path.stat().st_mode) == 0o600


def test_env_overrides_file_config(monkeypatch: pytest.MonkeyPatch):
    qt.save_qveris_config(
        qt.QVerisConfig(enabled=True, base_url="https://file.test", api_key="file-key")
    )
    monkeypatch.setenv("QVERIS_API_KEY", "env-key")
    monkeypatch.setenv("QVERIS_BASE_URL", "https://env.test/api")

    cfg = qt.load_qveris_config()

    assert cfg.api_key == "env-key"
    assert cfg.base_url == "https://env.test/api"


def test_free_mode_tools_are_hidden():
    assert qt.QVerisSearchTool.check_available() is False

    qt.save_qveris_config(qt.QVerisConfig(enabled=True, api_key="sk-live", mode="free"))

    assert qt.QVerisSearchTool.check_available() is False

    qt.save_qveris_config(qt.QVerisConfig(enabled=True, api_key="sk-live", mode="paid"))

    assert qt.QVerisSearchTool.check_available() is True


def test_free_mode_execute_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    qt.save_qveris_config(
        qt.QVerisConfig(enabled=True, api_key="sk-live", mode="free")
    )

    class FakeClient:
        def inspect(self, tool_ids, **kwargs):
            return {
                "results": [
                    {
                        "tool_id": tool_ids[0],
                        "expected_cost": "2 credits",
                        "billing_rule": {"kind": "call"},
                    }
                ]
            }

    monkeypatch.setattr(qt.QVerisExecuteTool, "_client", lambda self: FakeClient())

    payload = json.loads(
        qt.QVerisExecuteTool().execute(tool_id="tool_1", parameters={"x": 1})
    )

    assert payload == {"ok": False, "error": "QVeris is not configured"}


def test_paid_mode_rejects_when_expected_cost_exceeds_budget(monkeypatch):
    qt.save_qveris_config(
        qt.QVerisConfig(
            enabled=True,
            api_key="sk-live",
            mode="paid",
            budget_credits_per_session=1.0,
        )
    )

    class FakeClient:
        def execute(self, *args, **kwargs):  # pragma: no cover - must not call
            raise AssertionError("execute should be blocked by budget")

    monkeypatch.setattr(qt.QVerisExecuteTool, "_client", lambda self: FakeClient())

    payload = json.loads(
        qt.QVerisExecuteTool().execute(
            tool_id="tool_1",
            parameters={},
            session_id="s1",
            expected_cost="2 credits",
        )
    )

    assert payload["status"] == "budget_exceeded"
    assert payload["budget_credits_per_session"] == 1.0


def test_parallel_execute_reserves_shared_session_budget(monkeypatch):
    qt.save_qveris_config(
        qt.QVerisConfig(
            enabled=True,
            api_key="sk-live",
            mode="paid",
            budget_credits_per_session=1.0,
        )
    )
    entered = threading.Event()
    release = threading.Event()

    class FakeClient:
        calls = 0
        lock = threading.Lock()

        def execute(self, *args, **kwargs):
            del args, kwargs
            with self.lock:
                type(self).calls += 1
                call_number = type(self).calls
            if call_number == 1:
                entered.set()
                assert release.wait(timeout=2)
            return {"success": True, "cost": 0.75, "result": {}}

    client = FakeClient()
    monkeypatch.setattr(qt.QVerisExecuteTool, "_client", lambda self: client)
    tool = qt.QVerisExecuteTool()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            tool.execute,
            tool_id="tool_1",
            parameters={},
            session_id="shared",
            expected_cost="0.75 credits",
        )
        assert entered.wait(timeout=2)
        second = pool.submit(
            tool.execute,
            tool_id="tool_2",
            parameters={},
            session_id="shared",
            expected_cost="0.75 credits",
        )
        second_payload = json.loads(second.result(timeout=2))
        release.set()
        first_payload = json.loads(first.result(timeout=2))

    assert first_payload["ok"] is True
    assert second_payload["status"] == "budget_exceeded"
    assert FakeClient.calls == 1
    assert qt._SESSION_SPEND["shared"] == pytest.approx(0.75)
    assert qt._SESSION_RESERVED.get("shared", 0.0) == 0.0


def test_failed_execute_releases_credit_reservation(monkeypatch):
    qt.save_qveris_config(
        qt.QVerisConfig(
            enabled=True,
            api_key="sk-live",
            mode="paid",
            budget_credits_per_session=1.0,
        )
    )

    class FailOnceClient:
        calls = 0

        def execute(self, *args, **kwargs):
            del args, kwargs
            type(self).calls += 1
            if type(self).calls == 1:
                raise RuntimeError("provider failed")
            return {"success": True, "cost": 1.0, "result": {}}

    client = FailOnceClient()
    monkeypatch.setattr(qt.QVerisExecuteTool, "_client", lambda self: client)
    tool = qt.QVerisExecuteTool()
    call = {
        "tool_id": "tool_1",
        "parameters": {},
        "session_id": "retry",
        "expected_cost": "1 credit",
    }

    with pytest.raises(RuntimeError, match="provider failed"):
        tool.execute(**call)

    assert qt._SESSION_RESERVED.get("retry", 0.0) == 0.0
    payload = json.loads(tool.execute(**call))
    assert payload["ok"] is True
    assert payload["session_spent_credits"] == pytest.approx(1.0)


def test_429_retries_after_retry_after(monkeypatch: pytest.MonkeyPatch):
    sleeps: list[float] = []
    monkeypatch.setattr(qt.time, "sleep", lambda value: sleeps.append(value))
    fake = FakeHttpClient(
        [
            FakeResponse(429, {"error": "rate"}, headers={"Retry-After": "0"}),
            FakeResponse(200, {"results": [], "remaining_credits": 9}),
        ]
    )
    client = qt.QVerisClient(
        qt.QVerisConfig(enabled=True, api_key="sk-live"),
        client=fake,
        min_interval_seconds=0,
    )

    payload = client.search("aapl", limit=1)

    assert payload["remaining_credits"] == 9
    assert len(fake.calls) == 2
    assert sleeps == [0.0]


def test_execute_hydrates_truncated_full_content():
    fake = FakeHttpClient(
        [
            FakeResponse(
                200,
                {
                    "success": True,
                    "cost": 1.0,
                    "result": {
                        "message": "too long",
                        "full_content_file_url": "https://oss.qveris.cn/file.json",
                    },
                },
            ),
            FakeResponse(200, {"rows": [{"close": 1.23}]}),
        ]
    )
    client = qt.QVerisClient(
        qt.QVerisConfig(enabled=True, api_key="sk-live"),
        client=fake,
        min_interval_seconds=0,
    )

    payload = client.execute("tool_1", parameters={}, max_response_size=10)

    assert payload["result"]["full_content"] == {"rows": [{"close": 1.23}]}
    assert payload["result"]["full_content_downloaded"] is True
    assert fake.calls[1]["headers"] is None
