import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from src.platforms.base import BasePlatformAdapter, IncomingMessage

logger = logging.getLogger(__name__)


class PlatformManager:
    """Manages active messaging platform adapters and orchestrates session flow."""

    def __init__(self, session_service: Any) -> None:
        self.session_service = session_service
        self._adapters: Dict[str, BasePlatformAdapter] = {}
        self._running_trackers: Dict[str, asyncio.Task] = {}  # session_id -> tracking task

    def register_adapter(self, adapter: BasePlatformAdapter) -> None:
        """Register a platform adapter."""
        self._adapters[adapter.platform_name] = adapter
        logger.info("[PlatformManager] Registered platform adapter: %s", adapter.platform_name)

    async def start(self) -> None:
        """Initialize and start all registered platform adapters."""
        for adapter in self._adapters.values():
            try:
                await adapter.initialize(self)
            except Exception as e:
                logger.exception("[PlatformManager] Failed to start adapter %s: %s", adapter.platform_name, e)

    async def stop(self) -> None:
        """Close and clean up all registered platform adapters."""
        for adapter in self._adapters.values():
            try:
                await adapter.close()
            except Exception as e:
                logger.exception("[PlatformManager] Failed to close adapter %s: %s", adapter.platform_name, e)

    def submit_incoming_message(self, incoming: IncomingMessage) -> None:
        """Invoked by platform adapters when a new user message is received.

        Runs the message handling flow in a non-blocking asyncio task.
        """
        asyncio.create_task(self.handle_incoming_message(incoming))

    async def handle_incoming_message(self, incoming: IncomingMessage) -> None:
        """Orchestrate the message mapping, Session generation, and progress tracking."""
        try:
            adapter = self._adapters.get(incoming.platform)
            if not adapter:
                logger.error("[PlatformManager] Received message for unregistered platform: %s", incoming.platform)
                return

            # Check for reset/new session command
            cmd = incoming.content.lower().strip()
            if cmd in ("/new", "new", "/reset", "reset", "新建会话", "重置会话"):
                logger.info(
                    "[PlatformManager] Reset session command received for %s (chat: %s)",
                    incoming.platform, incoming.chat_id
                )
                await self._unbind_existing_sessions(incoming)
                
                # Send confirmation text back
                await adapter.send_message(
                    chat_id=incoming.chat_id,
                    content="🎉 **已成功重置会话！**\n我已为您开启了一个全新的量化投研沙箱，之前的历史会话已封存归档。您可以随时发送您的问题以开始新的一轮分析。"
                )
                return

            # 1. Resolve Session ID (or create one)
            session_id = await self._resolve_or_create_session(incoming)

            # 2. Trigger backend agent execution
            # Enable shell tools for authenticated API/Bot interactions
            response = await self.session_service.send_message(
                session_id=session_id,
                content=incoming.content,
                role="user",
                include_shell_tools=True,
            )

            attempt_id = response.get("attempt_id")
            if not attempt_id:
                # No execution attempt was spawned (e.g. system message or error)
                return

            # 3. Spawn background progress tracker to update Feishu card
            # Cancel any existing active tracking task for this session to avoid overlap
            if session_id in self._running_trackers:
                existing_task = self._running_trackers[session_id]
                if not existing_task.done():
                    existing_task.cancel()

            tracker_task = asyncio.create_task(
                self._track_session_progress(
                    adapter=adapter,
                    chat_id=incoming.chat_id,
                    session_id=session_id,
                    attempt_id=attempt_id,
                    user_prompt=incoming.content
                )
            )
            self._running_trackers[session_id] = tracker_task

        except Exception as e:
            logger.exception("[PlatformManager] Error handling incoming message: %s", e)

    async def _resolve_or_create_session(self, incoming: IncomingMessage) -> str:
        """Lookup an existing session mapped to chat_id, or create a new one."""
        loop = asyncio.get_running_loop()
        
        # Load sessions from store
        sessions = await loop.run_in_executor(
            None,
            lambda: self.session_service.store.list_sessions(limit=200)
        )

        for session in sessions:
            config = session.config or {}
            if (
                config.get("platform") == incoming.platform 
                and config.get("platform_chat_id") == incoming.chat_id
            ):
                logger.info(
                    "[PlatformManager] Mapped incoming message from %s (chat: %s) to existing session: %s",
                    incoming.platform, incoming.chat_id, session.session_id
                )
                return session.session_id

        # None found, create a new session
        adapter = self._adapters.get(incoming.platform)
        display_name = getattr(adapter, "display_name", incoming.platform.capitalize())
        
        # 自动将会话标题从首条真实消息生成
        clean_content = " ".join(incoming.content.split())
        for prefix in ("/goal", "/plan", "/research", "/run"):
            if clean_content.lower().startswith(prefix):
                clean_content = clean_content[len(prefix):].strip()
                break
        
        if clean_content:
            title = f"💬 {clean_content[:15]}..." if len(clean_content) > 15 else f"💬 {clean_content}"
        else:
            title = f"{display_name} 会话 ({incoming.chat_id[:8]})"
            
        config = {
            "platform": incoming.platform,
            "platform_chat_id": incoming.chat_id,
        }

        # Create session in executor to avoid blockages
        new_session = await loop.run_in_executor(
            None,
            lambda: self.session_service.create_session(title=title, config=config)
        )

        logger.info(
            "[PlatformManager] Created new session %s for platform %s (chat: %s)",
            new_session.session_id, incoming.platform, incoming.chat_id
        )
        return new_session.session_id

    async def _track_session_progress(
        self,
        adapter: BasePlatformAdapter,
        chat_id: str,
        session_id: str,
        attempt_id: str,
        user_prompt: str,
    ) -> None:
        """Subscribe to EventBus and update progress cards in real-time."""
        progress_msg_id = None
        current_thinking = ""
        current_text = ""
        current_status = "💡 正在启动智能体..."
        
        # Helper to format status card content
        def build_progress_markdown(show_preview: bool = True) -> str:
            lines = [
                f"**您的问题：** {user_prompt[:200]}...",
                "---",
                f"**当前状态：** {current_status}"
            ]
            if current_thinking:
                lines.append(f"**思考中：**\n> {current_thinking}")
            if current_text and show_preview:
                lines.append("---")
                lines.append("**最新回答预览：**")
                # Expose a preview of the response
                lines.append(current_text[-1000:] + ("..." if len(current_text) > 1000 else ""))
            return "\n".join(lines)

        try:
            # Send initial progress card
            title = "Vibe-Trading 量化分析智能体"
            progress_msg_id = await adapter.send_message(
                chat_id=chat_id,
                content=build_progress_markdown(),
                title=title,
            )

            # Subscribe to event stream
            event_bus = self.session_service.event_bus
            async for event in event_bus.subscribe(session_id, replay_all=False):
                event_type = event.event_type
                data = event.data or {}

                # Filter events relating to this attempt
                if data.get("attempt_id") != attempt_id:
                    continue

                if event_type == "text_delta":
                    current_status = "✍️ 正在生成回答..."
                    current_text += data.get("delta", "")
                    await adapter.update_message(chat_id, progress_msg_id, build_progress_markdown(), title)

                elif event_type == "tool_call":
                    tool = data.get("tool", "")
                    args = json.dumps(data.get("arguments", {}), ensure_ascii=False)
                    current_status = f"🔧 正在调用量化工具: `{tool}`\n`参数: {args[:150]}`"
                    await adapter.update_message(chat_id, progress_msg_id, build_progress_markdown(), title)

                elif event_type == "tool_result":
                    tool = data.get("tool", "")
                    status = data.get("status", "")
                    preview = data.get("preview", "")
                    current_status = f"✅ 工具 `{tool}` 已返回 ({status})\n`预览: {preview[:150]}`"
                    await adapter.update_message(chat_id, progress_msg_id, build_progress_markdown(), title)

                elif event_type == "thinking_done":
                    # Extract snippet of thinking
                    content = data.get("content", "")
                    current_thinking = content[:150] + ("..." if len(content) > 150 else "")
                    current_status = "🧠 思考完毕，开始作答。"
                    await adapter.update_message(chat_id, progress_msg_id, build_progress_markdown(), title)

                elif event_type == "attempt.completed":
                    # Mark card status as success
                    if hasattr(adapter, "set_message_status"):
                        adapter.set_message_status(progress_msg_id, "success")
                    
                    current_status = "🎉 分析完成！"
                    current_thinking = ""
                    await adapter.update_message(chat_id, progress_msg_id, build_progress_markdown(show_preview=False), title)
                    
                    # Fetch final complete response content from store or attempt summary
                    summary = data.get("summary", "")
                    
                    # If summary is empty, fetch the last assistant message
                    if not summary:
                        messages = self.session_service.get_messages(session_id, limit=2)
                        for msg in reversed(messages):
                            if msg.role == "assistant":
                                summary = msg.content
                                break
                    
                    # Send final response as a clean independent message
                    if summary:
                        await adapter.send_message(chat_id, summary)
                    break

                elif event_type == "attempt.failed":
                    # Mark card status as failed
                    if hasattr(adapter, "set_message_status"):
                        adapter.set_message_status(progress_msg_id, "failed")
                    
                    error = data.get("error", "未知运行错误")
                    current_status = f"❌ 运行遇到错误:\n```\n{error}\n```"
                    await adapter.update_message(chat_id, progress_msg_id, build_progress_markdown(show_preview=False), title)
                    break

        except asyncio.CancelledError:
            # Task was cancelled (new message came in for this session)
            if progress_msg_id:
                if hasattr(adapter, "set_message_status"):
                    adapter.set_message_status(progress_msg_id, "failed")
                current_status = "⚠️ 该会话已被新发起的任务中断。"
                await adapter.update_message(chat_id, progress_msg_id, build_progress_markdown(show_preview=False), title)
        except Exception as e:
            logger.exception("[PlatformManager] Error tracking progress for session %s: %s", session_id, e)
            if progress_msg_id:
                if hasattr(adapter, "set_message_status"):
                    adapter.set_message_status(progress_msg_id, "failed")
                current_status = f"❌ 运行监控异常: {e}"
                await adapter.update_message(chat_id, progress_msg_id, build_progress_markdown(show_preview=False), title)
        finally:
            self._running_trackers.pop(session_id, None)

    async def _unbind_existing_sessions(self, incoming: IncomingMessage) -> None:
        """Find all sessions mapped to incoming chat_id and remove platform config mapping."""
        loop = asyncio.get_running_loop()
        
        # Load sessions from store
        sessions = await loop.run_in_executor(
            None,
            lambda: self.session_service.store.list_sessions(limit=200)
        )

        for session in sessions:
            config = session.config or {}
            if (
                config.get("platform") == incoming.platform 
                and config.get("platform_chat_id") == incoming.chat_id
            ):
                new_config = dict(config)
                # Archive the keys to unbind them from current routing
                if "platform" in new_config:
                    new_config["archived_platform"] = new_config.pop("platform")
                if "platform_chat_id" in new_config:
                    new_config["archived_platform_chat_id"] = new_config.pop("platform_chat_id")
                
                session.config = new_config
                # Update session config in store
                await loop.run_in_executor(
                    None,
                    lambda s=session: self.session_service.store.update_session(s)
                )
