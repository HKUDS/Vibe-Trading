"""Inject OpenBB Workspace context into a user message.

Every ``/v1/query`` request carries the workspace state alongside the question.
Vibe-Trading's :class:`AgentLoop` has no concept of OpenBB widgets, so this
module distils the request into a compact natural-language prefix prepended to
the user's message.

Three sources are folded in, in decreasing order of usefulness:

* ``QueryRequest.context`` — explicit context items the user attached (tables,
  artifacts, parsed PDFs). ``RawContext.data.items[].content`` is plain text, so
  this is the one place actual **data** arrives, and it is ingested verbatim
  under a hard character budget.
* ``tool``-role messages — payloads returned by a widget-retrieval round trip,
  read out of ``DataContent.items[].content`` under the same budget.
* ``QueryRequest.widgets`` / ``workspace_state`` — widget and dashboard
  *metadata* only. OpenBB does not put widget values in these; fetching them
  requires the ``get_widget_data`` function-call round trip, which this bridge
  does not implement. The prefix therefore says so explicitly, so the model uses
  the widget parameters as intent (e.g. "the user is looking at AAPL") and pulls
  values with Vibe-Trading's own data tools instead of inventing them.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger("openbb_bridge")

# Guard rails to keep the injected context small.
MAX_WIDGETS = 10
MAX_VALUE_CHARS = 200
MAX_PARAMS_PER_WIDGET = 8

# Hard ceiling on attached data (context items + tool payloads combined). The
# agent's own 5-layer compression handles the rest of the prompt, but unbounded
# spreadsheet or PDF dumps would blow the first LLM call before it ever runs.
MAX_DATA_CHARS = 8000
DATA_TRUNCATION_MARKER = "... [truncated: attached data exceeded the 8000-character budget]"


def _safe(obj: Any, attr: str, default: Any = None) -> Any:
    """Return ``obj.attr`` (attribute) or ``obj[attr]`` (mapping) if present.

    Args:
        obj: Object or mapping to read from.
        attr: Attribute / key name.
        default: Value returned when absent or ``None``.

    Returns:
        The resolved value, or *default*.
    """
    if obj is None:
        return default
    value = getattr(obj, attr, None)
    if value is None and isinstance(obj, dict):
        value = obj.get(attr, default)
    return default if value is None else value


def _truncate(text: str, limit: int = MAX_VALUE_CHARS) -> str:
    """Return *text* clipped to *limit* characters with an ellipsis marker.

    Args:
        text: Value to clip; coerced to ``str``.
        limit: Maximum length of the result.

    Returns:
        The clipped text.
    """
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class WorkspaceContextInjector:
    """Format OpenBB workspace context and inject it into the user message."""

    def inject(self, request: Any, user_message: str) -> str:
        """Return ``user_message`` prefixed with a formatted context block.

        Args:
            request: The parsed ``openbb_ai.models.QueryRequest`` instance.
            user_message: The raw text of the last human message.

        Returns:
            The enriched message, or *user_message* unchanged when the request
            carried no usable context.
        """
        try:
            blocks: List[str] = []

            # Attached data first: it is the only block with real values, and it
            # owns the shared character budget.
            budget = MAX_DATA_CHARS
            data_block, budget = self._format_attached_data(request, budget)
            if data_block:
                blocks.append(data_block)

            tool_block, budget = self._format_tool_results(request, budget)
            if tool_block:
                blocks.append(tool_block)

            widget_block = self._format_widgets(request)
            if widget_block:
                blocks.append(widget_block)

            dashboard_block = self._format_dashboard(request)
            if dashboard_block:
                blocks.append(dashboard_block)

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
            logger.warning("Failed to inject workspace context: %s", exc)
            return user_message

    # ------------------------------------------------------------------
    # Attached data (QueryRequest.context)
    # ------------------------------------------------------------------
    def _format_attached_data(self, request: Any, budget: int) -> tuple[Optional[str], int]:
        """Render ``QueryRequest.context`` items within a character budget.

        Args:
            request: The parsed ``QueryRequest``.
            budget: Remaining characters available for attached data.

        Returns:
            A ``(block, remaining_budget)`` tuple; *block* is ``None`` when the
            request attached no context items.
        """
        items = _safe(request, "context", []) or []
        if not items:
            return None, budget

        lines = ["The user attached the following data. Treat it as authoritative:"]
        for item in items:
            name = _safe(item, "name", "context item")
            description = _safe(item, "description", "")
            header = f"- {name}"
            if description:
                header += f" ({_truncate(description)})"
            lines.append(header)

            payload, budget = self._render_data_content(_safe(item, "data"), budget)
            if payload:
                lines.append(self._indent(payload))
            if budget <= 0:
                self._note_truncation(lines)
                break

        return "\n".join(lines), budget

    # ------------------------------------------------------------------
    # Tool / function-call results carried in the message history
    # ------------------------------------------------------------------
    def _format_tool_results(self, request: Any, budget: int) -> tuple[Optional[str], int]:
        """Render ``tool``-role message payloads within a character budget.

        Args:
            request: The parsed ``QueryRequest``.
            budget: Remaining characters available for attached data.

        Returns:
            A ``(block, remaining_budget)`` tuple; *block* is ``None`` when the
            history carried no tool results.
        """
        messages = _safe(request, "messages", []) or []
        lines: List[str] = []
        for message in messages:
            if _safe(message, "role") != "tool":
                continue
            function = _safe(message, "function", "tool")
            entries = _safe(message, "data")
            if entries is None:
                continue
            if not isinstance(entries, (list, tuple)):
                entries = [entries]

            rendered: List[str] = []
            for entry in entries:
                payload, budget = self._render_data_content(entry, budget)
                if payload:
                    rendered.append(payload)
                if budget <= 0:
                    break
            if rendered:
                lines.append(f"- {function}:")
                lines.append(self._indent("\n".join(rendered)))
            if budget <= 0:
                self._note_truncation(lines)
                break

        if not lines:
            return None, budget
        return "\n".join(["Data already retrieved in this conversation:", *lines]), budget

    @staticmethod
    def _note_truncation(lines: List[str]) -> None:
        """Append the truncation marker unless the last line already carries it."""
        if not lines or not lines[-1].endswith(DATA_TRUNCATION_MARKER):
            lines.append(f"  {DATA_TRUNCATION_MARKER}")

    def _render_data_content(self, data: Any, budget: int) -> tuple[str, int]:
        """Extract text from a ``DataContent``-like payload within *budget*.

        Handles ``DataContent`` (``.items[].content``), a bare string, and
        anything else by falling back to ``str()`` so a Workspace-version drift
        degrades to a truncated repr instead of dropping the payload.

        Args:
            data: The payload to render.
            budget: Remaining characters available.

        Returns:
            A ``(text, remaining_budget)`` tuple; *text* is ``""`` when nothing
            renderable was found or the budget is exhausted.
        """
        if data is None or budget <= 0:
            return "", budget

        chunks: List[str] = []
        items = _safe(data, "items")
        if isinstance(items, (list, tuple)):
            for item in items:
                content = _safe(item, "content")
                if content:
                    chunks.append(str(content))
        elif isinstance(data, str):
            chunks.append(data)
        else:
            chunks.append(str(data))

        text = "\n".join(chunk for chunk in chunks if chunk).strip()
        if not text:
            return "", budget
        if len(text) > budget:
            return text[:budget] + DATA_TRUNCATION_MARKER, 0
        return text, budget - len(text)

    @staticmethod
    def _indent(text: str) -> str:
        """Indent every line of *text* by four spaces."""
        return "\n".join(f"    {line}" for line in text.splitlines())

    # ------------------------------------------------------------------
    # Widgets (metadata only)
    # ------------------------------------------------------------------
    def _collect_widgets(self, request: Any) -> List[Any]:
        """Return every widget across the primary / secondary / extra groups."""
        collection = _safe(request, "widgets")
        if collection is None:
            return []
        widgets: List[Any] = []
        for group in ("primary", "secondary", "extra"):
            widgets.extend(_safe(collection, group, []) or [])
        return widgets

    def _format_widgets(self, request: Any) -> Optional[str]:
        """Render widget names and current parameters, flagging the data gap.

        Args:
            request: The parsed ``QueryRequest``.

        Returns:
            The formatted block, or ``None`` when no widgets were supplied.
        """
        widgets = self._collect_widgets(request)
        if not widgets:
            return None

        lines = [
            "The user has these widgets on their dashboard. Only names and "
            "parameters are available — their values are NOT attached, so use "
            "your own data tools to fetch anything you need instead of guessing:"
        ]
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
                if p_name is None:
                    continue
                p_value = _safe(param, "current_value")
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
        """Render the current dashboard's name and active tab.

        ``openbb_ai.models.DashboardInfo`` exposes ``id`` / ``name`` /
        ``current_tab_id`` / ``tabs`` — there is no description field, so only
        those are reported.

        Args:
            request: The parsed ``QueryRequest``.

        Returns:
            The formatted line, or ``None`` when no dashboard info was supplied.
        """
        dashboard = _safe(_safe(request, "workspace_state"), "current_dashboard_info")
        if dashboard is None:
            return None

        name = _safe(dashboard, "name")
        if not name:
            return None
        line = f"Current dashboard: {name}"
        tab_id = _safe(dashboard, "current_tab_id")
        if tab_id:
            line += f" (active tab: {_truncate(tab_id, 60)})"
        return line
