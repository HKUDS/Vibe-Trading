"""Project session messages at each provider attempt and bound stream recovery."""

from __future__ import annotations

import contextvars
import logging
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.kernel import events
from src.kernel.contracts import LLMResponse, ModelMessage
from src.providers.response import ProviderStreamError
from src.providers.messages import repair_provider_messages
from src.session.context_budget import is_context_overflow

logger = logging.getLogger(__name__)


@dataclass
class SessionRequest:
    """Send the model requests of one run, retaining its stream failure streak."""

    llm: Any
    cancel: threading.Event
    should_stop: Callable[[], bool]
    record_usage: Callable[..., None]
    recover_overflow: Callable[[Exception, list[ModelMessage], Path, Any, int, int], None]
    timeout_seconds: Callable[[], float]
    backoff: Callable[[int], float]
    max_delay: Callable[[], float]
    _failure_streak: int = field(init=False, default=0)

    def send(
        self, messages: list[ModelMessage], tools: list | None, stream, *,
        run_dir: Path, trace, iteration: int, current_iter: int,
    ) -> tuple[LLMResponse, list[ModelMessage]] | None:
        """Return the response and exact input of the successful attempt."""
        seconds = self.timeout_seconds()
        timeout = seconds if seconds > 0 else None

        def attempt():
            prepared = repair_provider_messages(messages)
            try:
                response = self.llm.stream_chat(
                    prepared, tools=tools, on_text_chunk=stream.on_text,
                    on_reasoning_chunk=stream.on_reasoning, on_waiting_chunk=stream.on_waiting,
                    timeout=timeout, idle_timeout_s=timeout, should_cancel=self.cancel.is_set,
                )
            except ProviderStreamError as error:
                self.record_usage(run_dir, error.usage_metadata, current_iter, purpose="failed_stream")
                raise
            return response, prepared

        try:
            result = attempt()
        except ProviderStreamError as error:
            if is_context_overflow(str(error)):
                self.recover_overflow(error, messages, run_dir, trace, iteration, current_iter)
                reason = "context_overflow"
                delay = 0.0
            elif error.retryable:
                self._failure_streak += 1
                reason = "provider_stream_retry"
                if error.retry_after_s is None:
                    delay = self.backoff(self._failure_streak)
                else:
                    delay = min(error.retry_after_s, self.max_delay())
            else:
                raise
            stream.emit(events.ITEM_DELTA, {
                "kind": events.TEXT_RESET, "iter": current_iter, "reason": reason,
                "provider": error.provider, "model": error.model, "retry_delay_s": delay,
            })
            stream.reset_for_retry()
            self.cancel.wait(delay)
            if self.should_stop():
                return None
            return attempt()
        self._failure_streak = 0
        return result


class SummaryUnavailable(Exception):
    """A deadline-bound summary failed and compaction should degrade."""


def request_summary(llm, prompt: str, timeout: float) -> LLMResponse:
    """Send one summary request with the session binding and wall-clock deadline."""
    messages = repair_provider_messages([{"role": "user", "content": prompt}])
    if timeout <= 0:
        return llm.chat(messages)

    result: Future[LLMResponse] = Future()

    def summarize() -> None:
        try:
            result.set_result(llm.chat(messages, timeout=timeout))
        except BaseException as error:  # An unsuccessful worker degrades the summary.
            result.set_exception(error)

    worker = threading.Thread(
        target=contextvars.copy_context().run, args=(summarize,),
        name="compact-summary", daemon=True,
    )
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        logger.warning("Auto compact summary call exceeded %.1fs; degrading compaction", timeout)
        raise SummaryUnavailable
    try:
        return result.result()
    except BaseException as error:
        logger.warning("Auto compact LLM call failed (%s); degrading compaction", error)
        raise SummaryUnavailable from error
