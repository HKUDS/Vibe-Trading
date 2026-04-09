"""Tool registry: v7 atomic tools + domain tools."""

from src.agent.tools import ToolRegistry


def build_registry() -> ToolRegistry:
    """Build the v7 tool registry (atomic tools + domain tools).

    Returns:
        ToolRegistry containing all v7 tools.
    """
    from src.tools.bash_tool import BashTool
    from src.tools.read_file_tool import ReadFileTool
    from src.tools.write_file_tool import WriteFileTool
    from src.tools.edit_file_tool import EditFileTool
    from src.tools.load_skill_tool import LoadSkillTool
    from src.tools.backtest_tool import BacktestTool
    from src.tools.pattern_tool import PatternTool
    from src.tools.compact_tool import CompactTool
    from src.tools.subagent_tool import SubagentTool
    from src.tools.task_tools import TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool
    from src.tools.background_tools import BackgroundRunTool, CheckBackgroundTool
    from src.tools.web_reader_tool import WebReaderTool
    from src.tools.web_search_tool import WebSearchTool
    from src.tools.market_sentiment_tool import MarketSentimentTool
    from src.tools.doc_reader_tool import DocReaderTool
    from src.tools.factor_analysis_tool import FactorAnalysisTool
    from src.tools.options_pricing_tool import OptionsPricingTool
    from src.tools.swarm_tool import SwarmTool
    registry = ToolRegistry()
    for tool in [BashTool(), ReadFileTool(), WriteFileTool(),
                 EditFileTool(), LoadSkillTool(), BacktestTool(),
                 PatternTool(), CompactTool(), SubagentTool(),
                 TaskCreateTool(), TaskUpdateTool(), TaskListTool(), TaskGetTool(),
                 BackgroundRunTool(), CheckBackgroundTool(),
                 WebReaderTool(), WebSearchTool(), MarketSentimentTool(), DocReaderTool(),
                 FactorAnalysisTool(), OptionsPricingTool(), SwarmTool()]:
        registry.register(tool)
    return registry


def build_filtered_registry(tool_names: list[str]) -> ToolRegistry:
    """Build a ToolRegistry with only specified tools.

    Creates the full registry, then filters to include only tools
    whose names appear in the provided list. Unknown names are silently skipped.

    Args:
        tool_names: Tool names to include in the filtered registry.

    Returns:
        ToolRegistry containing only the requested tools.
    """
    full = build_registry()
    filtered = ToolRegistry()
    for name in tool_names:
        tool = full.get(name)
        if tool:
            filtered.register(tool)
    return filtered


__all__ = ["build_registry", "build_filtered_registry"]
