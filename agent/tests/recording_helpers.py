"""Drive isolated tool tests through real conversation recording."""
from pathlib import Path
from src.kernel.tool_runner import execute_batch
from src.session.runtime import SessionRuntime, TurnRecorder
from src.session.replay import diagnostic_records
from src.session.thread import ThreadLog


def recorder_at(directory: Path) -> TurnRecorder:
    runtime = SessionRuntime(ThreadLog(directory / "thread.jsonl"), directory.name)
    return runtime.begin_turn("test-turn")


def records_at(directory: Path) -> list[dict]:
    return diagnostic_records(ThreadLog(directory / "thread.jsonl").read())


def run_recorded_tools(agent, calls, context, messages, recorder, iteration):
    agent._conversation.thread = recorder
    agent._conversation.turn_messages = messages
    recorder.assistant(context.format_assistant_tool_calls(calls), phase="commentary")
    return agent.tools.process(calls, context, messages, recorder, iteration)


def run_recorded_tool(agent, call, context, messages, recorder, iteration):
    agent._conversation.thread = recorder
    agent._conversation.turn_messages = messages
    recorder.assistant(context.format_assistant_tool_calls([call]), phase="commentary")
    bound = agent.tools._bind(call, context, messages, recorder, iteration, parallel=False)
    execute_batch([bound], agent.activity.cancel.is_set)


def seed_message(store, message):
    """Seed a canonical item and boundary for a display-reader fixture."""
    log = store.thread_log(message.session_id)
    turn = message.linked_attempt_id or message.message_id
    log.append("turn_start", turn, prompt="")
    if message.role == "user":
        log.append("user", turn, content=message.content, llm_content=message.content)
    elif message.role == "assistant":
        log.append("assistant", turn, content=message.content, phase="final")
    else:
        log.append("inject", turn, role=message.role, content=message.content)
    log.append("turn_end", turn, status="completed", metadata=message.metadata)
