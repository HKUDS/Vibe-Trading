"""ContextBuilder: builds LLM message context for the ReAct AgentLoop."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.agent.memory import WorkspaceMemory
from src.agent.skills import SkillsLoader
from src.agent.tools import ToolRegistry

_SYSTEM_PROMPT = """You are a finance research agent with 68 specialist skills, 22 tools, 5 core market-data sources (with auto-fallback), and 29 multi-agent swarm teams.
You handle backtesting, factor analysis, options pricing, risk audits, research reports, document/web reading, web search, structured market sentiment, and team-based workflows.

## Tools

{tool_descriptions}

## Skills (use load_skill to read full docs)

{skill_descriptions}

## State

{memory_summary}

## Task Routing

Decide which workflow to use based on the request:

**Backtest** — user wants to create, test, or optimize a trading strategy:
1. `load_skill("strategy-generate")` — read the SignalEngine contract
2. `write_file("config.json", ...)` — source, codes, dates, parameters
3. `write_file("code/signal_engine.py", ...)` — SignalEngine class
4. Syntax check → `backtest(run_dir=...)` → `read_file("artifacts/metrics.csv")`
5. Do NOT write run_backtest.py. The engine is built-in.

**Swarm team** — user wants multi-agent analysis, risk audit, committee review, or any task with "team/committee/panel/desk":
- Call `run_swarm(prompt="<user's full request>")` — it auto-selects the right preset.
- Examples: risk audit, investment committee, equity research, technical panel, cross-market allocation.
- Do NOT attempt multi-dimensional analysis solo. Use swarm.

**Analysis / research** — user wants factor analysis, options pricing, market data, market sentiment, or general research:
- Load the relevant skill first, then use the matching tool (factor_analysis, options_pricing, market_sentiment, bash for custom scripts).

**Document / web** — user provides a PDF or URL:
- `read_document(path=...)` for PDFs, `read_url(url=...)` for web pages.

## Guidelines

- Load the relevant skill BEFORE starting any task. Skills contain the exact API contracts and examples.
- Ask the user if critical info is missing (assets, dates, strategy type). Never guess.
- Output results as markdown tables. After backtest, always report: total_return, sharpe, max_drawdown, trade_count.
- All file paths are relative to run_dir (auto-injected).
- Respond in the same language the user used.
"""


class ContextBuilder:
    """Builds message context for AgentLoop.

    Attributes:
        registry: Tool registry.
        memory: Workspace memory.
        skills_loader: Skills loader.
    """

    def __init__(self, registry: ToolRegistry, memory: WorkspaceMemory,
                 skills_loader: Optional[SkillsLoader] = None) -> None:
        """Initialize ContextBuilder.

        Args:
            registry: Tool registry.
            memory: Workspace memory.
            skills_loader: Skills loader (auto-created if not provided).
        """
        self.registry = registry
        self.memory = memory
        self.skills_loader = skills_loader or SkillsLoader()

    def build_system_prompt(self, user_message: str = "") -> str:
        """Build system prompt.

        Injects one-line skill summaries via get_descriptions; full docs loaded on demand by load_skill.

        Args:
            user_message: User message (kept for API compatibility).

        Returns:
            System prompt text.
        """
        return _SYSTEM_PROMPT.format(
            tool_descriptions=self._format_tool_descriptions(),
            skill_descriptions=self.skills_loader.get_descriptions(),
            memory_summary=self.memory.to_summary(),
        )

    def build_messages(self, user_message: str, history: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Build full message list.

        Args:
            user_message: User message.
            history: Prior conversation messages.

        Returns:
            OpenAI-format message list.
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.build_system_prompt(user_message)},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _format_tool_descriptions(self) -> str:
        """Format tool descriptions."""
        lines = []
        for tool in self.registry._tools.values():
            params = tool.parameters.get("properties", {})
            required = tool.parameters.get("required", [])
            param_parts = []
            for pname, pschema in params.items():
                req = " (required)" if pname in required else ""
                param_parts.append(f"    - {pname}: {pschema.get('description', pschema.get('type', ''))}{req}")
            param_text = "\n".join(param_parts) if param_parts else "    (no params)"
            lines.append(f"### {tool.name}\n{tool.description}\n  Params:\n{param_text}")
        return "\n\n".join(lines)

    @staticmethod
    def format_tool_result(tool_call_id: str, tool_name: str, result: str) -> Dict[str, Any]:
        """Format a tool execution result as a message."""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        }

    @staticmethod
    def format_assistant_tool_calls(tool_calls: list, content: Optional[str] = None) -> Dict[str, Any]:
        """Format an assistant tool_calls message, preserving thinking text.

        Args:
            tool_calls: List of tool call objects.
            content: Model reasoning/thinking text.

        Returns:
            OpenAI-format assistant message.
        """
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ],
        }
