"""Per-role validation: what each declared figure has to survive.

The model declares what each measurement-shaped number IS (spec §2); this
module checks that declaration against ledger evidence (spec §4). It reads no
prose word: roles come from the model, shape from :mod:`figures`.
"""

from __future__ import annotations

import ast
import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from src.agent.grounding.identity import (
    _CANONICAL_SYMBOL_RE,
    _normalize_symbol,
    _scan_symbols,
)
from src.agent.grounding.evidence import (
    EvidenceRecord,
    _is_metadata_count_leaf,
    _is_number,
    _is_price_kind,
    _metric_kind_for_path,
    _price_field_for_path,
    _timestamp_matches_claim_date,
)
from src.agent.grounding.figures import (
    Declaration,
    Figure,
    FiguresBlock,
    _lines_with_offsets,
    segment_bounds,
)

import re

#: An answer that relabels a locked listed identity as private contradicts the
#: resolver, which is an identity finding rather than a figure finding.
_PRIVATE_ASSERTION_RE = re.compile(
    r"(?:\b(?:is|remains|still)\s+(?:an?\s+)?(?:private company|privately held)\b|"
    r"\bnot publicly traded\b|\bunlisted company\b|"
    r"(?:是|仍是|属于)(?:一家)?(?:私人|私营|非上市)公司|未上市|没有上市)",
    re.IGNORECASE,
)

# #GGAL-B follow-up: NOT a grounding/role signal (this module still reads no
# prose word to decide whether a figure is valid — that stays entirely on
# declared role + evidence). This is consulted ONLY to tag whether a
# rejected figure's own clause is genuinely about a market quote, so
# ``recovery_action`` (release.py) can decide whether ``get_market_data``
# could plausibly ever answer it. A currency mark alone is not enough — EPS,
# net income, revenue, assets, equity, capex and FCF are all currency-marked
# and none of them is a quote.
#
# Deliberately conservative (#GGAL-B follow-up round 2): a bare word here
# ("cierre", "objetivo", "máximo", "mínimo", "open", "high", "low") also
# reads a fundamentals sentence — "Ratio de capital al CIERRE de FY2024",
# "OBJETIVO de eficiencia: 45%", "Capital MÍNIMO requerido: 11,5%" all
# contain one of those words with no quote in sight. Every alternative below
# is therefore a full bursátil PHRASE (closing/opening PRICE, closed/opened
# AT a value, intraday high/low, price TARGET, ...) or an unambiguous
# market-only term (cotización). On any doubt this must return False; the
# correction/cited/redacted-release path handles the rest.
_MARKET_PRICE_CONTEXT_RE = re.compile(
    r"(?:"
    r"\bprice\s+target\b|\btarget\s+price\b|"
    r"\bclosing\s+price\b|\bopening\s+price\b|"
    r"\bclos(?:e|ed)\s+at\b|\bopen(?:ed)?\s+at\b|"
    r"\bintraday\s+high\b|\bintraday\s+low\b|"
    r"\bprice\s+support\b|\bprice\s+resistance\b|"
    r"precio\s+de\s+cierre|precio\s+de\s+apertura|precio\s+objetivo|"
    r"cerr[oó]\s+en|abri[oó]\s+en|"
    r"cotizaci[oó]n|cotiz[oó]\b|"
    r"m[aá]ximo\s+intradiario|m[ií]nimo\s+intradiario|"
    r"soporte\s+de\s+precio|resistencia\s+de\s+precio|"
    r"nivel\s+de\s+soporte|nivel\s+de\s+resistencia|"
    r"开盘价|收盘价|最高价|最低价|现价|目标价|止损价|支撑位|阻力位|报价"
    r")",
    re.IGNORECASE,
)

# Loader ids are ASCII but the answer follows the user's language, so a source
# is surfaced by any alias ("数据来源：腾讯财经" for ``tencent``).
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

_CURRENCY_ALIASES = {
    "USD": ("usd", "us$", "美元", "美金"),
    # ¥ is also the yen sign, but ``_infer_currency`` maps no venue to JPY;
    # adding a JPY venue means revisiting this entry.
    "CNY": ("cny", "cnh", "rmb", "人民币", "¥", "￥"),
    "HKD": ("hkd", "hk$", "港元", "港币"),
    "KRW": ("krw", "韩元", "韩圜"),
    "INR": ("inr", "印度卢比", "卢比"),
    "CAD": ("cad", "c$", "加元", "加拿大元"),
}

# "元" counts as CNY only when no other currency's character precedes it
# (港元/美元/日元), or a Hong Kong listing would satisfy a CNY requirement.
_OTHER_CURRENCY_PREFIXES = "港美日欧韩台新加澳"

#: Relative band a value must fall in to count as matching evidence.
_TOLERANCE = 0.005

#: A plain integer is read as a price only for an instrument quoted in the
#: thousands (600519.SH, an index, BTC). Below that, a prose integer is a window,
#: a horizon or a count ("20 日均线", "200-day") and stays unchecked.
_INTEGER_PRICE_FLOOR = 1000.0

#: Price fields a rejected prose figure is pointed at, in order (#1433).
_CITABLE_FIELDS = ("close", "price", "adj_close")


@dataclass(frozen=True)
class ValidationResult:
    """Final-answer grounding decision.

    ``released_text`` is the draft without its declaration block, which is a
    contract with the gate and never reaches the user.
    """

    valid: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    released_text: str = ""


def _close(value: float, target: float) -> bool:
    """Whether two values agree inside the evidence tolerance."""
    return abs(value - target) <= max(abs(target) * _TOLERANCE, 1e-9)


def _close_any(value: float, targets: Iterable[float]) -> bool:
    """Whether ``value`` agrees with any of ``targets``."""
    return any(_close(value, target) for target in targets)


def _nearest(value: float, targets: Iterable[float], limit: int = 3) -> list[float]:
    """The observed values closest to a rejected figure.

    Args:
        value: The rejected figure's value.
        targets: Every value the relevant evidence pool holds.
        limit: How many to name.

    Returns:
        Up to ``limit`` distinct observed values, closest first.
    """
    unique = sorted({float(target) for target in targets}, key=lambda item: (abs(item - value), item))
    return unique[:limit]


def _written_half_unit(text: str) -> float:
    """Half a unit of the last digit a figure was written with ("37%" -> 0.5)."""
    body = text.strip().rstrip("%％").strip()
    decimals = len(body.split(".", 1)[1]) if "." in body else 0
    return 0.5 * 10.0 ** (-decimals)


def _explicit_sign(text: str) -> int:
    """``1`` or ``-1`` when a figure was written with a sign ("+36.8%"), else ``0``."""
    head = text.strip()[:1]
    return 1 if head == "+" else -1 if head == "-" else 0


def _is_plain_count(figure: Figure) -> bool:
    """Whether a figure can be a count or a parameter the model chose.

    A weight, threshold, window, probability or multiplier is unchecked; a
    figure with a currency mark is a price or an amount and is checked as
    observed. A price column is refused before this is asked.
    """
    return not figure.currency


def _note_tokens(note: str) -> set[str]:
    """Citation fragments in a note: CJK character pairs and ASCII words of four letters or more.

    Pairs, because Chinese is not space-separated: "财报毛利率桥" is visible in
    "毛利率下降" the way "gross margin bridge" is visible in "gross margin".
    Four letters, because "the" or "and" would make any English line visible.

    Args:
        note: A declaration's free-text note.

    Returns:
        The casefolded fragments; digits, spaces and punctuation separate runs.
    """
    tokens: set[str] = set()
    run, kind = "", ""
    for char in note.casefold() + " ":
        if "㐀" <= char <= "鿿":
            current = "cjk"
        elif char.isascii() and char.isalpha():
            current = "ascii"
        else:
            current = ""
        if current != kind:
            if kind == "cjk" and len(run) >= 2:
                tokens.update(run[index : index + 2] for index in range(len(run) - 1))
            elif kind == "ascii" and len(run) >= 4:
                tokens.add(run)
            run, kind = "", current
        if current:
            run += char
    return tokens


def _strip_sign(node: ast.AST) -> ast.AST:
    """The operand under any unary ``+`` or ``-``."""
    while isinstance(node, ast.UnaryOp):
        node = node.operand
    return node


def _is_sum(node: ast.AST) -> bool:
    """Whether a node is a binary ``+`` or ``-``."""
    return isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub))


def _is_unit_factor(node: ast.AST) -> bool:
    """Whether a sum is ``1 ± c ± …`` over constants: a percentage change as a factor."""
    node = _strip_sign(node)
    if not _is_sum(node):
        return False
    while _is_sum(node):
        if not isinstance(_strip_sign(node.right), ast.Constant):
            return False
        node = _strip_sign(node.left)
    return isinstance(node, ast.Constant) and node.value == 1


def _unanchored_term(tree: ast.Expression, observed: Callable[[float], bool]) -> bool:
    """Whether a formula adds or subtracts a term holding no observed operand.

    Multiplicative constants are free, so two forms are not offsets: ``1 ± c``
    used as a factor ("0.666 × (1 − 0.03)") and the 1 beside a quotient
    ("0.666 / 1.053 − 1"). Neither reaches a value a free multiplier could not.
    Both are recognised by structure: near a price of 1 the constant 1 is itself
    within tolerance of an observation.

    Args:
        tree: The parsed formula.
        observed: Whether an operand is a value this session observed.

    Returns:
        True when some added or subtracted term is unanchored.
    """

    def anchored(node: ast.AST) -> bool:
        return any(
            observed(float(item.value))
            for item in ast.walk(node)
            if isinstance(item, ast.Constant) and _is_number(item.value)
        )

    def visit(node: ast.AST, factor: bool) -> bool:
        node = _strip_sign(node)
        if not isinstance(node, ast.BinOp):
            return False
        if not _is_sum(node):
            return visit(node.left, True) or visit(node.right, True)
        if factor and _is_unit_factor(node):
            return False
        for side, other in ((node.left, node.right), (node.right, node.left)):
            side, other = _strip_sign(side), _strip_sign(other)
            unit_beside_ratio = (
                isinstance(side, ast.Constant)
                and side.value == 1
                and isinstance(other, ast.BinOp)
                and isinstance(other.op, ast.Div)
            )
            if not _is_sum(side) and not unit_beside_ratio and not anchored(side):
                return True
        return visit(node.left, False) or visit(node.right, False)

    return visit(tree.body, False)


def _evaluate_formula(expression: str) -> tuple[float, list[float], ast.Expression] | None:
    """Evaluate a numeric ``+ - * /`` expression without executing code.

    Args:
        expression: An arithmetic run, possibly using ``× ÷ −`` and commas.

    Returns:
        ``(result, operands, parsed tree)``, or None when the run is not a
        well-formed expression over at least two numeric operands.
    """
    normalized = (
        expression.replace("×", "*")
        .replace("✕", "*")
        .replace("÷", "/")
        .replace("−", "-")
        .replace("–", "-")
        .replace("（", "(")
        .replace("）", ")")
        .replace(",", "")
        .replace("%", "")
        .strip()
    )
    if not normalized:
        return None
    try:
        tree = ast.parse(normalized, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
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
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left = visit(node.left)
            right = visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise ValueError("division by zero")
            return left / right
        raise ValueError("unsupported formula")

    try:
        value = visit(tree)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    if len(inputs) < 2 or not math.isfinite(value):
        return None
    return value, inputs, tree


def _formula_in_note(note: str) -> tuple[float, list[float], ast.Expression] | None:
    """Find the derivation a note states.

    The whole note is tried first, then each segment between result separators
    ("0.666 × 0.97 = 0.646"); separators are punctuation, not vocabulary.

    Args:
        note: The declaration's free-text note.

    Returns:
        ``(result, operands, parsed tree)`` for the first parseable segment, or None.
    """
    candidates = [note]
    parts = [note]
    for separator in ("≈", "≒", "＝", "=", "→", "->"):
        parts = [piece for part in parts for piece in part.split(separator)]
    # A formula followed by its explanation ("(a − b) / b，自高点回撤"). A bare
    # "," is not split: it groups thousands inside a formula.
    for separator in ("，", "；", "：", "; ", ", "):
        parts = [piece for part in parts for piece in part.split(separator)]
    candidates.extend(part for part in parts if part.strip())
    for candidate in candidates:
        evaluated = _evaluate_formula(candidate)
        if evaluated is not None:
            return evaluated
    return None


class _PolicyMixin:
    """Policy behaviour of :class:`GroundingLedger`."""

    def _validate_identity(self, content: str) -> list[dict[str, Any]]:
        """Validate aggregate state and listed/private contradictions."""
        issues: list[dict[str, Any]] = []
        status = self.identity_status
        # Only a run that named an instrument can get its identity wrong: the
        # trigger phrase matches the user message, so "什么是市盈率估值法？" would
        # otherwise fail every draft. ``ambiguous`` is absent on purpose: a
        # shortlist is an answer and consumers stay blocked in ``authorize_tool_call``.
        if (
            self._identity_required
            and self._identities
            and status in {"unresolved", "conflicting", "invalidated"}
        ):
            issues.append(
                {
                    "code": "identity_not_locked",
                    "status": status,
                    "value": None,
                    "role": None,
                    "span": None,
                    "symbol": None,
                    "reason": "identity_not_locked",
                    "message": (
                        f"Instrument identity is {status}; a final market conclusion "
                        "requires locked identity."
                    ),
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
                    "value": None,
                    "role": None,
                    "span": None,
                    "symbol": None,
                    "reason": "listed_relabelled_private",
                    "message": (
                        f"Locked listed identity {', '.join(symbols)} was relabelled as "
                        "private/unlisted without a conflicting resolver result."
                    ),
                }
            )
        return issues

    def _validate_figures(
        self,
        content: str,
        block: FiguresBlock,
        figures: Sequence[Figure],
    ) -> list[dict[str, Any]]:
        """Check every measurement-shaped number against its declared role.

        Args:
            content: The candidate answer.
            block: Its parsed declaration block.
            figures: Every number located in its prose.

        Returns:
            One issue per figure that its role does not survive, plus one per
            malformed declaration line and the provenance findings.
        """
        issues: list[dict[str, Any]] = [
            {
                "code": "figures_block_malformed",
                "line": line_no,
                "claim": raw,
                "value": None,
                "role": None,
                "span": None,
                "symbol": None,
                "reason": "unparseable_declaration",
                "message": (
                    f"figures block line {line_no} could not be read as "
                    "`value | role | note | ref`: " + raw
                ),
            }
            for line_no, raw in block.malformed
        ]
        records = self._comparable_price_records()
        document_symbol = self._symbol_for_claim(content, records)
        positions = _lines_with_offsets(content)
        line_symbols = [
            self._symbol_for_claim(line, records) for line, _ in positions
        ]
        declared_observed = {
            declaration.value
            for declaration in block.declarations
            if declaration.role == "observed"
        }
        # Multipliers a declared derivation uses: a count equal to one is that factor.
        derived_constants = [
            operand
            for declaration in block.declarations
            if declaration.role == "derived"
            for evaluated in [_formula_in_note(declaration.note)]
            if evaluated is not None
            for operand in evaluated[1]
        ]
        checked_price = False
        for figure in figures:
            if figure.shape not in ("measured", "bare"):
                continue
            declaration = block.match(figure.value, figure.percent)
            symbol = self._figure_symbol(
                content, figure, declaration, line_symbols, document_symbol, records
            )
            market_price = self._figure_is_market_price(content, figure, declaration)
            if figure.shape == "bare" and not self._poses_as_price(
                figure, self._price_band(symbol, records)
            ):
                continue
            if declaration is not None:
                written = self._written_symbol(content, figure, line_symbols, records)
                if written and symbol and written != symbol:
                    # A declaration names where a number came from; it cannot
                    # move a figure the sentence attaches to another instrument.
                    issues.append(
                        self._figure_issue(
                            "numeric_claim_conflict",
                            figure,
                            declaration.role,
                            symbol,
                            "symbol_mismatch",
                            f"is declared for {symbol} but the answer writes it about {written}",
                        )
                    )
                    continue
            if declaration is None:
                found = self._check_observed(figure, None, symbol, records, market_price)
                if block.present and found:
                    issues.append(
                        self._figure_issue(
                            "figure_undeclared",
                            figure,
                            None,
                            symbol,
                            "undeclared",
                            "is not declared in the figures block and is not an observed "
                            "value; declare it as observed / derived / proposed / cited / "
                            "count, or remove it",
                        )
                    )
                    continue
                checked_price = True
                issues.extend(found)
                continue
            role = declaration.role
            if figure.column and role != "observed":
                issues.append(
                    self._figure_issue(
                        "numeric_claim_conflict",
                        figure,
                        role,
                        symbol,
                        "cited_as_observed" if role == "cited" else "role_in_price_column",
                        f"is declared {role}, but it sits in the {figure.column} column, "
                        "which holds observed prints only",
                    )
                )
                continue
            if role == "count":
                posing = (
                    _is_plain_count(figure)
                    and self._poses_as_price(figure, self._price_band(symbol, records))
                    and not _close_any(figure.value, derived_constants)
                )
                if not _is_plain_count(figure) or posing:
                    checked_price = True
                    issues.extend(
                        self._count_as_observed(
                            figure,
                            declaration,
                            symbol,
                            records,
                            market_price,
                            why=(
                                "it sits in the instrument's observed price range and no "
                                "declared derivation uses it"
                                if posing
                                else "a count cannot carry a currency mark"
                            ),
                        )
                    )
                continue
            if role == "cited":
                line = (
                    positions[figure.line][0]
                    if 0 <= figure.line < len(positions)
                    else ""
                )
                issues.extend(
                    self._check_cited(figure, declaration, symbol, declared_observed, line)
                )
                continue
            checked_price = True
            if role == "derived":
                issues.extend(
                    self._check_derived(figure, declaration, symbol, records)
                )
                continue
            if role == "proposed":
                issues.extend(
                    self._check_proposed(figure, declaration, symbol, records)
                )
                continue
            issues.extend(
                self._check_observed(figure, declaration, symbol, records, market_price)
            )
        market_records = self._price_records()
        if checked_price and market_records:
            issues.extend(self._validate_price_provenance(content, market_records))
        return issues

    @staticmethod
    def _figure_issue(
        code: str,
        figure: Figure,
        role: str | None,
        symbol: str | None,
        reason: str,
        message: str,
        **extra: Any,
    ) -> dict[str, Any]:
        """Build one figure-scoped issue with value, role, span, symbol and reason.

        ``percent``/``currency`` are carried through from the figure itself
        (#GGAL-B): a ratio like ROE/ROA is always ``percent=True``, which is
        what ``recovery_action`` uses to tell a fundamentals figure apart
        from a market quote it could plausibly recover with
        ``get_market_data`` — never the issue *code* name alone.
        """
        issue = {
            "code": code,
            "value": figure.text,
            "role": role,
            "span": [figure.start, figure.end],
            "symbol": symbol,
            "reason": reason,
            "claim": figure.text,
            "message": f"{figure.text} {message}.",
            "percent": figure.percent,
            "currency": figure.currency,
        }
        issue.update(extra)
        return issue

    def _figure_symbol(
        self,
        content: str,
        figure: Figure,
        declaration: Declaration | None,
        line_symbols: Sequence[str | None],
        document_symbol: str | None,
        records: Sequence[EvidenceRecord],
    ) -> str | None:
        """Resolve which instrument a figure is about (spec §4).

        Order: the declaration's ``ref``/``note``, the table row's symbol column,
        the figure's punctuation segment, its line, then the whole answer. The
        segment precedes the line because a comparison report names both
        instruments on one header line and then writes about one of them.
        """
        if declaration is not None:
            declared = self._symbol_for_claim(
                f"{declaration.ref} {declaration.note}", records
            )
            if declared:
                return declared
        return self._written_symbol(content, figure, line_symbols, records) or document_symbol

    def _written_symbol(
        self,
        content: str,
        figure: Figure,
        line_symbols: Sequence[str | None],
        records: Sequence[EvidenceRecord],
    ) -> str | None:
        """The instrument the answer's own text attaches a figure to, if one.

        The table row's symbol column, then the figure's punctuation segment,
        then its line; the whole-answer fallback is left to the caller.
        """
        if figure.symbol:
            normalized = _normalize_symbol(figure.symbol)
            if normalized:
                return normalized
        left, right = segment_bounds(content, figure.start, figure.end)
        segment_symbol = self._symbol_for_claim(content[left:right], records)
        if segment_symbol:
            return segment_symbol
        if 0 <= figure.line < len(line_symbols) and line_symbols[figure.line]:
            return line_symbols[figure.line]
        return None

    @staticmethod
    def _figure_is_market_price(
        content: str,
        figure: Figure,
        declaration: Declaration | None,
    ) -> bool:
        """Whether a figure is genuinely about a market quote, not a fundamental.

        A POSITIVE condition (#GGAL-B follow-up), not "has a currency mark":
        EPS, net income, revenue, assets, equity, capex and FCF are all
        currency-marked and none of them is a price. True only when a
        concrete OHLC/price/target/support/resistance signal is present —
        the figure sits in a recognized OHLC table column, or that
        vocabulary appears in the figure's own clause or its declared note.
        Uncertain cases return False on purpose: this must never make
        ``recovery_action`` suggest ``get_market_data`` on a guess.

        This does NOT affect whether the figure is valid — only whether a
        rejected figure could plausibly be resolved by fetching a quote; see
        ``recovery_action`` in ``release.py``, its only reader.
        """
        if figure.column:
            return True
        left, right = segment_bounds(content, figure.start, figure.end)
        if _MARKET_PRICE_CONTEXT_RE.search(content[left:right]):
            return True
        if declaration is not None and _MARKET_PRICE_CONTEXT_RE.search(declaration.note):
            return True
        return False

    def _referenced(
        self,
        ref: str,
        symbol: str | None,
        figure: Figure | None,
    ) -> tuple[list[EvidenceRecord], list[float]] | None:
        """The evidence one call, or every call of one tool, produced.

        A ``ref`` naming a call id or a tool name is the tightest scoping, and the
        only one that can ground a non-price figure (revenue, IC, volume). Records
        of another symbol are dropped when the figure's symbol is known; a
        currency-marked figure keeps only money-denominated records, a percent
        only the others, less metadata counts.

        Args:
            ref: The declaration's ``ref``.
            symbol: The figure's resolved symbol, or None.
            figure: The figure whose shape narrows the kind, or None for the
                operands of a derivation.

        Returns:
            ``(records, metric values)``, or None when ``ref`` names no call or tool.
        """
        key = (ref or "").strip()
        if not key:
            return None
        records = [
            record
            for record in self._evidence
            if key in (record.call_id, record.tool)
            and record.status == "observed"
            and record.value is not None
        ]
        metrics = [
            float(entry["value"])
            for entry in self._analysis_metrics
            if key in (entry.get("call_id"), entry.get("tool"))
            and entry.get("value") is not None
        ]
        if not records and not metrics:
            return None
        if symbol:
            records = [
                record for record in records if not record.symbol or record.symbol == symbol
            ]
        if figure is not None and figure.column:
            # A table cell quotes its own column, not whatever else the call returned.
            records = [record for record in records if record.field == figure.column]
            metrics = []
        if figure is not None and figure.percent:
            records = [
                record
                for record in records
                if not _is_price_kind(record) and not _is_metadata_count_leaf(record.field)
            ]
        elif figure is not None and figure.currency:
            records = [record for record in records if _is_price_kind(record)]
            metrics = []
        return records, metrics

    def _price_pool(
        self,
        symbol: str | None,
        records: Sequence[EvidenceRecord],
        *,
        column: str | None = None,
        date: str | None = None,
    ) -> list[float]:
        """Observed price values a figure may be compared against."""
        return [
            float(record.value)
            for record in self._price_candidates(symbol, records, column=column, date=date)
        ]

    def _price_candidates(
        self,
        symbol: str | None,
        records: Sequence[EvidenceRecord],
        *,
        column: str | None = None,
        date: str | None = None,
    ) -> list[EvidenceRecord]:
        """Observed price records a figure may be compared against.

        Filtered by symbol, then by OHLC field and trade date when the figure sits
        under those table headers (spec §4).
        """
        candidates = list(records)
        if symbol:
            candidates = [record for record in candidates if record.symbol == symbol]
        elif len({record.symbol for record in records if record.symbol}) > 1:
            # Two instruments and no resolved symbol: an indicator reading is
            # symbol-bound, so it cannot ground a figure attributed to neither.
            candidates = [record for record in candidates if record.field != "indicator"]
        if column:
            candidates = [record for record in candidates if record.field == column]
        if date:
            candidates = [
                record
                for record in candidates
                if record.timestamp
                and _timestamp_matches_claim_date(record.timestamp, date)
            ]
        return [record for record in candidates if record.value is not None]

    def _row_pool(self, symbol: str | None, *, money_only: bool = False) -> list[float]:
        """Numbers a market-data row carried (volume, amount, turnover, …).

        Only ``get_market_data`` and run-dir CSV rows count, so a generic tool's
        numeric leaves never widen the check. ``money_only`` keeps the
        money-denominated fields a currency-marked figure may quote.
        """
        return [
            float(record.value)
            for record in self._evidence
            if record.status == "observed"
            and record.value is not None
            and record.tool in {"get_market_data", "bash"}
            and (not symbol or record.symbol == symbol)
            and (not money_only or _is_price_kind(record))
        ]

    # Tools with a registered, citable count leaf (spec: position_count). Kept
    # per-tool rather than opening every tool's raw counts to citation.
    _COUNT_EVIDENCE_TOOLS = frozenset({"asistente_casa_portfolio_risk_xray"})

    def _tool_count_pool(self, symbol: str | None) -> list[float]:
        """Metadata-count leaves from tools with a registered count evidence path.

        Mirrors :meth:`_row_pool`'s per-tool allowlist pattern: only a leaf that
        already reads as a sample-size/count field (:func:`_is_metadata_count_leaf`)
        from a tool in ``_COUNT_EVIDENCE_TOOLS`` counts, so a generic tool's counts
        still cannot ground a claim.
        """
        return [
            float(record.value)
            for record in self._evidence
            if record.status == "observed"
            and record.value is not None
            and record.tool in self._COUNT_EVIDENCE_TOOLS
            and _is_metadata_count_leaf(record.field)
            and (not symbol or not record.symbol or record.symbol == symbol)
        ]

    @staticmethod
    def _nearest_prints(
        figure: Figure,
        scope: Sequence[EvidenceRecord],
        fallback: Sequence[float],
    ) -> list[float]:
        """The observed values a rejected figure is pointed at (#1433).

        A non-percent figure is pointed at its own table column, else at the
        closes (then last or adjusted prices) in scope, never at every field of
        every bar; a percent at the values it was compared with.

        Args:
            figure: The rejected figure.
            scope: The evidence records its check was scoped to.
            fallback: The values its check compared it against.

        Returns:
            Up to three observed values, closest first.
        """
        if not figure.percent:
            for name in (figure.column,) if figure.column else _CITABLE_FIELDS:
                values = [
                    float(record.value)
                    for record in scope
                    if record.value is not None
                    and (_price_field_for_path(record.field) or record.field) == name
                ]
                if values:
                    return _nearest(figure.value, values)
        return _nearest(figure.value, fallback)

    def _count_as_observed(
        self,
        figure: Figure,
        declaration: Declaration,
        symbol: str | None,
        records: Sequence[EvidenceRecord],
        market_price: bool = False,
        *,
        why: str = "a count cannot carry a currency mark",
    ) -> list[dict[str, Any]]:
        """Check a ``count`` that looks like a price as the observation it claims to be."""
        found = self._check_observed(figure, declaration, symbol, records, market_price)
        for issue in found:
            issue["role"] = "count"
            issue["message"] = (
                f"{figure.text} is declared count, but {why}, so it was checked as "
                "observed: " + issue["message"][len(figure.text) + 1 :]
            )
        return found

    def _price_band(
        self, symbol: str | None, records: Sequence[EvidenceRecord]
    ) -> tuple[float, float] | None:
        """The observed price range of a figure's instrument, or None when unknown."""
        if symbol is None and len({record.symbol for record in records if record.symbol}) > 1:
            return None
        prices = [value for value in self._price_pool(symbol, records) if value > 0]
        return (min(prices), max(prices)) if prices else None

    @staticmethod
    def _poses_as_price(figure: Figure, band: tuple[float, float] | None) -> bool:
        """Whether an unmarked number sits where its instrument's price does.

        A decimal inside the observed range (±10%) reads as a quote. An integer
        does only for an instrument quoted in the thousands, between half and
        twice its range. A percent is never a price.

        Args:
            figure: The figure.
            band: The instrument's observed ``(low, high)``, or None.

        Returns:
            True when the number should be checked as a price.
        """
        if band is None or figure.percent:
            return False
        low, high = band
        value = abs(figure.value)
        if "." in (figure.digits or figure.text):
            return low * 0.9 <= value <= high * 1.1
        return low >= _INTEGER_PRICE_FLOOR and low * 0.5 <= value <= high * 2.0

    def _metric_pool(self, symbol: str | None) -> list[float]:
        """Metric values from completed analysis results and metric-named leaves."""
        values = [
            float(entry["value"])
            for entry in self._analysis_metrics
            if entry.get("value") is not None
        ]
        values.extend(
            float(record.value)
            for record in self._evidence
            if record.status == "observed"
            and record.value is not None
            and _metric_kind_for_path(record.field) is not None
            and (not symbol or not record.symbol or record.symbol == symbol)
        )
        return values

    def _matches_evidence(
        self,
        figure: Figure,
        direct: Sequence[float],
        scaled: Sequence[float],
    ) -> bool:
        """Whether a figure equals evidence, at its own scale or a metric's.

        ``direct`` is compared literally. ``scaled`` absorbs fraction vs percent
        (0.182 vs 18.2%) and the sign of a fall (drawdown -0.094 quoted as 9.4%).
        """
        if _close_any(figure.value, direct):
            return True
        if figure.scale != 1.0 and _close_any(figure.value * figure.scale, direct):
            return True
        candidates = {abs(figure.value), abs(figure.value) / 100.0}
        magnitudes = [abs(target) for target in scaled]
        return any(_close_any(candidate, magnitudes) for candidate in candidates)

    def _check_observed(
        self,
        figure: Figure,
        declaration: Declaration | None,
        symbol: str | None,
        records: Sequence[EvidenceRecord],
        market_price: bool = False,
    ) -> list[dict[str, Any]]:
        """An observed figure must appear in evidence of its own kind.

        A currency-marked figure is answered only by money-denominated values
        and a percent only by the rest; a table cell only by its column's field.

        ``market_price`` (#GGAL-B follow-up) never changes whether the figure
        passes — it only rides along on a resulting issue so
        ``recovery_action`` can tell a genuine missing quote apart from a
        currency-marked fundamental (EPS, net income, revenue, ...) that
        ``get_market_data`` could never answer either way.
        """
        scoped = self._referenced(declaration.ref, symbol, figure) if declaration else None
        if scoped is not None:
            scoped_records, metric_values = scoped
            values = [float(record.value) for record in scoped_records] + metric_values
            money = figure.currency and not figure.percent
            if self._matches_evidence(figure, values, [] if money else values):
                return []
            return [
                self._figure_issue(
                    "numeric_claim_conflict",
                    figure,
                    "observed",
                    symbol,
                    "not_in_referenced_call",
                    f"is declared observed from {declaration.ref}, whose results "
                    f"{'for ' + symbol + ' ' if symbol else ''}do not contain it",
                    source_tool_call_ids=[declaration.ref],
                    observed_nearest=self._nearest_prints(figure, scoped_records, values),
                    market_price=market_price,
                )
            ]
        candidates = self._price_candidates(
            symbol, records, column=figure.column, date=figure.date
        )
        prices = [float(record.value) for record in candidates]
        if figure.percent:
            # A percent is a ratio; no price or volume may answer it.
            direct: list[float] = []
            scaled = [] if figure.column else self._metric_pool(symbol)
        elif figure.column:
            direct, scaled = prices, []
        elif figure.currency:
            direct, scaled = prices + self._row_pool(symbol, money_only=True), []
        else:
            direct = prices + self._row_pool(symbol) + self._tool_count_pool(symbol)
            scaled = self._metric_pool(symbol)
        if not direct and not scaled:
            return [
                self._figure_issue(
                    "numeric_claim_unavailable",
                    figure,
                    "observed",
                    symbol,
                    "no_evidence",
                    "is declared observed but this session holds no matching tool "
                    "evidence to check it against",
                    field=figure.column,
                    date=figure.date,
                    market_price=market_price,
                )
            ]
        if self._matches_evidence(figure, direct, scaled):
            return []
        observed = sorted(direct or scaled)
        attributable = symbol is not None or len(
            {record.symbol for record in records if record.symbol}
        ) <= 1
        return [
            self._figure_issue(
                "numeric_claim_conflict",
                figure,
                "observed",
                symbol,
                "value_mismatch",
                "is declared observed but conflicts with the "
                f"{figure.column or 'observed'} evidence "
                f"{observed[0]:g}–{observed[-1]:g}",
                field=figure.column,
                date=figure.date,
                observed_min=observed[0],
                observed_max=observed[-1],
                observed_nearest=(
                    self._nearest_prints(figure, candidates, observed)
                    if attributable
                    else []
                ),
                market_price=market_price,
            )
        ]

    def _derivation(
        self,
        declaration: Declaration | None,
        symbol: str | None,
        records: Sequence[EvidenceRecord],
        *,
        money: bool = False,
    ) -> tuple[float, list[float]] | str | None:
        """Evaluate a declaration's note as an observation-anchored formula.

        Returns the ``(result, operands)`` pair when the note is arithmetic
        over at least two operands, at least one of which the run observed and
        every added or subtracted term of which holds an observed operand;
        otherwise the reason it is not.
        """
        if declaration is None or not declaration.note.strip():
            return "no_formula"
        evaluated = _formula_in_note(declaration.note)
        if evaluated is None:
            return "formula_not_evaluable"
        result, operands, tree = evaluated
        if not symbol and len({record.symbol for record in records if record.symbol}) > 1:
            # Two instruments' bars and no resolved symbol: any arithmetic would
            # look anchored, with nothing to anchor it to.
            return "no_symbol"
        # A money-marked result is derived from money: an RSI or a volume is not
        # a price to take a discount of.
        anchors = self._price_pool(symbol, records) + self._row_pool(symbol, money_only=money)
        if not money:
            anchors += self._metric_pool(symbol)
        scoped = self._referenced(declaration.ref, symbol, None)
        if scoped is not None:
            anchors.extend(
                float(record.value)
                for record in scoped[0]
                if not money or _is_price_kind(record)
            )
            if not money:
                anchors.extend(scoped[1])
        if not anchors:
            return "no_evidence"

        def observed(operand: float) -> bool:
            return _close_any(operand, anchors)

        if not any(observed(operand) for operand in operands):
            return "formula_not_anchored"
        if _unanchored_term(tree, observed):
            return "additive_operand_not_observed"
        return result, operands

    @staticmethod
    def _result_matches(figure: Figure, result: float) -> bool:
        """Whether a formula's result is the value the prose figure states.

        The band is half a unit of the last digit the PROSE was written with
        ("约 37%" for 36.75%), so a coarser declaration cannot widen it. A "%"
        figure is compared only in percentage points, since against the fraction
        a half-unit band spans fifty points; a bare figure is tried both ways.
        Magnitudes are compared, because a fall is noted either as
        ``(low − high) / high`` or as the drop, unless the prose wrote a sign.
        """
        # The normalized reading, so "0,666" is three decimals and "−5,13%" is signed.
        half_unit = _written_half_unit(figure.digits or figure.text)
        targets = {result * 100.0} if figure.percent else {result, result * 100.0}
        sign = _explicit_sign(figure.sign or figure.text)
        value = abs(figure.value)
        return any(
            abs(value - abs(target)) <= max(abs(target) * _TOLERANCE, half_unit, 1e-9)
            for target in targets
            if not sign or target * sign >= 0
        )

    def _check_derived(
        self,
        figure: Figure,
        declaration: Declaration | None,
        symbol: str | None,
        records: Sequence[EvidenceRecord],
    ) -> list[dict[str, Any]]:
        """A derived figure must be the arithmetic its note states."""
        derivation = self._derivation(declaration, symbol, records, money=figure.currency)
        if isinstance(derivation, str):
            return [
                self._figure_issue(
                    "numeric_claim_conflict"
                    if derivation != "no_evidence"
                    else "numeric_claim_unavailable",
                    figure,
                    "derived",
                    symbol,
                    derivation,
                    "is declared derived, but its note adds or subtracts an operand "
                    "this session did not observe"
                    if derivation == "additive_operand_not_observed"
                    else "is declared derived, but its note is not arithmetic over at "
                    "least two operands with one of them observed in this session",
                )
            ]
        result, _ = derivation
        if self._result_matches(figure, result):
            return []
        # Reported in the figure's own units, as ``_result_matches`` compares it.
        scaled = result * 100.0 if figure.percent else result
        shown = f"{scaled:.6g}%" if figure.percent else f"{scaled:.6g}"
        return [
            self._figure_issue(
                "numeric_claim_conflict",
                figure,
                "derived",
                symbol,
                "derivation_result_mismatch",
                f"is declared derived, but its own formula evaluates to {shown}",
                derived_result=shown,
            )
        ]

    def _check_proposed(
        self,
        figure: Figure,
        declaration: Declaration | None,
        symbol: str | None,
        records: Sequence[EvidenceRecord],
    ) -> list[dict[str, Any]]:
        """A proposed level (entry, target, stop) is derived or inside the observed range.

        It cannot be required to equal a print, only to be anchored; a level far
        outside what the session saw is the invention this gate exists to stop.
        A level is a price, so a percent is never one, and a level attributed to
        no instrument of several has no range to lie in.
        """
        if figure.percent:
            return [
                self._figure_issue(
                    "numeric_claim_conflict",
                    figure,
                    "proposed",
                    symbol,
                    "proposed_not_a_price",
                    "is declared proposed, but a proposed level is a price and a percent "
                    "is not one; declare it derived with its arithmetic, or cited",
                )
            ]
        if not symbol and len({record.symbol for record in records if record.symbol}) > 1:
            return [
                self._figure_issue(
                    "numeric_claim_conflict",
                    figure,
                    "proposed",
                    symbol,
                    "no_symbol",
                    "is a proposed level, but the run holds prices for more than one "
                    "instrument and nothing attributes it to one",
                )
            ]
        derivation = self._derivation(declaration, symbol, records, money=figure.currency)
        if not isinstance(derivation, str) and self._result_matches(figure, derivation[0]):
            return []
        candidates = self._price_candidates(symbol, records)
        prices = [float(record.value) for record in candidates]
        if not prices:
            return [
                self._figure_issue(
                    "numeric_claim_unavailable",
                    figure,
                    "proposed",
                    symbol,
                    "no_evidence",
                    "is a proposed level but this session observed no price for "
                    "the instrument to anchor it to",
                )
            ]
        if min(prices) <= figure.value <= max(prices):
            return []
        return [
            self._figure_issue(
                "numeric_claim_conflict",
                figure,
                "proposed",
                symbol,
                "outside_observed_range",
                "is a proposed level outside the observed range "
                f"{min(prices):g}–{max(prices):g} and its note derives no value",
                observed_min=min(prices),
                observed_max=max(prices),
                observed_nearest=self._nearest_prints(figure, candidates, prices),
            )
        ]

    def _check_cited(
        self,
        figure: Figure,
        declaration: Declaration,
        symbol: str | None,
        declared_observed: set[float],
        line: str,
    ) -> list[dict[str, Any]]:
        """A cited figure names a source the reader can see and does not pose as a print.

        Its value is unchecked, so the citation may not launder an observation
        (the value may not also be declared observed). The block is stripped
        before release, so a source only the note names is no citation: a note
        token (``_note_tokens``) must appear on the figure's own line.
        """
        if not declaration.note.strip():
            return [
                self._figure_issue(
                    "numeric_claim_conflict",
                    figure,
                    "cited",
                    symbol,
                    "citation_without_source",
                    "is declared cited but names no source in its note",
                )
            ]
        if any(_close(figure.value, value) for value in declared_observed):
            return [
                self._figure_issue(
                    "numeric_claim_conflict",
                    figure,
                    "cited",
                    symbol,
                    "cited_as_observed",
                    "is declared cited yet presented as an observed value of this "
                    "instrument",
                )
            ]
        folded = line.casefold()
        if not any(token in folded for token in _note_tokens(declaration.note)):
            return [
                self._figure_issue(
                    "numeric_claim_conflict",
                    figure,
                    "cited",
                    symbol,
                    "citation_not_visible",
                    "is declared cited, but no source its note names appears on its "
                    "line, and the note is stripped before anyone reads the answer",
                )
            ]
        return []

    def _validate_unsourced_symbols(
        self,
        content: str,
        figures: Sequence[Figure],
        block: FiguresBlock,
    ) -> list[dict[str, Any]]:
        """Reject figures attached to an instrument no tool in this run handled.

        Naming a symbol is fine, but a line pairing an unhandled canonical symbol
        with a measured figure has no origin other than model memory (#886/#887).
        A figure declared ``cited`` is exempt, since a citation is an origin.
        """
        issues: list[dict[str, Any]] = []
        reported: set[str] = set()
        for index, (line, offset) in enumerate(_lines_with_offsets(content)):
            unknown = sorted(
                symbol
                for symbol in _scan_symbols(line)
                - self._session_symbols
                - reported
                if symbol.rsplit(".", 1)[0] not in self._session_symbol_roots
            )
            if not unknown:
                continue
            carried = [
                figure
                for figure in figures
                if figure.line == index and figure.shape == "measured"
            ]
            if not carried:
                continue
            if all(
                (block.match(figure.value, figure.percent) or _NO_DECLARATION).role
                == "cited"
                for figure in carried
            ):
                continue
            # #GGAL-B follow-up: positive aggregate over every figure this
            # line carries — ``market_price`` is True only when AT LEAST ONE
            # of them is genuinely about a quote (OHLC column, or price/
            # target/support/resistance context in its clause or note), not
            # merely currency-marked. A line of pure fundamentals (EPS,
            # net income, revenue, ...) attached to an unhandled peer stays
            # ineligible for ``get_market_data`` recovery.
            line_percent = all(figure.percent for figure in carried)
            line_currency = any(figure.currency for figure in carried)
            line_market_price = any(
                self._figure_is_market_price(
                    content, figure, block.match(figure.value, figure.percent)
                )
                for figure in carried
            )
            for symbol in unknown:
                reported.add(symbol)
                issues.append(
                    {
                        "code": "unsourced_symbol_figures",
                        "symbol": symbol,
                        "value": None,
                        "role": None,
                        "reason": "symbol_never_handled",
                        "claim": line.strip()[:200],
                        "span": [offset, offset + len(line)],
                        "percent": line_percent,
                        "currency": line_currency,
                        "market_price": line_market_price,
                        "message": (
                            f"No tool call in this session passed in or returned {symbol}, "
                            "yet the answer attaches figures to it. Retrieve it, or report "
                            "it as not retrieved."
                        ),
                    }
                )
        return issues

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
                    "value": None,
                    "role": None,
                    "span": None,
                    "symbol": None,
                    "reason": "symbol_not_surfaced",
                    "message": (
                        "A price claim must surface its locked canonical symbol and "
                        "venue suffix."
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
                for alias in _SOURCE_ALIASES.get(source.casefold(), (source.casefold(),))
            )
        ]
        if missing_sources:
            issues.append(
                {
                    "code": "data_source_not_surfaced",
                    "sources": missing_sources,
                    "value": None,
                    "role": None,
                    "span": None,
                    "symbol": None,
                    "reason": "source_not_surfaced",
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
                    "value": None,
                    "role": None,
                    "span": None,
                    "symbol": None,
                    "reason": "currency_not_surfaced",
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
        if code != "CNY":
            return False
        return any(
            char == "元"
            and (index == 0 or content[index - 1] not in _OTHER_CURRENCY_PREFIXES)
            for index, char in enumerate(content)
        )

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


#: The role an undeclared figure is validated under (spec §4, undeclared mode).
_NO_DECLARATION = Declaration(
    index=0, value_text="", value=0.0, percent=False, role="observed", note="", ref=""
)
