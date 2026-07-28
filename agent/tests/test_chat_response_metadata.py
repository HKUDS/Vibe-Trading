from types import SimpleNamespace

from src.providers.chat import ChatLLM


def test_parse_response_keeps_provider_reported_model() -> None:
    message = SimpleNamespace(
        content="hello",
        tool_calls=[],
        additional_kwargs={},
        response_metadata={
            "finish_reason": "stop",
            "model_name": "deepseek-v4-flash-202607",
        },
        usage_metadata=None,
    )

    response = ChatLLM._parse_response(message)

    assert response.response_model == "deepseek-v4-flash-202607"
