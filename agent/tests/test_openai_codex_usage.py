from __future__ import annotations

from src.providers.openai_codex import CodexAIMessage, _message_chunks_from_events


def test_completed_event_exposes_codex_token_usage() -> None:
    [chunk] = list(
        _message_chunks_from_events(
            [
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "usage": {
                            "input_tokens": 12,
                            "output_tokens": 7,
                            "total_tokens": 19,
                        },
                    },
                }
            ]
        )
    )

    assert chunk.usage_metadata == {
        "input_tokens": 12,
        "output_tokens": 7,
        "total_tokens": 19,
    }


def test_codex_message_accumulation_preserves_final_usage() -> None:
    message = CodexAIMessage(content="hello") + CodexAIMessage(
        usage_metadata={
            "input_tokens": 12,
            "output_tokens": 7,
            "total_tokens": 19,
        }
    )

    assert message.content == "hello"
    assert message.usage_metadata == {
        "input_tokens": 12,
        "output_tokens": 7,
        "total_tokens": 19,
    }


def test_completed_event_without_usage_stays_unreported() -> None:
    [chunk] = list(
        _message_chunks_from_events(
            [{"type": "response.completed", "response": {"status": "completed"}}]
        )
    )

    assert chunk.usage_metadata is None
