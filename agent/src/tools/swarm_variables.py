"""Prompt-to-variable extraction for swarm preset task templates.

`SwarmTool` resolves the team preset from the user prompt and then fills the
preset's YAML template variables. The helpers here keep those variables tied
to what the user actually asked for, using the vocabularies declared in each
preset YAML under ``agent/src/swarm/presets/``.
"""

from __future__ import annotations

import re
from typing import Any

# Market labels used in YAML templates (English, compatible with {market} placeholders).
_MARKET_PATTERNS: list[tuple[str, list[str]]] = [
    ("A-shares", [r"A股", r"a股", "沪深", "上证", "深证", "创业板", "科创板", "中证", r"\bCSI\b"]),
    ("crypto", ["加密", r"\bcrypto\b", r"\bBTC\b", r"\bETH\b", "币", "USDT", "数字货币"]),
    ("Hong Kong", ["港股", "恒生", r"H股", "港交所", r"\.HK\b"]),
    ("US", ["美股", "纳斯达克", "标普", "道琼斯", r"S&P", r"\.US\b"]),
]

# Risk tolerance for global_allocation_committee (English).
_RISK_PATTERNS: list[tuple[str, list[str]]] = [
    ("conservative", ["保守", r"低风险", "稳健偏保守", r"conservative"]),
    ("moderate", ["稳健", "中等风险", r"moderate", r"balanced"]),
    ("aggressive", ["激进", "高风险", "进取", r"aggressive"]),
]


_STRATEGY_TYPE_PATTERNS: list[tuple[str, list[str]]] = [
    ("low-price", [r"\blow[- ]price\b", r"\bcheap\b", r"\bdiscount\b", r"\blow premium\b"]),
    ("dual-low", [r"\bdual[- ]low\b", r"\bdouble[- ]low\b"]),
    ("high-convexity", [r"\bhigh[- ]convexity\b", r"\bconvexity\b"]),
    ("rotation", [r"\brotation\b", r"\brotate\b", r"\brebalance\b"]),
]

_TARGET_VARIABLE_PATTERNS: list[tuple[str, list[str]]] = [
    ("volatility", [r"\bvolatility\b", r"\bvol\b", r"\bvariance\b", r"\brisk\b"]),
    ("direction", [r"\bdirection(?:al)?\b", r"\bup[- ]down\b", r"\bclassification\b"]),
    ("return", [r"\breturns?\b", r"\balpha\b", r"\bpredict\b", r"\bforecast\b"]),
]

_REVIEW_PERIOD_PATTERNS: list[tuple[str, list[str]]] = [
    ("monthly", [r"\bmonthly\b", r"\bmonth(?:ly)?\b"]),
    ("quarterly", [r"\bquarter(?:ly)?\b", r"\bq[1-4]\b"]),
]

_SECTOR_PATTERNS: list[tuple[str, list[str]]] = [
    ("banks", [r"\bbank(?:s|ing)?\b", r"\bfinancials?\b"]),
    ("consumer", [r"\bconsumer\b", r"\bretail\b", r"\bstaples\b", r"\bdiscretionary\b"]),
    ("semiconductors", [r"\bsemi(?:s|conductors?)?\b", r"\bchip(?:s)?\b"]),
    ("technology", [r"\btech(?:nology)?\b", r"\bsoftware\b", r"\binternet\b"]),
    ("energy", [r"\benergy\b", r"\boil\b", r"\bgas\b", r"\bpower\b"]),
    ("healthcare", [r"\bhealth ?care\b", r"\bbiotech\b", r"\bpharma\b"]),
    ("industrials", [r"\bindustrial(?:s)?\b", r"\bmanufacturing\b"]),
    ("real estate", [r"\breal estate\b", r"\bproperty\b", r"\breit(?:s)?\b"]),
    ("utilities", [r"\butilit(?:y|ies)\b"]),
    ("materials", [r"\bmaterials?\b", r"\bmetals?\b", r"\bmining\b"]),
]

# Commodity labels accepted by commodity_research_team (see the preset YAML).
_COMMODITY_PATTERNS: list[tuple[str, list[str]]] = [
    ("crude oil", [r"\bcrude(?:\s+oil)?\b", r"\bWTI\b", r"\bBrent\b", "原油"]),
    ("natural gas", [r"\bnatural\s+gas\b", "天然气"]),
    ("iron ore", [r"\biron\s+ore\b", "铁矿石"]),
    ("gold", [r"\bgold\b", "黄金"]),
    ("silver", [r"\bsilver\b", "白银"]),
    ("copper", [r"\bcopper\b", "铜"]),
    ("aluminum", [r"\balumin(?:um|ium)\b", "铝"]),
    ("nickel", [r"\bnickel\b", "镍"]),
    ("lithium", [r"\blithium\b", "锂"]),
    ("coal", [r"\bcoal\b", r"\bcoking\s+coal\b", "煤炭", "焦煤"]),
    ("soybeans", [r"\bsoybeans?\b", "大豆"]),
    ("rebar", [r"\brebar\b", r"\bsteel\s+rebar\b", "螺纹钢"]),
]

# Factor types accepted by factor_research_committee (see the preset YAML).
_FACTOR_TYPE_PATTERNS: list[tuple[str, list[str]]] = [
    ("value", [r"\bvalue\b", r"\bvaluation\b", "价值"]),
    ("momentum", [r"\bmomentum\b", r"\btrend[- ]following\b", "动量"]),
    ("quality", [r"\bquality\b", "质量"]),
    ("growth", [r"\bgrowth\b", "成长"]),
    ("alternative", [r"\balternative\b", "另类"]),
]

# Event types accepted by event_driven_task_force (see the preset YAML).
_EVENT_TYPE_PATTERNS: list[tuple[str, list[str]]] = [
    ("M&A", [r"\bM&A\b", r"\bmergers?\b", r"\bacquisitions?\b", "并购", "收购"]),
    ("earnings", [r"\bearnings\b", "财报", "业绩"]),
    ("insider trading", [r"\binsider\b", "内部人", "内幕"]),
    ("policy", [r"\bpolicy\b", r"\bregulat(?:ion|ory)\b", "政策", "监管"]),
    ("litigation", [r"\blitigation\b", r"\blawsuits?\b", "诉讼"]),
    ("management change", [r"\bmanagement\s+change\b", "高管变动", "管理层变动"]),
]

# Market views accepted by derivatives_strategy_desk (see the preset YAML).
_VIEW_PATTERNS: list[tuple[str, list[str]]] = [
    ("long volatility", [r"\blong\s+vol(?:atility)?\b", "做多波动率"]),
    ("short volatility", [r"\bshort\s+vol(?:atility)?\b", "做空波动率"]),
    ("bullish", [r"\bbullish\b", r"\bupside\b", "看涨", "看多"]),
    ("bearish", [r"\bbearish\b", r"\bdownside\b", "看跌", "看空"]),
    ("neutral", [r"\bneutral\b", r"\brange[- ]bound\b", "中性", "震荡"]),
]

# Fund types accepted by fund_selection_panel (see the preset YAML).
_FUND_TYPE_PATTERNS: list[tuple[str, list[str]]] = [
    ("QDII", [r"\bQDII\b"]),
    ("index-enhanced", [r"\bindex[- ]enhanced\b", "指数增强"]),
    ("quant hedge", [r"\bquant(?:itative)?\s+hedge\b", r"\bhedge\s+fund\b", "量化对冲", "对冲基金"]),
    ("balanced", [r"\bbalanced\b", r"\bhybrid\b", "平衡型", "混合型"]),
    ("bond", [r"\bbond\b", r"\bfixed[- ]income\b", "债券", "固收", "债基"]),
    ("equity", [r"\bequit(?:y|ies)\b", r"\bstocks?\b", "股票型", "权益"]),
]

# Crypto assets recognised in crypto_research_lab prompts (symbols + common names).
_CRYPTO_TARGET_RE = re.compile(
    r"\b(BTC|ETH|SOL|BNB|XRP|ADA|DOGE|AVAX|DOT|LINK|TON|LTC|MATIC)\b"
    r"|(bitcoin|ethereum|solana|dogecoin|ripple|cardano|avalanche|polkadot|chainlink|toncoin|比特币|以太坊|索拉纳|狗狗币|瑞波)",
    re.IGNORECASE,
)
_CRYPTO_NAME_TO_SYMBOL = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "dogecoin": "DOGE",
    "ripple": "XRP",
    "cardano": "ADA",
    "avalanche": "AVAX",
    "polkadot": "DOT",
    "chainlink": "LINK",
    "toncoin": "TON",
    "比特币": "BTC",
    "以太坊": "ETH",
    "索拉纳": "SOL",
    "狗狗币": "DOGE",
    "瑞波": "XRP",
}

# Timeframe labels accepted by crypto_research_lab (see the preset YAML).
_TIMEFRAME_PATTERNS: list[tuple[str, list[str]]] = [
    ("short-term 1-4 weeks", [r"\bshort[- ]term\b", r"\b1[- ]?4\s+weeks\b", "短期", "短线"]),
    ("long-term 3-12 months", [r"\blong[- ]term\b", r"\b3[- ]12\s+months\b", "长期", "长线"]),
    ("medium-term 1-3 months", [r"\bmedium[- ]term\b", r"\bmid[- ]term\b", "中期", "中线"]),
]

# Macro cadence accepted by macro_strategy_forum (see the preset YAML).
_MACRO_HORIZON_PATTERNS: list[tuple[str, list[str]]] = [
    ("annual", [r"\bannual(?:ly)?\b", r"\byearly\b", r"\b1[- ]year\b", "年度", "全年"]),
    ("monthly", [r"\bmonthly\b", r"\b1[- ]month\b", "月度"]),
    ("quarterly", [r"\bquarterly\b", r"\bquarters?\b", r"\bQ[1-4]\b", "季度"]),
]


def _extract_market(prompt: str) -> str:
    """Extract target market label from prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Market label for template variables, default A-shares.
    """
    for market, patterns in _MARKET_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return market
    return "A-shares"


def _extract_risk_tolerance(prompt: str) -> str:
    """Extract risk tolerance from prompt (English labels).

    Args:
        prompt: User's natural language prompt.

    Returns:
        conservative | moderate | aggressive.
    """
    for level, patterns in _RISK_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return level
    return "moderate"


def _risk_to_etf_profile(risk: str) -> str:
    """Map tolerance to etf_allocation_desk risk_profile values."""
    return {"conservative": "conservative", "moderate": "balanced", "aggressive": "aggressive"}.get(risk, "balanced")


def _extract_strategy_type(prompt: str) -> str:
    """Extract convertible bond strategy type from prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Strategy type label used by the convertible bond preset.
    """
    for strategy_type, patterns in _STRATEGY_TYPE_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return strategy_type
    return "rotation"


def _extract_target_variable(prompt: str) -> str:
    """Extract ML prediction target from prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Prediction target label for ml_quant_lab.
    """
    for target_variable, patterns in _TARGET_VARIABLE_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return target_variable
    return "return"


def _extract_review_period(prompt: str) -> str:
    """Extract portfolio review cadence from prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Review cadence label for portfolio_review_board.
    """
    for review_period, patterns in _REVIEW_PERIOD_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return review_period
    return "quarterly"


def _extract_sector(prompt: str) -> str:
    """Extract sector constraint from prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Sector filter value, or empty string for full-market scans.
    """
    broad_market_patterns = [
        r"\bfull market\b",
        r"\bbroad market\b",
        r"\ball sectors\b",
        r"\bacross sectors\b",
    ]
    for pat in broad_market_patterns:
        if re.search(pat, prompt, re.IGNORECASE):
            return ""

    for sector, patterns in _SECTOR_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return sector
    return ""


def _extract_commodity(prompt: str) -> str:
    """Extract the commodity named by the prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Commodity label for commodity_research_team, default gold.
    """
    for commodity, patterns in _COMMODITY_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return commodity
    return "gold"


def _extract_horizon(prompt: str) -> str:
    """Extract an investment horizon phrase such as "6 months" or "1 year".

    Args:
        prompt: User's natural language prompt.

    Returns:
        Horizon phrase for commodity_research_team, default 3 months.
    """
    months = re.search(r"(\d{1,3})\s*(?:个)?\s*(?:months?|月)", prompt, re.IGNORECASE)
    if months:
        count = int(months.group(1))
        return f"{count} month" if count == 1 else f"{count} months"
    years = re.search(r"(\d{1,3})\s*(?:个)?\s*(?:years?|年)", prompt, re.IGNORECASE)
    if years:
        count = int(years.group(1))
        return f"{count} year" if count == 1 else f"{count} years"
    if re.search(r"半年|half\s*(?:a\s*)?year", prompt, re.IGNORECASE):
        return "6 months"
    if re.search(r"一年|one\s+year", prompt, re.IGNORECASE):
        return "1 year"
    return "3 months"


def _extract_factor_type(prompt: str) -> str:
    """Extract the factor type named by the prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Factor type label for factor_research_committee, default value.
    """
    for factor_type, patterns in _FACTOR_TYPE_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return factor_type
    return "value"


def _extract_event_type(prompt: str) -> str:
    """Extract the event type named by the prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Event type label for event_driven_task_force, default all types.
    """
    for event_type, patterns in _EVENT_TYPE_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return event_type
    return "all types"


def _extract_view(prompt: str) -> str:
    """Extract the market view named by the prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        View label for derivatives_strategy_desk, default neutral.
    """
    for view, patterns in _VIEW_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return view
    return "neutral"


def _extract_crypto_target(prompt: str) -> str:
    """Extract the crypto assets named by the prompt, in prompt order.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Comma-separated symbols for crypto_research_lab, default BTC, ETH, SOL.
    """
    found: list[str] = []
    for match in _CRYPTO_TARGET_RE.finditer(prompt):
        symbol = match.group(1).upper() if match.group(1) else _CRYPTO_NAME_TO_SYMBOL.get(match.group(2).lower(), "")
        if symbol and symbol not in found:
            found.append(symbol)
    return ", ".join(found) if found else "BTC, ETH, SOL"


def _extract_timeframe(prompt: str) -> str:
    """Extract the analysis timeframe for crypto_research_lab.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Timeframe label, default medium-term 1-3 months.
    """
    for timeframe, patterns in _TIMEFRAME_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return timeframe
    count_text, unit = _extract_horizon(prompt).split()
    months = int(count_text) * (12 if unit.startswith("year") else 1)
    return "medium-term 1-3 months" if months <= 3 else "long-term 3-12 months"


def _extract_fund_type(prompt: str) -> str:
    """Extract the fund type named by the prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Fund type label for fund_selection_panel, default equity.
    """
    for fund_type, patterns in _FUND_TYPE_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return fund_type
    return "equity"


def _extract_macro_horizon(prompt: str) -> str:
    """Extract the macro cadence named by the prompt.

    Args:
        prompt: User's natural language prompt.

    Returns:
        Cadence label for macro_strategy_forum, default quarterly.
    """
    for horizon, patterns in _MACRO_HORIZON_PATTERNS:
        for pat in patterns:
            if re.search(pat, prompt, re.IGNORECASE):
                return horizon
    return "quarterly"


def _snippet(prompt: str, max_len: int = 240) -> str:
    """Trim prompt for auxiliary fields."""
    s = prompt.strip()
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def build_variables(preset_name: str, prompt: str) -> dict[str, str]:
    """Build template variables from prompt for the matched preset.

    Args:
        preset_name: Matched preset name.
        prompt: User's original prompt.

    Returns:
        Dict of template variables required by the YAML preset.
    """
    market = _extract_market(prompt)
    risk = _extract_risk_tolerance(prompt)
    goal = prompt.strip()
    g = _snippet(goal, 2000)

    # Preset-specific variable sets (see agent/src/swarm/presets/*.yaml).
    builders: dict[str, dict[str, str]] = {
        "global_allocation_committee": {"goal": g, "risk_tolerance": risk},
        "equity_research_team": {"market": market, "goal": g},
        "quant_strategy_desk": {"market": market, "goal": g},
        "risk_committee": {"goal": g},
        "factor_research_committee": {"market": market, "factor_type": _extract_factor_type(prompt)},
        "event_driven_task_force": {"market": market, "event_type": _extract_event_type(prompt)},
        "etf_allocation_desk": {"risk_profile": _risk_to_etf_profile(risk), "market": market},
        "derivatives_strategy_desk": {"target": g, "view": _extract_view(prompt)},
        "crypto_research_lab": {"target": _extract_crypto_target(prompt), "timeframe": _extract_timeframe(prompt)},
        "credit_research_team": {"target": g, "market": "China credit bonds"},
        "convertible_bond_team": {
            "market": "A-share convertible bonds",
            "goal": g,
            "strategy_type": _extract_strategy_type(prompt),
        },
        "fundamental_research_team": {"target": g, "market": market},
        "commodity_research_team": {"commodity": _extract_commodity(prompt), "horizon": _extract_horizon(prompt)},
        "fund_selection_panel": {"fund_type": _extract_fund_type(prompt), "goal": g},
        "social_alpha_team": {"target": g, "timeframe": "daily"},
        "geopolitical_war_room": {"crisis": g, "market": market},
        "pairs_research_lab": {"market": market, "sector": _extract_sector(prompt)},
        "investment_committee": {"target": g, "market": market},
        "value_investing_committee": {"company": g, "market": market},
        "macro_strategy_forum": {"market": market, "horizon": _extract_macro_horizon(prompt)},
        "statistical_arbitrage_desk": {"market": market, "goal": g, "sector": _extract_sector(prompt)},
        "sentiment_intelligence_team": {"market": market, "timeframe": "daily"},
        "technical_analysis_panel": {"target": g, "timeframe": "daily"},
        "sector_rotation_team": {"market": market, "goal": g},
        "portfolio_review_board": {"portfolio": g, "review_period": _extract_review_period(prompt), "goal": g},
        "ml_quant_lab": {"market": market, "target_variable": _extract_target_variable(prompt), "goal": g},
    }

    return builders.get(preset_name, {"market": market, "goal": g})


def merge_variables(variables: dict[str, str], overrides: Any) -> tuple[dict[str, str], str | None]:
    """Merge caller-supplied template-variable overrides over extracted values.

    Args:
        variables: Variables extracted from the prompt.
        overrides: Explicit values from the tool call; None means no override.

    Returns:
        Tuple of (merged variables, error string or None).
    """
    if overrides is None:
        return variables, None
    if not isinstance(overrides, dict):
        return variables, "variables must be an object of string values"
    merged = dict(variables)
    for key, value in overrides.items():
        merged[str(key)] = str(value)
    return merged, None
