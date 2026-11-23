
from src.tools.path_utils import FileRoots


from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.runtime import AgentRuntime
from src.product.write_directives import WriteTargetState
from src.product.resources.memory import WorkspaceMemory


def test_successful_strategy_file_write_records_the_active_model(
    tmp_path: Path,
) -> None:
    targets = WriteTargetState(
        WorkspaceMemory(run_dir=str(tmp_path)),
        SimpleNamespace(provider="openai", configured_model="gpt-5.6-luna"), "configured",
    )
    targets.record({"path": "config.json"})
    targets.runtime = SimpleNamespace(provider="openrouter", configured_model="anthropic/claude-sonnet")
    targets.active_model_id = "claude-sonnet-4-5"
    targets.active_model_source = "provider_response"
    targets.record({"path": "code/signal_engine.py"})

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
    """A real AgentRuntime must carry the provenance fields from construction on.

    The test above sets them by hand; this one goes through ``__init__`` so a
    loop that never assigns them fails here instead of in a user's backtest.
    """
    from src.agent.tools import ToolRegistry

    loop = AgentRuntime(
        registry=ToolRegistry(policy=ToolPolicy.from_config(get_env_config())),
        llm=None,
        memory=WorkspaceMemory(run_dir=str(tmp_path)),
    )

    loop._write_targets.record({"path": "config.json"})

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
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(WriteFileTool(roots=FileRoots.from_config(get_env_config().api)))
    loop = AgentRuntime(
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
