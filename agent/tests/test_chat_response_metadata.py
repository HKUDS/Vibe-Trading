from pathlib import Path
from types import MethodType, SimpleNamespace

import src.providers.chat as chat_module
from src.agent.loop import AgentLoop
from src.config.accessor import reset_env_config
from src.providers.chat import ChatLLM, LLMResponse


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


class _EmptyRegistry:
    _tools = {}

    def get_definitions(self):
        return []


def test_runtime_metadata_is_frozen_at_construction_with_model_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "deepseek")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "deepseek-configured")
    monkeypatch.setenv("LANGCHAIN_REASONING_EFFORT", "high")
    reset_env_config()
    monkeypatch.setattr(chat_module, "build_llm", lambda **kwargs: object())

    llm = ChatLLM(model_name="explicit-model-override")

    def _stream_chat(self, *args, **kwargs):
        del self, args, kwargs
        return LLMResponse(
            content="done",
            response_model="provider-reported-model",
        )

    llm.stream_chat = MethodType(_stream_chat, llm)

    monkeypatch.setenv("LANGCHAIN_PROVIDER", "openai")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "changed-after-construction")
    monkeypatch.setenv("LANGCHAIN_REASONING_EFFORT", "low")
    reset_env_config()

    agent = AgentLoop(
        registry=_EmptyRegistry(),  # type: ignore[arg-type]
        llm=llm,
        max_iterations=1,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)

    result = agent.run("hello")

    assert result["provider"] == "deepseek"
    assert result["configured_model"] == "explicit-model-override"
    assert result["model"] == "provider-reported-model"
    assert result["model_source"] == "provider_response"
    assert result["reasoning_effort"] == "high"
