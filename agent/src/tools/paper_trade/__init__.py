"""paper_trade — deterministic paper-trading matching engine (pt-v1.1/pt-v1.2).

Research-only engine that matches injected orders (or a strategy's per-day
orders) against bars under each market's frozen rules and returns one in-band
JSON document.  It NEVER places a real order and touches no broker /
trading connector (REQUIREMENTS R1).

Module map — matching and wire (pt-v1.1 core): ``schema.py`` (wire contract +
boundary parse), ``state_hash.py`` (JCS ``received_state_hash`` and the D3
engine fingerprint), ``calendar.py`` (cn_a CH truth / hk-us zero calendar),
``limits_cn_a.py`` (cn_a limit/ST/suspension), ``data.py`` (market data supply +
AM-9 federation), ``rules.py`` (three-market rule matrix + ``RULES_VERSION``),
``engine.py`` (day-loop matching), ``corporate_actions.py`` (split detector),
``wire.py`` (success/error serialization), ``tool.py`` (the ``paper_trade_step``
entry), ``strategy_exec.py`` (Step 7 strategy_path execution).

pt-v1.2 additive surface (cn_a 5m post-close step, P0): ``data_5m.py`` (stk_mins
fetch + continuous-session assembly) and ``session_5m.py`` (per-bar
``OrderBook`` wiring).  It is opt-in: a call that omits every v1.2 request field
is byte-identical to pt-v1.1.

The persistent v1.2 runner/account/store layer (``runner.py``, ``account.py``,
``store.py``, ``storage_io.py``, ``engine_adapter.py``, ``recovery.py``,
``trading_days.py``) is a follow-up branch (``paper-trade-v12-persistence``),
not part of this change: it is not wired to any CLI, API or MCP surface yet.

The tool registry's auto-discovery (``src/tools/__init__.py``) imports this
package at agent startup and collects :class:`PaperTradeStepTool` via
``BaseTool.__subclasses__()`` (VD-12).  Consumers import submodules explicitly
(``from src.tools.paper_trade import engine``); this ``__init__`` re-exports
only the tool class the registry discovers.
"""

from __future__ import annotations

from .tool import PaperTradeStepTool

__all__ = ["PaperTradeStepTool"]
