"""Inject OpenBB Workspace widget / dashboard context into a user message.

OpenBB Workspace sends the full workspace state (loaded widgets, dashboard
metadata, previously-retrieved tool results) with every ``/v1/query`` request.
Vibe-Trading's :class:`AgentLoop` has no concept of these widgets, so this
module distils the context into a compact natural-language prefix that is
prepended to the user's message.

The distillation is deliberately conservative: only metadata and short value
summaries are injected to avoid blowing up the prompt / token budget. Full
widget data can still be fetched on demand by Vibe-Trading's own tools.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger("openbb_bridge")

# Guard rails to keep the injected context small.
MAX_WIDGETS = 10
MAX_VALUE_CHARS = 200
MAX_PARAMS_PER_WIDGET = 8


def _safe(obj: Any, attr: str, default: Any = None) -> Any:
    """Return ``obj.attr`` (attribute) or ``obj[attr]`` (mapping) if present."""
    if obj is None:
        return default
    value = getattr(obj, attr, None)
    if value is None and isinstance(obj, dict):
        value = obj.get(attr, default)
    return default if value is None else value


def _truncate(text: str, limit: int = MAX_VALUE_CHARS) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class WidgetContextInjector:
    """Format widget & dashboard context and inject it into the user message."""

    def inject(self, request: Any, user_message: str) -> str:
        """Return ``user_message`` prefixed with a formatted context block.

        Parameters
        ----------
        request:
            The parsed ``openbb_ai.models.QueryRequest`` instance.
        user_message:
            The raw text of the last human message.
        """
        try:
            blocks: List[str] = []

            widget_block = self._format_widgets(request)
            if widget_block:
                blocks.append(widget_block)

            dashboard_block = self._format_dashboard(request)
            if dashboard_block:
                blocks.append(dashboard_block)

            tool_block = self._format_prior_tool_results(request)
            if tool_block:
                blocks.append(tool_block)

            if not blocks:
                return user_message

            context = "\n\n".join(blocks)
            return (
                "[OpenBB Workspace context]\n"
                f"{context}\n"
                "[End of context]\n\n"
                f"{user_message}"
            )
        except Exception as exc:  # never break a query because of context
            logger.warning("Failed to inject widget context: %s", exc)
            return user_message

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------
    def _collect_widgets(self, request: Any) -> List[Any]:
        collection = _safe(request, "widgets")
        if collection is None:
            return []
        widgets: List[Any] = []
        for group in ("primary", "secondary", "extra"):
            group_widgets = _safe(collection, group, []) or []
            for widget in group_widgets:
                widgets.append(widget)
        return widgets

    def _format_widgets(self, request: Any) -> Optional[str]:
        widgets = self._collect_widgets(request)
        if not widgets:
            return None

        lines = ["The user has the following widgets loaded on their dashboard:"]
        for widget in widgets[:MAX_WIDGETS]:
            name = _safe(widget, "name", "Unnamed widget")
            description = _safe(widget, "description", "")
            origin = _safe(widget, "origin", "")
            header = f"- {name}"
            if origin:
                header += f" (source: {origin})"
            if description:
                header += f": {_truncate(description)}"
            lines.append(header)

            params = _safe(widget, "params", []) or []
            param_summaries: List[str] = []
            for param in params[:MAX_PARAMS_PER_WIDGET]:
                p_name = _safe(param, "name")
                p_value = _safe(param, "current_value")
                if p_name is None:
                    continue
                if p_value is not None:
                    param_summaries.append(f"{p_name}={_truncate(p_value, 60)}")
                else:
                    param_summaries.append(str(p_name))
            if param_summaries:
                lines.append(f"    params: {', '.join(param_summaries)}")

        remaining = len(widgets) - MAX_WIDGETS
        if remaining > 0:
            lines.append(f"  ...and {remaining} more widget(s).")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    def _format_dashboard(self, request: Any) -> Optional[str]:
        workspace_state = _safe(request, "workspace_state")
        if workspace_state is None:
            return None
        dashboard = _safe(workspace_state, "current_dashboard_info")
        if dashboard is None:
            return None

        name = _safe(dashboard, "name")
        description = _safe(dashboard, "description")
        parts: List[str] = []
        if name:
            parts.append(f"Current dashboard: {name}")
        if description:
            parts.append(_truncate(description))
        if not parts:
            return None
        return " - ".join(parts)

    # ------------------------------------------------------------------
    # Prior tool / function-call results carried in the message history
    # ------------------------------------------------------------------
    def _format_prior_tool_results(self, request: Any) -> Optional[str]:
        messages = _safe(request, "messages", []) or []
        summaries: List[str] = []
        for message in messages:
            role = _safe(message, "role")
            if role != "tool":
                continue
            function = _safe(message, "function", "tool")
            data = _safe(message, "data")
            if data is None:
                continue
            summaries.append(f"- {function}: {_truncate(data)}")

        if not summaries:
            return None
        header = "Previously retrieved data in this conversation:"
        return "\n".join([header, *summaries[-MAX_WIDGETS:]])
