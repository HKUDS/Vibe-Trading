"""Budget worker context without discarding a fresh batch of observations."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from src.session.context_budget import CompactionBudget, ContextMeter, estimate_tokens, resolve_window
from src.product.result_artifacts import save_result_parts
from src.config.accessor import get_env_config
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools.redaction import redact_tool_result

logger = logging.getLogger(__name__)
_OFFLOADED = "[Worker context result saved: "


class WorkerContext:
    """Track real prompt size and save old observations before removing them.

    A result stays visible for at least one successful model request. Under
    pressure, older results may move to readable files inside this worker's
    workspace. Neither a tool count nor a batch position implies obsolescence.
    """

    def __init__(self, *, model: str, artifact_dir: Path, can_read_files: bool) -> None:
        cfg = get_env_config()
        self.window, self.window_source = resolve_window(
            cfg.llm.langchain_provider, model or cfg.llm.langchain_model_name,
            env_window=cfg.agent_tuning.vibe_trading_context_window,
        )
        self.max_tokens = cfg.agent_tuning.vibe_trading_context_max_tokens
        self.meter = ContextMeter()
        self.artifact_dir = artifact_dir.resolve()
        self.can_read_files = can_read_files
        self.pending: set[str] = set()

    def budget(self, messages: list[dict], tools: list[dict] | None) -> CompactionBudget:
        """Return the same window/cost ceiling used by the main agent."""
        return CompactionBudget(
            window=self.window, source=self.window_source, max_tokens=self.max_tokens,
            static_tokens=self.meter.static(messages, estimate_tokens(tools or [])),
        )

    def tokens(self, messages: list[dict], tools: list[dict] | None) -> int:
        """Estimate the next request from the last provider input-token count."""
        return self.meter.tokens(messages, estimate_tokens(tools or []))

    def observe(self, messages: list[dict], tools: list[dict] | None, usage: dict | None) -> None:
        """Record a successful request; its pending results have now been seen."""
        self.meter.observe((usage or {}).get('input_tokens'), messages,
                           tool_schema_tokens=estimate_tokens(tools or []))
        self.pending.clear()

    def compact(self, messages: list[dict], tools: list[dict] | None) -> list[dict[str, Any]]:
        """Offload only old results needed to get below the pressure threshold.

        Args:
            messages: Mutable current worker conversation.
            tools: Exact schemas for the next model request.

        Returns:
            Receipts for results successfully saved to disk. An unavailable
            reader or failed write leaves the original result in context.
        """
        budget = self.budget(messages, tools)
        target = min(budget.micro_at, budget.total)
        if not self.can_read_files or self.tokens(messages, tools) <= target:
            return []
        receipts = []
        for message in messages:
            if self.tokens(messages, tools) <= target:
                break
            content = message.get('content')
            call_id = message.get('tool_call_id')
            if (message.get('role') != 'tool' or call_id in self.pending
                    or not isinstance(content, str) or content.startswith(_OFFLOADED)):
                continue
            digest = hashlib.sha256(content.encode()).hexdigest()
            if len(content) < TOOL_RESULT_LIMIT // 10:
                continue
            try:
                paths = self._save_result(redact_tool_result(content), digest)
            except (OSError, ValueError):
                logger.warning('Could not preserve worker context result', exc_info=True)
                continue
            marker = (
                f'{_OFFLOADED}{json.dumps(paths)}] This result was returned earlier, not missing. '
                'Use read_file on these parts in order to recover it; do not refetch external '
                'data just because its earlier result was moved out of context.'
            )
            if len(content) <= len(marker):
                continue
            message['content'] = marker
            receipts.append({'tool_call_id': call_id, 'paths': paths, 'characters': len(content)})
        return receipts

    def _save_result(self, content: str, digest: str) -> list[str]:
        """Save parts that fit through the real read_file result envelope.

        JSON escaping and the path count toward the shared result cap. Splitting
        prevents a successfully saved observation from being truncated again
        when the model reads it back. Existing symlinks cannot redirect writes.
        """
        return save_result_parts(
            content, self.artifact_dir / "context-results" / digest, self.artifact_dir,
        )
