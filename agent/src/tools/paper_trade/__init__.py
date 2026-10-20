"""paper_trade — deterministic paper-trading matching engine (pt-v1.1).

Research-only engine that matches injected orders (or a strategy's per-day
orders) against daily bars under each market's frozen rules and returns one
in-band JSON document.  It NEVER places a real order and touches no broker /
trading connector (REQUIREMENTS R1).

Module map: ``schema.py`` (wire contract + boundary parse), ``state_hash.py``
(JCS ``received_state_hash``), ``calendar.py`` (cn_a CH truth / hk-us zero
calendar), ``limits_cn_a.py`` (cn_a limit/ST/suspension), ``data.py`` (market
data supply + AM-9 federation), ``rules.py`` (three-market rule matrix),
``engine.py`` (day-loop matching), ``corporate_actions.py`` (split detector),
``wire.py`` (success/error serialization), ``tool.py`` (the ``paper_trade_step``
entry), ``strategy_exec.py`` (Step 7 strategy_path execution).

The tool registry's auto-discovery (``src/tools/__init__.py``) imports this
package at agent startup and collects :class:`PaperTradeStepTool` via
``BaseTool.__subclasses__()`` (VD-12).  Consumers import submodules explicitly
(``from src.tools.paper_trade import engine``); this ``__init__`` re-exports
only the tool class the registry discovers.
"""

from __future__ import annotations

from .tool import PaperTradeStepTool

__all__ = ["PaperTradeStepTool"]
