"""Session events reach IM during a run, without leaking unchecked answers."""
import asyncio
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
            ('a', 'reasoning_delta', {'delta': 'Let me check the source.'}),
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
    asyncio.run(scenario())
