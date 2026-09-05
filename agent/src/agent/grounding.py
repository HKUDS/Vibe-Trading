"""Run-scoped identity and numeric evidence gates for the main agent loop.

The language model remains responsible for research and explanation, but three
facts are structural rather than advisory:

* a market-data consumer may only use an identity that was locked before the
  current assistant tool-call batch started;
* a final price claim may not contradict the full, untruncated tool result; and
* a figure may not be attached to an instrument that no tool call in this run
  ever passed in or returned.

Those are the mechanically decidable parts of the agent's output principles.
The rest of that contract — "state the as-of", "analysis, not advice", "refuse
out loud" — stays in the system prompt on purpose: see ``_validate_price_claims``
and the module tests for why a regex gate on them rejects correct answers.

This module deliberately contains no provider or tool-registry dependencies so
its state machine and final-answer checks remain deterministic and testable.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from src.market_data import canonical_fx_pair

from src.agent.resolution_context import (
    IdentityConstraint,
    ResolutionContext,
    candidate_market,
)


GROUNDING_ARTIFACT = "grounding_evidence.json"

_RESOLVER_TOOL = "search_symbol"

# Tools whose successful completion can ground backtest/analysis metric claims
# (#1336). Success alone is not authority: only results that actually carried
# metric output (parsed from the result or its run-dir artifacts) raise
# ``analysis_claim_unavailable``. A deduplicated ("skipped") call is never a
# completion.
_ANALYSIS_TOOLS = frozenset(
    {"backtest", "factor_analysis", "run_shadow_backtest", "quantlib_call"}
)
# Tools whose run produces the equity/regime windows behind a categorical
# "all N-month windows were profitable" statement.
_ANALYSIS_WINDOW_TOOLS = frozenset({"backtest", "run_shadow_backtest"})
_PRIVATE_COMPANY_SKILL_NAMES = {
    "private-company",
    "private-company-analysis",
    "private-company-research",
    "private_company",
    "private_company_analysis",
    "private_company_research",
}
_SYMBOL_ARGUMENT_KEYS = {
    "code",
    "codes",
    "symbol",
    "symbols",
    "ticker",
    "tickers",
    "underlying",
    "underlyings",
}
# Workflow selection must not race an in-flight resolution or proceed on
# contradicted identity. It may proceed once the resolver has answered — and
# ``ambiguous`` is an answer: a screening request ("推荐低价高增长股票") resolves to
# many candidates by design. Requiring a locked identity there stalls every
# discovery task before it can load a screening skill, which is #955.
_RESOLUTION_INCOMPLETE_STATUSES = {"unresolved", "conflicting", "invalidated"}
# Bounded read-only recovery (#1081): a missing instrument identity or price
# evidence is often recoverable deterministically, so the loop should keep
# driving the original task through `search_symbol` and `get_market_data`
# instead of handing the user a terminal "confirm and continue" fallback.
# These budgets are separate from the rejected-draft count so real recovery
# progress is never cut off at the three-draft retry cap.
MAX_GROUNDING_RECOVERY_ROUNDS = 6
MAX_SYMBOL_RESOLUTION_ATTEMPTS = 2
MAX_PRICE_EVIDENCE_ATTEMPTS = 3
_PRICE_FIELDS = {"open", "high", "low", "close", "adj_close", "price"}
_TIMESTAMP_FIELDS = ("trade_date", "date", "datetime", "timestamp", "time", "index")
_MAX_GENERIC_EVIDENCE = 2_000
_MAX_TRACKED_SYMBOLS = 5_000

# CSV columns (case-insensitive) accepted from OHLC files the run wrote via
# bash+yfinance, and their canonical price-field names. Everything else in the
# file (Volume, Adj Close, etc.) is deliberately ignored so the contradiction
# check does not gain values it would be willing to accept.
_CSV_PRICE_COLUMNS = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "price": "price",
}
_CSV_DATE_COLUMNS = {"date", "datetime", "trade_date", "timestamp", "index"}
# Filename -> symbol mapping for run-dir CSVs. The bash workaround writes each
# series with a filesystem-safe stem: ``BYN_V.csv`` for ``BYN.V``, ``PDI_TO.csv``
# for ``PDI.TO``, ``GC_F.csv`` for ``GC=F``.
_CSV_FILENAME_SUFFIX_MAP = (
    ("_V", ".V"),
    ("_TO", ".TO"),
    ("_F", "=F"),
    # A US name is written ``INTC_US.csv`` by the same workaround, and
    # ``.US`` is the venue suffix the rest of the project resolves on. Without
    # this row the CSV was ingested as no evidence at all, so every price the
    # run had actually fetched came back "numeric_claim_unavailable".
    ("_US", ".US"),
)

# Only ``get_market_data`` returns bars whose columns are already the canonical
# OHLC field names. Every other market-sensitive tool nests its quote somewhere,
# and ``_ingest_generic_numeric`` stores that JSON path verbatim — "data.last",
# "quote[0].close_price". Without this map those observations never reach the
# final-answer check, so a price the run genuinely retrieved is rejected as
# "no matching observed tool evidence": measured against the live validator, an
# answer quoting a ``get_stock_profile`` price failed with
# ``numeric_claim_unavailable`` while the identical claim backed by
# ``get_market_data`` passed. Only unambiguous quote fields are mapped; ratios,
# volumes, strikes, and analyst targets stay out so the contradiction check does
# not gain a wider set of values it is willing to accept.
_GENERIC_PRICE_FIELD_ALIASES = {
    "open": "open",
    "open_price": "open",
    "openprice": "open",
    "开盘": "open",
    "开盘价": "open",
    "high": "high",
    "high_price": "high",
    "最高": "high",
    "最高价": "high",
    "low": "low",
    "low_price": "low",
    "最低": "low",
    "最低价": "low",
    "close": "close",
    "close_price": "close",
    "closeprice": "close",
    "prev_close": "close",
    "pre_close": "close",
    "preclose": "close",
    "previous_close": "close",
    "收盘": "close",
    "收盘价": "close",
    "昨收": "close",
    "adj_close": "adj_close",
    "adjclose": "adj_close",
    "adjusted_close": "adj_close",
    "price": "price",
    "last": "price",
    "last_price": "price",
    "lastprice": "price",
    "latest_price": "price",
    "current_price": "price",
    "market_price": "price",
    "settle": "price",
    "settlement": "price",
    "settle_price": "price",
    "vwap": "price",
    "现价": "price",
    "最新价": "price",
}

# Project-style canonical symbols. A bare model-generated ticker is still
# checked when it appears under a symbol argument key, but it is not accepted
# as user-provided identity because it lacks venue information.
#
# A joined crypto pair (``BTCUSDT``, ``ETHUSDT`` …) is recognized alongside
# the dashed/slashed form so a user message like ``Get BTCUSDT spot price``
# seeds an asserted identity and the asserted-symbol conflict check at
# ``_ingest_resolution`` runs against it. The base is restricted to alpha
# so a numeric prefix cannot masquerade as a joined pair, and the suffix
# list is the unambiguous stablecoin set (``USDT`` / ``USDC`` / ``BUSD`` /
# ``TUSD``) — ``USD`` is excluded because too many non-crypto strings end
# in those three letters and over-matching would lock the wrong identity.
_JOINED_CRYPTO_QUOTE_SUFFIXES = ("USDT", "USDC", "BUSD", "TUSD")
# Spot precious metals quoted in USD collide with the TUSD suffix: XPTUSD is
# XPT + USD (platinum), but stripping "TUSD" leaves the alpha base "XP" and
# folds it to XP-TUSD — a crypto pair that does not exist, and the same class
# of misresolution the USD exclusion above exists to prevent. XAU/XAG/XPD do
# not collide today; they are listed together because they are the same kind
# of symbol and a future suffix would collide with them the same way.
_METAL_USD_PAIR_RE = re.compile(r"^(?:XAU|XAG|XPT|XPD)USD$", re.IGNORECASE)
_JOINED_CRYPTO_RE = re.compile(
    r"(?<![A-Za-z0-9_])[A-Z]{2,15}(?:" + "|".join(_JOINED_CRYPTO_QUOTE_SUFFIXES) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_CANONICAL_SYMBOL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"\d{3,6}\.(?:SH|SZ|BJ|SS|HK|KS|KQ)|"
    r"[A-Z][A-Z0-9&.-]{0,19}\.(?:US|NS|BO|FX|TO|V)|"
    r"[A-Z0-9]{2,15}(?:-|/)(?:USDT|USDC|USD|BTC|ETH)|"
    r"[A-Z]{2,15}(?:" + "|".join(_JOINED_CRYPTO_QUOTE_SUFFIXES) + r")|"
    r"\^[A-Z0-9&.\-]{1,20}|"
    r"[A-Z0-9]{2,15}=[FX]"
    r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_ACTIONABLE_MARKET_RE = re.compile(
    r"(?:\bbuy\b|\bsell\b|\bentry\b|\btarget price\b|\bcurrent price\b|"
    r"\blatest price\b|\bprice of\b|\btrade\b|"
    r"\bvaluation of\b|\bwhat (?:is|are) .{1,80} worth\b|"
    r"\bis .{1,80} (?:listed|publicly traded)\b|"
    r"买入|卖出|入场|目标价|现价|最新价|股价|交易价格|估值|值多少钱|"
    r".{1,40}(?:是否|有没有|已经|已)(?:在.{0,20})?上市)",
    re.IGNORECASE,
)
_PRIVATE_ASSERTION_RE = re.compile(
    r"(?:\b(?:is|remains|still)\s+(?:an?\s+)?(?:private company|privately held)\b|"
    r"\bnot publicly traded\b|\bunlisted company\b|"
    r"(?:是|仍是|属于)(?:一家)?(?:私人|私营|非上市)公司|未上市|没有上市)",
    re.IGNORECASE,
)
# The bare verbs below are present tense only, which is not how an answer
# actually states an observed price: "closed at 412.35" and "last traded at
# 412.35" are the ordinary spellings and neither matches \bclose\b or
# \btrade\b. Chinese 收盘 / 现价 match, so the gate was strictly leakier in
# English than in Chinese — a fabricated USD price in the most natural
# phrasing walked straight through while its Chinese translation was caught.
# The past-tense forms are required to be followed by "at" so that reporting
# volume ("traded 1.2M shares") or a corporate event ("the deal closed at a
# 30% premium" — a percentage, already masked) is not read as a quote.
_PRICE_VERB_PAST_RE = r"\b(?:closed|opened|traded|quoted|priced|settled|fixed)\s+at\b"
_PRICE_CONTEXT_RE = re.compile(
    r"(?:\b(?:opening|open|high|low|closing|close|price|quote)\b|"
    + _PRICE_VERB_PAST_RE + r"|"
    r"\b(?:entry|buy|target|support|resistance)\s+(?:price|level)\b|"
    r"开盘价?|最高价?|最低价?|收盘价?|买入价|入场价|目标价|支撑位?|阻力位?|"
    # Chinese had the mirror-image gap: these four are as ordinary as 收盘价
    # and none of them matched, so a fabricated 成交价 / 股价 walked through
    # exactly the way "closed at" did in English.
    r"成交价|最新价|股价|收报|"
    r"现价|报价|价格|价位)",
    re.IGNORECASE,
)
_ANALYSIS_METRIC_RE = re.compile(
    r"(?:\breturn vol(?:atility)?\b|\bmax(?: |\.)?drawdown\b|\bmaxdd\b|"
    r"\bsharpe(?: ratio)?\b|\bwin rate\b|\bhit rate\b|"
    r"\bprob(?:ability)?\.?\s+of\b|\bvolatility\b|\bdrawdown\b|"
    r"\bannualiz\w*\b|\bwindow(?:s)?\b|\bregime(?:s)?\b|"
    r"\b(?:annual|cumulative|total)\s+return\b|"
    r"夏普|回撤|波动率|胜率|命中率|概率|年化|回测|窗口|收益(?:率)?|回报(?:率)?)",
    re.IGNORECASE,
)
# Phrases that indicate a figure is attributed to an external source rather
# than model memory (paper restatement, #1338 review). Attributing a number
# to a named source is the opposite of an unsourced claim. The subject list
# is deliberately restricted to sources that cannot be this run's own output
# (papers, studies, analysts, filings): "the backtest reports" / "the data
# shows" is exactly how a model dresses up its own numbers (#1336), so
# data/backtest/strategy/report subjects do NOT count.
_ATTRIBUTION_RE = re.compile(
    r"(?:"
    r"\b(?:the\s+(?:papers?|studies?|researchers?|analysts?|surveys?"
    r"|regulators?|authorities|literature|authors?)"
    r"|analysts?|researchers?|literature|sec\s+filings?\b|filings?"
    r"|annual\s+filings?|quarterly\s+filings?|rating\s+agencies?)"
    r"\s+(?:reports?|estimates?|shows?|indicates?|suggests?|states?|claims?"
    r"|notes?|cites?|mentions?|reveals?|discloses?|publishes?|found"
    r"|calculated|computed|derived)\b"
    r"|"
    r"(?:论文|文献|分析师|研究机构|学者)"
    r"[^。，\n]{0,6}?(?:报告|显示|表明|指出|称|估计|发现)"
    r")",
    re.IGNORECASE,
)
# Measurement-shaped numbers for analysis claims: keeps the % sign and sign
# (unlike _numbers_without_dates_or_percent, which drops percentages on
# purpose). A bare integer is NOT a measurement — "252 个交易日年化" is the
# standard convention, not a claim about this run's analysis (#1032-style
# definitional prose must stay untouched). Dates can still look like
# measurements, so date masks run first.
_MEASURE_NUMBER_RE = re.compile(
    r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)\s*[%％]?"  # decimal: 1.21, -8.1%
    r"|[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)\s*[%％]"  # integer percent: 55%, 70%
)
# A forward-looking frame means the figure is a forecast, not a claim that a
# backtest/analysis measured it — the measurement gate only polices "measured
# facts" (#1336), forecasts stay under the "analysis, not advice" prompt rule.
_FORECAST_FRAME_RE = re.compile(
    r"(?:\b(?:forecast|expected|projected|predicted)\b|预计|预期|预测|估计|展望)",
    re.IGNORECASE,
)

# Metric family for a claim/evidence leaf, so a figure is only grounded by
# evidence of its own kind: an observed price must never stand in for an
# invented volatility (#1336).
_ANALYSIS_KIND_ALIASES = {
    "annualized_vol": "vol",
    "annualized_volatility": "vol",
    "volatility": "vol",
    "return_vol": "vol",
    "return_volatility": "vol",
    "vol": "vol",
    "max_drawdown": "drawdown",
    "maxdd": "drawdown",
    "drawdown": "drawdown",
    "sharpe": "sharpe",
    "sharpe_ratio": "sharpe",
    "win_rate": "win_rate",
    "hit_rate": "win_rate",
    "hitrate": "win_rate",
    "probability": "probability",
    "prob": "probability",
    "total_return": "return",
    "annual_return": "return",
    "cumulative_return": "return",
    "benchmark_return": "return",
    "excess_return": "return",
    "annualized_return": "return",
    "return": "return",
    "returns": "return",
    "ic_positive_ratio": "win_rate",
}

# Order matters: 最大回撤 is drawdown before 收益/return, and 年化波动率 is vol
# before the generic return branch.
_ANALYSIS_KIND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:回撤|drawdown|maxdd|最大亏损)", re.IGNORECASE), "drawdown"),
    (
        re.compile(
            r"(?:波动率|波动性|volatility|annualized\s*vol|return\s*vol|年化波动)",
            re.IGNORECASE,
        ),
        "vol",
    ),
    (re.compile(r"(?:夏普|sharpe)", re.IGNORECASE), "sharpe"),
    (re.compile(r"(?:胜率|命中率|win\s*rate|hit\s*rate)", re.IGNORECASE), "win_rate"),
    (re.compile(r"(?:概率|probability|prob)", re.IGNORECASE), "probability"),
    (re.compile(r"(?:收益|回报|收益率|回报率|\breturns?\b)", re.IGNORECASE), "return"),
)

# Definitional prose ("夏普比率大于 1.0 通常被认为较好") states a convention,
# not a measurement this session produced (#1336: preserve explicitly labelled
# definitions). The bare 通常 alone is deliberately not enough — "通常实现
# 18.2% 年化" is a measured claim.
_DEFINITION_FRAME_RE = re.compile(
    r"(?:通常(?:认为|被?认为|说来|指|用于)|一般认为|定义为|是指|惯例|"
    r"conventionally|typically\s+(?:considered|regarded|seen)|"
    r"generally\s+(?:accepted|considered|regarded)|by\s+convention)",
    re.IGNORECASE,
)

# A categorical "all N-month windows were profitable" claim carries only an
# integer window length, which _MEASURE_NUMBER_RE deliberately ignores; it is a
# measured fact about the run and needs a window-producing analysis result.
_CATEGORICAL_WINDOW_RE = re.compile(
    r"(?:所有|全部|每个|任何|each|every|all)[\s\S]{0,40}?"
    r"(?:窗口|区间|windows?|periods?)[\s\S]{0,30}?"
    r"(?:正收益|均为正|都为正|盈利|上涨|positive|profitable)",
    re.IGNORECASE,
)
_DERIVATION_RE = re.compile(
    r"(?:\bderived\b|\bcalculated\b|\bformula\b|\bbased on\b|计算|推导|公式|基于)",
    re.IGNORECASE,
)
# "从 2026-08-03 的 100.0 涨到 2026-09-02 的 112.4" / "rose from 100.0 to
# 112.4": a return figure framed as growth between two endpoints is
# arithmetic on sourced inputs, not an invented backtest metric (#1338
# review). The frame alone never grounds anything — the values must also
# match an observed endpoint pair exactly (see _return_derived_from_observed).
_GROWTH_FRAME_RE = re.compile(
    r"从[^，。;；\n]{0,60}?(?:到|至)|\bfrom\b[^,;。\n]{0,80}?\bto\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?![A-Za-z0-9_])"
)
# A line-leading ordered-list marker ("1. **标题**") is prose structure, not a
# number. Without masking it, "1." is parsed as a float and rejected downstream
# as a numeric_claim_conflict against an observed OHLC range (#BUGS-1). The
# pattern only matches a digit run at the start of a line followed by "." or ")"
# and whitespace, so an in-text decimal like "1.5" (digit after the dot) is
# never affected.
_MD_LIST_ITEM_RE = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
# Unitless identity constants in a symbolic rate formula are not quoted prices.
# Without this mask, ``1 - 单边成本率`` in a position-sizing formula is read as
# a one-yuan price merely because the same clause also mentions a close price.
# Keep the relaxation narrow: only 0/1 directly participating in arithmetic
# with a token explicitly labelled as a rate is removed.
_RATE_FORMULA_IDENTITY_RE = re.compile(
    r"\b[01](?=\s*[-+]\s*(?:[A-Za-z_][A-Za-z0-9_]*_?rate\b|[^\d\s()+*/=-]{0,12}(?:成本率|费率|税率|滑点率)))",
    re.IGNORECASE,
)
# re.ASCII keeps ``\b`` a *byte* word boundary. Without it, ``\w`` is
# Unicode-aware and CJK letters count as word characters, so a date that runs
# straight into Chinese text -- "(2026-07-14最低)" -- has no boundary after
# "14" and is left unmasked, contributing 2026/7/14 as candidate prices that
# reject a correct report (#1122).
_DATE_RE = re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", re.ASCII)
# A year-less "8/5" is how a trading day is written in running prose, and it
# contributed 8 and 5 as candidate prices (#983). The month and day ranges are
# bounded, and both sides are fenced off from a longer slash run, so the window
# enumeration "20/50/200-day" cannot be mistaken for a date. Reports also write
# the same day as "08-10(一)" or "08-10盘中"; that dash form is masked by
# ``_DASH_DATE_RE`` below, where a zero-padded month or a weekday/session
# marker is required so a quoted price range like "8-10 元" stays checkable.
_SHORT_DATE_RE = re.compile(
    r"(?<![\d/])(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])(?![\d/])"
)
# A report writes a trading day as "08-10(一)" or "08-10盘中", and the dash form
# leaked 8 and 10 as candidate prices exactly as "8/5" once did. The dash is
# NOT symmetric with the slash, though: it also separates a range, and "目标价
# 10-20 元" must stay checkable. So the two halves are split -- a zero-padded
# month (01-09) is a formatting intent no price range imitates, while 10/11/12
# have to carry a weekday or session marker to read as a date.
_DASH_DATE_RE = re.compile(
    r"(?<![\d/-])(?:"
    r"0[1-9]-(?:0[1-9]|[12]\d|3[01])"
    r"|1[0-2]-(?:0[1-9]|[12]\d|3[01])"
    r"(?=\s*(?:[(（]\s*(?:周|星期)?[一二三四五六日天]\s*[)）]"
    r"|盘中|盘后|盘前|收盘|开盘|最低|最高"
    r"|\s*(?:close|open|intraday|low|high)\b))"
    r")(?![\d/-])",
    re.IGNORECASE,
)
# A level stated as a RANGE has the same shape: the separator touches the
# second number, so masking "目标价 10" left "-20" behind and a negative price
# matches no OHLC window at all -- a guaranteed rejection of a correct draft.
# The tail is optional, so a single-value level is unaffected.
_RANGE_TAIL = r"(?:\s*[-–—~～至到]\s*[-+]?\d[\d,]*(?:\.\d+)?)?"

# A percentage range masks only its upper bound through the "%" tail check
# below, because the sign touches the second number: "1–2%" left 1 behind
# (#983). Mask the span as a whole.
_PERCENT_RANGE_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*[-–—~至]\s*\d[\d,]*(?:\.\d+)?\s*[%％]"
)
# A percentage-POINT delta is not a quoted price. "~3.6pp below Penumbra"
# describes a margin gap; left unmasked the ".6" is consumed as a decimal
# and the number reaches the OHLC comparator, which then rejects an
# otherwise correct fundamentals answer and demands `get_market_data` to
# substantiate a claim that has nothing to do with price.
# The trailing "%" spellings are already handled above; this covers the
# percentage-point spellings, which the percent masks never matched.
# The Chinese units take an optional measure word ("3.6 个百分点" is the
# ordinary spelling; bare "3.6 百分点" is the rare one) and are matched
# without a trailing \b: after a CJK character \b requires a non-word
# character to follow, so "下降 3.6 个百分点，主因…" would not match. The
# ASCII units keep \b, which is what stops "3.6ppm" being read as pp.
_PERCENTAGE_POINT_RE = re.compile(
    r"[-+~≈]?\s*\d[\d,]*(?:\.\d+)?\s*"
    r"(?:(?:pp|ppt|ppts|bps|bp)\b|个?(?:百分点|基点))",
    re.IGNORECASE,
)
# Localized calendar text carries digits that the ISO pattern above leaves
# behind: "8 月 3 日" otherwise contributes 8 and 3 as candidate prices.
_LOCALIZED_DATE_RE = re.compile(
    r"(?:(?:19|20)\d{2}\s*年\s*)?\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?|(?:19|20)\d{2}\s*年"
)
# An aggregate amount is not a quoted price. "100 股成本 820 CNY" states a
# position cost; comparing 820 against a per-share OHLC range is a category
# error. The tradeoff is that a per-share figure written only as "成本 8.20"
# goes unchecked — provenance still requires symbol, source, and currency.
_AGGREGATE_AMOUNT_RE = re.compile(
    r"(?:成本|总额|总价|总市值|市值|合计|金额|cost|total|notional|market value)"
    r"\s*(?:为|是|约)?\s*[:：]?\s*[-+]?\d[\d,]*(?:\.\d+)?",
    re.IGNORECASE,
)
# Quantities, horizons, lot sizes, and lookback windows are unit-bearing:
# "100 股", "1–4 周", "3 个月", "52-week", "20/50/200-day". None are prices.
# The hyphenated English compound needs its own branch: the range alternation
# consumes "-4" in "1-4 周" but stalls on "-week", which left 52 behind to be
# compared against an OHLC range (#1001). The slash enumeration shares a single
# trailing unit, so "20/50/200-day" has to be masked as one span or its first
# two window lengths survive. ASCII units carry a trailing word boundary so
# "120 more" is not read as a quantity; the CJK branch cannot, because 周 and
# 内 are both word characters and "1–4 周内" must still mask.
_QUANTITY_WITH_UNIT_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?"
    r"(?:\s*/\s*\d[\d,]*(?:\.\d+)?)*"
    r"(?:\s*[-–—~至]\s*\d[\d,]*(?:\.\d+)?)?"
    r"\s*[-–—]?\s*"
    r"(?:"
    r"(?:股|手|张|份|口|笔|倍|个月|周|天|日|年|次|个交易日|项|行)"
    r"|(?:shares?|contracts?|lots?|units?|sessions?|bars?|periods?|"
    r"wks?|weeks?|months?|days?|years?|yrs?)\b"
    r")",
    re.IGNORECASE,
)
# A conviction reading is on a labelled scale, not a price scale: the 6 in
# "CONFIDENCE: 6" is bounded by the label that introduces it. Only the value
# bound to the label is masked, so a genuine quote elsewhere in the same
# clause is still checked. The optional denominator covers "6/10" (#1001).
_LABELLED_SCORE_RE = re.compile(
    r"(?:confidence|conviction|score|rating|probability|odds|weighting|"
    r"置信度|信心|评分|得分|概率|胜率)"
    r"\s*(?:is|of|=|为|是)?\s*[:：]?\s*"
    r"[-+]?\d[\d,]*(?:\.\d+)?(?:\s*/\s*\d[\d,]*(?:\.\d+)?)?",
    re.IGNORECASE,
)
# A named indicator reads on its own scale — "RSI of 46.7" is bounded at 100,
# not quoted in the instrument's currency. The name must be adjacent to the
# value, so a bare number elsewhere in the clause stays checked. Only
# unambiguous indicator names are listed: generic words such as "momentum" or
# "volatility" sit too close to price prose to mask safely.
_INDICATOR_VALUE_RE = re.compile(
    r"\b(?:rsi|macd|atr|adx|cci|obv|kdj|boll|dif|dea|vix|iv|"
    r"sharpe|sortino|beta)\b"
    r"(?:\s*\([^)]{0,20}\))?"
    r"\s*(?:is|at|of|reads?|=|为|是)?\s*[:：]?\s*"
    r"[-+]?\d[\d,]*(?:\.\d+)?",
    re.IGNORECASE,
)
# A currency token may sit between a level marker or comparison operator and
# the number: "收盘 <$2.86", "目标位 C$6.80", "trigger at $119.68". Without
# it, the number survives masking and is compared against observed OHLC as a
# price claim even though it is a prospective level, not an observed quote.
_CURRENCY_TOKEN = r"(?:\$|US\$|C\$|HK\$|CAD|USD|CNY|HKD|¥|￥)?"

# An order line is an instruction, not an observation. "100 @ $3.50" states
# where a limit sits and "100" is a share count that was never a price at all,
# yet both went to the OHLC check and rejected a weekly update whose quotes
# were correct. This is the same category as the target/stop levels below -- a
# level the report proposes, not one the data source reported.
_ORDER_LEVEL_RE = re.compile(
    r"(?:"
    # (a) "<qty> [股|shares] @ <price>" -- the whole clause, quantity included
    r"\d[\d,]*(?:\.\d+)?\s*(?:股|shares?)?\s*@\s*"
    + _CURRENCY_TOKEN + r"\s*[-+]?\d[\d,]*(?:\.\d+)?"
    r"|"
    # (b) an order label, optionally carrying its own "<qty> @", then the level.
    # There is deliberately no bare "@ <price>" branch: dates are masked before
    # this runs, so "收盘 2026-08-10 @ 8.20" would arrive here as "@ 8.20" and a
    # genuinely observed close would stop being checked. 买入价 / 卖出价 are
    # absent for the same reason -- in running prose they name a price the
    # report says it observed, not an instruction it proposes.
    r"(?:挂单|限价单|限价|委托价?|订单"
    r"|limit\s+(?:order|price)|\bGTC\b|\bGTD\b|\bIOC\b|\bFOK\b)"
    r"\s*(?:为|是|at|=)?\s*[:：]?\s*"
    r"(?:\d[\d,]*(?:\.\d+)?\s*(?:股|shares?)?\s*@\s*)?"
    + _CURRENCY_TOKEN + r"\s*[-+]?\d[\d,]*(?:\.\d+)?"
    r")" + _RANGE_TAIL,
    re.IGNORECASE,
)
# A historical reference names a price the instrument once traded at — an
# all-time high, a 52-week extreme — and the answer is not claiming it as
# today's observed quote. "8/12 高 149.60 为 6/16 ATH 225.64 以来最高" was
# rejected because 225.64 (the June ATH) fell outside this session's observed
# OHLC range. The marker must be adjacent to the number, so a plain field
# reading such as "8/12 高 149.60" stays checked: its 高 carries no historical
# qualifier. "创历史新高" shares the 历史新高 marker and is masked with it; the
# relaxation follows the same trade-off as prospective levels — the historical
# extreme is a reference, not an assertion about the current bar.
_REFERENCE_LEVEL_RE = re.compile(
    r"(?:"
    r"\bATH\b|all[- ]?time\s+(?:high|low)|"
    r"52\s*[- ]?W(?:EEK)?\s*(?:high|low)|52\s*[- ]?W(?:EEK)?\s*高(?:点|位)?|"
    r"52\s*周(?:高|低)(?:点|位)?|"
    r"历史(?:最高|最低|新高|新低|高|低)(?:点|位|价)?|"
    r"上市以来(?:最高|最低)(?:点|位|价)?"
    r")"
    r"\s*(?:of|为|是|约|at)?\s*[:：]?\s*\(?"
    r"\s*" + _CURRENCY_TOKEN + r"\s*[-+]?\d[\d,]*(?:\.\d+)?" + _RANGE_TAIL,
    re.IGNORECASE,
)
# A date-anchored reference puts the historical extreme after the number:
# "7/10(150.57)以来最高" and "highest since 7/10 (150.57)". The parenthesized
# value is the earlier high/low, not a current quote, and was rejected against
# the session's observed window (which does not reach back to July).
_SINCE_REFERENCE_RE = re.compile(
    r"[-+]?\d[\d,]*(?:\.\d+)?\s*\)?\s*以来(?:最高|最低|高|低)(?:点|位)?"
    # Dates are masked before this runs, so "since 7/10 (150.57)" has lost its
    # date digits by the time the connector is matched.
    r"|(?:highest|lowest)\s+since[^0-9\n]{0,16}"
    r"[-+]?\d[\d,]*(?:\.\d+)?",
    re.IGNORECASE,
)
# A validation report cites a plan file by line number — "~line 206",
# "第 206 行" — and the number is a document location, not a price. Before
# this mask, "**文档 ~line 206「…」不成立" contributed 206.0 as a candidate
# price claim and was rejected against the observed OHLC range.
_LINE_REFERENCE_RE = re.compile(
    r"(?:~\s*)?\blines?\b\s*[:#]?\s*\d{1,5}(?:\s*[-–—至~]\s*\d{1,5})?"
    r"|第\s*\d{1,5}(?:\s*[-–—至~]\s*\d{1,5})?\s*行"
    r"|行\s*[:：]?\s*\d{1,5}(?:\s*[-–—至~]\s*\d{1,5})?",
    re.IGNORECASE,
)
# A numbered markdown heading ("### 6. 关键价位") names a section index, not
# a price. The ordered-list mask only covers line-leading "1." and stops at
# the "### " prefix, so the section number was extracted as a claim.
_NUMBERED_HEADING_RE = re.compile(r"(?m)^\s*#{1,6}\s*\d+(?:[.、．])?\s*")
# A ratio ("6:1 折算", "10:1") names a conversion basis, not a quote price.
_RATIO_RE = re.compile(r"\d+(?:\.\d+)?\s*[:：]\s*\d+(?:\.\d+)?")
# A currency conversion cited inside a report ("USD/CAD≈1.36") is a basis, not
# an instrument quote. But `EUR/USD` IS this project's canonical forex symbol
# (``backtest/engines/forex.py``, and akshare_loader accepts the slash form), so
# masking every ``AAA/BBB <number>`` would stop checking real FX quotes on a
# first-class market — an invented rate would pass. The pair form therefore
# requires an approximation marker, which a conversion basis carries and a quote
# does not: "USD/CAD≈1.36" is masked, bare "USD/CAD 1.36" stays checked. The
# labelled 汇率 / "exchange rate" form is unambiguous and needs no marker.
_FX_RATE_RE = re.compile(
    r"[A-Z]{3}\s*/\s*[A-Z]{3}\s*(?:≈|~|约)\s*\d+(?:\.\d+)?"
    r"|(?:汇率|FX\s*rate|exchange\s+rate)\s*(?:≈|~|=|为|是)?\s*\d+(?:\.\d+)?",
    re.IGNORECASE,
)
# A trading plan quotes levels it does not claim to have observed. In the
# committee report attached to #983, "收盘 ≥6.45 且量 ≥35M手" is an entry
# trigger, "年线 4.63 成目标区" is a target zone, and neither asserts anything
# about what the instrument traded at. Compared against observed OHLC evidence
# they were reported first as numeric_claim_unavailable (before the run fetched
# prices) and then as numeric_claim_conflict (after it did) — the same false
# positive under two codes.
#
# This is a real relaxation, so every branch is span-local and anchored to the
# token that makes the number prospective, never to a word elsewhere in the
# clause: "现价 5.97，目标位 6.45" masks 6.45 and still checks 5.97. An
# assertion carries no such token and stays checked.
#
# Branch (d) accepts a conditional opener. A number inside "若收盘 5.36" is a
# hypothesis, and a hypothesis does not misrepresent observed data the way a
# bare quote does — but it is the widest branch here, so it requires the opener
# to PRECEDE the number with no digits in between, which keeps it from reaching
# back over an assertion that was already made.
_PROSPECTIVE_LEVEL_RE = re.compile(
    r"(?:"
    # (a) comparison operator immediately before the number
    r"(?:>=|<=|≥|≤|>|<|大于|小于|不低于|不高于|高于|低于)"
    r"\s*" + _CURRENCY_TOKEN + r"\s*[-+]?\d[\d,]*(?:\.\d+)?" + _RANGE_TAIL
    + r"|"
    # (b) a level marker introducing the number
    r"(?:目标位|目标区|目标价|均值目标(?:价)?|平均目标(?:价)?|止损位?|止盈位?|触发价|触发位|触发点|上看|下看|"
    r"支撑(?:阶梯|位|线)?|阻力(?:位|线)?|压力位|压力线|support(?:\s+(?:level|line|zone))?|"
    r"resistance(?:\s+(?:level|line|zone))?|target\s+(?:price|level|zone)|trigger|stop[-\s]?loss|take[-\s]?profit)"
    r"\s*(?:为|是|至|到|on|at|of|=)?\s*[:：]?\s*"
    + _CURRENCY_TOKEN
    + r"\s*[-+]?\d[\d,]*(?:\.\d+)?" + _RANGE_TAIL
    + r"|"
    # (c) the number followed by a level marker
    r"" + _CURRENCY_TOKEN + r"[-+]?\d[\d,]*(?:\.\d+)?" + _RANGE_TAIL
    + r"\s*(?:一线|附近)?\s*(?:成为?|作为|是)?\s*"
    r"(?:目标区|目标位|止损位|止盈位)"
    r"|"
    # (d) a conditional opener before the number, digits fencing the reach
    r"(?:若|如果|一旦|倘若|假如|\bif\b|\bwhen\b|\bshould\b)[^0-9\n]{0,12}"
    r"[-+]?\d[\d,]*(?:\.\d+)?"
    r")",
    re.IGNORECASE,
)
# Full-width enumeration commas delimit prose clauses. Paired brackets (ASCII
# or full-width ()()[]) are deliberately not separators: an explicit
# derivation such as "(8.5 - 7.9) / 2" must stay in one segment for the
# formula check, and 公司名（代码）价格 must stay in one segment so the
# unsourced-symbol gate can see the symbol with its figure (#1260).
_CLAUSE_SEPARATOR_RE = re.compile(r"[,，;；。、\n]")


# The ASCII comma both separates clauses and groups thousands, and the clause
# split ran first: "收盘价 ¥1,309.22" became a clause ending in "¥1", whose 1 was
# compared against the observed 1300.01–1363.35 range and rejected as a
# conflict. That is every price above 999 written the ordinary way, and it is
# self-contradictory — ``_NUMBER_RE`` and the float conversion below it both
# already understand grouped numbers. Only a real group is removed: a comma
# needs a digit before it and exactly three digits after.
_THOUSANDS_SEPARATOR_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def _split_clauses(text: str) -> list[str]:
    """Split prose into clauses without breaking a grouped number apart.

    Args:
        text: One line of candidate answer text.

    Returns:
        The clause segments, with thousands separators removed so a grouped
        price survives as one number.
    """
    return _CLAUSE_SEPARATOR_RE.split(_THOUSANDS_SEPARATOR_RE.sub("", text))
_TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")

_TABLE_FIELD_ALIASES = {
    "open": "open",
    "opening": "open",
    "opening price": "open",
    "开盘": "open",
    "开盘价": "open",
    "high": "high",
    "highest": "high",
    "最高": "high",
    "最高价": "high",
    "low": "low",
    "lowest": "low",
    "最低": "low",
    "最低价": "low",
    "close": "close",
    "closing": "close",
    "closing price": "close",
    "收盘": "close",
    "收盘价": "close",
}
_DATE_HEADERS = {"date", "datetime", "trade date", "timestamp", "日期", "交易日", "时间"}

# A loader's id is ASCII, but the answer follows the user's language, so a
# Chinese report names the same provider in Chinese. Demanding the ASCII id
# verbatim rejected correct prose: an answer reading "数据来源：腾讯财经" was
# reported as ``data_source_not_surfaced`` against evidence sourced from
# ``tencent``, and no rewrite short of writing the English word could pass.
_SOURCE_ALIASES = {
    "akshare": ("akshare", "ak share"),
    "baostock": ("baostock",),
    "binance": ("binance", "币安"),
    "ccxt": ("ccxt",),
    "eastmoney": ("eastmoney", "东方财富", "东财"),
    "futu": ("futu", "富途"),
    "mootdx": ("mootdx", "通达信"),
    "okx": ("okx", "欧易"),
    "pykrx": ("pykrx", "krx"),
    "sina": ("sina", "新浪"),
    "stooq": ("stooq",),
    "tencent": ("tencent", "腾讯"),
    "tushare": ("tushare",),
    "yahoo": ("yahoo", "雅虎"),
    "yfinance": ("yfinance", "yahoo", "雅虎"),
}
# "元" is how a Chinese answer writes a CNY quote, but it is also the tail of
# 港元/美元/日元, so accepting it unguarded would let an answer about a Hong Kong
# listing satisfy a CNY requirement. It counts only when no other currency's
# character owns it.
_BARE_YUAN_RE = re.compile(r"(?<![港美日欧韩台新加澳])元")
_CURRENCY_ALIASES = {
    "USD": ("usd", "us$", "美元", "美金"),
    # ¥ is how a model actually writes a CNY quote. It is the yen sign too, but
    # ``_infer_currency`` maps no venue to JPY, so nothing in this system can
    # mean yen by it; adding a JPY venue means revisiting this entry.
    "CNY": ("cny", "cnh", "rmb", "人民币", "¥", "￥"),
    "HKD": ("hkd", "hk$", "港元", "港币"),
    "KRW": ("krw", "韩元", "韩圜"),
    "INR": ("inr", "印度卢比", "卢比"),
    "CAD": ("cad", "c$", "加元", "加拿大元"),
}
_SYMBOL_HEADERS = {"symbol", "ticker", "code", "标的", "代码", "证券代码"}


def _utc_now() -> str:
    """Return an audit-friendly UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Provider spellings that denote one instrument. Shanghai is quoted as ``.SH``
# by Eastmoney and ``.SS`` by Yahoo, A-share tools also accept an exchange
# prefix (``sh600519``), Hong Kong codes are zero-padded to five digits, and
# ccxt writes a crypto pair with a slash. Every one of these is a spelling, not
# an identity: ``_infer_venue`` and ``_infer_currency`` below already map ``.SS``
# and ``.SH`` to the same venue and the same currency. Treating them as
# different identities made ``search_symbol("600519")`` return two candidates
# for one listing, which no tie-break could resolve, so every Shanghai listing
# resolved ``ambiguous`` and no market tool could run for the rest of the run.
_EXCHANGE_PREFIXED_RE = re.compile(r"^(SH|SZ|BJ)(\d{6})$")


def _normalize_symbol(value: Any) -> str:
    """Normalize a symbol onto one canonical identity for exact comparison.

    Args:
        value: Any provider- or model-supplied symbol spelling.

    Returns:
        The canonical spelling — uppercased, with Shanghai's ``.SS`` alias
        folded onto ``.SH``, an exchange prefix rewritten as a suffix, a Hong
        Kong code zero-padded, and a crypto pair hyphenated. A joined crypto
        pair with no separator (``BTCUSDT``) is rewritten as the dashed form
        (``BTC-USDT``) so every downstream check sees one identity. Text that
        is not a symbol is returned uppercased and otherwise untouched.
    """
    # A fiat/fiat pair is one FX instrument regardless of spelling: ``GBP/USD``
    # and ``GBPUSD`` are both ``GBPUSD=X``. Checked BEFORE the slash is
    # rewritten ("GBP/USD" -> "GBP-USD", the crypto-pair spelling), which
    # disagreed with the resolver's ``GBPUSD=X`` answer — a contradictory
    # identity that outranked every later lock and blocked all further tools.
    raw = str(value or "").strip().upper()
    fx = canonical_fx_pair(raw)
    if fx is not None:
        return fx
    symbol = raw.replace("/", "-")
    if not symbol:
        return ""

    prefixed = _EXCHANGE_PREFIXED_RE.match(symbol)
    if prefixed:
        return f"{prefixed.group(2)}.{prefixed.group(1)}"
    base, dot, suffix = symbol.rpartition(".")
    if not dot:
        # No separator at all: rewrite a joined crypto pair (``BTCUSDT``)
        # as the dashed form so the dash/slash branch and the canonical
        # regex both match. The base must be all-alpha so a numeric prefix
        # cannot collide with another numeric-code branch downstream.
        joined = _JOINED_CRYPTO_RE.fullmatch(symbol)
        if joined and not _METAL_USD_PAIR_RE.fullmatch(symbol):
            for quote in _JOINED_CRYPTO_QUOTE_SUFFIXES:
                if symbol.endswith(quote) and len(symbol) > len(quote):
                    base_part = symbol[: -len(quote)]
                    if base_part.isalpha():
                        return f"{base_part}-{quote}"
        return symbol
    if suffix == "SS":
        suffix = "SH"
    if suffix == "HK" and base.isdigit():
        base = base.zfill(5)
    return f"{base}.{suffix}"


def _symbol_from_csv_filename(stem: str) -> str | None:
    """Map a run-dir CSV stem back to a canonical project symbol.

    The bash workaround writes filesystem-safe stems: ``BYN_V.csv`` -> ``BYN.V``,
    ``PDI_TO.csv`` -> ``PDI.TO``, ``GC_F.csv`` -> ``GC=F``, ``INTC_US.csv`` ->
    ``INTC.US``. A stem without a recognized suffix (e.g. a bare US name
    ``AAPL``) maps to None because the project convention requires an explicit
    venue suffix.

    Args:
        stem: CSV filename without the ``.csv`` extension.

    Returns:
        The canonical symbol, or ``None`` when the stem has no recognizable
        venue suffix.
    """
    upper = (stem or "").strip().upper()
    if not upper:
        return None
    for raw, canonical in _CSV_FILENAME_SUFFIX_MAP:
        if upper.endswith(raw) and len(upper) > len(raw):
            return upper[: -len(raw)] + canonical
    return None


def _query_key(value: Any) -> str:
    """Normalize resolver queries into stable state-machine keys."""
    return " ".join(str(value or "").casefold().split())


def _json_object(value: Any) -> dict[str, Any] | None:
    """Parse a JSON object from a tool result when possible."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_number(value: Any) -> bool:
    """Return whether a value is a finite JSON-style number, excluding bool."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _coerce_csv_number(value: Any) -> int | float | None:
    """Coerce a CSV cell to a finite number, or return None.

    CSV readers return every cell as text (``"0.375"``), so a bare
    ``_is_number`` check would discard them all. Values that do not parse as a
    finite number (blank cells, ``-``, ``N/A``) return ``None``.
    """
    if _is_number(value):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value.strip().replace(",", ""))
        except (TypeError, ValueError):
            return None
        if math.isfinite(parsed):
            return parsed
    return None


# "." is deliberately not a separator: a decimal price such as 8.5 would parse
# as month 8 day 5 and match a real trading day.
# A report writes the day as a table cell -- "08-10(一)", "08-10(周一)盘中",
# "08-10盘中" -- and the weekday or session suffix made the cell match no
# evidence row at all, so every price in that row came back
# "numeric_claim_unavailable" even though the run had fetched the bar.
_TRADING_DAY_SUFFIX = (
    r"(?:\s*[(（]\s*(?:周|星期)?[一二三四五六日天]\s*[)）])?"
    r"\s*(?:盘中|盘后|盘前|收盘|开盘|早盘|尾盘)?"
)
_YEARLESS_CLAIM_DATE_RE = re.compile(
    r"^(0?[1-9]|1[0-2])\s*[-/月]\s*(0?[1-9]|[12]\d|3[01])\s*[日号]?"
    + _TRADING_DAY_SUFFIX
    + r"$"
)
# Two-digit day alternatives are tried before a bare digit so an
# unanchored prefix match consumes the full day ("10" of "08-10(一)")
# instead of stopping at "1".
_ISO_CLAIM_DATE_PREFIX_RE = re.compile(
    r"^\s*((?:19|20)\d{2})\s*[-/]\s*(0?[1-9]|1[0-2])\s*[-/]\s*([12]\d|3[01]|0?[1-9])"
)
_YEARLESS_CLAIM_DATE_PREFIX_RE = re.compile(
    r"^\s*(0?[1-9]|1[0-2])\s*[-/月]\s*([12]\d|3[01]|0?[1-9])"
)
_ISO_TIMESTAMP_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")


def _claim_date_tuple(date_value: str) -> tuple[int, int] | None:
    """Extract the (month, day) named by a report-style date cell.

    Reports routinely annotate a trading day: the date column reads
    ``08-10(一)``, ``08-10(周一)盘中`` or ``08-10盘中`` rather than the bare
    ``08-10`` the strict full-cell matchers accept. Any leading month-day (or
    full ISO date) prefix is therefore accepted so such a claim still compares
    against the matching evidence row instead of being reported as
    unevidenced.

    Args:
        date_value: Date cell as written in the answer.

    Returns:
        The (month, day) tuple, or None when no date prefix is present.
    """
    claim = (date_value or "").strip()
    match = _YEARLESS_CLAIM_DATE_RE.match(claim)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    match = _ISO_CLAIM_DATE_PREFIX_RE.match(claim)
    if match:
        return (int(match.group(2)), int(match.group(3)))
    match = _YEARLESS_CLAIM_DATE_PREFIX_RE.match(claim)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return None


def _timestamp_matches_claim_date(timestamp: str, date_value: str) -> bool:
    """Match an evidence timestamp against the date cell of a claim.

    The comparison used to be ``timestamp.startswith(date_value)``, which can
    only succeed when the answer repeats the year. A table whose date column
    reads ``08-05`` — the ordinary way a report writes a trading day — matched
    nothing, so every cell in the row was reported as having no supporting
    evidence while that evidence sat right there (#983: 79 such rejections in
    one run, every value inside the observed range).

    A year-less date is matched on month and day, and a date cell may carry
    weekday or intraday annotations (``08-10(一)``, ``08-10盘中``) whose
    leading month-day is still recognized. Matching the wrong year is a
    smaller failure than matching nothing, but it is a real one, so the
    caller still compares the value against every record that matched rather
    than trusting the date.

    Args:
        timestamp: Evidence timestamp, normally ISO ``YYYY-MM-DD``.
        date_value: Date cell as written in the answer.

    Returns:
        True when the timestamp denotes the day the claim names.
    """
    stamp = (timestamp or "").strip()
    claim = (date_value or "").strip()
    if not stamp or not claim:
        return False
    if stamp.startswith(claim):
        return True
    claim_tuple = _claim_date_tuple(claim)
    iso = _ISO_TIMESTAMP_RE.match(stamp)
    if claim_tuple is None or not iso:
        return False
    return (int(iso.group(2)), int(iso.group(3))) == claim_tuple


def _price_field_for_path(path: str) -> str | None:
    """Map a generic evidence JSON path to a canonical price field.

    Args:
        path: Recorded evidence field, e.g. ``"data.quote[0].last_price"``.

    Returns:
        The matching member of ``_PRICE_FIELDS``, or ``None`` when the leaf is
        not an unambiguous quote field.
    """
    leaf = str(path or "").rsplit(".", 1)[-1]
    leaf = re.sub(r"\[\d+\]$", "", leaf).strip().casefold()
    return _GENERIC_PRICE_FIELD_ALIASES.get(leaf)


def _metric_kind_for_path(path: str) -> str | None:
    """Map an evidence JSON path to an analysis metric kind."""
    leaf = re.sub(r"\[\d+\]$", "", str(path or "").rsplit(".", 1)[-1])
    leaf = leaf.strip().casefold()
    kind = _ANALYSIS_KIND_ALIASES.get(leaf)
    if kind is not None:
        return kind
    # Compound leaves name the kind as a token ("reported_annualized_return",
    # "strategy_max_drawdown"). #1338 review: matching only the verbatim alias
    # table makes every other spelling silently ungroundable. Scan from the
    # right — English compounds put the head noun last, so "return_vol"
    # resolves to vol, never to return.
    tokens = [token for token in re.split(r"[_.]", leaf) if token]
    for size in (2, 1):
        for start in range(len(tokens) - size, -1, -1):
            kind = _ANALYSIS_KIND_ALIASES.get("_".join(tokens[start : start + size]))
            if kind is not None:
                return kind
    return _metric_kind_for_text(path)


def _metric_kind_for_text(text: str) -> str | None:
    """Return the analysis metric kind named in a claim or header."""
    for pattern, kind in _ANALYSIS_KIND_PATTERNS:
        if pattern.search(text):
            return kind
    return None


def _scan_symbols(text: str) -> set[str]:
    """Return the canonical symbols written anywhere in a blob of text."""
    return {
        _normalize_symbol(match.group(0))
        for match in _CANONICAL_SYMBOL_RE.finditer(text or "")
    }


def _infer_venue(symbol: str) -> str | None:
    """Infer a coarse venue from a project symbol."""
    upper = _normalize_symbol(symbol)
    suffixes = {
        ".US": "us",
        ".SH": "shanghai",
        ".SZ": "shenzhen",
        ".BJ": "beijing",
        ".HK": "hong_kong",
        ".KS": "kospi",
        ".KQ": "kosdaq",
        ".NS": "nse",
        ".BO": "bse",
        ".FX": "forex",
        ".TO": "toronto",
        ".V": "tsx_venture",
    }
    for suffix, venue in suffixes.items():
        if upper.endswith(suffix):
            return venue
    if "-" in upper or "/" in upper:
        return "crypto_or_fx"
    if upper.endswith("=F"):
        return "futures"
    return None


def _infer_currency(symbol: str) -> str | None:
    """Infer quote currency without performing an implicit conversion."""
    upper = _normalize_symbol(symbol)
    suffixes = {
        ".US": "USD",
        ".SH": "CNY",
        ".SZ": "CNY",
        ".BJ": "CNY",
        ".HK": "HKD",
        ".KS": "KRW",
        ".KQ": "KRW",
        ".NS": "INR",
        ".BO": "INR",
        ".TO": "CAD",
        ".V": "CAD",
    }
    for suffix, currency in suffixes.items():
        if upper.endswith(suffix):
            return currency
    for separator in ("-", "/"):
        if separator in upper:
            quote = upper.rsplit(separator, 1)[-1]
            if 3 <= len(quote) <= 5:
                return quote
    if upper.endswith("=X"):
        pair = upper[:-2]
        if len(pair) == 6:
            return pair[3:6]
    return None


def _infer_instrument_type(symbol: str, candidate_type: Any = None) -> str:
    """Normalize provider types into the identity contract."""
    raw = str(candidate_type or "").strip().casefold()
    if "fund" in raw or "etf" in raw or "trust" in raw:
        return "fund"
    if "crypto" in raw:
        return "crypto"
    if "future" in raw:
        return "future"
    if "option" in raw:
        return "option"
    if "forex" in raw or raw == "currency":
        return "forex"
    if "index" in raw:
        return "index"
    upper = _normalize_symbol(symbol)
    if upper.endswith("=F"):
        return "future"
    if upper.endswith(".FX"):
        return "forex"
    if "-" in upper or "/" in upper:
        return "crypto"
    if upper.startswith("^"):
        return "index"
    return "listed_security"


@dataclass(frozen=True)
class IdentityRecord:
    """One versioned entity-to-instrument resolution result."""

    query: str
    status: str
    symbol: str | None = None
    venue: str | None = None
    instrument_type: str | None = None
    currency: str | None = None
    source_tool_call_id: str | None = None
    source: list[str] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    resolution_constraints: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1
    updated_at: str = field(default_factory=_utc_now)


@dataclass(frozen=True)
class EvidenceRecord:
    """One observed, unavailable, or derived numeric evidence item."""

    call_id: str
    tool: str
    symbol: str | None
    source: str
    timestamp: str | None
    field: str
    value: int | float | None
    status: str
    currency: str | None = None
    venue: str | None = None
    currency_conversion: str | None = None


@dataclass(frozen=True)
class ToolAuthorization:
    """Deterministic decision made before a tool starts."""

    allowed: bool
    error_code: str | None = None
    message: str | None = None
    symbols: tuple[str, ...] = ()

    def error_payload(self, tool_name: str, identity: Mapping[str, Any]) -> str:
        """Render a blocked tool call as a normal structured error result."""
        return json.dumps(
            {
                "status": "error",
                "error_code": self.error_code or "identity_gate_blocked",
                "tool": tool_name,
                "message": self.message or "Tool call blocked by identity gate",
                "symbols": list(self.symbols),
                "identity": dict(identity),
                "required_action": (
                    "Call search_symbol in a separate assistant tool turn, wait for "
                    "its result, then reuse the exact locked symbol and venue. If the "
                    "resolver answers with a shortlist rather than one instrument, "
                    "show the candidates and ask the user which one to use — narrowing "
                    "the query again will not turn a genuine dual listing into one."
                ),
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class ValidationResult:
    """Final-answer grounding decision."""

    valid: bool
    issues: list[dict[str, Any]] = field(default_factory=list)


class GroundingLedger:
    """Run-scoped identity state machine and evidence ledger."""

    def __init__(
        self,
        *,
        run_dir: Path,
        user_message: str,
        history: Sequence[Mapping[str, Any]] | None = None,
        contextual_identity_constraints: bool = True,
    ) -> None:
        """Create a ledger and seed only authoritative prior identities.

        Args:
            run_dir: Active run directory.
            user_message: Current user request.
            history: Optional prior message history. It remains available to
                the model. Only explicit constraints whose clause names the
                current resolver subject may carry forward; stale global
                instructions cannot authorize a new subject.
            contextual_identity_constraints: Whether explicit market words in
                the original conversation may narrow resolver candidates.
        """
        self.run_dir = Path(run_dir)
        self.user_message = user_message
        self.resolution_context = ResolutionContext.from_messages(
            user_message,
            history,
            enabled=contextual_identity_constraints,
        )
        self._identities: dict[str, IdentityRecord] = {}
        self._evidence: list[EvidenceRecord] = []
        self._tool_failures: list[dict[str, Any]] = []
        self._analysis_completed: list[dict[str, Any]] = []
        self._analysis_metrics: list[dict[str, Any]] = []
        self._validations: list[dict[str, Any]] = []
        self._recovery_rounds = 0
        self._symbol_resolution_attempts = 0
        self._price_evidence_attempts = 0
        self._ingested_csvs: set[str] = set()
        self._identity_required = bool(_ACTIONABLE_MARKET_RE.search(user_message))
        self._buffer_output = self._identity_required
        # Every instrument this run is entitled to write about: the ones the
        # user named, plus the ones a succeeding tool call passed in or returned.
        self._session_symbols: set[str] = _scan_symbols(user_message)
        # Bare tickers a succeeding call passed in, e.g. "AAPL" for the nine
        # tools whose contract is a bare US ticker. "AAPL.US" in the answer then
        # names an instrument the run really handled.
        self._session_symbol_roots: set[str] = set()

        self._seed_symbols(user_message, source="user_message")
        self.persist()

    @property
    def authorized_symbols(self) -> set[str]:
        """Return exact symbols locked before the next tool batch."""
        return {
            record.symbol
            for record in self._identities.values()
            if record.status == "locked" and record.symbol
        }

    @property
    def identity_status(self) -> str:
        """Return the aggregate first-class identity state.

        ``conflicting`` is the only state that outranks a successful lock: two
        sources contradicting each other about one query is a fact about the
        data, not a gap in it. Every other blocking state means "not known
        yet", and a side query that failed, went unanswered, or returned a
        shortlist must not retract an identity the run did lock — one flaky
        resolver call otherwise poisons every remaining answer in the session,
        with no path back. Per-symbol safety does not depend on this aggregate:
        a consumer still has to match a locked symbol in
        :meth:`_match_authorized_symbol` before it may run.
        """
        records = list(self._identities.values())
        if not records:
            return "unresolved" if self._identity_required else "not_required"
        statuses = {record.status for record in records}
        if "conflicting" in statuses:
            return "conflicting"
        if "locked" in statuses:
            return "locked"
        for blocking in ("ambiguous", "invalidated", "unresolved"):
            if blocking in statuses:
                return blocking
        if "not_found" in statuses:
            return "not_found"
        return "unresolved"

    @property
    def should_buffer_output(self) -> bool:
        """Return whether unverified model prose must be hidden from live sinks."""
        return self._buffer_output or bool(self._evidence)

    @property
    def validation_count(self) -> int:
        """Return the number of final drafts checked so far."""
        return len(self._validations)

    def identity_summary(self) -> dict[str, Any]:
        """Return compact identity state for traces and tool errors."""
        return {
            "status": self.identity_status,
            "authorized_symbols": sorted(self.authorized_symbols),
            "records": [asdict(record) for record in self._identities.values()],
            "recovery": self.recovery_summary(),
        }

    def recovery_summary(self) -> dict[str, Any]:
        """Return bounded-recovery budget state for traces and the artifact."""
        return {
            "rounds": self._recovery_rounds,
            "max_rounds": MAX_GROUNDING_RECOVERY_ROUNDS,
            "symbol_resolution_attempts": self._symbol_resolution_attempts,
            "max_symbol_resolution_attempts": MAX_SYMBOL_RESOLUTION_ATTEMPTS,
            "price_evidence_attempts": self._price_evidence_attempts,
            "max_price_evidence_attempts": MAX_PRICE_EVIDENCE_ATTEMPTS,
        }

    def authorize_tool_call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        batch_authorized_symbols: Iterable[str],
        call_id: str,
        batch_identity_status: str | None = None,
    ) -> ToolAuthorization:
        """Authorize against identity state frozen before the whole LLM batch.

        Args:
            tool_name: Requested tool.
            arguments: Model-supplied arguments.
            batch_authorized_symbols: Snapshot taken before processing any call
                from this assistant response.
            call_id: Provider tool-call identity.
            batch_identity_status: Aggregate identity status from the same
                pre-batch snapshot. Defaults to the current state for direct
                callers outside the Agent loop.

        Returns:
            An allow/block decision. Resolver calls are allowed but their result
            cannot affect another call in this same batch.
        """
        if tool_name == _RESOLVER_TOOL:
            self._identity_required = True
            self._buffer_output = True
            self._begin_resolution(str(arguments.get("query") or ""), call_id)
            return ToolAuthorization(allowed=True)

        if self._is_private_company_skill(tool_name, arguments):
            return self._authorize_private_company_skill()

        if tool_name == "load_skill" and self._identity_required:
            frozen_status = batch_identity_status or self.identity_status
            if frozen_status in _RESOLUTION_INCOMPLETE_STATUSES:
                return ToolAuthorization(
                    allowed=False,
                    error_code="identity_required",
                    message=(
                        "Market-sensitive workflow selection is blocked while instrument "
                        "resolution is in flight or contradicted; a resolver result from "
                        "this same batch cannot be consumed."
                    ),
                )
            return ToolAuthorization(allowed=True)

        symbols = tuple(self._extract_symbol_arguments(arguments))
        if not symbols:
            return ToolAuthorization(allowed=True)

        self._identity_required = True
        self._buffer_output = True
        authorized = {_normalize_symbol(item) for item in batch_authorized_symbols}
        frozen_status = batch_identity_status or self.identity_status
        if frozen_status != "locked" or not authorized:
            return ToolAuthorization(
                allowed=False,
                error_code=(
                    "identity_conflict"
                    if frozen_status in {"ambiguous", "conflicting", "invalidated"}
                    else "identity_required"
                ),
                message=(
                    "A canonical, non-conflicting identity was not locked before this "
                    "assistant tool-call batch started. A resolver result from this same "
                    "batch cannot be consumed."
                ),
                symbols=symbols,
            )

        mismatched = tuple(
            symbol
            for symbol in symbols
            if self._match_authorized_symbol(symbol, authorized) is None
        )
        if mismatched:
            message = (
                "Consumer symbol/venue differs from the locked resolver identity; "
                "silent suffix or exchange rewrites are forbidden."
            )
            hints = [
                hint
                for symbol in mismatched
                for hint in self._venue_mismatch_hints(symbol, authorized)
            ]
            if hints:
                message += " " + " ".join(hints)
            return ToolAuthorization(
                allowed=False,
                error_code="identity_mismatch",
                message=message,
                symbols=mismatched,
            )
        return ToolAuthorization(allowed=True, symbols=symbols)

    @staticmethod
    def _venue_mismatch_hints(
        requested_symbol: str,
        authorized_symbols: Iterable[str],
    ) -> list[str]:
        """Turn a same-issuer venue mismatch into an actionable resolver hint.

        ``BLDP.US`` against a locked ``BLDP.TO`` is not a typo of one identity;
        it is a second listing of the same company that was never resolved.
        Naming the exact ``search_symbol`` query keeps the model from retrying
        the identical unauthorized call. A bare ticker that collides with
        several locked venues gets a "use the full suffix" hint instead.
        """
        requested = _normalize_symbol(requested_symbol)
        authorized = {_normalize_symbol(item) for item in authorized_symbols}
        if "." in requested:
            base = requested.rsplit(".", 1)[0]
            same_issuer = sorted(
                item
                for item in authorized
                if "." in item and item.rsplit(".", 1)[0] == base
            )
            if same_issuer:
                return [
                    f"[{requested_symbol} is a second venue of {', '.join(same_issuer)}; "
                    f"call search_symbol('{requested_symbol}') in a separate turn "
                    f"before querying it.]"
                ]
            return []
        matches = sorted(
            item
            for item in authorized
            if "." in item and item.rsplit(".", 1)[0] == requested
        )
        if len(matches) > 1:
            return [
                f"[{requested_symbol} matches multiple locked identities "
                f"({', '.join(matches)}); use the full venue-suffixed symbol.]"
            ]
        return []

    @staticmethod
    def _match_authorized_symbol(
        requested_symbol: str,
        authorized_symbols: Iterable[str],
    ) -> str | None:
        """Map a consumer argument to one unique locked canonical symbol.

        Both sides are canonicalized first, so a provider alias (``600519.SS``),
        an exchange prefix (``sh600519``), an unpadded Hong Kong code
        (``700.HK``) or a slashed pair (``BTC/USDT``) addresses the instrument
        it names rather than being read as a silent venue rewrite.

        A bare code carries no venue, so it is accepted only when exactly one
        locked identity has it as its base. That uniqueness — not a list of
        which tools are allowed to use one — is what makes a bare ticker safe.
        The list this replaced named nine tools while eleven documented
        argument spellings across the registry were bare or prefixed, so the
        tools' own schema examples were being rejected.

        Args:
            requested_symbol: Model-supplied symbol argument.
            authorized_symbols: Symbols locked before the tool batch.

        Returns:
            The unique canonical identity consumed by the argument, or ``None``.
        """
        requested = _normalize_symbol(requested_symbol)
        authorized = {_normalize_symbol(item) for item in authorized_symbols}
        if requested in authorized:
            return requested
        if "." in requested:
            return None
        matches = [
            symbol
            for symbol in authorized
            if "." in symbol and symbol.rsplit(".", 1)[0] == requested
        ]
        return matches[0] if len(matches) == 1 else None

    def ingest_tool_result(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        result: str,
        call_id: str,
        success: bool,
    ) -> None:
        """Consume the full untruncated tool result and persist its evidence.

        Args:
            tool_name: Executed tool name.
            arguments: Exact normalized tool arguments.
            result: Full raw result, before model-context truncation.
            call_id: Provider tool-call identity.
            success: Result-envelope success classification.
        """
        payload = _json_object(result)
        if not success:
            self._record_tool_failure(tool_name, call_id, result)
            if tool_name == _RESOLVER_TOOL:
                self._finish_failed_resolution(arguments, call_id)
            self.persist()
            return

        self._track_session_symbols(arguments, result)
        if tool_name in _ANALYSIS_TOOLS:
            self._ingest_analysis_result(tool_name, arguments, payload, call_id)
        if tool_name == _RESOLVER_TOOL:
            self._ingest_resolution(arguments, payload, call_id)
        elif tool_name == "get_market_data":
            self._ingest_market_data(arguments, payload, call_id)
        elif payload is not None:
            self._ingest_generic_numeric(tool_name, arguments, payload, call_id)
        self.persist()

    def _ingest_analysis_result(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        payload: dict[str, Any] | None,
        call_id: str,
    ) -> None:
        """Record metric numbers a completed analysis result actually produced.

        Success of the call envelope is not enough: ``backtest`` reports ok for
        any runner exit, and a deduplicated ("skipped") call carries no new
        result at all (#1336). Only results that yielded at least one
        recognisable metric figure count as completed analysis.
        """
        if payload is None or payload.get("skipped"):
            return
        if tool_name == "backtest":
            if str(payload.get("status") or "").casefold() != "ok" and payload.get(
                "exit_code"
            ) not in (0, "0"):
                return
            recorded = self._record_backtest_metrics(arguments, payload, call_id)
        elif tool_name == "factor_analysis":
            if str(payload.get("status") or "").casefold() != "ok":
                return
            recorded = self._record_leaf_metrics(payload, call_id, tool_name, "")
        elif tool_name == "run_shadow_backtest":
            if str(payload.get("status") or "").casefold() != "ok":
                return
            combined = payload.get("combined")
            if not isinstance(combined, dict):
                # A combined dict containing only {"error": ...} is no analysis.
                return
            recorded = self._record_leaf_metrics(combined, call_id, tool_name, "combined")
        elif tool_name == "quantlib_call":
            if payload.get("ok") is not True or str(
                arguments.get("action") or ""
            ).casefold() != "call":
                return
            function = str(arguments.get("function") or "")
            recorded = self._record_leaf_metrics(
                payload.get("result"), call_id, tool_name, function
            )
        else:
            return
        if recorded:
            self._analysis_completed.append(
                {"call_id": call_id, "tool": tool_name, "recorded_at": _utc_now()}
            )

    def _record_leaf_metrics(
        self,
        value: Any,
        call_id: str,
        tool_name: str,
        field_prefix: str,
    ) -> int:
        """Record nested numeric leaves whose key names a metric kind."""
        recorded = 0

        def visit(item: Any, path: str) -> None:
            nonlocal recorded
            if _is_number(item):
                kind = _metric_kind_for_path(path)
                if kind is None:
                    return
                self._analysis_metrics.append(
                    {
                        "metric": kind,
                        "value": float(item),
                        "tool": tool_name,
                        "call_id": call_id,
                        "field": path,
                    }
                )
                recorded += 1
                return
            if isinstance(item, dict):
                for key, child in item.items():
                    visit(child, f"{path}.{key}" if path else str(key))
            elif isinstance(item, list):
                for index, child in enumerate(item):
                    visit(child, f"{path}[{index}]")

        visit(value, field_prefix or "")
        return recorded

    def _record_backtest_metrics(
        self,
        arguments: Mapping[str, Any],
        payload: dict[str, Any],
        call_id: str,
    ) -> int:
        """Parse metric figures from a successful backtest's run-dir artifacts."""
        root = self.run_dir.resolve()
        candidates: list[Path] = []
        raw_dir = arguments.get("run_dir") or payload.get("run_dir")
        if raw_dir:
            candidate = Path(str(raw_dir))
            if not candidate.is_absolute():
                candidate = self.run_dir / candidate
            try:
                resolved = candidate.resolve()
                if resolved == root or resolved.is_relative_to(root):
                    candidates.append(resolved)
            except OSError:
                pass
        # The loop archives a detached backtest's artifacts into the active run
        # dir right after it succeeds, so that copy is the second candidate.
        candidates.append(root)
        artifacts = payload.get("artifacts")
        if isinstance(artifacts, dict):
            for path_value in artifacts.values():
                if not isinstance(path_value, str):
                    continue
                try:
                    resolved = Path(path_value).resolve()
                    if resolved.is_relative_to(root):
                        candidates.append(resolved)
                except OSError:
                    continue
        files: list[Path] = []
        seen_dirs: set[Path] = set()
        for candidate in candidates:
            if candidate.is_file():
                files.append(candidate)
                continue
            if candidate in seen_dirs:
                continue
            seen_dirs.add(candidate)
            for dir_path in (candidate, candidate / "artifacts"):
                for name in ("metrics.csv", "metrics.json"):
                    target = dir_path / name
                    if target.is_file():
                        files.append(target)
        recorded = 0
        seen_files: set[Path] = set()
        for file_path in files:
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            recorded += self._record_metrics_file(file_path, call_id)
        return recorded

    def _record_metrics_file(self, path: Path, call_id: str) -> int:
        """Record metric figures from one metrics.csv/metrics.json artifact."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return 0
        if path.suffix == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return 0
            if not isinstance(data, dict):
                return 0
            return self._record_leaf_metrics(data, call_id, "backtest", "")
        try:
            rows = list(csv.reader(text.splitlines()))
        except csv.Error:
            return 0
        if len(rows) < 2:
            return 0
        header = [cell.strip().casefold() for cell in rows[0]]
        recorded = 0
        for index, raw in enumerate(rows[1]):
            if index >= len(header):
                break
            kind = _ANALYSIS_KIND_ALIASES.get(header[index])
            value = _coerce_csv_number(raw)
            if kind is not None and value is not None:
                self._analysis_metrics.append(
                    {
                        "metric": kind,
                        "value": float(value),
                        "tool": "backtest",
                        "call_id": call_id,
                        "field": header[index],
                    }
                )
                recorded += 1
        return recorded

    def validate_final_answer(self, content: str) -> ValidationResult:
        """Validate identity assertions and numeric price claims.

        Args:
            content: Candidate assistant answer.

        Returns:
            A deterministic validation result. A record containing only the
            answer hash and structured issues is appended to the artifact.
        """
        self._ingest_run_dir_ohlc_csvs()
        issues: list[dict[str, Any]] = []
        issues.extend(self._validate_identity(content))
        issues.extend(self._validate_unsourced_symbols(content))
        issues.extend(self._validate_price_claims(content))
        issues.extend(self._validate_analysis_claims(content))
        result = ValidationResult(valid=not issues, issues=issues)
        self._validations.append(
            {
                "attempt": len(self._validations) + 1,
                "checked_at": _utc_now(),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "valid": result.valid,
                "issues": issues,
            }
        )
        self.persist()
        return result

    def correction_prompt(self, validation: ValidationResult) -> str:
        """Build bounded feedback for one rejected model draft."""
        lines = [
            "[GROUNDING GATE] The previous draft was rejected and was not released to the user.",
            "Correct every issue using the existing structured identity and tool evidence:",
        ]
        for issue in validation.issues[:12]:
            lines.append(f"- {issue.get('message', issue.get('code', 'grounding error'))}")
        # Name the exact values that must be REMOVED, not rephrased. The model
        # tends to restate a rejected figure in a new format; the gate then
        # rejects it again and the run burns iterations until the fallback.
        banned: list[str] = []
        for issue in validation.issues:
            code = issue.get("code")
            value = issue.get("value")
            if code in {"numeric_claim_conflict", "numeric_claim_unavailable", "unsourced_symbol_figures", "analysis_claim_unavailable"} and value is not None:
                symbol = issue.get("symbol") or ""
                label = f"{value:g}" if isinstance(value, (int, float)) else str(value)
                banned.append(f"{label} ({symbol})" if symbol else label)
        if banned:
            deduped = list(dict.fromkeys(banned))
            lines.append(
                "REMOVE these rejected value(s) entirely - do NOT restate, rephrase, "
                "or recompute them in any other format: " + ", ".join(deduped) + "."
            )
            repeated: list[str] = []
            for prior in self._validations:
                for prior_issue in prior.get("issues", []):
                    prior_value = prior_issue.get("value")
                    if isinstance(prior_value, (int, float)):
                        mark = f"{prior_value:g}"
                        if any(entry.startswith(mark) for entry in deduped):
                            repeated.append(mark)
            if repeated:
                lines.append(
                    "These value(s) have now been rejected repeatedly across drafts: "
                    + ", ".join(dict.fromkeys(repeated))
                    + ". Repeating them in any form keeps failing; drop them, or show "
                    "the full derivation from the observed inputs."
                )
        lines.extend(
            [
                "If a value is a derived or prospective level (stop, target, entry, etc.), "
                "you must EITHER show the full derivation with the observed inputs and the "
                "formula, OR omit it from the draft.",
                "Reuse the exact locked symbol and venue.",
                "Do not attach figures to a symbol no tool call in this session handled; "
                "report it as not retrieved instead.",
            ]
        )
        recovery = self.recovery_action(validation)
        if recovery == _RESOLVER_TOOL:
            lines.extend(
                [
                    "Instrument identity is unresolved. Call `search_symbol` for the "
                    "candidate name in a separate tool-call turn, lock the exact canonical "
                    "symbol and venue it returns, then call `get_market_data` before finalizing.",
                    "Do NOT ask the user to confirm or continue while this read-only recovery "
                    "remains available.",
                ]
            )
        elif recovery == "get_market_data":
            lines.extend(
                [
                    "Identity is locked but price evidence is missing. Call `get_market_data` "
                    "for the locked canonical symbol and venue in a separate tool-call turn, "
                    "then regenerate and re-validate the final answer.",
                    "Do NOT ask the user to confirm or continue while this read-only recovery "
                    "remains available.",
                ]
            )
        else:
            lines.append(
                "If evidence is genuinely unavailable or conflicting and recovery is "
                "exhausted, say so and ask for clarification; do not guess."
            )
        return "\n".join(lines)

    def recovery_action(self, validation: ValidationResult) -> str | None:
        """Decide the next safe read-only recovery step for a rejected draft.

        Returns ``search_symbol`` when instrument identity is unresolved and
        resolution attempts remain; ``get_market_data`` when identity is locked
        but a price claim has no observed evidence and fetch attempts remain;
        otherwise ``None`` (genuinely ambiguous, conflicting, or exhausted —
        the loop must then ask the user or fail closed).

        This is the deterministic half of #1081: recoverable missing evidence is
        often obtainable through read-only tools, so a rejected draft should
        drive the original task forward instead of stopping.
        """
        if self._recovery_rounds >= MAX_GROUNDING_RECOVERY_ROUNDS:
            return None
        if self._identity_required and self.identity_status == "unresolved":
            if self._symbol_resolution_attempts < MAX_SYMBOL_RESOLUTION_ATTEMPTS:
                return _RESOLVER_TOOL
            return None
        if self.identity_status == "locked" and any(
            issue.get("code") in {"numeric_claim_unavailable", "unsourced_symbol_figures"}
            for issue in validation.issues
        ):
            if self._price_evidence_attempts < MAX_PRICE_EVIDENCE_ATTEMPTS:
                return "get_market_data"
        return None

    def record_recovery(self, action: str) -> None:
        """Account one bounded recovery attempt against its budget."""
        self._recovery_rounds += 1
        if action == _RESOLVER_TOOL:
            self._symbol_resolution_attempts += 1
        elif action == "get_market_data":
            self._price_evidence_attempts += 1

    def recovery_prompt(self, action: str, validation: ValidationResult) -> str:
        """Build an executable next-step message for one bounded recovery turn."""
        if action == _RESOLVER_TOOL:
            return (
                "[GROUNDING RECOVERY] Instrument identity is not yet locked and is "
                "recoverable with read-only tools. Call `search_symbol` for the candidate "
                "name in a separate assistant tool-call turn, lock and reuse the exact "
                "canonical symbol and venue it returns, then call `get_market_data`. "
                "Do NOT ask the user to confirm or continue while this read-only recovery "
                "remains available, and do NOT finalize yet."
            )
        if action == "get_market_data":
            return (
                "[GROUNDING RECOVERY] Identity is locked but price evidence is missing. "
                "Call `get_market_data` for the locked canonical symbol and venue in a "
                "separate tool-call turn and use its existing bounded provider fallback, "
                "then regenerate and re-validate the final answer. Do NOT ask the user to "
                "confirm or continue while this read-only recovery remains available, and "
                "do NOT finalize yet."
            )
        return self.correction_prompt(validation)

    def safe_fallback(self) -> str:
        """Return a deterministic fail-closed answer after repeated rejection."""
        is_zh = bool(re.search(r"[\u3400-\u9fff]", self.user_message))
        price_records = self._price_records()
        if price_records:
            by_symbol: dict[str, list[EvidenceRecord]] = {}
            for record in price_records:
                by_symbol.setdefault(record.symbol or "unknown", []).append(record)
            facts = []
            for symbol, records in sorted(by_symbol.items()):
                values = [float(record.value) for record in records if record.value is not None]
                currency = next((record.currency for record in records if record.currency), None)
                sources = sorted({record.source for record in records if record.source})
                source_label = "/".join(sources) if sources else "unknown"
                unit = f" {currency}" if currency else ""
                facts.append(
                    f"{symbol}: {min(values):g}–{max(values):g}{unit} "
                    f"(source: {source_label}; currency conversion: none)"
                )
            joined = "；".join(facts) if is_zh else "; ".join(facts)
            if is_zh:
                return (
                    "为避免输出与工具证据冲突的价格，我已拒绝上一版答案。"
                    f"当前可验证的已观测 OHLC 范围是：{joined}。"
                    "在重新核对标的或明确展示推导公式前，我不会生成买入价。"
                )
            return (
                "I rejected the previous draft because its prices conflicted with tool evidence. "
                f"The verified observed OHLC range is: {joined}. "
                "I will not invent an entry price without a visible derivation or refreshed evidence."
            )
        # No observed price evidence: distinguish "identity unresolved" from
        # "the draft cited prices this session never observed". Reporting the
        # identity message for the latter is misleading (the run may not even
        # have touched the market tools).
        issue_codes = {
            code
            for validation in self._validations
            for code in (issue.get("code") for issue in validation.get("issues", []))
        }
        if issue_codes & {
            "numeric_claim_unavailable", "numeric_claim_conflict", "unsourced_symbol_figures"
        }:
            if is_zh:
                return (
                    "我的回答被安全门槛拒绝:草稿引用了本会话未通过工具获取的价格数字,无法核验。"
                    "请重新发起任务,让模型先调用行情工具获取数据,或要求它去掉这些价格引用后重试。"
                )
            return (
                "My previous answer was rejected by the verification gate: it cited price "
                "figures that this session never obtained through a tool, so they could not "
                "be verified. Re-run the task and let the agent fetch the market data first, "
                "or ask it to answer without the unverified prices."
            )
        if is_zh:
            return (
                "当前无法安全确认标的身份或价格证据，因此没有生成交易结论。"
                "请确认候选证券代码和交易所后再继续。"
            )
        return (
            "I could not safely lock the instrument identity or price evidence, so I did not "
            "produce a trading conclusion. Please confirm the candidate symbol and venue."
        )

    def persist(self) -> None:
        """Atomically persist the current structured ledger."""
        artifact_dir = self.run_dir / "artifacts"
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = artifact_dir / GROUNDING_ARTIFACT
            temp = path.with_suffix(path.suffix + ".tmp")
            payload = {
                "schema_version": 1,
                "updated_at": _utc_now(),
                "identity": self.identity_summary(),
                "session_symbols": sorted(self._session_symbols),
                "session_symbol_roots": sorted(self._session_symbol_roots),
                "evidence": [asdict(record) for record in self._evidence],
                "tool_failures": list(self._tool_failures),
                "analysis_completed": list(self._analysis_completed),
                "analysis_evidence": list(self._analysis_metrics),
                "validations": list(self._validations),
            }
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temp.replace(path)
        except OSError:
            # Grounding decisions remain in memory; a read-only/broken artifact
            # directory must not crash the agent's error path.
            return

    def _seed_symbols(self, text: str, *, source: str) -> None:
        """Lock exact symbols explicitly supplied by a user."""
        for match in _CANONICAL_SYMBOL_RE.finditer(text or ""):
            symbol = _normalize_symbol(match.group(0))
            key = f"explicit:{symbol}"
            existing = self._identities.get(key)
            version = existing.version + 1 if existing else 1
            self._identities[key] = IdentityRecord(
                query=symbol,
                status="locked",
                symbol=symbol,
                venue=_infer_venue(symbol),
                instrument_type=_infer_instrument_type(symbol),
                currency=_infer_currency(symbol),
                source_tool_call_id=source,
                source=[source],
                version=version,
            )
            self._identity_required = True
            self._buffer_output = True

    def _begin_resolution(self, query: str, call_id: str) -> None:
        """Enter unresolved state before the resolver executes."""
        key = _query_key(query) or f"call:{call_id}"
        existing = self._identities.get(key)
        self._identities[key] = IdentityRecord(
            query=query,
            status="unresolved",
            source_tool_call_id=call_id,
            version=(existing.version + 1) if existing else 1,
        )
        self.persist()

    def _finish_failed_resolution(
        self,
        arguments: Mapping[str, Any],
        call_id: str,
    ) -> None:
        """Mark transport/business failure as invalidated, never not-found."""
        query = str(arguments.get("query") or "")
        key = _query_key(query) or f"call:{call_id}"
        existing = self._identities.get(key)
        self._identities[key] = IdentityRecord(
            query=query,
            status="invalidated",
            source_tool_call_id=call_id,
            version=(existing.version + 1) if existing else 1,
        )

    def _ingest_resolution(
        self,
        arguments: Mapping[str, Any],
        payload: dict[str, Any] | None,
        call_id: str,
    ) -> None:
        """Advance unresolved identity from a structured resolver result."""
        data = payload.get("data") if isinstance(payload, dict) else None
        data = data if isinstance(data, dict) else {}
        query = str(data.get("query") or arguments.get("query") or "")
        key = _query_key(query) or f"call:{call_id}"
        existing = self._identities.get(key)
        version = (existing.version + 1) if existing else 1

        if not isinstance(payload, dict) or payload.get("ok") is False:
            self._identities[key] = IdentityRecord(
                query=query,
                status="invalidated",
                source_tool_call_id=call_id,
                version=version,
            )
            return

        raw_candidates = data.get("candidates")
        candidates = [dict(item) for item in raw_candidates if isinstance(item, dict)] if isinstance(raw_candidates, list) else []
        resolver_candidates = candidates
        relevant_constraints = self.resolution_context.constraints_for(query)
        constraint_audit = [item.audit_record() for item in relevant_constraints]
        sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
        if not candidates:
            # "This entity does not exist" may only be concluded when every
            # source that could answer did answer. Counting two clean sources
            # instead was unreachable for a Chinese query — Yahoo cannot serve
            # one at all — so an entity that simply is not listed came back as
            # ``invalidated``, which blocks the run rather than answering it.
            # A source that skipped an unsupported query shape is not an outage.
            clean_sources = [
                str(name)
                for name, value in sources.items()
                if str(value).casefold() == "ok"
            ]
            failed_sources = [
                str(name)
                for name, value in sources.items()
                if str(value).casefold() != "ok"
                and not str(value).casefold().startswith("skipped")
            ]
            self._identities[key] = IdentityRecord(
                query=query,
                status="not_found" if clean_sources and not failed_sources else "invalidated",
                source_tool_call_id=call_id,
                source=clean_sources,
                candidates=[],
                resolution_constraints=constraint_audit,
                version=version,
            )
            return

        market_values = {
            item.value
            for item in relevant_constraints
            if item.dimension == "market" and item.explicit
        }
        if market_values:
            constrained = [
                candidate
                for candidate in candidates
                if candidate_market(candidate) in market_values
            ]
            if constrained:
                candidates = constrained
            else:
                # A mismatch with an explicit constraint must stay fail closed.
                # The candidate list may be truncated, so this is ambiguity,
                # not proof that the requested listing does not exist.
                self._identities[key] = IdentityRecord(
                    query=query,
                    status="ambiguous",
                    source_tool_call_id=call_id,
                    candidates=resolver_candidates,
                    resolution_constraints=constraint_audit,
                    version=version,
                )
                return

        chosen = self._choose_candidate(query, candidates)
        if chosen is None:
            self._identities[key] = IdentityRecord(
                query=query,
                status="ambiguous",
                source_tool_call_id=call_id,
                candidates=resolver_candidates,
                resolution_constraints=constraint_audit,
                version=version,
            )
            return

        symbol = _normalize_symbol(chosen.get("symbol"))
        if not symbol:
            self._identities[key] = IdentityRecord(
                query=query,
                status="invalidated",
                source_tool_call_id=call_id,
                candidates=resolver_candidates,
                resolution_constraints=constraint_audit,
                version=version,
            )
            return

        # A query that already spells a canonical symbol is asserting one, so a
        # resolver answering with a different instrument contradicts it rather
        # than refining it. This generalizes the ``.SS``/``.SH`` alias check it
        # replaces: that one fired on one exchange's two spellings and stayed
        # silent on an actual cross-exchange swap, which is the case that
        # matters.
        asserted = _scan_symbols(query)
        if asserted and symbol not in asserted:
            conflicting = list(candidates)
            conflicting.extend({"symbol": item, "source": ["query"]} for item in sorted(asserted))
            self._identities[key] = IdentityRecord(
                query=query,
                status="conflicting",
                source_tool_call_id=call_id,
                candidates=conflicting,
                resolution_constraints=constraint_audit,
                version=version,
            )
            return

        if existing and existing.status == "locked" and existing.symbol != symbol:
            conflicting = list(candidates)
            conflicting.insert(0, {"symbol": existing.symbol, "source": existing.source})
            self._identities[key] = IdentityRecord(
                query=query,
                status="conflicting",
                source_tool_call_id=call_id,
                candidates=conflicting,
                resolution_constraints=constraint_audit,
                version=version,
            )
            return

        source_names = []
        for value in [chosen.get("source"), *(chosen.get("also_from") or [])]:
            name = str(value or "").strip()
            if name and name not in source_names:
                source_names.append(name)
        venue = str(chosen.get("exchange") or chosen.get("market") or "").strip() or _infer_venue(symbol)
        self._identities[key] = IdentityRecord(
            query=query,
            status="locked",
            symbol=symbol,
            venue=venue,
            instrument_type=_infer_instrument_type(symbol, chosen.get("type")),
            currency=_infer_currency(symbol),
            source_tool_call_id=call_id,
            source=source_names,
            candidates=resolver_candidates,
            resolution_constraints=constraint_audit,
            version=version,
        )
        self._supersede_shortlists(symbol)

    def _supersede_shortlists(self, symbol: str) -> None:
        """Retire ambiguous shortlists that this lock has just answered.

        A screening query resolves to many candidates by design. Once one of
        them is locked by a later, narrower resolution, the earlier shortlist is
        answered rather than unresolved — leaving it ``ambiguous`` blocks every
        final answer in the run for the rest of the session (#955).

        Args:
            symbol: Canonical symbol locked by the current resolution.
        """
        for key, record in self._identities.items():
            if record.status != "ambiguous":
                continue
            offered = {
                _normalize_symbol(candidate.get("symbol")) for candidate in record.candidates
            }
            if symbol in offered:
                self._identities[key] = replace(
                    record, status="superseded", updated_at=_utc_now()
                )

    @staticmethod
    def _choose_candidate(
        query: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Choose only a unique or strongly corroborated resolver candidate.

        Candidates are collapsed onto their canonical symbol first. Two rows
        that differ only by a provider's suffix convention describe one listing,
        and counting them as rival candidates is what left every Shanghai query
        with two "exact" matches and therefore no choice at all.
        """
        by_symbol: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            by_symbol.setdefault(_normalize_symbol(candidate.get("symbol")), candidate)
        candidates = list(by_symbol.values())
        if len(candidates) == 1:
            return candidates[0]
        normalized_query = re.sub(r"[^a-z0-9\u3400-\u9fff]", "", query.casefold())
        exact: list[dict[str, Any]] = []
        strong: list[dict[str, Any]] = []
        for candidate in candidates:
            symbol = _normalize_symbol(candidate.get("symbol"))
            base = symbol.split(".", 1)[0].split("-", 1)[0].split("/", 1)[0]
            name = str(candidate.get("name") or "")
            comparable = {
                re.sub(r"[^a-z0-9\u3400-\u9fff]", "", base.casefold()),
                re.sub(r"[^a-z0-9\u3400-\u9fff]", "", name.casefold()),
                re.sub(r"[^a-z0-9\u3400-\u9fff]", "", symbol.casefold()),
            }
            if normalized_query and normalized_query in comparable:
                exact.append(candidate)
            if candidate.get("also_from") or candidate.get("cik"):
                strong.append(candidate)
        if len(exact) == 1:
            return exact[0]
        if len(strong) == 1:
            return strong[0]
        return None

    def _authorize_private_company_skill(self) -> ToolAuthorization:
        """Keep private-company routing symmetric with locked listing evidence."""
        locked_listings = [
            record
            for record in self._identities.values()
            if record.status == "locked"
            and record.instrument_type in {"listed_security", "fund"}
        ]
        if locked_listings:
            return ToolAuthorization(
                allowed=False,
                error_code="identity_conflict",
                message=(
                    "A resolver has locked this entity to a listed security. Model memory "
                    "cannot replace that evidence with a private-company workflow."
                ),
                symbols=tuple(
                    record.symbol for record in locked_listings if record.symbol
                ),
            )
        if self.identity_status == "not_found" or not self._identity_required:
            return ToolAuthorization(allowed=True)
        return ToolAuthorization(
            allowed=False,
            error_code="identity_required",
            message=(
                "Private-company routing requires a completed resolver result with clean "
                "not_found status; current identity is unresolved, ambiguous, or invalidated."
            ),
        )

    @staticmethod
    def _is_private_company_skill(
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> bool:
        """Return whether this call selects a private-company skill."""
        if tool_name != "load_skill":
            return False
        name = str(arguments.get("name") or "").strip().casefold()
        return name in _PRIVATE_COMPANY_SKILL_NAMES or (
            "private" in name and "company" in name
        )

    @staticmethod
    def _extract_symbol_arguments(arguments: Mapping[str, Any]) -> list[str]:
        """Extract model-selected identities from well-known argument keys."""
        symbols: list[str] = []
        for key, value in arguments.items():
            if str(key).casefold() not in _SYMBOL_ARGUMENT_KEYS:
                continue
            values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
            for item in values:
                if not isinstance(item, (str, int)):
                    continue
                symbol = _normalize_symbol(item)
                if symbol and symbol not in symbols:
                    symbols.append(symbol)
        return symbols

    def _track_session_symbols(
        self,
        arguments: Mapping[str, Any],
        result: str,
    ) -> None:
        """Widen the run's instrument surface from one succeeding tool call.

        Both sides of a successful call count. The result is the strong signal —
        a resolver shortlist, an OHLC panel, a filing index. The arguments are
        the weaker one, but a symbol the model handed to a tool that then
        succeeded has at least been exercised against a real system, whereas a
        symbol that surfaces for the first time in the final prose has been
        exercised against nothing. Failed calls are deliberately excluded, so a
        blocked or erroring call never launders an invented ticker.

        Bare symbol arguments are tracked separately as roots. Many tools take a
        bare ticker by contract, so a run that legitimately fetched ``AAPL``
        never writes ``AAPL.US`` into any argument or result. Without the root,
        the canonical spelling the rest of this module demands — see
        ``canonical_symbol_not_surfaced`` — would be the one spelling this gate
        rejects.

        Args:
            arguments: Exact normalized tool arguments.
            result: Full raw result, before model-context truncation.
        """
        if len(self._session_symbols) >= _MAX_TRACKED_SYMBOLS:
            return
        try:
            rendered_arguments = json.dumps(arguments, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            rendered_arguments = ""
        found = _scan_symbols(rendered_arguments) | _scan_symbols(result)
        room = _MAX_TRACKED_SYMBOLS - len(self._session_symbols)
        self._session_symbols.update(sorted(found)[:room])
        self._session_symbol_roots.update(
            symbol
            for symbol in self._extract_symbol_arguments(arguments)
            if "." not in symbol
        )

    def _record_tool_failure(self, tool_name: str, call_id: str, result: str) -> None:
        """Store structured unavailable evidence for failed business envelopes."""
        payload = _json_object(result) or {}
        self._tool_failures.append(
            {
                "call_id": call_id,
                "tool": tool_name,
                "status": "unavailable",
                "error_code": payload.get("error_code"),
                "message": str(payload.get("error") or payload.get("message") or "tool failed")[:500],
                "recorded_at": _utc_now(),
            }
        )

    def _ingest_market_data(
        self,
        arguments: Mapping[str, Any],
        payload: dict[str, Any] | None,
        call_id: str,
    ) -> None:
        """Convert full OHLCV payloads into source-linked evidence rows."""
        if payload is None:
            self._record_tool_failure("get_market_data", call_id, "malformed JSON result")
            return
        requested_source = str(arguments.get("source") or "auto")
        provenance = payload.get("_provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        for raw_symbol, raw_rows in payload.items():
            if str(raw_symbol).startswith("_"):
                continue
            symbol = _normalize_symbol(raw_symbol)
            rows = raw_rows.get("data") if isinstance(raw_rows, dict) else raw_rows
            if not isinstance(rows, list):
                continue
            symbol_provenance = provenance.get(raw_symbol)
            actual_source = (
                str(symbol_provenance.get("source"))
                if isinstance(symbol_provenance, dict) and symbol_provenance.get("source")
                else requested_source
            )
            currency_conversion = (
                str(symbol_provenance.get("currency_conversion"))
                if isinstance(symbol_provenance, dict)
                and symbol_provenance.get("currency_conversion")
                else None
            )
            for row in rows:
                if not isinstance(row, dict):
                    continue
                timestamp = next(
                    (str(row[key]) for key in _TIMESTAMP_FIELDS if row.get(key) is not None),
                    None,
                )
                for field_name, value in row.items():
                    normalized_field = str(field_name).casefold()
                    if normalized_field in _TIMESTAMP_FIELDS or not _is_number(value):
                        continue
                    self._evidence.append(
                        EvidenceRecord(
                            call_id=call_id,
                            tool="get_market_data",
                            symbol=symbol,
                            source=actual_source,
                            timestamp=timestamp,
                            field=normalized_field,
                            value=value,
                            status="observed",
                            currency=_infer_currency(symbol),
                            venue=_infer_venue(symbol),
                            currency_conversion=currency_conversion,
                        )
                    )
        unresolved = payload.get("_unresolved")
        if isinstance(unresolved, list):
            for raw_symbol in unresolved:
                symbol = _normalize_symbol(raw_symbol)
                self._evidence.append(
                    EvidenceRecord(
                        call_id=call_id,
                        tool="get_market_data",
                        symbol=symbol,
                        source=requested_source,
                        timestamp=None,
                        field="availability",
                        value=None,
                        status="unavailable",
                        currency=_infer_currency(symbol),
                        venue=_infer_venue(symbol),
                    )
                )

    def _ingest_generic_numeric(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        payload: dict[str, Any],
        call_id: str,
    ) -> None:
        """Flatten bounded numeric leaves from other market-sensitive tools."""
        symbols = self._extract_symbol_arguments(arguments)
        symbol = symbols[0] if len(symbols) == 1 else None
        if symbol:
            symbol = (
                self._match_authorized_symbol(symbol, self.authorized_symbols) or symbol
            )
        source = str(payload.get("source") or tool_name)
        remaining = _MAX_GENERIC_EVIDENCE
        timestamp_fields = (*_TIMESTAMP_FIELDS, "as_of")

        def visit(value: Any, path: str, timestamp: str | None = None) -> None:
            nonlocal remaining
            if remaining <= 0:
                return
            if _is_number(value):
                self._evidence.append(
                    EvidenceRecord(
                        call_id=call_id,
                        tool=tool_name,
                        symbol=symbol,
                        source=source,
                        timestamp=timestamp,
                        field=path or "value",
                        value=value,
                        status="observed",
                        currency=_infer_currency(symbol or ""),
                        venue=_infer_venue(symbol or ""),
                    )
                )
                remaining -= 1
                return
            if isinstance(value, dict):
                local_timestamp = next(
                    (
                        str(value[key])
                        for key in timestamp_fields
                        if value.get(key) is not None
                    ),
                    timestamp,
                )
                for key, item in value.items():
                    if str(key).casefold() in timestamp_fields:
                        continue
                    visit(
                        item,
                        f"{path}.{key}" if path else str(key),
                        local_timestamp,
                    )
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    visit(item, f"{path}[{index}]", timestamp)

        visit(payload, "")

    def _ingest_run_dir_ohlc_csvs(self) -> None:
        """Register OHLC rows from CSVs the run wrote via the bash workaround.

        The bash+yfinance escape hatch writes per-symbol OHLC CSVs into the run
        directory (e.g. ``data/raw/BYN_V.csv``) instead of returning them through
        ``get_market_data``. Those prices were genuinely observed tool output,
        but they never entered the ledger, so the final-answer gate rejected
        every one of them as ``numeric_claim_unavailable``. Scan the run dir for
        such CSVs and register their open/high/low/close/price rows as observed
        evidence, keyed to the symbol derived from the filename.

        Only files whose filename maps to a symbol already tracked in this run
        are accepted, so a stray CSV cannot mint new identity. Rows are bounded
        by ``_MAX_GENERIC_EVIDENCE`` and each file is ingested at most once.
        """
        if not self.run_dir.is_dir():
            return
        entitled = self._session_symbols | self.authorized_symbols
        if not entitled:
            return
        room = _MAX_GENERIC_EVIDENCE
        for path in sorted(self.run_dir.rglob("*.csv")):
            if room <= 0:
                return
            try:
                identity_key = f"{path.resolve()}:{path.stat().st_mtime_ns}"
            except (OSError, ValueError):
                continue
            if identity_key in self._ingested_csvs:
                continue
            self._ingested_csvs.add(identity_key)
            symbol = _symbol_from_csv_filename(path.stem)
            if not symbol or symbol not in entitled:
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                    rows = list(csv.DictReader(handle))
            except (OSError, UnicodeDecodeError, csv.Error):
                continue
            for row in rows:
                if room <= 0:
                    return
                if not isinstance(row, dict):
                    continue
                timestamp = next(
                    (
                        str(row[key]).strip()
                        for key in row
                        if str(key).strip().casefold() in _CSV_DATE_COLUMNS
                        and row[key] not in (None, "")
                    ),
                    None,
                )
                for key, value in row.items():
                    field_name = _CSV_PRICE_COLUMNS.get(
                        str(key).strip().casefold().replace(" ", "_")
                    )
                    if field_name is None:
                        continue
                    numeric = _coerce_csv_number(value)
                    if numeric is None:
                        continue
                    self._evidence.append(
                        EvidenceRecord(
                            call_id=f"csv:{path.name}",
                            tool="bash",
                            symbol=symbol,
                            source="yfinance",
                            timestamp=timestamp,
                            field=field_name,
                            value=numeric,
                            status="observed",
                            currency=_infer_currency(symbol),
                            venue=_infer_venue(symbol),
                        )
                    )
                    room -= 1

    def _validate_identity(self, content: str) -> list[dict[str, Any]]:
        """Validate aggregate state and listed/private contradictions."""
        issues: list[dict[str, Any]] = []
        status = self.identity_status
        # Two conditions, both load-bearing.
        #
        # ``self._identities`` — a run that never named an instrument has no
        # identity to get wrong. The trigger phrase is matched against the user
        # message, so "什么是市盈率估值法？" set identity_required and then failed
        # every draft it could ever produce, including the honest answer. This
        # relaxation invents no licence to guess: a figure still has to survive
        # ``_validate_price_claims``, and a figure attached to a symbol no tool
        # handled still has to survive ``_validate_unsourced_symbols``.
        #
        # ``ambiguous`` is deliberately absent. A shortlist is an answer, which
        # is why ``_RESOLUTION_INCOMPLETE_STATUSES`` already lets workflow
        # selection proceed on it (#955) — but the final answer stayed blocked,
        # so a screening run loaded its skill and was then refused a conclusion.
        # Consumers remain blocked on ambiguous in ``authorize_tool_call``, so
        # such a run still cannot fetch a quote to misattribute.
        if (
            self._identity_required
            and self._identities
            and status in {"unresolved", "conflicting", "invalidated"}
        ):
            issues.append(
                {
                    "code": "identity_not_locked",
                    "status": status,
                    "message": f"Instrument identity is {status}; a final market conclusion requires locked identity.",
                }
            )
        listed = [
            record
            for record in self._identities.values()
            if record.status == "locked"
            and record.instrument_type in {"listed_security", "fund"}
        ]
        if listed and _PRIVATE_ASSERTION_RE.search(content):
            symbols = sorted(record.symbol for record in listed if record.symbol)
            issues.append(
                {
                    "code": "listed_identity_relabelled_private",
                    "symbols": symbols,
                    "message": (
                        f"Locked listed identity {', '.join(symbols)} was relabelled as private/unlisted "
                        "without a conflicting resolver result."
                    ),
                }
            )
        return issues

    def _validate_unsourced_symbols(self, content: str) -> list[dict[str, Any]]:
        """Reject figures attached to an instrument no tool in this run handled.

        This is the mechanically decidable half of "what the tools did not
        return, you do not supply" (#886/#887). Naming a symbol is left alone —
        prose may legitimately mention an index or a peer — but the moment a
        clause pairs an unhandled canonical symbol with a figure, the figure has
        no possible origin other than model memory.

        Args:
            content: Candidate assistant answer.

        Returns:
            One issue per distinct unsourced symbol carrying figures.
        """
        issues: list[dict[str, Any]] = []
        reported: set[str] = set()
        for line in content.splitlines():
            for segment in _split_clauses(line):
                unknown = sorted(
                    symbol
                    for symbol in _scan_symbols(segment) - self._session_symbols - reported
                    if symbol.rsplit(".", 1)[0] not in self._session_symbol_roots
                )
                if not unknown or not self._numbers_without_dates_or_percent(segment):
                    continue
                # Accept figures that are attributed to an external source
                # (e.g., "The paper reports a Sharpe ratio of 1.8.") rather
                # than model memory. Scoped to the clause: a line-level check
                # would let a citation in one clause launder an invented
                # sibling metric in the next.
                if _ATTRIBUTION_RE.search(segment):
                    continue
                for symbol in unknown:
                    reported.add(symbol)
                    issues.append(
                        {
                            "code": "unsourced_symbol_figures",
                            "symbol": symbol,
                            "claim": segment.strip()[:200],
                            "message": (
                                f"No tool call in this session passed in or returned {symbol}, "
                                "yet the answer attaches figures to it. Retrieve it, or report "
                                "it as not retrieved."
                            ),
                        }
                    )
        return issues

    def _validate_analysis_claims(self, content: str) -> list[dict[str, Any]]:
        """Reject backtest/analysis metrics with no kind-scoped evidence.

        #1336: after failed or deduplicated market-data calls the model may
        still present return-volatility / drawdown / probability figures as
        measured facts. A metric figure is legitimate only when the run's
        evidence contains the same *kind* of figure — recorded from a
        completed analysis result (backtest artifacts, factor/shadow/quantlib
        output) or from any successful tool's numeric output (e.g.
        ``portfolio_risk_xray``, flattened into ``_evidence``). Kind scoping
        is what keeps an observed price from standing in for an invented
        volatility figure. Definitional prose ("夏普比率大于 1.0 通常被认为
        较好"), explicitly forward-looking forecasts, and categorical
        historical-window facts without any window-producing analysis are
        handled separately here.

        Args:
            content: Candidate assistant answer.

        Returns:
            One issue per metric-bearing clause or table cell.
        """
        issues: list[dict[str, Any]] = []
        lines = content.splitlines()
        consumed: set[int] = set()
        price_records = self._comparable_price_records()
        for header, rows, row_indices in self._pipe_tables(lines):
            consumed.update(row_indices)
            columns = [
                (cell, _metric_kind_for_text(cell), bool(_FORECAST_FRAME_RE.search(cell)))
                for cell in header
            ]
            if not any(kind for _, kind, _ in columns):
                continue
            for row in rows:
                cells = row + [""] * (len(columns) - len(row))
                for (cell_text, kind, header_forecast), cell in zip(columns, cells):
                    if kind is None or header_forecast:
                        continue
                    values = self._measure_numbers(cell)
                    if not values:
                        continue
                    # A forecast annotation inside the cell ("预计 12.4%")
                    # exempts only that cell, never its neighbours.
                    if _FORECAST_FRAME_RE.search(cell) or _DEFINITION_FRAME_RE.search(
                        cell
                    ):
                        continue
                    unsupported = [
                        value
                        for value in values
                        if not self._analysis_value_observed(value, kind)
                    ]
                    if not unsupported:
                        continue
                    issues.append(
                        {
                            "code": "analysis_claim_unavailable",
                            "claim": f"{cell_text}: {cell}"[:200],
                            "value": unsupported[0],
                            "kind": kind,
                            "message": (
                                "No supporting analysis evidence (a completed "
                                "backtest result or observed risk metric) exists "
                                "for this figure. Mark the analysis as incomplete "
                                "and omit these figures."
                            ),
                        }
                    )
        for index, line in enumerate(lines):
            if index in consumed:
                continue
            line_symbol = self._symbol_for_claim(line, price_records)
            for segment in _split_clauses(line):
                if _CATEGORICAL_WINDOW_RE.search(segment) and _NUMBER_RE.search(segment):
                    if not any(
                        entry.get("tool") in _ANALYSIS_WINDOW_TOOLS
                        for entry in self._analysis_completed
                    ):
                        match = _NUMBER_RE.search(segment)
                        issues.append(
                            {
                                "code": "analysis_claim_unavailable",
                                "claim": segment.strip()[:200],
                                "value": match.group(0) if match else None,
                                "message": (
                                    "No backtest completed in this session, yet the "
                                    "answer states a categorical historical-window "
                                    "fact. Mark the analysis as incomplete and omit "
                                    "this claim."
                                ),
                            }
                        )
                    continue
                if _DEFINITION_FRAME_RE.search(segment):
                    continue
                # Attributed figures ("The paper reports a Sharpe of 1.8",
                # or the marker in a neighbouring clause: "据研究显示，策略
                # 年化收益 18.2%") are citations, not invented measurements
                # — skip the gate.
                if _ATTRIBUTION_RE.search(segment):
                    continue
                values = self._measure_numbers(segment)
                if not values:
                    continue
                if not _ANALYSIS_METRIC_RE.search(segment):
                    continue
                if _FORECAST_FRAME_RE.search(segment):
                    continue
                kind = _metric_kind_for_text(segment)
                unsupported = [
                    value
                    for value in values
                    if not self._analysis_value_observed(value, kind)
                ]
                if not unsupported:
                    continue
                # A return figure may be arithmetic on sourced inputs rather
                # than an invented backtest metric (#1338 review): an explicit
                # formula anchored to observed values, or growth between two
                # observed endpoints stated in the same line.
                if kind == "return":
                    if _DERIVATION_RE.search(line) and self._is_explicit_derivation(
                        line, price_records, line_symbol
                    ):
                        continue
                    if _GROWTH_FRAME_RE.search(line) and self._return_derived_from_observed(
                        unsupported, price_records, line_symbol
                    ):
                        continue
                issues.append(
                    {
                        "code": "analysis_claim_unavailable",
                        "claim": segment.strip()[:200],
                        "value": unsupported[0],
                        "kind": kind,
                        "message": (
                            "No supporting analysis evidence (a completed "
                            "backtest result or observed risk metric) exists for "
                            "this figure. Mark the analysis as incomplete and omit "
                            "these figures."
                        ),
                    }
                )
        return issues

    @staticmethod
    def _measure_numbers(text: str) -> list[str]:
        """Extract measurement-shaped numbers (decimal or percent) from a claim."""
        masked = _LOCALIZED_DATE_RE.sub(" ", text)
        masked = _DATE_RE.sub(" ", masked)
        masked = _SHORT_DATE_RE.sub(" ", masked)
        masked = _DASH_DATE_RE.sub(" ", masked)
        return [
            match.group(0).replace(" ", "").replace(",", "")
            for match in _MEASURE_NUMBER_RE.finditer(masked)
        ]

    @staticmethod
    def _pipe_tables(
        lines: Sequence[str],
    ) -> list[tuple[list[str], list[list[str]], list[int]]]:
        """Yield (header cells, row cells, row line indices) per pipe table."""
        tables: list[tuple[list[str], list[list[str]], list[int]]] = []
        index = 0
        while index < len(lines):
            if lines[index].count("|") < 2:
                index += 1
                continue
            block_start = index
            block: list[str] = []
            while index < len(lines) and lines[index].count("|") >= 2:
                block.append(lines[index])
                index += 1
            rows: list[list[str]] = []
            row_indices: list[int] = []
            for offset, block_line in enumerate(block[1:], start=1):
                cells = GroundingLedger._table_cells(block_line)
                if not cells or all(
                    _TABLE_SEPARATOR_RE.fullmatch(cell.strip()) for cell in cells
                ):
                    continue
                rows.append(cells)
                row_indices.append(block_start + offset)
            tables.append((GroundingLedger._table_cells(block[0]), rows, row_indices))
        return tables

    def _analysis_value_observed(self, raw: str, kind: str | None) -> bool:
        """Return True when a claim measurement matches kind-scoped evidence.

        Tools disagree on scale: ``compute_risk_xray`` returns fractions
        (annualized_vol 0.182, max_drawdown -0.094) while answers quote
        percents (18.2%, -9.4%). Try both the value and its percent scaling
        so an observed 0.182 grounds an 18.2% claim and vice versa. Drawdown
        sign conventions disagree too (positive vs negative fraction), so
        magnitude is compared for that kind. Only evidence of the claim's own
        kind counts: an observed price never grounds a volatility figure.
        """
        try:
            value = float(raw.replace("%", "").replace("％", "").replace(",", ""))
        except ValueError:
            return True
        observed: list[float] = []
        for record in self._analysis_metrics:
            if record.get("metric") == kind and record.get("value") is not None:
                observed.append(float(record["value"]))
        for record in self._evidence:
            if record.status != "observed" or record.value is None:
                continue
            if _metric_kind_for_path(record.field) != kind:
                continue
            observed.append(float(record.value))
        candidates = {value, value / 100.0}
        if kind == "drawdown":
            candidates |= {abs(value), abs(value) / 100.0}

        def close(candidate: float, item: float) -> bool:
            return abs(candidate - item) <= max(abs(item) * 0.005, 1e-9)

        return any(close(candidate, item) for candidate in candidates for item in observed)

    def _return_derived_from_observed(
        self,
        claimed: Sequence[str],
        records: Sequence[EvidenceRecord],
        symbol: str | None,
    ) -> bool:
        """True when a return figure equals growth between observed endpoints.

        #1338 review: "AAPL.US 从 2026-08-03 的 100.0 涨到 2026-09-02 的
        112.4，区间收益率为 12.4%" states arithmetic on sourced inputs. Only
        an exact (±0.5%) match against a pair of observed values grounds the
        figure; the caller must already have verified the from/to frame, so a
        bare unanchored return claim never reaches here.
        """
        candidates = [record for record in records if record.value is not None]
        if symbol:
            candidates = [record for record in candidates if record.symbol == symbol]
        observed = sorted({float(record.value) for record in candidates})
        if len(observed) < 2:
            return False
        values: list[float] = []
        for raw in claimed:
            try:
                values.append(float(str(raw).rstrip("%％")))
            except ValueError:
                continue
        for base in observed:
            for target in observed:
                if target == base:
                    continue
                derived = (target - base) / base
                for value in values:
                    if abs(value - derived) <= max(abs(derived) * 0.005, 1e-9):
                        return True
                    if abs(value - derived * 100.0) <= max(
                        abs(derived * 100.0) * 0.005, 1e-9
                    ):
                        return True
        return False

    def _validate_price_claims(self, content: str) -> list[dict[str, Any]]:
        """Check Markdown OHLC tables and price prose against observed records.

        Comparison runs against every observed quote in the run, whichever tool
        produced it. The provenance demands below stay keyed on ``get_market_data``
        evidence, whose ``source``/``currency``/venue fields are authoritative;
        a generic tool's fallback source is its own name, and requiring the
        answer to spell that out would reject correct prose.
        """
        issues, table_lines = self._validate_price_tables(content)
        records = self._comparable_price_records()
        # A report names its subject once and then writes prose about it. Both
        # narrower scopes are tried first; this is the last resort, and it only
        # resolves when the whole answer names exactly one evidence symbol.
        document_symbol = self._symbol_for_claim(content, records)
        has_price_claim = any(
            self._numbers_without_dates_or_percent(line)
            for index, line in enumerate(content.splitlines())
            if index in table_lines
        )
        for index, line in enumerate(content.splitlines()):
            if index in table_lines or "|" in line:
                continue
            line_symbol = self._symbol_for_claim(line, records)
            for segment in _split_clauses(line):
                if not _PRICE_CONTEXT_RE.search(segment):
                    continue
                values = self._numbers_without_dates_or_percent(segment)
                if not values:
                    continue
                has_price_claim = True
                symbol = (
                    self._symbol_for_claim(segment, records)
                    or line_symbol
                    or document_symbol
                )
                if self._is_explicit_derivation(segment, records, symbol):
                    continue
                # An attributed figure ("The paper reports TSLA.US traded at
                # 412.35") is a citation, not an invented price — skip the
                # price gate too, for the same reason as the analysis and
                # unsourced-symbol gates. Without this, an attributed price
                # is rejected or accepted purely on whether its verb happens
                # to match _PRICE_CONTEXT_RE ("reports" does, "estimate"
                # doesn't), which is the exact vocabulary asymmetry under
                # review.
                if _ATTRIBUTION_RE.search(segment):
                    continue
                for value in values:
                    issue = self._compare_price_claim(
                        value=value,
                        records=records,
                        field_name=None,
                        date_value=None,
                        symbol=symbol,
                        claim=segment.strip(),
                    )
                    if issue:
                        issues.append(issue)
        market_records = self._price_records()
        if has_price_claim and market_records:
            issues.extend(self._validate_price_provenance(content, market_records))
        return self._dedupe_issues(issues)

    @staticmethod
    def _symbol_for_claim(
        content: str,
        records: Sequence[EvidenceRecord],
    ) -> str | None:
        """Return one canonical evidence symbol explicitly named in a claim."""
        known = {record.symbol for record in records if record.symbol}
        matches = {
            _normalize_symbol(match.group(0))
            for match in _CANONICAL_SYMBOL_RE.finditer(content)
            if _normalize_symbol(match.group(0)) in known
        }
        return next(iter(matches)) if len(matches) == 1 else None

    def _validate_price_provenance(
        self,
        content: str,
        records: Sequence[EvidenceRecord],
    ) -> list[dict[str, Any]]:
        """Require canonical symbol, actual source, and quote currency in output."""
        issues: list[dict[str, Any]] = []
        folded = content.casefold()
        symbols = sorted({record.symbol for record in records if record.symbol})
        # ``_scan_symbols`` canonicalizes, so an answer that writes Shanghai as
        # ``600519.SS`` still surfaces the ``600519.SH`` identity it names.
        written = _scan_symbols(content)
        mentioned = [
            symbol
            for symbol in symbols
            if symbol in written or symbol.casefold() in folded
        ]
        if not mentioned:
            issues.append(
                {
                    "code": "canonical_symbol_not_surfaced",
                    "symbols": symbols,
                    "message": (
                        "A price claim must surface its locked canonical symbol and venue suffix."
                    ),
                }
            )
        target_symbols = set(mentioned or (symbols if len(symbols) == 1 else []))
        target_records = [
            record
            for record in records
            if not target_symbols or record.symbol in target_symbols
        ]

        sources = sorted(
            {
                record.source
                for record in target_records
                if record.source and record.source.casefold() not in {"auto", "unknown"}
            }
        )
        missing_sources = [
            source
            for source in sources
            if not any(
                alias in folded
                for alias in _SOURCE_ALIASES.get(
                    source.casefold(), (source.casefold(),)
                )
            )
        ]
        if missing_sources:
            issues.append(
                {
                    "code": "data_source_not_surfaced",
                    "sources": missing_sources,
                    "message": (
                        "Price claims must name the actual data source: "
                        + ", ".join(missing_sources)
                        + "."
                    ),
                }
            )

        currencies = sorted(
            {record.currency for record in target_records if record.currency}
        )
        missing_currencies = [
            currency
            for currency in currencies
            if not self._currency_is_surfaced(currency, content)
        ]
        if missing_currencies:
            issues.append(
                {
                    "code": "currency_not_surfaced",
                    "currencies": missing_currencies,
                    "message": (
                        "Price claims must name their quote currency: "
                        + ", ".join(missing_currencies)
                        + "."
                    ),
                }
            )
        return issues

    @staticmethod
    def _currency_is_surfaced(currency: str, content: str) -> bool:
        """Return whether a quote currency or an unambiguous alias is visible."""
        folded = content.casefold()
        code = currency.upper()
        tokens = _CURRENCY_ALIASES.get(code, (currency.casefold(),))
        if any(token.casefold() in folded for token in tokens):
            return True
        return code == "CNY" and bool(_BARE_YUAN_RE.search(content))

    def _validate_price_tables(
        self,
        content: str,
    ) -> tuple[list[dict[str, Any]], set[int]]:
        """Validate field/date-specific claims in Markdown OHLC tables."""
        lines = content.splitlines()
        issues: list[dict[str, Any]] = []
        consumed: set[int] = set()
        index = 0
        records = self._comparable_price_records()
        while index + 1 < len(lines):
            header = self._table_cells(lines[index])
            separator = self._table_cells(lines[index + 1])
            if not header or not separator or len(header) != len(separator):
                index += 1
                continue
            if not all(_TABLE_SEPARATOR_RE.match(cell.replace(" ", "")) for cell in separator):
                index += 1
                continue
            field_columns = {
                position: _TABLE_FIELD_ALIASES[cell.strip().casefold()]
                for position, cell in enumerate(header)
                if cell.strip().casefold() in _TABLE_FIELD_ALIASES
            }
            if not field_columns:
                index += 1
                continue
            date_column = next(
                (position for position, cell in enumerate(header) if cell.strip().casefold() in _DATE_HEADERS),
                None,
            )
            symbol_column = next(
                (position for position, cell in enumerate(header) if cell.strip().casefold() in _SYMBOL_HEADERS),
                None,
            )
            consumed.update({index, index + 1})
            row_index = index + 2
            while row_index < len(lines):
                row = self._table_cells(lines[row_index])
                if not row or len(row) != len(header):
                    break
                consumed.add(row_index)
                date_value = row[date_column].strip() if date_column is not None else None
                symbol = _normalize_symbol(row[symbol_column]) if symbol_column is not None else None
                for position, field_name in field_columns.items():
                    values = self._numbers_without_dates_or_percent(row[position])
                    if len(values) != 1:
                        continue
                    issue = self._compare_price_claim(
                        value=values[0],
                        records=records,
                        field_name=field_name,
                        date_value=date_value,
                        symbol=symbol,
                        claim=row[position].strip(),
                    )
                    if issue:
                        issues.append(issue)
                row_index += 1
            index = max(row_index, index + 1)
        return issues, consumed

    @staticmethod
    def _table_cells(line: str) -> list[str]:
        """Split one Markdown table row, or return an empty list."""
        if "|" not in line:
            return []
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [cell.strip() for cell in stripped.split("|")]

    def _compare_price_claim(
        self,
        *,
        value: float,
        records: list[EvidenceRecord],
        field_name: str | None,
        date_value: str | None,
        symbol: str | None,
        claim: str,
    ) -> dict[str, Any] | None:
        """Compare one unlabelled observed claim to the closest evidence value."""
        candidates = records
        if symbol:
            candidates = [record for record in candidates if record.symbol == symbol]
        symbols = sorted({record.symbol for record in candidates if record.symbol})
        if not symbol and len(symbols) == 1:
            symbol = symbols[0]
        # An unattributed claim used to be rejected outright once the run held
        # evidence for more than one symbol. That is every comparison report:
        # "Apple's closing price was 313.33 USD. Microsoft closed higher." names
        # its subject by company name, and the clause was refused although the
        # value was exactly the observed close sitting in evidence. Such a claim
        # is now checked against the union of the observed quotes instead, so a
        # number the run never observed is still caught below — it simply has to
        # match nothing at all rather than nothing under one chosen symbol.
        if field_name:
            candidates = [record for record in candidates if record.field == field_name]
        if date_value:
            candidates = [
                record
                for record in candidates
                if record.timestamp
                and _timestamp_matches_claim_date(record.timestamp, date_value)
            ]
        if not candidates:
            return {
                "code": "numeric_claim_unavailable",
                "claim": claim,
                "value": value,
                "symbol": symbol,
                "field": field_name,
                "date": date_value,
                "message": f"Price claim {value:g} has no matching observed tool evidence.",
            }
        observed = [float(record.value) for record in candidates if record.value is not None]
        if any(abs(value - item) <= max(abs(item) * 0.005, 1e-9) for item in observed):
            return None
        return {
            "code": "numeric_claim_conflict",
            "claim": claim,
            "value": value,
            "symbol": symbol,
            "field": field_name,
            "date": date_value,
            "observed_min": min(observed),
            "observed_max": max(observed),
            "source_tool_call_ids": sorted({record.call_id for record in candidates}),
            "message": (
                f"Price claim {value:g} conflicts with observed {field_name or 'OHLC'} "
                f"evidence {min(observed):g}–{max(observed):g}."
            ),
        }

    def _price_records(self) -> list[EvidenceRecord]:
        """Return observed OHLC/price evidence only."""
        return [
            record
            for record in self._evidence
            if record.status == "observed"
            and record.field in _PRICE_FIELDS
            and record.value is not None
        ]

    def _comparable_price_records(self) -> list[EvidenceRecord]:
        """Return every observed quote a numeric claim may be checked against.

        ``_price_records`` only sees fields already named ``open``/``close``/…,
        which in practice means ``get_market_data``. Quotes returned by the
        other market-sensitive tools are re-keyed onto the same canonical field
        so the contradiction check compares like with like instead of reporting
        the claim as unevidenced.

        Returns:
            Observed price evidence with canonical ``field`` values.
        """
        records = self._price_records()
        already_counted = {id(record) for record in records}
        for record in self._evidence:
            if id(record) in already_counted:
                continue
            if record.status != "observed" or record.value is None:
                continue
            field_name = _price_field_for_path(record.field)
            if field_name is None:
                continue
            records.append(replace(record, field=field_name))
        return records

    @staticmethod
    def _numbers_without_dates_or_percent(text: str) -> list[float]:
        """Extract the numbers in a claim that could plausibly be prices.

        Digits that belong to a canonical symbol, a calendar date, an aggregate
        amount, a labelled score, a named indicator reading, a unit-bearing
        quantity, or a percentage are masked first. Left unmasked they are
        compared against observed OHLC ranges and reject a correct draft:
        ``000543.SZ`` alone contributes 543, and a well-formed verdict line
        contributes its confidence score and every moving-average window it
        names (#1001).

        Args:
            text: One claim segment or table cell.

        Returns:
            Candidate price values, in order of appearance.
        """
        masked = _MD_LIST_ITEM_RE.sub(" ", text)
        masked = _RATE_FORMULA_IDENTITY_RE.sub(" ", masked)
        masked = _CANONICAL_SYMBOL_RE.sub(" ", masked)
        masked = _LOCALIZED_DATE_RE.sub(" ", masked)
        masked = _DATE_RE.sub(" ", masked)
        masked = _SHORT_DATE_RE.sub(" ", masked)
        masked = _DASH_DATE_RE.sub(" ", masked)
        masked = _PERCENT_RANGE_RE.sub(" ", masked)
        masked = _PERCENTAGE_POINT_RE.sub(" ", masked)
        masked = _ORDER_LEVEL_RE.sub(" ", masked)
        masked = _AGGREGATE_AMOUNT_RE.sub(" ", masked)
        masked = _LABELLED_SCORE_RE.sub(" ", masked)
        masked = _INDICATOR_VALUE_RE.sub(" ", masked)
        masked = _PROSPECTIVE_LEVEL_RE.sub(" ", masked)
        masked = _REFERENCE_LEVEL_RE.sub(" ", masked)
        masked = _SINCE_REFERENCE_RE.sub(" ", masked)
        masked = _LINE_REFERENCE_RE.sub(" ", masked)
        masked = _NUMBERED_HEADING_RE.sub(" ", masked)
        masked = _RATIO_RE.sub(" ", masked)
        masked = _FX_RATE_RE.sub(" ", masked)
        without_dates = _QUANTITY_WITH_UNIT_RE.sub(" ", masked)
        values: list[float] = []
        for match in _NUMBER_RE.finditer(without_dates):
            tail = without_dates[match.end() :].lstrip()
            if tail.startswith(("%", "％")):
                continue
            try:
                values.append(float(match.group(0).replace(",", "")))
            except ValueError:
                continue
        return values

    def _is_explicit_derivation(
        self,
        text: str,
        records: Sequence[EvidenceRecord],
        symbol: str | None,
    ) -> bool:
        """Allow only an arithmetically valid formula anchored to observed input."""
        if not _DERIVATION_RE.search(text):
            return False
        candidates = list(records)
        if symbol:
            candidates = [record for record in candidates if record.symbol == symbol]
        candidate_symbols = {record.symbol for record in candidates if record.symbol}
        if not symbol and len(candidate_symbols) > 1:
            return False
        observed = [
            float(record.value) for record in candidates if record.value is not None
        ]
        if not observed:
            return False

        for equals in re.finditer(r"=", text):
            left = re.search(r"([0-9.,+\-*/×÷()\s]+)$", text[: equals.start()])
            right = re.match(
                r"\s*([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)",
                text[equals.end() :],
            )
            if not left or not right:
                continue
            evaluated = self._evaluate_formula(left.group(1))
            if evaluated is None:
                continue
            computed, inputs = evaluated
            try:
                claimed = float(right.group(1).replace(",", ""))
            except ValueError:
                continue
            if not any(
                abs(item - value) <= max(abs(value) * 0.005, 1e-9)
                for item in inputs
                for value in observed
            ):
                continue
            if abs(computed - claimed) <= max(abs(computed) * 0.005, 1e-9):
                return True
        return False

    @staticmethod
    def _evaluate_formula(expression: str) -> tuple[float, list[float]] | None:
        """Evaluate a numeric ``+ - * /`` expression without executing code."""
        normalized = expression.replace("×", "*").replace("÷", "/").replace(",", "").strip()
        try:
            tree = ast.parse(normalized, mode="eval")
        except (SyntaxError, ValueError):
            return None
        inputs: list[float] = []

        def visit(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Constant) and _is_number(node.value):
                value = float(node.value)
                inputs.append(value)
                return value
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand)
                return value if isinstance(node.op, ast.UAdd) else -value
            if isinstance(node, ast.BinOp) and isinstance(
                node.op,
                (ast.Add, ast.Sub, ast.Mult, ast.Div),
            ):
                left_value = visit(node.left)
                right_value = visit(node.right)
                if isinstance(node.op, ast.Add):
                    return left_value + right_value
                if isinstance(node.op, ast.Sub):
                    return left_value - right_value
                if isinstance(node.op, ast.Mult):
                    return left_value * right_value
                if right_value == 0:
                    raise ValueError("division by zero")
                return left_value / right_value
            raise ValueError("unsupported formula")

        try:
            value = visit(tree)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            return None
        if len(inputs) < 2 or not math.isfinite(value):
            return None
        return value, inputs

    @staticmethod
    def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicate validator findings while preserving order."""
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for issue in issues:
            key = json.dumps(issue, sort_keys=True, ensure_ascii=False, default=str)
            if key in seen:
                continue
            seen.add(key)
            unique.append(issue)
        return unique


__all__ = [
    "GROUNDING_ARTIFACT",
    "GroundingLedger",
    "IdentityConstraint",
    "IdentityRecord",
    "ResolutionContext",
    "ToolAuthorization",
    "ValidationResult",
]
