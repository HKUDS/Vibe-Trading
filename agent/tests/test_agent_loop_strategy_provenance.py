import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.loop import AgentLoop
from src.agent.memory import WorkspaceMemory


def test_successful_strategy_file_write_records_the_active_model(
    tmp_path: Path,
) -> None:
    loop = object.__new__(AgentLoop)
    loop.memory = WorkspaceMemory(run_dir=str(tmp_path))
    loop._written_files = set()
    loop._active_model_id = "gpt-5.6-luna"
    loop._active_model_source = "configured"
    loop._llm_runtime = SimpleNamespace(
        provider="openai",
        configured_model="gpt-5.6-luna",
    )

    loop._record_written_target({"path": "config.json"})
    loop._llm_runtime = SimpleNamespace(
        provider="openrouter",
        configured_model="anthropic/claude-sonnet",
    )
    loop._active_model_id = "claude-sonnet-4-5"
    loop._active_model_source = "provider_response"
    loop._record_written_target({"path": "code/signal_engine.py"})

    provenance = json.loads(
        (tmp_path / "strategy_provenance.json").read_text(encoding="utf-8")
    )
    assert provenance == {
        "files": {
            "config.json": {
                "provider": "openai",
                "model_id": "gpt-5.6-luna",
                "model_source": "configured",
            },
            "code/signal_engine.py": {
                "provider": "openrouter",
                "model_id": "claude-sonnet-4-5",
                "model_source": "provider_response",
            },
        }
    }


def test_strategy_file_write_on_a_constructed_loop_records_the_configured_model(
    tmp_path: Path,
) -> None:
    """A real AgentLoop must carry the provenance fields from construction on.

    The test above sets them by hand; this one goes through ``__init__`` so a
    loop that never assigns them fails here instead of in a user's backtest.
    """
    from src.agent.tools import ToolRegistry

    loop = AgentLoop(
        registry=ToolRegistry(),
        llm=None,
        memory=WorkspaceMemory(run_dir=str(tmp_path)),
    )

    loop._record_written_target({"path": "config.json"})

    provenance = json.loads(
        (tmp_path / "strategy_provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["files"]["config.json"] == {
        "provider": loop._llm_runtime.provider or None,
        "model_id": loop._llm_runtime.configured_model or None,
        "model_source": "configured",
    }


def test_real_tool_execution_uses_each_responses_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider identity follows the writing turn, falling back when absent."""
    from src.agent.tools import ToolRegistry
    from src.tools.write_file_tool import WriteFileTool

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    responses = []
    for index, (path, model) in enumerate(
        [
            ("config.json", "provider-reported-model"),
            ("code/signal_engine.py", None),
        ]
    ):
        responses.append(
            SimpleNamespace(
                content="Writing the requested strategy file.",
                reasoning_content=None,
                usage_metadata=None,
                response_model=model,
                has_tool_calls=True,
                tool_calls=[
                    SimpleNamespace(
                        id=f"write-{index}",
                        name="write_file",
                        arguments={"path": path, "content": "{}"},
                    )
                ],
            )
        )
    responses.append(
        SimpleNamespace(
            content="The strategy files have been saved successfully.",
            reasoning_content=None,
            usage_metadata=None,
            response_model=None,
            has_tool_calls=False,
            tool_calls=[],
        )
    )
    turns = iter(responses)
    llm = SimpleNamespace(
        model_name="configured-model",
        stream_chat=lambda *args, **kwargs: next(turns),
    )
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    loop = AgentLoop(
        registry=registry,
        llm=llm,
        memory=WorkspaceMemory(run_dir=str(tmp_path)),
        max_iterations=3,
    )

    result = loop.run(user_message="Write the requested strategy files.")

    assert result["status"] == "success", result
    run_dir = Path(result["run_dir"])
    assert (run_dir / "config.json").read_text() == "{}"
    assert (run_dir / "code/signal_engine.py").read_text() == "{}"
    provenance = json.loads((run_dir / "strategy_provenance.json").read_text())
    assert provenance["files"]["config.json"]["model_id"] == "provider-reported-model"
    assert provenance["files"]["config.json"]["model_source"] == "provider_response"
    assert (
        provenance["files"]["code/signal_engine.py"]["model_id"] == "configured-model"
    )
    assert provenance["files"]["code/signal_engine.py"]["model_source"] == "configured"
