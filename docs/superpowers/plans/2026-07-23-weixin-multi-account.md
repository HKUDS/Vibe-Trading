# Weixin Multi-Account Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support two to three concurrently logged-in Weixin ClawBot accounts through one Vibe-Trading channel while preserving the current primary account token, pairing approvals, and sessions without another QR login.

**Architecture:** Keep `WeixinChannel` as the single ChannelManager adapter and extract the existing single-account implementation into an internal `WeixinAccountRuntime`. The wrapper owns one legacy-compatible primary runtime plus optional auxiliary runtimes, uses opaque account-qualified route keys for auxiliary peers, and delegates lifecycle and outbound delivery to the selected runtime. Primary paths and identifiers remain unchanged.

**Tech Stack:** Python 3.11 runtime in Docker, asyncio, httpx, Pydantic v2, pytest/pytest-asyncio, Rich argparse CLI, Docker Compose, Git worktrees, Windows PowerShell.

---

## File Map

- Create `agent/src/channels/weixin_routing.py`: validated account aliases and opaque auxiliary route encoding/decoding.
- Create `agent/src/channels/weixin_account.py`: extracted per-account iLink implementation and account-scoped authorization/routing.
- Modify `agent/src/channels/weixin.py`: public multi-account wrapper and config models.
- Modify `agent/src/channels/registry.py`: exclude internal Weixin helper modules from channel auto-discovery.
- Modify `agent/src/channels/base.py`: redaction-safe status extension hook and pairing logs.
- Modify `agent/src/channels/manager.py`: merge channel-specific sanitized status details.
- Modify `agent/src/channels/pairing/store.py`: remove pairing codes and sender IDs from logs.
- Modify `agent/src/channels/utils.py`: stable opaque log label helper.
- Modify `agent/cli/_legacy.py`: account-aware Weixin login CLI.
- Create `agent/tests/test_weixin_multi_account.py`: config, routing, lifecycle, isolation, status, and redaction coverage.
- Modify `agent/tests/test_cli_channels.py`: `--account` parsing and dispatch coverage.
- Modify `agent/tests/test_channels_runtime.py`: account-qualified session isolation and reset coverage.
- Modify `README.md`: document account-aware Weixin login and compatibility.
- Modify host-only `F:\VibeTrading\config\agent.json` during staged onboarding; never commit it.

### Task 1: Create An Isolated Worktree And Prove The Baseline

**Files:**
- No source changes.
- Worktree: `F:\VibeTrading\worktrees\weixin-multi-account`

- [ ] **Step 1: Invoke the worktree setup skill**

Use `superpowers:using-git-worktrees` before running any worktree command. Confirm that the current repository is `F:\VibeTrading\Vibe-Trading`, the approved design commit `06eb2fb` is an ancestor of the current planning branch `HEAD`, and the local-only `docker-compose.local.yml` remains untracked in the production checkout.

- [ ] **Step 2: Create the feature worktree**

```powershell
New-Item -ItemType Directory -Force -Path 'F:\VibeTrading\worktrees' | Out-Null
$baseCommit = (git -C 'F:\VibeTrading\Vibe-Trading' rev-parse HEAD).Trim()
git -C 'F:\VibeTrading\Vibe-Trading' merge-base --is-ancestor 06eb2fb $baseCommit
if ($LASTEXITCODE -ne 0) { throw 'Approved design commit is not an ancestor of HEAD' }
git -C 'F:\VibeTrading\Vibe-Trading' worktree add `
  'F:\VibeTrading\worktrees\weixin-multi-account' `
  -b feature/weixin-multi-account $baseCommit
```

Expected: Git reports a new worktree on `feature/weixin-multi-account` at the current planning branch `HEAD`, which contains both the approved design and this implementation plan.

- [ ] **Step 3: Verify isolation and secret hygiene**

```powershell
git -C 'F:\VibeTrading\worktrees\weixin-multi-account' status --short
Test-Path 'F:\VibeTrading\worktrees\weixin-multi-account\docker-compose.local.yml'
Test-Path 'F:\VibeTrading\worktrees\weixin-multi-account\agent\.env'
```

Expected: clean worktree; both local secret/config paths are `False`.

- [ ] **Step 4: Run the focused baseline tests in the existing image**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker run --rm `
  --mount 'type=bind,source=F:\VibeTrading\worktrees\weixin-multi-account\agent,target=/app/agent,readonly' `
  --workdir /app/agent `
  --entrypoint sh `
  vibe-trading-vibe-trading `
  -lc "/opt/venv/bin/python -m pip install --disable-pip-version-check -q pytest pytest-socket && /opt/venv/bin/python -m pytest tests/test_channels_runtime.py tests/test_cli_channels.py tests/test_packaging_dependencies.py -q"
```

Expected: all existing focused tests pass. A read-only pytest cache warning is acceptable.

### Task 2: Add Account Alias And Route-Key Primitives

**Files:**
- Create: `agent/src/channels/weixin_routing.py`
- Modify: `agent/src/channels/registry.py`
- Create: `agent/tests/test_weixin_multi_account.py`

- [ ] **Step 1: Write failing route and alias tests**

```python
import pytest

from src.channels.weixin_routing import (
    PRIMARY_ACCOUNT_ID,
    decode_aux_route,
    encode_aux_route,
    validate_account_alias,
)


def test_account_alias_validation() -> None:
    assert validate_account_alias("account2") == "account2"
    assert validate_account_alias("desk_user-3") == "desk_user-3"
    for value in ("primary", "Account2", "2account", "../escape", "a" * 33):
        with pytest.raises(ValueError):
            validate_account_alias(value)


def test_aux_route_round_trip_is_account_qualified() -> None:
    route = encode_aux_route("account2", "peer:@chatroom/中文")
    assert route.startswith("weixin-route:v1:account2:")
    assert decode_aux_route(route) == ("account2", "peer:@chatroom/中文")
    assert decode_aux_route("plain-primary-peer") is None


def test_aux_route_rejects_malformed_values() -> None:
    with pytest.raises(ValueError):
        decode_aux_route("weixin-route:v1:account2:not-base64***")
    with pytest.raises(ValueError):
        encode_aux_route(PRIMARY_ACCOUNT_ID, "peer")
```

- [ ] **Step 2: Run the new tests and verify RED**

```powershell
docker run --rm `
  --mount 'type=bind,source=F:\VibeTrading\worktrees\weixin-multi-account\agent,target=/app/agent' `
  --workdir /app/agent --entrypoint sh vibe-trading-vibe-trading `
  -lc "/opt/venv/bin/python -m pip install --disable-pip-version-check -q pytest pytest-socket && /opt/venv/bin/python -m pytest tests/test_weixin_multi_account.py -q"
```

Expected: collection fails because `src.channels.weixin_routing` does not exist.

- [ ] **Step 3: Implement the routing module**

```python
"""Internal account-qualified routing for the Weixin adapter."""

from __future__ import annotations

import base64
import re

PRIMARY_ACCOUNT_ID = "primary"
_ROUTE_PREFIX = "weixin-route:v1:"
_ACCOUNT_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def validate_account_alias(value: str) -> str:
    alias = str(value).strip()
    if alias == PRIMARY_ACCOUNT_ID or not _ACCOUNT_ALIAS_RE.fullmatch(alias):
        raise ValueError(
            "Weixin account aliases must match [a-z][a-z0-9_-]{0,31} "
            "and cannot be 'primary'"
        )
    return alias


def encode_aux_route(account_id: str, peer_id: str) -> str:
    alias = validate_account_alias(account_id)
    peer = str(peer_id)
    if not peer or "\x00" in peer:
        raise ValueError("Weixin peer ID must be non-empty and contain no NUL")
    encoded = base64.urlsafe_b64encode(peer.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{_ROUTE_PREFIX}{alias}:{encoded}"


def decode_aux_route(value: str) -> tuple[str, str] | None:
    text = str(value)
    if not text.startswith(_ROUTE_PREFIX):
        return None
    remainder = text[len(_ROUTE_PREFIX):]
    alias, separator, encoded = remainder.partition(":")
    if not separator or not encoded:
        raise ValueError("Malformed Weixin auxiliary route")
    alias = validate_account_alias(alias)
    try:
        padding = "=" * (-len(encoded) % 4)
        peer = base64.b64decode(encoded + padding, altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Malformed Weixin auxiliary route") from exc
    if not peer or "\x00" in peer:
        raise ValueError("Malformed Weixin auxiliary route")
    return alias, peer
```

Add both helper module names to the registry internal set:

```python
_INTERNAL = frozenset({
    "base", "bus", "config", "manager", "pairing", "registry", "runtime", "utils",
    "weixin_account", "weixin_routing",
})
```

- [ ] **Step 4: Run the route and registry tests**

```powershell
docker run --rm `
  --mount 'type=bind,source=F:\VibeTrading\worktrees\weixin-multi-account\agent,target=/app/agent' `
  --workdir /app/agent --entrypoint sh vibe-trading-vibe-trading `
  -lc "/opt/venv/bin/python -m pytest tests/test_weixin_multi_account.py tests/test_packaging_dependencies.py -q"
```

Expected: PASS; built-in channel discovery still reports `weixin` but not either helper module.

- [ ] **Step 5: Commit the routing primitives**

```powershell
git add agent/src/channels/weixin_routing.py agent/src/channels/registry.py agent/tests/test_weixin_multi_account.py
git commit -m "feat: add Weixin account routing primitives"
```

### Task 3: Extract The Existing Adapter Into A Primary Account Runtime

**Files:**
- Create by move: `agent/src/channels/weixin_account.py`
- Replace: `agent/src/channels/weixin.py`
- Modify: `agent/tests/test_weixin_multi_account.py`

- [ ] **Step 1: Add failing legacy-compatibility tests**

```python
from pathlib import Path

from src.channels.bus.queue import MessageBus
from src.channels.weixin import WeixinChannel, WeixinConfig


def test_no_accounts_builds_only_legacy_primary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.channels.weixin_account.get_runtime_subdir",
        lambda name: tmp_path / name,
    )
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=[]),
        MessageBus(),
    )
    assert list(channel.account_ids) == ["primary"]
    assert channel.account("primary").state_file == tmp_path / "weixin" / "account.json"


def test_primary_wrapper_preserves_raw_route() -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True), MessageBus())
    assert channel.route_for("primary", "peer-1") == "peer-1"
```

- [ ] **Step 2: Run the compatibility tests and verify RED**

Run:

```powershell
docker run --rm --mount 'type=bind,source=F:\VibeTrading\worktrees\weixin-multi-account\agent,target=/app/agent' --workdir /app/agent --entrypoint sh vibe-trading-vibe-trading -lc "/opt/venv/bin/python -m pytest tests/test_weixin_multi_account.py -q"
```

Expected: FAIL because the current channel has no account wrapper API.

- [ ] **Step 3: Move the existing implementation and rename its public types**

```powershell
git mv agent/src/channels/weixin.py agent/src/channels/weixin_account.py
```

In `weixin_account.py`:

```python
class WeixinAccountConfig(BaseModel):
    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)
    base_url: str = "https://ilinkai.weixin.qq.com"
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    route_tag: str | int | None = None
    token: str = ""
    state_dir: str = ""
    poll_timeout: int = DEFAULT_LONG_POLL_TIMEOUT_S


class WeixinAccountRuntime(BaseChannel):
    name = "weixin"
    display_name = "WeChat"

    def __init__(
        self,
        config: WeixinAccountConfig,
        bus: MessageBus,
        *,
        account_id: str = "primary",
    ) -> None:
        super().__init__(config, bus)
        self.account_id = account_id
        # Keep the existing state initialization unchanged below this point.

    @property
    def state_file(self) -> Path:
        return self._get_state_dir() / "account.json"

    @property
    def has_saved_credentials(self) -> bool:
        if self._token or self.config.token:
            return True
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return bool(data.get("token"))
```

Replace every internal `WeixinConfig` annotation/construction with `WeixinAccountConfig`, and every class reference with `WeixinAccountRuntime`. Do not change HTTP, QR, media, typing, polling, or send behavior in this task.

- [ ] **Step 4: Create a primary-only compatibility wrapper**

Create `agent/src/channels/weixin.py`:

```python
"""Multi-account wrapper for the personal Weixin adapter."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from src.channels import weixin_account as account_impl
from src.channels.base import BaseChannel
from src.channels.bus.events import OutboundMessage
from src.channels.bus.queue import MessageBus


class WeixinConfig(account_impl.WeixinAccountConfig):
    accounts: dict[str, dict[str, Any]] = Field(default_factory=dict)


class WeixinChannel(BaseChannel):
    name = "weixin"
    display_name = "WeChat"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WeixinConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus) -> None:
        parsed = config if isinstance(config, WeixinConfig) else WeixinConfig.model_validate(config)
        super().__init__(parsed, bus)
        primary_payload = parsed.model_dump(exclude={"accounts"})
        self._accounts = {
            "primary": account_impl.WeixinAccountRuntime(
                account_impl.WeixinAccountConfig.model_validate(primary_payload),
                bus,
                account_id="primary",
            )
        }

    @property
    def account_ids(self) -> tuple[str, ...]:
        return tuple(self._accounts)

    def account(self, account_id: str) -> account_impl.WeixinAccountRuntime:
        return self._accounts[account_id]

    def route_for(self, account_id: str, peer_id: str) -> str:
        if account_id != "primary":
            raise KeyError(account_id)
        return str(peer_id)

    def _sync_flags(self) -> None:
        for runtime in self._accounts.values():
            runtime.send_progress = self.send_progress
            runtime.send_tool_hints = self.send_tool_hints
            runtime.show_reasoning = self.show_reasoning

    async def login(self, force: bool = False) -> bool:
        self._sync_flags()
        return await self._accounts["primary"].login(force=force)

    async def start(self) -> None:
        self._sync_flags()
        await self._accounts["primary"].start()

    async def stop(self) -> None:
        await self._accounts["primary"].stop()

    async def send(self, msg: OutboundMessage) -> None:
        self._sync_flags()
        await self._accounts["primary"].send(msg)

    async def send_delta(
        self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None,
    ) -> None:
        self._sync_flags()
        await self._accounts["primary"].send_delta(chat_id, delta, metadata)

    @property
    def is_running(self) -> bool:
        return self._accounts["primary"].is_running
```

- [ ] **Step 5: Run legacy channel regression tests**

```powershell
docker run --rm --mount 'type=bind,source=F:\VibeTrading\worktrees\weixin-multi-account\agent,target=/app/agent' --workdir /app/agent --entrypoint sh vibe-trading-vibe-trading -lc "/opt/venv/bin/python -m pytest tests/test_weixin_multi_account.py tests/test_channels_runtime.py tests/test_cli_channels.py tests/test_packaging_dependencies.py -q"
```

Expected: PASS with the wrapper operating only the unchanged primary runtime.

- [ ] **Step 6: Commit the compatibility extraction**

```powershell
git add agent/src/channels/weixin.py agent/src/channels/weixin_account.py agent/tests/test_weixin_multi_account.py
git commit -m "refactor: isolate Weixin account runtime"
```

### Task 4: Build Auxiliary Account Configuration And Lifecycle Isolation

**Files:**
- Modify: `agent/src/channels/weixin.py`
- Modify: `agent/src/channels/weixin_account.py`
- Modify: `agent/tests/test_weixin_multi_account.py`

- [ ] **Step 1: Add failing config, state-path, and lifecycle tests**

```python
import asyncio

import pytest
from pydantic import ValidationError


def test_auxiliary_accounts_have_confined_state_dirs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.channels.weixin.get_runtime_subdir",
        lambda name: tmp_path / name,
    )
    channel = WeixinChannel(
        {
            "enabled": True,
            "accounts": {
                "account2": {"enabled": False, "allow_from": []},
                "account3": {"enabled": True, "allow_from": []},
            },
        },
        MessageBus(),
    )
    assert channel.account_ids == ("primary", "account2", "account3")
    assert channel.account("account2").state_file == (
        tmp_path / "weixin" / "accounts" / "account2" / "account.json"
    )


@pytest.mark.parametrize("alias", ["primary", "../escape", "Account2"])
def test_invalid_auxiliary_alias_is_rejected(alias: str) -> None:
    with pytest.raises(ValidationError):
        WeixinConfig.model_validate({"accounts": {alias: {"enabled": True}}})


@pytest.mark.asyncio
async def test_one_account_failure_does_not_cancel_siblings(monkeypatch) -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )
    primary_started = asyncio.Event()
    auxiliary_failed = asyncio.Event()

    async def primary_start() -> None:
        primary_started.set()
        await asyncio.Event().wait()

    async def auxiliary_start() -> None:
        auxiliary_failed.set()
        raise RuntimeError("isolated failure")

    monkeypatch.setattr(channel.account("primary"), "start", primary_start)
    monkeypatch.setattr(channel.account("account2"), "start", auxiliary_start)
    channel.account("primary")._token = "primary-test-token"
    channel.account("account2")._token = "auxiliary-test-token"
    task = asyncio.create_task(channel.start())
    await asyncio.wait_for(primary_started.wait(), 1)
    await asyncio.wait_for(auxiliary_failed.wait(), 1)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_enabled_account_without_credentials_never_starts_qr_login(monkeypatch) -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )
    starts: list[str] = []

    async def record_start() -> None:
        starts.append("started")

    monkeypatch.setattr(channel.account("account2"), "start", record_start)
    await channel.start()
    assert starts == []
    assert "account2" in channel.login_required_accounts
```

- [ ] **Step 2: Run the tests and verify RED**

Expected failures: auxiliary config is unvalidated, state directories are absent, and lifecycle is primary-only.

- [ ] **Step 3: Implement explicit auxiliary config**

```python
import asyncio

from pydantic import BaseModel, Field, field_validator

from src.channels.utils import get_runtime_subdir
from src.channels.weixin_routing import validate_account_alias


class AuxiliaryWeixinAccountConfig(BaseModel):
    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)
    base_url: str = "https://ilinkai.weixin.qq.com"
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    route_tag: str | int | None = None
    poll_timeout: int = account_impl.DEFAULT_LONG_POLL_TIMEOUT_S


class WeixinConfig(account_impl.WeixinAccountConfig):
    accounts: dict[str, AuxiliaryWeixinAccountConfig] = Field(default_factory=dict)

    @field_validator("accounts")
    @classmethod
    def validate_accounts(
        cls, value: dict[str, AuxiliaryWeixinAccountConfig],
    ) -> dict[str, AuxiliaryWeixinAccountConfig]:
        return {validate_account_alias(alias): config for alias, config in value.items()}
```

- [ ] **Step 4: Build primary and auxiliary runtimes**

```python
def _runtime_config_for_auxiliary(
    self,
    alias: str,
    config: AuxiliaryWeixinAccountConfig,
) -> account_impl.WeixinAccountConfig:
    state_dir = get_runtime_subdir("weixin") / "accounts" / alias
    return account_impl.WeixinAccountConfig(
        **config.model_dump(),
        state_dir=str(state_dir),
    )


def _build_accounts(self, parsed: WeixinConfig) -> dict[str, account_impl.WeixinAccountRuntime]:
    primary_payload = parsed.model_dump(exclude={"accounts"})
    runtimes = {
        "primary": account_impl.WeixinAccountRuntime(
            account_impl.WeixinAccountConfig.model_validate(primary_payload),
            self.bus,
            account_id="primary",
        )
    }
    for alias, auxiliary in parsed.accounts.items():
        runtimes[alias] = account_impl.WeixinAccountRuntime(
            self._runtime_config_for_auxiliary(alias, auxiliary),
            self.bus,
            account_id=alias,
        )
    return runtimes
```

Initialize lifecycle tracking immediately after building the account map:

```python
self._account_tasks: dict[str, asyncio.Task[None]] = {}
self._account_errors: dict[str, str] = {}
self._login_required: set[str] = set()


@property
def login_required_accounts(self) -> frozenset[str]:
    return frozenset(self._login_required)
```

Keep a task per enabled account and gather with `return_exceptions=True`:

```python
async def _run_account(self, alias: str) -> None:
    runtime = self._accounts[alias]
    try:
        await runtime.start()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        self._account_errors[alias] = type(exc).__name__
        self.logger.exception("Weixin account %s stopped unexpectedly", alias)


async def start(self) -> None:
    self._sync_flags()
    self._login_required.clear()
    self._account_tasks = {
        alias: asyncio.create_task(self._run_account(alias))
        for alias, runtime in self._accounts.items()
        if runtime.config.enabled and runtime.has_saved_credentials
    }
    self._login_required.update(
        alias
        for alias, runtime in self._accounts.items()
        if runtime.config.enabled and not runtime.has_saved_credentials
    )
    if not self._account_tasks:
        return
    await asyncio.gather(*self._account_tasks.values(), return_exceptions=True)


async def stop(self) -> None:
    started_aliases = tuple(self._account_tasks)
    for alias in started_aliases:
        await self._accounts[alias].stop()
    for task in self._account_tasks.values():
        if not task.done():
            task.cancel()
    await asyncio.gather(*self._account_tasks.values(), return_exceptions=True)
    self._account_tasks.clear()
```

This credential gate is mandatory: the wrapper must not call an enabled
account runtime's existing `start()` method unless saved credentials are
present, because the legacy runtime falls back to interactive QR login.

- [ ] **Step 5: Run the focused tests**

Expected: all config, state-path, and lifecycle isolation tests pass.

- [ ] **Step 6: Commit lifecycle support**

```powershell
git add agent/src/channels/weixin.py agent/src/channels/weixin_account.py agent/tests/test_weixin_multi_account.py
git commit -m "feat: add isolated Weixin account lifecycles"
```

### Task 5: Route Messages, Pairings, And Sessions Per Account

**Files:**
- Modify: `agent/src/channels/weixin.py`
- Modify: `agent/src/channels/weixin_account.py`
- Modify: `agent/tests/test_weixin_multi_account.py`
- Modify: `agent/tests/test_channels_runtime.py`

- [ ] **Step 1: Add failing route-selection and authorization tests**

```python
from dataclasses import replace

from src.channels.bus.events import InboundMessage, OutboundMessage
from src.channels.pairing.store import approve_code, list_pending
from src.channels.weixin_routing import encode_aux_route


def test_primary_and_auxiliary_route_selection() -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )
    assert channel.route_for("primary", "peer") == "peer"
    route = channel.route_for("account2", "peer")
    assert route == encode_aux_route("account2", "peer")
    assert channel.account_for_route(route).account_id == "account2"
    assert channel.account_for_route("peer").account_id == "primary"


@pytest.mark.asyncio
async def test_auxiliary_outbound_uses_selected_account(monkeypatch) -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )
    sent: list[tuple[str, str]] = []

    async def capture_primary(msg: OutboundMessage) -> None:
        sent.append(("primary", msg.chat_id))

    async def capture_auxiliary(msg: OutboundMessage) -> None:
        sent.append(("account2", msg.chat_id))

    monkeypatch.setattr(channel.account("primary"), "send", capture_primary)
    monkeypatch.setattr(channel.account("account2"), "send", capture_auxiliary)
    route = encode_aux_route("account2", "peer")
    await channel.send(OutboundMessage(channel="weixin", chat_id=route, content="ok"))
    assert sent == [("account2", route)]


def test_auxiliary_pairing_identity_is_account_scoped(tmp_path, monkeypatch) -> None:
    import src.channels.pairing.store as pairing_store
    monkeypatch.setattr(pairing_store, "_store_path", lambda: tmp_path / "pairing.json")
    route2 = encode_aux_route("account2", "same-peer")
    route3 = encode_aux_route("account3", "same-peer")
    code2 = pairing_store.generate_code("weixin", route2)
    assert approve_code(code2, restrict_channel="weixin") is not None
    assert pairing_store.is_approved("weixin", route2)
    assert not pairing_store.is_approved("weixin", route3)
```

Add a runtime test that publishes two inbound messages with the same raw peer but different routed `chat_id` values and asserts two session-map keys exist. Reset one routed session and assert the other remains.

- [ ] **Step 2: Run the tests and verify RED**

Expected: route selection, auxiliary authorization, and session isolation are not implemented.

- [ ] **Step 3: Add account routing helpers to the wrapper**

```python
from src.channels.weixin_routing import decode_aux_route, encode_aux_route


def route_for(self, account_id: str, peer_id: str) -> str:
    if account_id == "primary":
        return str(peer_id)
    if account_id not in self._accounts:
        raise KeyError(account_id)
    return encode_aux_route(account_id, peer_id)


def account_for_route(self, route: str) -> account_impl.WeixinAccountRuntime:
    decoded = decode_aux_route(route)
    alias = decoded[0] if decoded else "primary"
    try:
        return self._accounts[alias]
    except KeyError as exc:
        raise ValueError(f"Unknown Weixin account route: {alias}") from exc


async def send(self, msg: OutboundMessage) -> None:
    self._sync_flags()
    runtime = self.account_for_route(msg.chat_id)
    await runtime.send(msg)
```

Delegate `send_delta` through the same `account_for_route(chat_id)` selection.

- [ ] **Step 4: Make the account runtime route inbound IDs and decode outbound IDs**

```python
from dataclasses import replace

from src.channels.pairing import is_approved
from src.channels.weixin_routing import decode_aux_route, encode_aux_route


def _route_peer_id(self, peer_id: str) -> str:
    if self.account_id == "primary":
        return str(peer_id)
    return encode_aux_route(self.account_id, peer_id)


def _decode_peer_id(self, route: str) -> str:
    if self.account_id == "primary":
        if decode_aux_route(route) is not None:
            raise ValueError("Auxiliary route cannot be sent by primary account")
        return str(route)
    decoded = decode_aux_route(route)
    if decoded is None or decoded[0] != self.account_id:
        raise ValueError("Weixin route does not belong to this account")
    return decoded[1]


def is_allowed(self, sender_id: str) -> bool:
    raw_sender = self._decode_peer_id(sender_id)
    allow_list = self.config.allow_from or []
    return (
        "*" in allow_list
        or raw_sender in allow_list
        or is_approved(self.name, str(sender_id))
    )
```

In `_process_message`, compute `routed_sender_id = self._route_peer_id(from_user_id)` once. Use the routed ID for every `is_allowed`, `_handle_message(sender_id=...)`, and `_handle_message(chat_id=...)` call. Continue using the raw `from_user_id` for iLink context tokens, typing, media, and HTTP calls.

At the start of `send`, replace the routed chat ID with the raw selected peer:

```python
raw_chat_id = self._decode_peer_id(msg.chat_id)
msg = replace(msg, chat_id=raw_chat_id)
```

Do the same route decoding before `send_delta` flushes account-local tool hints.

- [ ] **Step 5: Run routing, pairing, and runtime session tests**

Expected: primary compatibility remains green; auxiliary messages use distinct sessions and the correct outbound runtime.

- [ ] **Step 6: Commit message isolation**

```powershell
git add agent/src/channels/weixin.py agent/src/channels/weixin_account.py agent/tests/test_weixin_multi_account.py agent/tests/test_channels_runtime.py
git commit -m "feat: isolate Weixin account messages and sessions"
```

### Task 6: Add Sanitized Per-Account Status

**Files:**
- Modify: `agent/src/channels/base.py`
- Modify: `agent/src/channels/manager.py`
- Modify: `agent/src/channels/weixin.py`
- Modify: `agent/tests/test_weixin_multi_account.py`

- [ ] **Step 1: Add failing status tests**

```python
def test_status_details_are_account_scoped_and_sanitized() -> None:
    channel = WeixinChannel(
        {
            "enabled": True,
            "accounts": {
                "account2": {"enabled": True},
                "account3": {"enabled": False},
            },
        },
        MessageBus(),
    )
    details = channel.status_details()
    assert set(details["accounts"]) == {"primary", "account2", "account3"}
    assert set(details["accounts"]["account2"]) == {
        "configured", "enabled", "loaded", "running", "login_required", "error"
    }
    serialized = repr(details)
    assert "token" not in serialized.lower()
    assert "context" not in serialized.lower()
    assert "peer" not in serialized.lower()
```

Add a manager test that a fake channel's `status_details()` is merged into the normal status payload.

- [ ] **Step 2: Run status tests and verify RED**

Expected: `BaseChannel` and `WeixinChannel` do not expose a status-details hook.

- [ ] **Step 3: Add the generic status extension hook**

In `BaseChannel`:

```python
def status_details(self) -> dict[str, Any]:
    """Return redaction-safe adapter-specific status fields."""
    return {}
```

In `ChannelManager.get_status()`:

```python
details = channel.status_details()
if details:
    status[name].update(details)
```

- [ ] **Step 4: Implement Weixin account status**

```python
def status_details(self) -> dict[str, Any]:
    accounts: dict[str, dict[str, Any]] = {}
    for alias, runtime in self._accounts.items():
        accounts[alias] = {
            "configured": True,
            "enabled": bool(runtime.config.enabled),
            "loaded": True,
            "running": runtime.is_running,
            "login_required": bool(
                runtime.config.enabled and not runtime.has_saved_credentials
            ),
            "error": self._account_errors.get(alias, ""),
        }
    return {"accounts": accounts}
```

Set top-level `is_running` to `any(runtime.is_running for runtime in self._accounts.values())`.

- [ ] **Step 5: Run status and API tests**

```powershell
docker run --rm --mount 'type=bind,source=F:\VibeTrading\worktrees\weixin-multi-account\agent,target=/app/agent' --workdir /app/agent --entrypoint sh vibe-trading-vibe-trading -lc "/opt/venv/bin/python -m pytest tests/test_weixin_multi_account.py tests/test_channels_api.py tests/test_channels_runtime.py -q"
```

Expected: PASS; status contains aliases and booleans only.

- [ ] **Step 6: Commit status support**

```powershell
git add agent/src/channels/base.py agent/src/channels/manager.py agent/src/channels/weixin.py agent/tests/test_weixin_multi_account.py
git commit -m "feat: report sanitized Weixin account status"
```

### Task 7: Add Account-Aware Login CLI

**Files:**
- Modify: `agent/cli/_legacy.py`
- Modify: `agent/src/channels/weixin.py`
- Modify: `agent/tests/test_cli_channels.py`
- Modify: `agent/tests/test_weixin_multi_account.py`

- [ ] **Step 1: Add failing CLI tests**

```python
def test_channels_login_parser_accepts_account_selector() -> None:
    parser = _legacy._build_parser()
    login = parser.parse_args(
        ["channels", "login", "weixin", "--account", "account2", "--force"]
    )
    assert login.account_id == "account2"
    assert login.force is True


def test_channels_login_dispatch_passes_account(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        _legacy,
        "cmd_channels_login",
        lambda name, *, force=False, account_id="primary": captured.update(
            name=name, force=force, account_id=account_id
        ) or _legacy.EXIT_SUCCESS,
    )
    assert _legacy.main(
        ["channels", "login", "weixin", "--account", "account2"]
    ) == _legacy.EXIT_SUCCESS
    assert captured == {"name": "weixin", "force": False, "account_id": "account2"}
```

Add adapter tests asserting `login_account("missing")` raises a sanitized `KeyError`, `login()` selects primary, and `--force` reaches only the selected account runtime.

- [ ] **Step 2: Run CLI tests and verify RED**

Expected: parser rejects `--account` and dispatch has no account parameter.

- [ ] **Step 3: Add wrapper login selection**

```python
async def login_account(self, account_id: str = "primary", *, force: bool = False) -> bool:
    self._sync_flags()
    try:
        runtime = self._accounts[account_id]
    except KeyError as exc:
        raise KeyError(f"Unknown configured Weixin account: {account_id}") from exc
    ok = await runtime.login(force=force)
    if ok:
        self._login_required.discard(account_id)
    return ok


async def login(self, force: bool = False) -> bool:
    return await self.login_account("primary", force=force)
```

- [ ] **Step 4: Extend CLI parser and command dispatch**

```python
channels_login.add_argument(
    "--account",
    dest="account_id",
    default="primary",
    help="Configured Weixin account alias (default: primary)",
)
```

Change the command signature and selected call:

```python
def cmd_channels_login(
    channel_name: str,
    *,
    force: bool = False,
    account_id: str = "primary",
) -> int:
    ...
    if channel_name == "weixin":
        ok = asyncio.run(adapter.login_account(account_id, force=force))
    elif account_id != "primary":
        console.print("[red]--account is supported only for the weixin channel.[/red]")
        return EXIT_USAGE_ERROR
    else:
        ok = asyncio.run(adapter.login(force=force))
```

Dispatch with:

```python
return cmd_channels_login(
    args.channel_name,
    force=args.force,
    account_id=args.account_id,
)
```

- [ ] **Step 5: Run CLI and adapter tests**

Expected: primary syntax remains valid; auxiliary selection and force isolation pass.

- [ ] **Step 6: Commit CLI support**

```powershell
git add agent/cli/_legacy.py agent/src/channels/weixin.py agent/tests/test_cli_channels.py agent/tests/test_weixin_multi_account.py
git commit -m "feat: add account-aware Weixin login"
```

### Task 8: Remove Sensitive Weixin And Pairing Identifiers From Logs

**Files:**
- Modify: `agent/src/channels/utils.py`
- Modify: `agent/src/channels/base.py`
- Modify: `agent/src/channels/pairing/store.py`
- Modify: `agent/src/channels/weixin_account.py`
- Modify: `agent/tests/test_weixin_multi_account.py`

- [ ] **Step 1: Add failing redaction tests**

```python
from src.channels.utils import opaque_log_id


def test_opaque_log_id_is_stable_and_non_reversible() -> None:
    value = "sensitive-weixin-peer"
    label = opaque_log_id(value)
    assert label == opaque_log_id(value)
    assert label.startswith("id:")
    assert value not in label
    assert len(label) == 15


def test_pairing_logs_exclude_code_and_sender(caplog, tmp_path, monkeypatch) -> None:
    import src.channels.pairing.store as pairing_store
    monkeypatch.setattr(pairing_store, "_store_path", lambda: tmp_path / "pairing.json")
    code = pairing_store.generate_code("weixin", "sensitive-sender")
    pairing_store.approve_code(code, restrict_channel="weixin")
    text = caplog.text
    assert code not in text
    assert "sensitive-sender" not in text
```

Add a Weixin inbound-log test with a known raw peer ID and assert only the opaque label is present.

- [ ] **Step 2: Run redaction tests and verify RED**

Expected: current BaseChannel, pairing store, and Weixin logs expose codes or raw identifiers.

- [ ] **Step 3: Add one opaque identifier helper**

```python
import hashlib


def opaque_log_id(value: str) -> str:
    """Return a stable short label without logging the source identifier."""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"id:{digest}"
```

- [ ] **Step 4: Replace sensitive log arguments**

In `BaseChannel._handle_message`, log only channel and `opaque_log_id(sender_id)`; never log the pairing code or chat ID.

In pairing-store mutation logs, use messages with no code and no sender ID:

```python
logger.info("Generated pairing request for channel %s", channel)
logger.info("Approved pairing request for channel %s", channel)
logger.info("Denied pairing request for channel %s", info.get("channel", "unknown"))
logger.info("Revoked paired sender for channel %s", channel)
```

In `weixin_account.py`, replace every peer-bearing log argument with:

```python
peer_label = opaque_log_id(from_user_id)
self.logger.info("account=%s inbound peer=%s items=%s bodyLen=%s", ...)
```

Do not alter user-facing pairing replies; the pairing code must still be sent to the requesting user.

- [ ] **Step 5: Verify no sensitive log patterns remain**

```powershell
rg -n 'pairing code %s|sender %s|chat %s|from=\{\}|user_id=\{\}|bot_id=\{\}' `
  agent/src/channels/base.py `
  agent/src/channels/pairing/store.py `
  agent/src/channels/weixin_account.py
```

Expected: no raw-identifier logging call remains in these files.

- [ ] **Step 6: Run redaction and channel tests**

Expected: redaction tests and all existing channel tests pass.

- [ ] **Step 7: Commit log hardening**

```powershell
git add agent/src/channels/utils.py agent/src/channels/base.py agent/src/channels/pairing/store.py agent/src/channels/weixin_account.py agent/tests/test_weixin_multi_account.py
git commit -m "fix: redact Weixin channel identifiers from logs"
```

### Task 9: Document, Run Full Verification, And Build A Candidate Image

**Files:**
- Modify: `README.md`
- Verify all files changed in Tasks 2-8.

- [ ] **Step 1: Document account-aware login**

Add this concise example near the existing channels CLI examples:

```markdown
# Existing primary Weixin account (backward compatible)
vibe-trading channels login weixin

# Configured auxiliary account
vibe-trading channels login weixin --account account2
```

Document that the primary state path remains unchanged and auxiliary accounts require an `accounts.<alias>` config entry before QR login.

- [ ] **Step 2: Run focused tests**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker run --rm `
  --mount 'type=bind,source=F:\VibeTrading\worktrees\weixin-multi-account\agent,target=/app/agent' `
  --workdir /app/agent --entrypoint sh vibe-trading-vibe-trading `
  -lc "/opt/venv/bin/python -m pip install --disable-pip-version-check -q pytest pytest-socket ruff && /opt/venv/bin/python -m pytest tests/test_weixin_multi_account.py tests/test_channels_runtime.py tests/test_channels_api.py tests/test_cli_channels.py tests/test_packaging_dependencies.py tests/test_agent_config.py -q && /opt/venv/bin/python -m ruff check src/channels/weixin.py src/channels/weixin_account.py src/channels/weixin_routing.py src/channels/base.py src/channels/manager.py src/channels/pairing/store.py src/channels/utils.py tests/test_weixin_multi_account.py tests/test_cli_channels.py tests/test_channels_runtime.py"
```

Expected: PASS with no Ruff findings.

- [ ] **Step 3: Run LLM regression tests**

```powershell
& $docker run --rm `
  --mount 'type=bind,source=F:\VibeTrading\worktrees\weixin-multi-account\agent,target=/app/agent' `
  --workdir /app/agent --entrypoint sh vibe-trading-vibe-trading `
  -lc "/opt/venv/bin/python -m pytest tests/test_llm.py tests/test_llm_provider_defaults.py -q"
```

Expected: PASS; no provider behavior changed.

- [ ] **Step 4: Build a separately tagged candidate image**

```powershell
$dockerBin = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin'
$env:PATH = "$dockerBin;$env:PATH"
docker build --progress plain `
  -t vibe-trading:weixin-multi-account-candidate `
  'F:\VibeTrading\worktrees\weixin-multi-account'
```

Expected: build completes without replacing the running container image.

- [ ] **Step 5: Smoke-test legacy config in the candidate image**

```powershell
$code = "from src.channels.bus.queue import MessageBus; from src.channels.weixin import WeixinChannel; c=WeixinChannel({'enabled':True,'allow_from':[]}, MessageBus()); print('ACCOUNTS=' + ','.join(c.account_ids)); print('PRIMARY_STATE=' + str(c.account('primary').state_file))"
docker run --rm --entrypoint python vibe-trading:weixin-multi-account-candidate -c $code
```

Expected: `ACCOUNTS=primary`; primary state ends in `runtime/weixin/account.json`.

- [ ] **Step 6: Commit documentation and final code state**

```powershell
git add README.md
git commit -m "docs: explain multi-account Weixin login"
git status --short
```

Expected: clean feature worktree.

### Task 10: Create Recovery Points And Deploy Primary-Only Compatibility

**Files:**
- Read: `F:\VibeTrading\config\agent.json`
- Create outside Git: `F:\VibeTrading\backups\weixin-multi-account-<timestamp>\`
- No source edits.

- [ ] **Step 1: Invoke verification and branch-completion review skills**

Use `superpowers:verification-before-completion` and `superpowers:requesting-code-review` before production cutover. Resolve all review findings and rerun Task 9 verification.

- [ ] **Step 2: Record current recovery identifiers**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
$preImage = (& $docker image inspect vibe-trading-vibe-trading --format '{{.Id}}').Trim()
$preCommit = (git -C 'F:\VibeTrading\Vibe-Trading' rev-parse HEAD).Trim()
Write-Output ('PRE_IMAGE_SET=' + [bool]$preImage)
Write-Output ('PRE_COMMIT=' + $preCommit)
& $docker tag vibe-trading-vibe-trading vibe-trading:pre-weixin-multi-account
```

Expected: both identifiers are present and the rollback image tag is created.

- [ ] **Step 3: Create an ACL-restricted runtime snapshot**

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = "F:\VibeTrading\backups\weixin-multi-account-$stamp"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
icacls.exe $backupDir /inheritance:r | Out-Null
icacls.exe $backupDir /grant:r "${env:USERNAME}:(OI)(CI)(F)" 'SYSTEM:(OI)(CI)(F)' | Out-Null

$volume = (& $docker inspect vibe-trading-vibe-trading-1 --format '{{range .Mounts}}{{if eq .Destination "/home/vibe/.vibe-trading"}}{{.Name}}{{end}}{{end}}').Trim()
if (-not $volume) { throw 'Unable to resolve vibe-home volume' }
$archive = Join-Path $backupDir 'vibe-home.tar.gz'
$code = "import pathlib,tarfile; source=pathlib.Path('/source'); target=pathlib.Path('/backup/vibe-home.tar.gz'); tf=tarfile.open(target,'w:gz'); tf.add(source,arcname='vibe-home'); tf.close(); print('SNAPSHOT_CREATED=' + str(target.exists()))"
& $docker run --rm `
  --mount "type=volume,source=$volume,target=/source,readonly" `
  --mount "type=bind,source=$backupDir,target=/backup" `
  --entrypoint python vibe-trading-vibe-trading -c $code
Copy-Item -LiteralPath 'F:\VibeTrading\config\agent.json' -Destination (Join-Path $backupDir 'agent.json')
Get-FileHash -Algorithm SHA256 -LiteralPath $archive | Select-Object Algorithm,Hash
```

Expected: snapshot exists, hash is printed, and ACL entries contain only the current user and `SYSTEM`. Do not copy `agent.env`; it is not changed by this feature.

- [ ] **Step 4: Promote the candidate image and recreate the service**

```powershell
& $docker tag vibe-trading:weixin-multi-account-candidate vibe-trading-vibe-trading:latest
$env:PATH = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin;' + $env:PATH
docker compose `
  -f 'F:\VibeTrading\Vibe-Trading\docker-compose.yml' `
  -f 'F:\VibeTrading\Vibe-Trading\docker-compose.local.yml' `
  up -d --no-deps --force-recreate --no-build vibe-trading
```

Expected: the container restarts without a Windows restart.

- [ ] **Step 5: Verify primary compatibility without printing secrets**

Poll `/health`, then query `/channels/status` from inside the container. Report only:

```text
HTTP_HEALTHY=True
RUNTIME_RUNNING=True
PRIMARY_RUNNING=True
PRIMARY_LOGIN_REQUIRED=False
PRIMARY_TOKEN_PRESENT=True
APPROVED_USER_COUNT=<unchanged count>
UNEXPECTED_QR=False
```

Also verify the primary state path is still exactly `/home/vibe/.vibe-trading/runtime/weixin/account.json`.

- [ ] **Step 6: Run the primary user checkpoint**

Ask the operator to send:

```text
Only reply: VIBE_PRIMARY_MULTI_OK
```

Do not proceed until the exact reply is received.

- [ ] **Step 7: Roll back immediately if primary verification fails**

```powershell
& $docker tag vibe-trading:pre-weixin-multi-account vibe-trading-vibe-trading:latest
docker compose `
  -f 'F:\VibeTrading\Vibe-Trading\docker-compose.yml' `
  -f 'F:\VibeTrading\Vibe-Trading\docker-compose.local.yml' `
  up -d --no-deps --force-recreate --no-build vibe-trading
```

Restore the protected volume snapshot only if verification proves runtime state changed or became unreadable. Prefer image rollback because the design is non-destructive to primary state.

### Task 11: Onboard Account2 And Verify Two-Account Isolation

**Files:**
- Modify outside Git: `F:\VibeTrading\config\agent.json`
- No source edits.

- [ ] **Step 1: Add disabled account2 configuration**

Use `apply_patch` to add:

```json
"accounts": {
  "account2": {
    "enabled": false,
    "allow_from": []
  }
}
```

Preserve `send_progress: false`, `send_tool_hints: false`, `reply_timeout_s: 1800`, the primary `allow_from`, and the protected ACL. Validate the JSON through `load_agent_config` without printing identifiers.

- [ ] **Step 2: Verify the running container can read account2 without recreation**

The bind-mounted `agent.json` is read afresh by each CLI process, so do not
interrupt the primary service here. Run a local config check inside the current
container and print only:

```text
ACCOUNT2_CONFIGURED=True
ACCOUNT2_ENABLED=False
PRIMARY_RUNNING=True
```

If the CLI cannot see `account2`, validate the mounted path and JSON loader;
do not recreate the service merely to refresh config.

- [ ] **Step 3: Open an interactive account2 QR login window**

Launch a visible PowerShell window whose command is:

```powershell
docker exec -it vibe-trading-vibe-trading-1 `
  vibe-trading channels login weixin --account account2 --force
```

Tell the operator to scan with the second Weixin account and wait for `login completed`. Do not display or copy the token.

- [ ] **Step 4: Verify account2 credentials without exposing them**

Check only that:

```text
/home/vibe/.vibe-trading/runtime/weixin/accounts/account2/account.json exists
token is non-empty
primary token remains non-empty
the two state files are distinct
```

- [ ] **Step 5: Enable account2 and perform the second short recreation**

Use `apply_patch` to change only `account2.enabled` from `false` to `true`, revalidate ACL, and recreate the container. Verify both account statuses show `running=True`, `login_required=False`, and no sanitized errors.

- [ ] **Step 6: Pair the account2 user safely**

Ask the second account to send `account2 pairing test`. Approve only when pending pairing records belong to one routed account2 identity. Print counts and booleans only; never print the pairing code or routed sender key.

- [ ] **Step 7: Verify exact replies on both accounts**

Primary account sends:

```text
Only reply: VIBE_PRIMARY_FINAL_OK
```

Account2 sends:

```text
Only reply: VIBE_ACCOUNT2_OK
```

Expected: each ClawBot returns only its own exact marker.

- [ ] **Step 8: Verify session isolation and persistence**

Query sanitized runtime state and assert:

```text
PRIMARY_RUNNING=True
ACCOUNT2_RUNNING=True
ACCOUNT_STATUS_COUNT=2
SESSION_COUNT increased for both routed conversations
PAIRING_PENDING=0
NO_TOKEN_IN_LOGS=True
NO_RAW_ROUTE_IN_LOGS=True
```

Treat the second recreation from Step 5 as the persistence test: account2 credentials were written before that recreation, and both accounts must have returned to `running` without any QR prompt. Do not perform a third service recreation.

- [ ] **Step 9: Run final regression and branch completion workflow**

Run all Task 9 tests against the committed feature worktree, then invoke `superpowers:verification-before-completion` and `superpowers:finishing-a-development-branch`. Keep the feature branch and worktree until the operator chooses merge, PR, or continued local deployment. Do not push or merge without explicit approval.

While the candidate image is deployed and the feature branch is not integrated, do not run `docker compose build` from the production checkout because that checkout does not yet contain the multi-account source. Operational restarts must use `--no-build` and the already promoted image until the branch decision is complete.

## Completion Conditions

- Current primary account never re-scans during the normal upgrade.
- Primary pairing and session keys remain valid.
- Account2 obtains its own QR token and state file.
- Both accounts run concurrently after container recreation.
- Exactly two planned service recreations occur: primary compatibility cutover, then account2 activation.
- Identical peer IDs cannot share pairing or session state across accounts.
- One account failure cannot stop another account.
- Tokens, pairing codes, peer IDs, and route keys are absent from Git, public status, logs, and reported verification output.
- A tested old-image rollback and ACL-protected runtime snapshot exist.
