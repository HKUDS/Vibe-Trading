# Channels Adapter Catalog

Core: `base.py` → `bus/` → `runtime.py` (inbound→SessionService) + `manager.py` (outbound).

Adapters analyzed: **16**.

| name | display | file | lines | _handle override | libs (hint) | doc |
|------|---------|------|------:|:----------------:|-------------|-----|
| `dingtalk` | DingTalk | `dingtalk.py` | 774 |  | `httpx`, `pydantic`, `zipfile` | DingTalk/DingDing channel implementation using Stream Mode. |
| `discord` | Discord | `discord.py` | 819 |  | `__future__`, `importlib`, `pydantic` | Discord channel implementation using discord.py. |
| `email` | Email | `email.py` | 915 |  | `email`, `fnmatch`, `imaplib`, `pydantic`, `smtplib` | Email channel implementation using IMAP polling + SMTP replies. |
| `feishu` | Feishu | `feishu.py` | 2360 |  | `__future__`, `importlib`, `pydantic`, `rich` | Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection. |
| `matrix` | Matrix | `matrix.py` | 1033 |  | `pydantic` | Matrix (Element) channel — inbound sync + outbound message/media delivery. |
| `mochat` | Mochat | `mochat.py` | 944 |  | `__future__`, `httpx`, `pydantic` | Mochat channel implementation using Socket.IO with HTTP polling fallback. |
| `msteams` | Microsoft Teams | `msteams.py` | 823 |  | `__future__`, `httpx`, `importlib`, `pydantic` | Microsoft Teams channel MVP using a tiny built-in HTTP webhook server. |
| `napcat` | Napcat (QQ) | `napcat.py` | 581 |  | `__future__`, `aiohttp`, `pydantic`, `random`, `websockets` | Napcat (OneBot v11) channel for QQ, over WebSocket. |
| `qq` | QQ | `qq.py` | 715 |  | `__future__`, `aiohttp`, `pydantic` | QQ channel implementation using botpy SDK. |
| `signal` | Signal | `signal.py` | 1421 | Y | `__future__`, `httpx`, `pydantic`, `unicodedata` | Signal channel implementation using signal-cli daemon JSON-RPC interface. |
| `slack` | Slack | `slack.py` | 741 |  | `httpx`, `pydantic`, `slack_sdk`, `slackify_markdown` | Slack channel implementation using Socket Mode. |
| `telegram` | Telegram | `telegram.py` | 1691 |  | `__future__`, `pydantic`, `telegram`, `unicodedata` | Telegram channel implementation using python-telegram-bot. |
| `websocket` | WebSocket | `websocket.py` | 1204 |  | `__future__`, `pydantic`, `websockets` | WebSocket server channel: vibe-trading acts as a WebSocket server and serves connected clients. |
| `wecom` | WeCom | `wecom.py` | 555 |  | `importlib`, `pydantic` | WeCom (Enterprise WeChat) channel implementation using wecom_aibot_sdk. |
| `weixin` | WeChat | `weixin.py` | 1587 |  | `__future__`, `httpx`, `pydantic`, `random` | Personal WeChat (微信) channel using HTTP long-poll API. |
| `whatsapp` | WhatsApp | `whatsapp.py` | 683 |  | `__future__`, `pydantic`, `secrets` | WhatsApp channel implementation using neonize. |

## Per-adapter notes (from code structure)

### `dingtalk`

- class: `DingTalkChannel` (774 lines)
- start/send: yes / yes
- note: dingtalk_stream Stream Mode.

### `discord`

- class: `DiscordChannel` (819 lines)
- start/send: yes / yes
- note: discord.py gateway; thread session_key.

### `email`

- class: `EmailChannel` (915 lines)
- start/send: yes / yes
- note: IMAP poll + SMTP reply.

### `feishu`

- class: `FeishuChannel` (2360 lines)
- start/send: yes / yes
- note: lark_oapi WebSocket.

### `matrix`

- class: `MatrixChannel` (1033 lines)
- start/send: yes / yes
- note: matrix-nio sync; workspace restrict kwargs.

### `mochat`

- class: `MochatChannel` (944 lines)
- start/send: yes / yes
- note: Socket.IO + HTTP polling fallback.

### `msteams`

- class: `MSTeamsChannel` (823 lines)
- start/send: yes / yes
- note: Bot Framework webhook HTTP (DM MVP).

### `napcat`

- class: `NapcatChannel` (581 lines)
- start/send: yes / yes
- note: OneBot v11 WebSocket.

### `qq`

- class: `QQChannel` (715 lines)
- start/send: yes / yes
- note: botpy official QQ bot.

### `signal`

- class: `SignalChannel` (1421 lines)
- start/send: yes / yes
- note: signal-cli REST/JSON-RPC; **overrides _handle_message** (direct publish).

### `slack`

- class: `SlackChannel` (741 lines)
- start/send: yes / yes
- note: Socket Mode; emoji react progress.

### `telegram`

- class: `TelegramChannel` (1691 lines)
- start/send: yes / yes
- note: python-telegram-bot long polling; media download; pairing via BaseChannel.

### `websocket`

- class: `WebSocketChannel` (1204 lines)
- start/send: yes / yes
- note: Local WS/Unix + channelsui gateway for WebUI.

### `wecom`

- class: `WecomChannel` (555 lines)
- start/send: yes / yes
- note: enterprise WeCom aibot SDK.

### `weixin`

- class: `WeixinChannel` (1587 lines)
- start/send: yes / yes
- note: personal WeChat HTTP long-poll (ilink).

### `whatsapp`

- class: `WhatsAppChannel` (683 lines)
- start/send: yes / yes
- note: neonize WhatsApp Web; rich media.
