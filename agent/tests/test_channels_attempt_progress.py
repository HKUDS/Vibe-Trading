"""Session events reach IM during a run, without leaking unchecked answers."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from src.channels.bus.events import InboundMessage
from src.channels.bus.queue import MessageBus
from src.channels.runtime import ChannelRuntime
from src.channels.manager import ChannelManager
from src.session.events import EventBus
from src.session.models import Message, Session


class _Service:
    def __init__(self):
        self.event_bus = EventBus()
        self.messages = []

    def create_session(self, **kwargs):
        return Session(session_id='s', **kwargs)

    async def send_message(self, session_id, content, **kwargs):
        for attempt, kind, data in [
            ('old', 'tool_call', {'tool': 'stale_tool'}),
            ('a', 'attempt.created', {}),
            ('a', 'reasoning_delta', {'iter': 1, 'chars': 24, 'tail': 'Let me check the source.'}),
            ('a', 'tool_call', {'tool': 'get_market_data'}),
            ('a', 'text_delta', {'delta': 'UNVALIDATED 987.65'}),
            ('a', 'tool_result', {'result': 'RAW_PAYLOAD'}),
        ]:
            self.event_bus.emit(session_id, kind, {**data, 'attempt_id': attempt})
        return {'attempt_id': 'a'}

    def get_messages(self, *args, **kwargs):
        return self.messages


def test_progress_is_delivered_before_reply_and_drafts_stay_private(tmp_path):
    async def scenario():
        bus, service = MessageBus(), _Service()
        runtime = ChannelRuntime(bus=bus, session_service=service, manager=None,
                                 session_map_path=tmp_path/'sessions.json', poll_interval_s=.001)
        msg = InboundMessage(channel='feishu', chat_id='oc_chat', sender_id='u', content='research',
                             metadata={'message_id': 'm', 'chat_type': 'group', '_wants_stream': True})
        task = asyncio.create_task(runtime._handle_inbound(msg))
        first = await asyncio.wait_for(bus.consume_outbound(), 1)
        assert first.metadata['_stream_delta']
        assert not task.done()  # status actually arrives while work is in flight
        service.messages.append(Message(session_id='s', role='assistant', content='Checked answer', linked_attempt_id='a'))
        await task
        messages = [first]
        while bus.outbound_size:
            messages.append(await bus.consume_outbound())
        contents = ''.join(m.content for m in messages)
        assert 'Using get_market_data' in contents
        assert 'stale_tool' not in contents and 'UNVALIDATED' not in contents and 'RAW_PAYLOAD' not in contents
        assert contents.count('Checked answer') == 1
        assert any(m.metadata.get('_reasoning_end') for m in messages)
        assert any(m.metadata.get('_stream_end') for m in messages)
        assert all(m.metadata.get('message_id') == 'm' for m in messages)
        assert messages[-1].metadata['chat_type'] == 'group'
        # Exercise real manager dispatch into a Feishu adapter's CardKit path.
        from src.channels.feishu import FeishuChannel, FeishuConfig
        channel = FeishuChannel(FeishuConfig(), bus)
        channel._client = object()
        channel._create_streaming_card_sync = Mock(return_value='card-1')
        channel._stream_update_text_with_reopen_sync = Mock(return_value=(True, 2))
        channel._close_streaming_mode_sync = Mock(return_value=True)
        await ChannelManager._send_once(channel, first)
        channel._create_streaming_card_sync.assert_called_once()
        assert channel._stream_bufs['m'].text == first.content
        end = next(m for m in messages if m.metadata.get('_stream_end'))
        await ChannelManager._send_once(channel, end)
        channel._close_streaming_mode_sync.assert_called_once()
        assert not channel._stream_bufs
    asyncio.run(scenario())


def test_timeout_closes_transient_stream(tmp_path):
    async def scenario():
        bus, service = MessageBus(), _Service()
        runtime = ChannelRuntime(bus=bus, session_service=service, manager=None,
                                 session_map_path=tmp_path/'sessions.json',
                                 poll_interval_s=.001, reply_timeout_s=.01)
        await runtime._handle_inbound(InboundMessage(channel='feishu', chat_id='c', sender_id='u', content='q', metadata={'_wants_stream': True}))
        messages = []
        while bus.outbound_size:
            messages.append(await bus.consume_outbound())
        assert any(m.metadata.get('_stream_end') for m in messages)
        assert messages[-1].metadata['error']
        # Abandoned, not finished: the agent may still be working, so a later
        # consumer (e.g. Feishu's OnIt->done_emoji transition) must not treat
        # this as the real end.
        end = next(m for m in messages if m.metadata.get('_stream_end'))
        assert end.metadata.get('_resuming') is True
    asyncio.run(scenario())


def test_successful_completion_reports_resuming_false(tmp_path):
    """_resuming must be false on the attempt's true end, or Feishu's OnIt ->
    done_emoji reaction transition (`not meta.get('_resuming')`) never fires.
    """
    async def scenario():
        bus, service = MessageBus(), _Service()
        runtime = ChannelRuntime(bus=bus, session_service=service, manager=None,
                                 session_map_path=tmp_path/'sessions.json', poll_interval_s=.001)
        msg = InboundMessage(channel='feishu', chat_id='oc_chat', sender_id='u', content='research',
                             metadata={'message_id': 'm', '_wants_stream': True})
        task = asyncio.create_task(runtime._handle_inbound(msg))
        first = await asyncio.wait_for(bus.consume_outbound(), 1)
        service.messages.append(Message(session_id='s', role='assistant', content='Checked answer', linked_attempt_id='a'))
        await task
        messages = [first]
        while bus.outbound_size:
            messages.append(await bus.consume_outbound())
        end = next(m for m in messages if m.metadata.get('_stream_end'))
        assert not end.metadata.get('_resuming')
    asyncio.run(scenario())


def test_real_reasoning_tails_are_incremental_and_redaction_stays_private():
    from src.channels.attempt_progress import AttemptProgress

    async def scenario():
        bus, events = MessageBus(), EventBus()
        message = InboundMessage(channel="feishu", chat_id="c", sender_id="u", content="q", metadata={"_wants_stream": True})
        progress = AttemptProgress(bus, events, message, "s", "a")
        for data in [
            {"iter": 1, "chars": 5, "tail": "Hello"},
            {"iter": 1, "chars": 11, "tail": "Hello world"},
            {"iter": 1, "chars": 11, "tail": "Hello world"},
            {"iter": 2, "chars": 20},  # grounding withheld the text
        ]:
            events.emit("s", "reasoning_delta", {**data, "attempt_id": "a"})
        events.emit("s", "llm_waiting", {"attempt_id": "a", "iter": 2})
        await progress.poll()
        sent = []
        while bus.outbound_size:
            sent.append(await bus.consume_outbound())
        reasoning = "".join(m.content for m in sent if m.metadata.get("_reasoning_delta"))
        assert reasoning == "Hello world"
        assert any(m.content == "Reasoning…\n" for m in sent)
        assert any(m.content == "Waiting for the model…\n" for m in sent)
    asyncio.run(scenario())


def test_hidden_tool_hints_do_not_break_status_dedupe():
    from src.channels.attempt_progress import AttemptProgress

    async def scenario():
        bus, events = MessageBus(), EventBus()
        message = InboundMessage(channel="feishu", chat_id="c", sender_id="u", content="q", metadata={})
        progress = AttemptProgress(bus, events, message, "s", "a",
                                   is_visible=lambda *, tool_hint: not tool_hint)
        for kind, data in [
            ("llm_waiting", {"iter": 1}),
            ("tool_call", {"tool": "session_search"}),
            ("llm_waiting", {"iter": 2}),
            ("tool_call", {"tool": "read_file"}),
            ("llm_waiting", {"iter": 3}),
        ]:
            events.emit("s", kind, {**data, "attempt_id": "a"})
        await progress.poll()
        sent = []
        while bus.outbound_size:
            sent.append(await bus.consume_outbound())
        assert [m.content for m in sent] == ["Waiting for the model…\n"]
    asyncio.run(scenario())


def test_runtime_applies_the_channel_progress_settings(tmp_path):
    async def scenario():
        bus, service = MessageBus(), _Service()
        manager = ChannelManager({}, bus)
        # Channel defaults: progress shown, tool hints hidden.
        manager.channels['feishu'] = SimpleNamespace(send_progress=True, send_tool_hints=False)
        runtime = ChannelRuntime(bus=bus, session_service=service, manager=manager,
                                 session_map_path=tmp_path/'sessions.json', poll_interval_s=.001)
        service.messages.append(Message(session_id='s', role='assistant', content='Checked answer', linked_attempt_id='a'))
        await runtime._handle_inbound(InboundMessage(channel='feishu', chat_id='c', sender_id='u', content='q', metadata={}))
        contents = []
        while bus.outbound_size:
            contents.append((await bus.consume_outbound()).content)
        assert 'Working on your request…\n' in contents
        assert not any('Using get_market_data' in c for c in contents)
    asyncio.run(scenario())
