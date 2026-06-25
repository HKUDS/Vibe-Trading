import asyncio
import json
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional, Set

from src.platforms.base import BasePlatformAdapter, IncomingMessage

logger = logging.getLogger(__name__)

# Lazy imports for lark-oapi
lark = None
FeishuWSClient = None
CreateMessageRequest = None
CreateMessageRequestBody = None
UpdateMessageRequest = None
UpdateMessageRequestBody = None
PatchMessageRequest = None
PatchMessageRequestBody = None
EventDispatcherHandler = None


def _ensure_lark_imports():
    global lark, FeishuWSClient, CreateMessageRequest, CreateMessageRequestBody, UpdateMessageRequest, UpdateMessageRequestBody, PatchMessageRequest, PatchMessageRequestBody, EventDispatcherHandler
    if lark is not None:
        return
    import lark_oapi
    from lark_oapi.ws import Client as FeishuWSClient
    from lark_oapi.api.im.v1.model.create_message_request import CreateMessageRequest
    from lark_oapi.api.im.v1.model.create_message_request_body import CreateMessageRequestBody
    from lark_oapi.api.im.v1.model.update_message_request import UpdateMessageRequest
    from lark_oapi.api.im.v1.model.update_message_request_body import UpdateMessageRequestBody
    from lark_oapi.api.im.v1.model.patch_message_request import PatchMessageRequest
    from lark_oapi.api.im.v1.model.patch_message_request_body import PatchMessageRequestBody
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
    lark = lark_oapi

    # Monkey patch lark-oapi's ws client loop to be thread-local event loop proxy
    import lark_oapi.ws.client
    import asyncio

    class LoopProxy:
        def __getattr__(self, name):
            try:
                return getattr(asyncio.get_event_loop(), name)
            except RuntimeError:
                # If no loop in this thread, automatically create one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                return getattr(loop, name)
            
        def __str__(self):
            try:
                return str(asyncio.get_event_loop())
            except RuntimeError:
                return "No running event loop"
            
        def __repr__(self):
            try:
                return repr(asyncio.get_event_loop())
            except RuntimeError:
                return "<No running event loop>"

    lark_oapi.ws.client.loop = LoopProxy()
    logger.info("[Feishu] Applied thread-local event loop proxy patch to lark-oapi ws client.")


class FeishuAdapter(BasePlatformAdapter):
    """Feishu/Lark messenger platform adapter using official lark-oapi WebSocket client."""

    def __init__(
        self,
        channel_id: str,
        name: str,
        app_id: str,
        app_secret: str,
        allowed_users: str = "",
        allow_all_users: bool = False,
    ) -> None:
        self._channel_id: str = channel_id
        self._name: str = name
        self._app_id: str = app_id.strip()
        self._app_secret: str = app_secret.strip()
        self._allowed_users: Set[str] = {uid.strip() for uid in allowed_users.split(",") if uid.strip()} if allowed_users else set()
        self._allow_all_users: bool = allow_all_users
        
        self._client: Optional[Any] = None
        self._ws_client: Optional[Any] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._manager: Optional[Any] = None
        
        # Throttled card update states
        self._pending_card_updates: Dict[str, tuple[str, str, str]] = {}  # msg_id -> (chat_id, title, content)
        self._pending_card_statuses: Dict[str, str] = {}  # msg_id -> status ("running"/"success"/"failed")
        self._card_updater_task: Optional[asyncio.Task] = None
        self._is_running: bool = False

    @property
    def platform_name(self) -> str:
        return f"feishu_{self._channel_id}"

    @property
    def display_name(self) -> str:
        return self._name

    async def initialize(self, manager: Any) -> None:
        _ensure_lark_imports()
        self._manager = manager
        
        if not self._app_id or not self._app_secret:
            logger.warning(f"[Feishu] App ID or App Secret is not configured for channel {self._name}. Channel disabled.")
            return

        # Initialize Lark API Client (HTTP client)
        domain = os.getenv("FEISHU_DOMAIN", "https://open.feishu.cn").strip()
        self._client = lark.Client.builder().app_id(self._app_id).app_secret(self._app_secret).domain(domain).build()

        self._is_running = True
        self._card_updater_task = asyncio.create_task(self._card_flush_loop())
        
        # Start WebSocket Client in a dedicated background thread with isolated event loop
        self._ws_thread = threading.Thread(
            target=self._run_ws_client_thread,
            name=f"feishu-ws-{self._channel_id}",
            daemon=True
        )
        self._ws_thread.start()
        logger.info(f"[Feishu] WebSocket adapter initialized and started in dedicated thread for channel: {self._name}")

    def _run_ws_client_thread(self) -> None:
        logger.info(f"[Feishu WS Thread] Thread started for channel '{self._name}' ({self._channel_id}).")
        import time

        # 只要外部 adapter 仍在运行，就在此循环内保持 WS 客户端活跃
        while self._is_running:
            try:
                # 每次重连前，创建一个全新的 event loop 确保环境干净
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._ws_loop = loop
                
                # 为该轮连接实例化一个全新的 FeishuWSClient
                domain = os.getenv("FEISHU_DOMAIN", "https://open.feishu.cn").strip()
                event_handler = (
                    EventDispatcherHandler.builder("", "")
                    .register_p2_im_message_receive_v1(self._on_message_received)
                    .build()
                )
                self._ws_client = FeishuWSClient(
                    app_id=self._app_id,
                    app_secret=self._app_secret,
                    log_level=lark.LogLevel.INFO,
                    event_handler=event_handler,
                    domain=domain,
                )
                
                logger.info(f"[Feishu WS Thread] Launching custom start sequence for channel '{self._name}'...")
                loop.run_until_complete(self._custom_start())
                logger.info(f"[Feishu WS Thread] Custom start sequence returned for channel '{self._name}'.")
            except Exception as e:
                logger.exception(f"[Feishu WS Thread] Error running WebSocket client sequence: %s", e)
            finally:
                # 确保当前 loop 彻底关闭，并在关闭前取消所有 pending 任务，避免垃圾回收时报错
                try:
                    if hasattr(self, "_ws_loop") and self._ws_loop and not self._ws_loop.is_closed():
                        pending = asyncio.all_tasks(self._ws_loop)
                        for task in pending:
                            task.cancel()
                        if pending:
                            self._ws_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        self._ws_loop.close()
                except Exception as ce:
                    logger.warning("[Feishu WS Thread] Error closing event loop: %s", ce)
            
            # 如果依然在运行，等待 5 秒后触发下一次重建与重连
            if self._is_running:
                logger.info(f"[Feishu WS Thread] Connection lost or failed to start. Re-trying in 5 seconds...")
                time.sleep(5)
        
        logger.info(f"[Feishu WS Thread] Thread exiting for channel '{self._name}'.")

    async def _custom_start(self) -> None:
        """自定义启动逻辑，避开官方 start() 内部对 _select() 的死等，实现可靠的断线检测。"""
        from websockets.protocol import State
        
        # 1. 触发连接
        try:
            logger.info("[Feishu] Custom start: Attempting initial connection...")
            await self._ws_client._connect()
            logger.info("[Feishu] Custom start: Initial connection successful.")
        except Exception as e:
            logger.error("[Feishu] Custom start: Initial connection failed: %s. Initiating client reconnect...", e)
            await self._ws_client._disconnect()
            await self._ws_client._reconnect()
            logger.info("[Feishu] Custom start: Reconnect finished.")

        # 2. 启动心跳 ping 循环
        ping_task = self._ws_loop.create_task(self._ws_client._ping_loop())
        logger.info("[Feishu] Custom start: Heartbeat ping loop started.")

        # 3. 监控连接状态，发现异常即退出循环以触发外层重建
        try:
            while self._is_running:
                await asyncio.sleep(2)
                # 检测底层 websockets.WebSocketClientProtocol 状态
                conn = self._ws_client._conn
                if conn is None or conn.state != State.OPEN:
                    logger.warning("[Feishu] Custom start: WS connection detected as closed or not OPEN.")
                    break
        except asyncio.CancelledError:
            logger.info("[Feishu] Custom start: Monitor loop cancelled.")
        except Exception as me:
            logger.error("[Feishu] Custom start: Exception in monitor loop: %s", me)
        finally:
            # 清理 ping_task 和连接
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
            
            logger.info("[Feishu] Custom start: Cleaning up WS connection...")
            await self._ws_client._disconnect()

    def _on_message_received(self, data: Any) -> None:
        """Invoked by lark-oapi on a background thread when a new message arrives."""
        print(f"[Feishu WS Event] Raw message event received from Feishu Gateway!", flush=True)
        try:
            event = getattr(data, "event", None)
            message = getattr(event, "message", None)
            sender = getattr(event, "sender", None)
            if not message or not sender:
                print(f"[Feishu WS Event] Warning: Missing message or sender in event data.", flush=True)
                return

            message_id = getattr(message, "message_id", "")
            chat_id = getattr(message, "chat_id", "")
            raw_content = getattr(message, "content", "")
            message_type = getattr(message, "message_type", "")
            sender_id = getattr(sender, "sender_id", None)
            sender_open_id = getattr(sender_id, "open_id", "") if sender_id else ""

            if not message_id or not chat_id or not sender_open_id:
                print(f"[Feishu WS Event] Warning: Missing message_id, chat_id, or sender_open_id in event.", flush=True)
                return

            # Parse message content first (needed for both public commands and authorized checks)
            text_content = ""
            if message_type.lower() == "text":
                try:
                    payload = json.loads(raw_content)
                    text_content = payload.get("text", "").strip()
                except Exception:
                    text_content = raw_content.strip()
            else:
                print(f"[Feishu WS Event] Warning: Ignored non-text message type: {message_type}", flush=True)
                # Skip non-text messages for now
                return

            print(f"[Feishu WS Event] Received text: '{text_content}' from user {sender_open_id} in chat {chat_id}", flush=True)

            # Feature: Help users fetch their OpenID directly from the Bot
            if text_content.lower() in ("/myid", "/id", "myid", "id", "我的id", "我的openid", "我的id是什么", "获取id"):
                print(f"[Feishu WS Event] ID command detected! Sending OpenID back to user...", flush=True)
                asyncio.run_coroutine_threadsafe(
                    self.send_message(chat_id, f"您的飞书 OpenID 是:\n`{sender_open_id}`"),
                    asyncio.get_event_loop()
                )
                return

            # Check authorization
            if not self._allow_all_users and self._allowed_users and sender_open_id not in self._allowed_users:
                print(f"[Feishu WS Event] User {sender_open_id} is unauthorized. Allowed: {self._allowed_users}. Replying with block message...", flush=True)
                logger.warning("[Feishu] Unauthorized user %s tried to send message: %s", sender_open_id, message_id)
                # Send polite unauthorized message back with their OpenID
                err_msg = (
                    f"⚠️ 您没有权限使用此智能体系统。请联系管理员将您的 OpenID 添加到白名单。\n\n"
                    f"您的 OpenID 是:\n`{sender_open_id}`"
                )
                asyncio.run_coroutine_threadsafe(
                    self.send_message(chat_id, err_msg),
                    asyncio.get_event_loop()
                )
                return

            # Remove self mentions if in group chats
            if "@_all" in text_content:
                pass # Can parse if needed

            incoming = IncomingMessage(
                platform=self.platform_name,
                chat_id=chat_id,
                message_id=message_id,
                content=text_content,
                sender_id=sender_open_id,
                timestamp=float(getattr(event, "create_time", 0)) / 1000.0,
                raw_payload=data.event,
            )

            # Route to Manager (which runs in the main asyncio loop)
            if self._manager:
                self._manager.submit_incoming_message(incoming)

        except Exception as e:
            logger.exception("[Feishu] Error processing incoming message: %s", e)

    async def send_message(
        self,
        chat_id: str,
        content: str,
        title: Optional[str] = None,
    ) -> str:
        _ensure_lark_imports()
        
        # Always deliver via interactive markdown cards to ensure rich-text formatting (bold, tables, code blocks)
        card_json = self._build_card_json(title, content, "running" if title else "success")
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(card_json)
            .build()
        )
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        loop = asyncio.get_running_loop()
        try:
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._client.im.v1.message.create(request)
                ),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.error("[Feishu] Timeout sending message to chat %s after 10 seconds", chat_id)
            raise RuntimeError(f"Timeout sending message to chat {chat_id}")
        except Exception as e:
            logger.error("[Feishu] Exception sending message to chat %s: %s", chat_id, e)
            raise e

        if response.code != 0:
            logger.error("[Feishu] Failed to send message: %s (%s)", response.msg, response.code)
            raise RuntimeError(f"Feishu send failed: {response.msg}")

        # Parse message ID from response data
        data_dict = json.loads(response.raw.content.decode("utf-8"))
        msg_id = data_dict.get("data", {}).get("message_id", "")
        return msg_id

    async def update_message(
        self,
        chat_id: str,
        message_id: str,
        content: str,
        title: Optional[str] = None,
    ) -> None:
        # Rather than sending API request instantly, we mark it as pending
        # The background loop will flush it to comply with Feishu rate limits.
        status = self._pending_card_statuses.get(message_id, "running")
        self._pending_card_updates[message_id] = (chat_id, title, content)
        self._pending_card_statuses[message_id] = status

    async def update_message_immediate(
        self,
        chat_id: str,
        message_id: str,
        content: str,
        title: Optional[str],
        status: str,
    ) -> None:
        _ensure_lark_imports()
        card_json = self._build_card_json(title, content, status)
        body = (
            PatchMessageRequestBody.builder()
            .content(card_json)
            .build()
        )
        request = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )

        loop = asyncio.get_running_loop()
        try:
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._client.im.v1.message.patch(request)
                ),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.error("[Feishu] Timeout updating message %s via API after 10 seconds", message_id)
            raise RuntimeError(f"Timeout updating message {message_id}")
        except Exception as e:
            logger.error("[Feishu] Exception updating message %s via API: %s", message_id, e)
            raise e

        if response.code != 0:
            raw_err = response.raw.content.decode("utf-8") if response.raw else "No raw content"
            logger.warning("[Feishu] Failed to update message %s: %s (code %s). Raw response: %s", message_id, response.msg, response.code, raw_err)
        else:
            logger.info("[Feishu] Successfully updated message %s", message_id)

    def set_message_status(self, message_id: str, status: str) -> None:
        """Mark a pending update message status as success or failed."""
        self._pending_card_statuses[message_id] = status

    async def _card_flush_loop(self) -> None:
        """Background loop that flushes card updates once every 1.5 seconds to prevent rate-limiting."""
        retries_limit = 3
        failed_msg_retries = {}  # msg_id -> count

        while self._is_running:
            try:
                await asyncio.sleep(1.5)
                if not self._pending_card_updates:
                    continue

                # Take a snapshot of pending updates to process
                to_update = list(self._pending_card_updates.keys())
                for msg_id in to_update:
                    update_data = self._pending_card_updates.get(msg_id)
                    if not update_data:
                        continue
                    chat_id, title, content = update_data
                    status = self._pending_card_statuses.get(msg_id, "running")
                    
                    try:
                        await self.update_message_immediate(chat_id, msg_id, content, title, status)
                        # 成功后，从 pending 中 pop 掉，并清除重试计数
                        self._pending_card_updates.pop(msg_id, None)
                        self._pending_card_statuses.pop(msg_id, None)
                        failed_msg_retries.pop(msg_id, None)
                    except Exception as e:
                        logger.error("[Feishu] Failed to update card %s in flush loop: %s", msg_id, e)
                        
                        # 增加重试计数
                        count = failed_msg_retries.get(msg_id, 0) + 1
                        if count >= retries_limit:
                            logger.error("[Feishu] Card %s update reached retry limit (%d). Dropping update.", msg_id, retries_limit)
                            self._pending_card_updates.pop(msg_id, None)
                            self._pending_card_statuses.pop(msg_id, None)
                            failed_msg_retries.pop(msg_id, None)
                        else:
                            failed_msg_retries[msg_id] = count
                            # 保留在 pending 中，等下一次循环重试
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Feishu] Error in card flush loop: %s", e)

    def _parse_markdown_into_elements(self, text: str) -> List[Dict[str, Any]]:
        if not text:
            return [{"tag": "markdown", "content": "..."}]
            
        elements = []
        lines = text.split("\n")
        n = len(lines)
        i = 0
        current_md_chunk = []
        
        def flush_md_chunk():
            if current_md_chunk:
                md_text = "\n".join(current_md_chunk)
                chunk_size = 15000
                for offset in range(0, len(md_text), chunk_size):
                    elements.append({
                        "tag": "markdown",
                        "content": md_text[offset:offset+chunk_size]
                    })
                current_md_chunk.clear()
                
        while i < n:
            line = lines[i]
            stripped = line.strip()
            if (stripped.startswith("|") and stripped.endswith("|") and 
                i + 1 < n and 
                lines[i+1].strip().startswith("|") and 
                lines[i+1].strip().endswith("|") and 
                re.match(r"^\|\s*[:-]+[\s:-]*\|", lines[i+1].strip())):
                
                flush_md_chunk()
                
                headers = [c.strip() for c in stripped.split("|")]
                if len(headers) > 1 and headers[0] == "":
                    headers = headers[1:]
                if len(headers) > 0 and headers[-1] == "":
                    headers = headers[:-1]
                
                i += 2
                
                rows_data = []
                while i < n and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                    row_cells = [c.strip() for c in lines[i].split("|")]
                    if len(row_cells) > 1 and row_cells[0] == "":
                        row_cells = row_cells[1:]
                    if len(row_cells) > 0 and row_cells[-1] == "":
                        row_cells = row_cells[:-1]
                    
                    while len(row_cells) < len(headers):
                        row_cells.append("")
                    if len(row_cells) > len(headers):
                        row_cells = row_cells[:len(headers)]
                        
                    rows_data.append(row_cells)
                    i += 1
                    
                columns = [
                    {
                        "name": f"col_{idx}",
                        "display_name": header or f"列 {idx+1}",
                        "data_type": "text"
                    }
                    for idx, header in enumerate(headers)
                ]
                rows = [
                    {
                        f"col_{idx}": val for idx, val in enumerate(row_cells)
                    }
                    for row_cells in rows_data
                ]
                
                elements.append({
                    "tag": "table",
                    "columns": columns,
                    "rows": rows
                })
            else:
                current_md_chunk.append(line)
                i += 1
                
        flush_md_chunk()
        return elements

    def _preprocess_markdown(self, text: str) -> str:
        if not text:
            return text
            
        # 1. 转换标题 ## -> 加粗并加 Emoji 前缀，使排版更清晰端正，支持飞书 Markdown
        text = re.sub(r'(?m)^#\s+(.*)$', r'**👑 \1**', text)
        text = re.sub(r'(?m)^##\s+(.*)$', r'**■ \1**', text)
        text = re.sub(r'(?m)^###\s+(.*)$', r'**○ \1**', text)
        
        return text

    def _build_card_json(self, title: Optional[str], content: str, status: str = "running") -> str:
        # 在构建 JSON 卡片内容的最开始，对 Markdown 进行预处理，转换标题
        content = self._preprocess_markdown(content)

        template_color = "blue"
        if status == "success":
            template_color = "green"
        elif status == "failed":
            template_color = "red"
            
        elements = self._parse_markdown_into_elements(content)
        
        card = {
            "schema": "2.0",
            "config": {
                "wide_screen_mode": True
            },
            "body": {
                "elements": elements
            }
        }
        
        if title:
            card["header"] = {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": template_color
            }
            
        return json.dumps(card, ensure_ascii=False)

    def _stop_ws_client_thread(self) -> None:
        try:
            if hasattr(self._ws_client, "stop"):
                self._ws_client.stop()
            elif hasattr(self._ws_client, "_disconnect"):
                loop = getattr(self, "_ws_loop", None)
                if loop and loop.is_running():
                    if asyncio.iscoroutinefunction(self._ws_client._disconnect):
                        future = asyncio.run_coroutine_threadsafe(self._ws_client._disconnect(), loop)
                        try:
                            future.result(timeout=3.0)
                        except Exception as te:
                            logger.warning("[Feishu] Timeout or error awaiting _disconnect: %s", te)
                    else:
                        loop.call_soon_threadsafe(self._ws_client._disconnect)
                else:
                    temp_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(temp_loop)
                    if asyncio.iscoroutinefunction(self._ws_client._disconnect):
                        temp_loop.run_until_complete(self._ws_client._disconnect())
                    else:
                        self._ws_client._disconnect()
        except Exception as e:
            logger.exception("[Feishu] Error stopping WebSocket client in thread: %s", e)

    async def close(self) -> None:
        self._is_running = False
        if self._card_updater_task:
            self._card_updater_task.cancel()
            try:
                await self._card_updater_task
            except asyncio.CancelledError:
                pass
        
        if self._ws_client:
            logger.info("[Feishu] Shutting down Feishu WebSocket client...")
            try:
                stop_thread = threading.Thread(
                    target=self._stop_ws_client_thread,
                    name=f"feishu-ws-stop-{self._channel_id}",
                    daemon=True
                )
                stop_thread.start()
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, stop_thread.join)
            except Exception as e:
                logger.warning("[Feishu] Error stopping WebSocket client: %s", e)
                
        logger.info("[Feishu] WebSocket adapter shut down.")
