# Personal WeChat Channel Design

**Date:** 2026-07-23
**Status:** Approved design, pending implementation plan

## Goal

Connect the existing Docker-isolated Vibe-Trading installation to the user's
personal WeChat account so WeChat can serve as a chat and final-notification
entry point. The first release supports the user's private chat and an explicit
allowlist of selected WeChat groups. It does not connect to a broker or execute
orders.

## Accepted Constraints

- The user will scan with their primary personal WeChat account and accepts the
  session-expiry, rate-limit, and account-control risks of the reverse-engineered
  iLink adapter.
- Selected groups are authorized at the group-ID level. Any member of an
  allowed group can trigger Vibe-Trading; per-member authorization inside a
  group is not available in the current adapter.
- WeChat sends only final answers and important completion notifications.
  Progress messages and tool-call hints remain disabled.
- Content submitted through WeChat is processed by the configured cloud model
  gateway at `http://219.223.200.237:8080`. This transport is not protected by
  TLS, so broker credentials, identity documents, and unsanitized trading
  records must not be sent through WeChat.

## Architecture

The existing `weixin` channel adapter remains the only messaging integration
component. No new channel implementation is introduced.

- Host-managed structured config:
  `F:\VibeTrading\config\agent.json`
- Container config mount:
  `/home/vibe/.vibe-trading/agent.json`, read-only
- Persistent authentication and channel state:
  the existing `vibe-home` Docker named volume
- WeChat account state:
  `/home/vibe/.vibe-trading/weixin/account.json`
- Pairing state:
  `/home/vibe/.vibe-trading/pairing.json`
- Channel-to-session mapping:
  `/home/vibe/.vibe-trading/channels/sessions.json`

The Docker image will include the locked `qrcode` dependency so interactive
login can render a QR code locally without sending the login URL to an external
QR-code service.

## Configuration

The structured config uses a closed allowlist and final-only delivery:

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

`VIBE_TRADING_CHANNELS_AUTO_START=1` will be added to the protected runtime
environment so the enabled adapter starts when the API container starts.

The initial `allow_from` list is empty. Private access is granted through the
pairing store. Group IDs are added only after an attempted message from the
group is observed in local container logs and the operator confirms that the
observed ID belongs to the intended group. A wildcard allowlist is prohibited.

## Onboarding Flow

1. Add `qrcode>=7.4.2` to the hash-locked runtime dependencies and rebuild the
   image.
2. Create the ACL-restricted host `agent.json` and mount it read-only.
3. Recreate the container and verify that `weixin` is configured and available.
4. Run the interactive WeChat login command in the container.
5. The user scans and confirms the QR code in WeChat.
6. Restart the channel runtime and verify that WeChat is running.
7. The user sends a private test message and receives a pairing code.
8. Approve the pairing code only through the local Docker CLI.
9. Verify a private research request returns a final answer without progress
   chatter.
10. For each intended group, send a harmless test message, identify the denied
    `@chatroom` ID from local logs, confirm the group, add it to `allow_from`,
    and recreate the container.
11. Verify allowed groups work and an unlisted group remains denied.

## Security Boundaries

- Never commit `agent.json`, WeChat account state, pairing state, sender IDs, or
  group IDs.
- Restrict the host config ACL to the current Windows user and SYSTEM.
- Mount structured config read-only in the container.
- Keep the API bound to `127.0.0.1`; the WeChat adapter makes only outbound
  connections to the WeChat service.
- Do not place broker credentials in the channel config or WeChat messages.
- Approve private senders through the local CLI, not through an untrusted chat.
- Do not configure `allow_from: ["*"]`.
- Do not treat a WeChat message as authorization to place a live order. A later
  order-confirmation service must use immutable order summaries, one-time
  confirmation codes, explicit sender validation, and expiration.

## Failure Handling

- If QR login fails, leave the channel disabled or stopped and preserve the Web
  UI and model runtime.
- If the session expires, require a new explicit QR login; do not bypass or
  silently replace authentication.
- If WeChat rate limits outbound messages, retain final-only delivery and use
  the adapter's bounded retry behavior rather than increasing message volume.
- If a group cannot be identified with confidence, do not add its ID.
- If startup fails, disable `channels.weixin`, recreate the container, and keep
  the rest of Vibe-Trading operational.

## Verification

Implementation is complete only when all of the following are demonstrated:

- The dependency lock installs with hashes and the Docker image builds.
- Existing provider and channel tests pass.
- `vibe-trading channels status --local` reports `weixin` configured, enabled,
  available, and loaded.
- QR login succeeds without exposing the token in terminal output or logs.
- Private pairing succeeds and an approved private message receives a model
  response.
- No progress messages or tool hints are delivered.
- An unlisted group is denied, then an explicitly confirmed group ID works after
  allowlist configuration.
- The WeChat login state survives container recreation.
- The service remains healthy, loopback-only, non-root, and read-only-rootfs.
- Git contains no API key, WeChat token, sender ID, or group ID values. Recent
  container logs contain no API key or WeChat token, and verification output
  does not disclose observed sender or group IDs.

## Rollback

Set `channels.weixin.enabled` to `false`, remove
`VIBE_TRADING_CHANNELS_AUTO_START`, and recreate the container. The Web UI,
model configuration, research sessions, and existing data volumes remain
untouched. Account and pairing state may be retained for later reactivation or
deleted only after explicit user confirmation.
