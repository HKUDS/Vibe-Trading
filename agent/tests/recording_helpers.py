"""Drive isolated tool tests through real conversation recording."""
from pathlib import Path
from src.session.runtime import SessionRuntime, TurnRecorder
from src.session.thread import ThreadLog, diagnostic_records


def recorder_at(directory: Path) -> TurnRecorder:
    runtime = SessionRuntime(ThreadLog(directory / "thread.jsonl"), directory.name)
    return runtime.begin_turn("test-turn", [])


def records_at(directory: Path) -> list[dict]:
    return diagnostic_records(ThreadLog(directory / "thread.jsonl").read())


def run_recorded_tools(agent, calls, context, messages, recorder, iteration):
    agent._thread = recorder
    agent._conversation.thread = recorder
    agent._turn_messages = messages
    recorder.assistant(context.format_assistant_tool_calls(calls), phase="commentary")
    return agent._process_tool_calls(calls, context, messages, recorder, iteration)


def run_recorded_tool(agent, call, context, messages, recorder, iteration):
    agent._thread = recorder
    agent._conversation.thread = recorder
    agent._turn_messages = messages
    recorder.assistant(context.format_assistant_tool_calls([call]), phase="commentary")
    return agent._execute_single(call, context, messages, recorder, iteration)


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
