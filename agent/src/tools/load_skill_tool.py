"""Load skill tool: load full skill documentation by name."""

from __future__ import annotations

import json
import re
from typing import Any

from src.agent.skills import SkillsLoader
from src.agent.tools import BaseTool

_MARKET_DATA_NAME_PATTERN = re.compile(
    r"(crypto|market|btc|eth|price|ohlcv|ticker).{0,12}(price|fetch|fetcher|data)|"
    r"(price|fetch|fetcher|data).{0,12}(crypto|market|btc|eth|ohlcv|ticker)",
    re.IGNORECASE,
)


class LoadSkillTool(BaseTool):
    """Load the full documentation for a named skill."""

    name = "load_skill"
    description = "Load full documentation for a named skill. Use this to learn about unfamiliar strategy patterns or workflows before starting."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name (e.g. 'strategy-generate', 'momentum')"},
        },
        "required": ["name"],
    }
    repeatable = True

    def __init__(self, skills_loader: SkillsLoader | None = None) -> None:
        """Initialize LoadSkillTool.

        Args:
            skills_loader: SkillsLoader instance; creates one automatically if omitted.
        """
        self._loader = skills_loader or SkillsLoader()

    def execute(self, **kwargs: Any) -> str:
        """Load skill documentation.

        Args:
            **kwargs: Must include name.

        Returns:
            Full skill documentation or an error message.
        """
        name = kwargs["name"]
        content = self._loader.get_content(name)
        if content.startswith("Error:"):
            if _MARKET_DATA_NAME_PATTERN.search(name or ""):
                hint = (
                    f"skill '{name}' does not exist. For price/OHLCV/ticker/candle "
                    f"data use the get_market_data tool instead — never invent "
                    f"a market-data skill name."
                )
            else:
                hint = (
                    f"skill '{name}' does not exist. Do not invent skill names. "
                    f"For price/OHLCV/ticker data use the get_market_data tool. "
                    f"For other workflows, choose from the skills listed in the "
                    f"system prompt."
                )
            return json.dumps({"status": "error", "content": hint, "error": hint}, ensure_ascii=False)
        return json.dumps({"status": "ok", "content": content}, ensure_ascii=False)
