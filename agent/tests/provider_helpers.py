"""Shared provider test setup: real ChatLLM initialization and local HTTP wire."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from src.providers.chat import ChatLLM
from src.providers.settings import resolve_config


def chat_with_adapter(adapter, model="test"):
    """Initialize ChatLLM normally while substituting only its SDK adapter."""
    snapshot = resolve_config(model_name=model, environment=dict(os.environ))
    with patch("src.providers.chat.build_llm", return_value=adapter):
        return ChatLLM(snapshot=snapshot)


def assert_stream_tool_roundtrip(llm, model):
    """Exercise fragmented arguments and a tool-result turn through the real SDK."""
    parameters = {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}
    function = {"name": "quote", "description": "Read a quote", "parameters": parameters}
    tools = [{"type": "function", "function": function}]
    messages = [{"role": "user", "content": "Quote AAPL"}]
    first = llm.stream_chat(messages, tools=tools)
    assert len(first.tool_calls) == 1
    assert first.tool_calls[0].id == "call_quote" and first.tool_calls[0].name == "quote"
    assert first.tool_calls[0].arguments == {"symbol": "AAPL"}
    assert first.finish_reason == "tool_calls"
    tool_call = {
        "id": "call_quote", "type": "function",
        "function": {"name": "quote", "arguments": '{"symbol":"AAPL"}'},
    }
    followup = messages + [
        {"role": "assistant", "content": "", "tool_calls": [tool_call]},
        {"role": "tool", "tool_call_id": "call_quote", "content": '{"price":100}'},
    ]
    chunks = []
    second = llm.stream_chat(followup, tools=tools, on_text_chunk=chunks.append)
    assert second.content == "".join(chunks) == model
    assert not second.tool_calls
    assert second.usage_metadata["input_tokens"] == 17
    assert second.response_model == f"served-{model}"


@pytest.fixture
def provider_server():
    """Serve JSON completions and fragmented SSE tool calls, recording requests."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if "/external/" in self.path:
                self.send_response(307)
                self.send_header("Location", f"http://localhost:{self.server.server_port}" + self.path.replace("/external", "", 1))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if "/redirect/" in self.path:
                self.send_response(307)
                self.send_header("Location", self.path.replace("/redirect/", "/"))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            received.append((self.path, self.headers, body))
            frame = {"id": "test", "created": 1, "model": f"served-{body['model']}"}
            message = {"role": "assistant", "content": body["model"]}
            if self.path.endswith("/messages"):
                message = dict(frame, type="message", role="assistant", stop_reason="end_turn",
                               content=[{"type": "text", "text": body["model"]}],
                               usage={"input_tokens": 17, "output_tokens": 4})
                if body.get("stream"):
                    is_tool = body.get("tools") and not any(
                        block.get("type") == "tool_result"
                        for block in body["messages"][-1]["content"] if isinstance(block, dict)
                    )
                    if is_tool:
                        block = {"type": "tool_use", "id": "call_quote", "name": "quote", "input": {}}
                        deltas = [
                            {"type": "input_json_delta", "partial_json": part}
                            for part in ['{"symbol":', '"AAPL"}']
                        ]
                    else:
                        block = {"type": "text", "text": ""}
                        deltas = [{"type": "text_delta", "text": body["model"]}]
                    events = [
                        {"type": "message_start", "message": dict(
                            message, content=[], stop_reason=None, usage={"input_tokens": 0, "output_tokens": 0},
                        )},
                        {"type": "content_block_start", "index": 0, "content_block": block},
                        *[{"type": "content_block_delta", "index": 0, "delta": delta} for delta in deltas],
                        {"type": "content_block_stop", "index": 0},
                        {"type": "message_delta", "delta": {"stop_reason": "tool_use" if is_tool else "end_turn"},
                         "usage": {"input_tokens": 17, "output_tokens": 4}},
                        {"type": "message_stop"},
                    ]
                    chunks = [f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events]
                    content_type = "text/event-stream"
                else:
                    chunks = [json.dumps(message)]
                    content_type = "application/json"
            elif body.get("stream"):
                frame["object"] = "chat.completion.chunk"
                deltas, reason = [message], "stop"
                if body.get("tools") and body["messages"][-1]["role"] != "tool":
                    tool_call = {
                        "index": 0, "id": "call_quote", "type": "function",
                        "function": {"name": "quote", "arguments": '{"symbol":'},
                    }
                    continuation = {"index": 0, "function": {"arguments": '"AAPL"}'}}
                    deltas = [{"tool_calls": [tool_call]}, {"tool_calls": [continuation]}]
                    reason = "tool_calls"
                events = []
                for delta in deltas + [{}]:
                    choice = {"index": 0, "delta": delta, "finish_reason": reason if not delta else None}
                    events.append(dict(frame, choices=[choice]))
                usage = {"prompt_tokens": 17, "completion_tokens": 4, "total_tokens": 21}
                events.append(dict(frame, choices=[], usage=usage))
                chunks = [f"data: {json.dumps(event)}\n\n" for event in events] + ["data: [DONE]\n\n"]
                content_type = "text/event-stream"
            else:
                choice = {"index": 0, "finish_reason": "stop", "message": message}
                chunks = [json.dumps(dict(frame, object="chat.completion", choices=[choice]))]
                content_type = "application/json"
            encoded = [chunk.encode() for chunk in chunks]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(sum(map(len, encoded))))
            self.end_headers()
            for chunk in encoded:
                self.wfile.write(chunk)
                self.wfile.flush()

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", received
        finally:
            server.shutdown()
            thread.join(timeout=5)
