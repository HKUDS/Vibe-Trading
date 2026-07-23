# Personal WeChat Channel Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, allowlisted personal WeChat channel to the existing Docker deployment so the user can send research prompts and receive final responses and completion notifications.

**Architecture:** Keep the built-in `weixin` adapter and add only its QR rendering dependency to the hash-locked runtime. Store operator configuration in an ACL-restricted host JSON file mounted read-only, while login tokens, pairing records, and session mappings remain in the existing `vibe-home` Docker volume. Perform QR login before enabling channel auto-start, then authorize private chat through the pairing store and add confirmed group IDs one at a time without a wildcard.

**Tech Stack:** Windows PowerShell, Docker Desktop/Compose, Python 3.11, pip-tools, Vibe-Trading channel runtime, WeChat iLink adapter, pytest.

---

### Task 1: Add the QR Renderer to the Locked Runtime

**Files:**
- Modify: `agent/tests/test_packaging_dependencies.py`
- Modify: `agent/requirements.txt`
- Modify: `requirements-lock.txt`

- [ ] **Step 1: Add a failing packaging regression test**

Append this test to `agent/tests/test_packaging_dependencies.py`:

```python
def test_weixin_qr_dependency_is_installed_in_runtime() -> None:
    """The Docker runtime must render WeChat login QR codes locally."""
    requirements_txt = {
        _normalized_requirement_name(line)
        for line in (ROOT / "agent" / "requirements.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }

    assert "qrcode" in requirements_txt
```

- [ ] **Step 2: Run the test and verify RED**

Run in an ephemeral test container:

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker run --rm --user root `
  --mount type=bind,source='F:\VibeTrading\Vibe-Trading\agent',target=/app/agent,readonly `
  --mount type=bind,source='F:\VibeTrading\Vibe-Trading\pyproject.toml',target=/app/pyproject.toml,readonly `
  -w /app/agent --entrypoint sh vibe-trading-vibe-trading `
  -c "/opt/venv/bin/python -m pip install --disable-pip-version-check -q pytest pytest-socket && /opt/venv/bin/python -m pytest tests/test_packaging_dependencies.py::test_weixin_qr_dependency_is_installed_in_runtime -q"
```

Expected: FAIL because `qrcode` is present only in the optional PyPI extra and not in `agent/requirements.txt`.

- [ ] **Step 3: Add the minimal runtime dependency**

Add this section to `agent/requirements.txt` immediately before `# REST API & SSE`:

```text
# IM Channels
qrcode>=7.4.2
```

- [ ] **Step 4: Regenerate the complete hash lock**

Run from the repository root:

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker run --rm `
  --mount type=bind,source='F:\VibeTrading\Vibe-Trading',target=/src `
  -w /src python:3.11-slim `
  sh -c "python -m pip install --disable-pip-version-check pip-tools==7.6.0 && pip-compile --resolver=backtracking --allow-unsafe --generate-hashes --output-file=requirements-lock.txt agent/requirements.txt"
```

Expected: `requirements-lock.txt` contains a hash-pinned `qrcode` release while existing critical pins, including `langchain-openai==1.3.5` and `openai==2.46.0`, remain unchanged.

- [ ] **Step 5: Verify a clean hash-only install and QR import**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker run --rm `
  --mount type=bind,source='F:\VibeTrading\Vibe-Trading\requirements-lock.txt',target=/tmp/requirements-lock.txt,readonly `
  python:3.11-slim sh -c "python -m venv /tmp/verify && /tmp/verify/bin/pip install --disable-pip-version-check --require-hashes -r /tmp/requirements-lock.txt && /tmp/verify/bin/python -c 'import qrcode; print(\"QRCODE_OK\")'"
```

Expected: installation succeeds and prints `QRCODE_OK`.

- [ ] **Step 6: Run packaging and channel tests**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker run --rm --user root `
  --mount type=bind,source='F:\VibeTrading\Vibe-Trading',target=/src,readonly `
  -w /src/agent --entrypoint sh vibe-trading-vibe-trading `
  -c "/opt/venv/bin/python -m pip install --disable-pip-version-check -q pytest pytest-socket && /opt/venv/bin/python -m pytest tests/test_packaging_dependencies.py tests/test_channels_runtime.py tests/test_cli_channels.py -q"
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit the dependency change**

```powershell
git add -- agent/tests/test_packaging_dependencies.py agent/requirements.txt requirements-lock.txt
git commit -m "feat: include WeChat QR runtime dependency"
```

Expected: the commit includes only the test, source dependency, and regenerated lock.

### Task 2: Create Protected Host Configuration

**Files:**
- Create: `F:\VibeTrading\config\agent.json`
- Modify locally: `F:\VibeTrading\Vibe-Trading\docker-compose.local.yml`
- Read without exposing values: `F:\VibeTrading\config\agent.env`

- [ ] **Step 1: Create the structured channel config**

Create `F:\VibeTrading\config\agent.json` with exactly:

```json
{
  "channels": {
    "send_progress": false,
    "send_tool_hints": false,
    "reply_timeout_s": 1800,
    "weixin": {
      "enabled": true,
      "allow_from": []
    }
  }
}
```

Do not add `allow_from: ["*"]`. Keep auto-start disabled until QR login succeeds so container startup does not launch an invisible competing login flow.

- [ ] **Step 2: Restrict the host JSON ACL**

```powershell
icacls 'F:\VibeTrading\config\agent.json' /inheritance:r
icacls 'F:\VibeTrading\config\agent.json' /grant:r "${env:USERNAME}:(F)" 'SYSTEM:(F)'
icacls 'F:\VibeTrading\config\agent.json'
```

Expected: only the current Windows user and SYSTEM have access; `Users` and `Everyone` are absent.

- [ ] **Step 3: Add the read-only nested config mount**

Update `docker-compose.local.yml` to exactly:

```yaml
services:
  vibe-trading:
    volumes:
      - F:/VibeTrading/config/agent.env:/app/agent/.env:ro
      - F:/VibeTrading/config/agent.json:/home/vibe/.vibe-trading/agent.json:ro
```

The existing `vibe-home` named volume remains mounted at `/home/vibe/.vibe-trading`; the nested bind controls only `agent.json`, while account and pairing state remain writable in the named volume.

- [ ] **Step 4: Validate the merged Compose model**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker compose -f docker-compose.yml -f docker-compose.local.yml config
```

Expected:

- Port `8899` is published only on `127.0.0.1`.
- Both host configuration files are read-only mounts.
- The `vibe-home`, sessions, runs, uploads, and swarm volumes remain present.
- `read_only`, resource limits, capabilities, and `no-new-privileges` remain unchanged.

- [ ] **Step 5: Validate the JSON using the project schema**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker run --rm `
  --mount type=bind,source='F:\VibeTrading\config\agent.json',target=/home/vibe/.vibe-trading/agent.json,readonly `
  --entrypoint python vibe-trading-vibe-trading `
  -c "from src.config.loader import load_agent_config; c=load_agent_config(); print(c.channels.model_dump(mode='json'))"
```

Expected: parsed output shows `send_progress=False`, `send_tool_hints=False`, `reply_timeout_s=1800`, and an enabled `weixin` section with an empty allowlist.

### Task 3: Build and Stage the Channel Without Auto-Start

**Files:**
- Runtime image and containers only.

- [ ] **Step 1: Build the updated production image**

```powershell
$dockerBin = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin'
$env:PATH = "$dockerBin;$env:PATH"
& "$dockerBin\docker.exe" compose -f docker-compose.yml -f docker-compose.local.yml build
```

Expected: the image builds successfully and installs dependencies with `--require-hashes`.

- [ ] **Step 2: Recreate the service with channel auto-start still disabled**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --force-recreate --no-build
```

Poll `docker inspect` until the container reports `healthy`.

- [ ] **Step 3: Verify the staged channel status**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker exec vibe-trading-vibe-trading-1 vibe-trading channels status --local
```

Expected: `weixin` reports configured `yes`, enabled `yes`, available `yes`, and loaded `yes`. It is not yet running because auto-start remains disabled.

- [ ] **Step 4: Verify the QR package in the production container**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker exec vibe-trading-vibe-trading-1 python -c "import qrcode; print('QRCODE_OK')"
```

Expected: `QRCODE_OK`.

### Task 4: Perform Interactive WeChat QR Login

**Files:**
- Persistent runtime state only: Docker volume path `/home/vibe/.vibe-trading/weixin/account.json`

- [ ] **Step 1: Open a visible PowerShell login window**

Run from the Codex process:

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
$loginCommand = "& '$docker' exec -it vibe-trading-vibe-trading-1 vibe-trading channels login weixin; Write-Host ''; Write-Host 'Keep this window open and report the result in Codex.'"
Start-Process powershell.exe -WindowStyle Normal -ArgumentList '-NoExit', '-Command', $loginCommand
```

Expected: a visible PowerShell window displays an ASCII QR code.

- [ ] **Step 2: Pause for the user to scan**

Tell the user:

1. Open WeChat on the phone.
2. Tap `+` and then `扫一扫`.
3. Scan the QR code shown in the visible PowerShell window.
4. Confirm authorization on the phone.
5. Wait for `login successful!` in the PowerShell window.
6. Reply `已扫码成功` in Codex.

Do not continue until the user reports success or a concrete error.

- [ ] **Step 3: Verify saved login state without printing the token**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker exec vibe-trading-vibe-trading-1 python -c "import json,pathlib; p=pathlib.Path.home()/'.vibe-trading'/'weixin'/'account.json'; d=json.loads(p.read_text()) if p.exists() else {}; print('STATE_FILE='+str(p.exists())); print('TOKEN_PRESENT='+str(bool(d.get('token'))))"
```

Expected: `STATE_FILE=True` and `TOKEN_PRESENT=True`. Do not print the token, bot ID, or user ID.

- [ ] **Step 4: Enable persistent channel auto-start**

Add this line to `F:\VibeTrading\config\agent.env` without changing or printing existing secret values:

```dotenv
VIBE_TRADING_CHANNELS_AUTO_START=1
```

Recheck the file ACL after editing.

- [ ] **Step 5: Recreate and verify the running channel**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --force-recreate --no-build
```

Wait for health, then run:

```powershell
& $docker exec vibe-trading-vibe-trading-1 vibe-trading channels status
```

Expected: the API runtime and `weixin` adapter report running.

### Task 5: Pair Private Chat and Add Confirmed Groups

**Files:**
- Modify locally after confirmation: `F:\VibeTrading\config\agent.json`
- Persistent pairing state: Docker volume path `/home/vibe/.vibe-trading/pairing.json`

- [ ] **Step 1: Generate the private pairing request**

Ask the user to send `测试连接` to the WeChat bot conversation created by the authorization flow. Wait until WeChat returns a pairing code.

- [ ] **Step 2: Approve the sole pending WeChat pairing request locally**

Run:

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker exec vibe-trading-vibe-trading-1 python -c "from src.channels.pairing.store import approve_code,list_pending; pending=list_pending('weixin'); assert len(pending)==1, 'Unexpected pending request count: '+str(len(pending)); ok=approve_code(pending[0]['code'], restrict_channel='weixin') is not None; print('PAIRING_APPROVED='+str(ok))"
```

The code and sender ID remain inside the container process. The command prints only the approval boolean unless the pending-request count is not exactly one.

Expected: exactly one pending request and `PAIRING_APPROVED=True`. If there are zero or multiple requests, stop and ask the user to resolve which phone/chat generated the request.

- [ ] **Step 3: Verify private final-only messaging**

Ask the user to send:

```text
只回复：VIBE_WECHAT_OK
```

Expected: WeChat receives a final response containing `VIBE_WECHAT_OK`, with no progress messages and no tool-call hints.

- [ ] **Step 4: Discover one intended group ID safely**

For one group at a time, ask the user to send:

```text
VIBE群聊绑定测试
```

The first attempt must be denied. Inspect only new container logs for a single denied sender ending in `@chatroom`. Do not relay the raw ID in chat output. If more than one new group ID appears, stop and repeat with only one group sending a message.

- [ ] **Step 5: Add the confirmed group ID to the closed allowlist**

After the user confirms which group just sent the test, add the exact observed `@chatroom` ID to `channels.weixin.allow_from` in `F:\VibeTrading\config\agent.json`. Preserve all other fields and keep the list free of `"*"`.

Recreate the container so the channel manager reloads the structured config.

- [ ] **Step 6: Verify the allowed group**

Ask the group to send:

```text
只回复：VIBE_GROUP_OK
```

Expected: the group receives a final response containing `VIBE_GROUP_OK`. Any member of that group can trigger the bot, consistent with the accepted design constraint.

- [ ] **Step 7: Repeat for each additional selected group**

Repeat Steps 4-6 sequentially, one group at a time. Never enable a group whose ID cannot be uniquely associated with the user's test message.

### Task 6: Persistence and Security Verification

**Files:**
- No additional source changes.

- [ ] **Step 1: Recreate the container and verify login persistence**

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --force-recreate --no-build
```

Expected: the service becomes healthy, `weixin` returns to running without another QR prompt, and `TOKEN_PRESENT=True` when checked without printing the token.

- [ ] **Step 2: Verify container hardening and mounts**

Inspect the running container and confirm:

- Runtime user is `vibe`.
- Root filesystem is read-only.
- Published address is `127.0.0.1:8899`.
- Both `agent.env` and `agent.json` mounts are read-only.
- Memory is 4 GB, CPU is 2, PIDs limit is 512.
- Capabilities drop `ALL` and add only `SETUID`/`SETGID`.
- `no-new-privileges` is enabled.

- [ ] **Step 3: Scan logs and Git without exposing identifiers**

Load the API key and WeChat token into memory only, search recent logs for exact matches, and output booleans only. Confirm:

- API key is not present in logs.
- WeChat token is not present in logs.
- Neither secret is tracked by Git.
- `F:\VibeTrading\config\agent.json` is outside the repository.
- `docker-compose.local.yml` remains intentionally untracked.

- [ ] **Step 4: Run final regression tests**

Run:

```powershell
$docker = 'C:\Users\DELL\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
& $docker run --rm --user root `
  --mount type=bind,source='F:\VibeTrading\Vibe-Trading',target=/src,readonly `
  -w /src/agent --entrypoint sh vibe-trading-vibe-trading `
  -c "/opt/venv/bin/python -m pip install --disable-pip-version-check -q pytest pytest-socket ruff && /opt/venv/bin/python -m pytest tests/test_packaging_dependencies.py tests/test_channels_runtime.py tests/test_cli_channels.py tests/test_llm.py tests/test_llm_provider_defaults.py -q && /opt/venv/bin/python -m ruff check src/channels/weixin.py tests/test_packaging_dependencies.py"
```

Expected: all selected tests and Ruff checks pass.

- [ ] **Step 5: Record final state**

Run:

```powershell
git status --short --branch
git log -5 --oneline
& $docker compose -f docker-compose.yml -f docker-compose.local.yml ps
& $docker exec vibe-trading-vibe-trading-1 vibe-trading channels status
```

Expected: the branch contains the design, plan, dependency, and prior Responses API commits; only `docker-compose.local.yml` is untracked; the container and WeChat channel are running and healthy.

- [ ] **Step 6: Record the non-destructive rollback procedure**

Do not execute this during a successful installation. Record in the final handoff that rollback consists of:

1. Set `channels.weixin.enabled` to `false` in `F:\VibeTrading\config\agent.json`.
2. Remove `VIBE_TRADING_CHANNELS_AUTO_START=1` from `F:\VibeTrading\config\agent.env`.
3. Recreate only the Vibe-Trading container with the existing Compose files.
4. Retain the `vibe-home` volume by default so login and pairing state are not destroyed.
5. Delete `/home/vibe/.vibe-trading/weixin/account.json` or pairing state only after explicit user confirmation.

Expected: rollback disables the WeChat transport without changing the Web UI, model provider, research sessions, or broker-isolation posture.
