"""Per-role validation: what each declared figure has to survive.

The model declares what each measurement-shaped number IS (spec §2); this
module checks that declaration against ledger evidence (spec §4). It reads no
prose word: roles come from the model, shape from :mod:`figures`.
"""

from __future__ import annotations

import ast
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.agent.grounding.identity import (
    _CANONICAL_SYMBOL_RE,
    _normalize_symbol,
    _scan_symbols,
)
from src.agent.grounding import identity_checks  # noqa: F401  (registers declared checks)
from src.agent.grounding.registry import GROUNDING_CHECKS
from src.agent.grounding.evidence import (
    EvidenceRecord,
    _is_metadata_count_leaf,
    _is_number,
    _is_price_kind,
    _metric_kind_for_path,
    _price_field_for_path,
    _timestamp_matches_claim_date,
    tail_risk_identity,
)
from src.agent.grounding.figures import (
    ROUNDED_BAND,
    Declaration,
    Figure,
    FiguresBlock,
    _lines_with_offsets,
    segment_bounds,
)

import re

# ``a.0.b`` and ``a[0].b`` name the same list element; evidence paths are
# emitted with brackets, so refs are compared in that spelling.
_DOTTED_INDEX_RE = re.compile(r"(?<=\w)\.(\d+)(?=\.|\[|$)")
_INDEX_RE = re.compile(r"\[\d+\]")
_MAX_INDEXED_REF_CANDIDATES = 12
#: A container ref is answered only with leaves that hold the figure's value, so
#: a handful is enough; calls returning one field are capped the same way.
_MAX_CONTAINER_REF_CANDIDATES = 5
_MAX_CALL_REF_CANDIDATES = 5


def _index_normalized(path: str) -> str:
    """Spell dotted collection indices with brackets (``a.0.b`` -> ``a[0].b``)."""
    return _DOTTED_INDEX_RE.sub(r"[\1]", path)

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
    "GBP": ("gbp", "£", "英镑"),
    "VND": ("vnd", "₫", "越南盾"),
    "ARS": ("ars", "ar$", "阿根廷比索"),
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

    ``passed_figures`` names the measured figures the gate checked and let
    through, as written, so the correction prompt can tell the model what to
    keep, not only what to fix.
    """

    valid: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    released_text: str = ""
    passed_figures: tuple[str, ...] = ()


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

    exponents = {
        id(item.right)
        for item in ast.walk(tree)
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Pow)
    }

    def anchored(node: ast.AST) -> bool:
        return any(
            observed(float(item.value))
            for item in ast.walk(node)
            if isinstance(item, ast.Constant)
            and _is_number(item.value)
            and id(item) not in exponents
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
        .replace("²", "**2")
        .replace("³", "**3")
        .replace("^", "**")
        .strip()
    )
    # "12.87% − 11.36%" is 0.1287 − 0.1136: an operand written as a percent is
    # the fraction the evidence holds, and "0.666 × (1 − 3%)" means 0.97.
    normalized = _PERCENT_OPERAND_RE.sub(
        lambda match: format(float(match.group(1)) / 100.0, ".12g"), normalized
    ).replace("%", "").replace("％", "")
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
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            # A square or a cube (HHI is a sum of squared weights). The
            # exponent is part of the operator, not an operand.
            if not _is_small_exponent(node.right):
                raise ValueError("unsupported exponent")
            return visit(node.left) ** int(node.right.value)
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


#: A number written with a percent sign inside a formula.
_PERCENT_OPERAND_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]")


def _is_small_exponent(node: ast.AST) -> bool:
    """Whether a power's exponent is a literal 2 or 3."""
    return isinstance(node, ast.Constant) and node.value in (2, 3) and not isinstance(node.value, bool)


#: A bracketed aside holding a word: "（收益差，约−1.17pp）", "(portfolio)".
_ANNOTATION_RE = re.compile(r"[（(\[][^（）()\[\]]*?(?:[\u3400-\u9fff]|[A-Za-z]{2})[^（）()\[\]]*[）)\]]")

#: A label or unit written against a number: a CJK run, or an ASCII word of
#: two letters or more ("Sharpe", "RP", "pp"). One letter is kept, so "1e3"
#: stays a number and "5 x 3" stays unreadable rather than becoming "5 3".
_LABEL_RE = re.compile(r"[\u3400-\u9fff]+|[A-Za-z]{2,}")


def _without_labels(text: str) -> str:
    """A note with its words removed, so the arithmetic between them can be read.

    "等权Sharpe 0.692 − 风险平价 0.651" is the arithmetic "0.692 − 0.651";
    an aside in brackets goes whole, because the number inside it
    ("约−1.17pp") is a restatement of the result, not an operand. Nothing is
    read from the words themselves.
    """
    return _LABEL_RE.sub(" ", _ANNOTATION_RE.sub(" ", text))


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
    for separator in ("，", "；", "：", ":", "; ", ", "):
        parts = [piece for part in parts for piece in part.split(separator)]
    candidates.extend(part for part in parts if part.strip())
    # Only once the note as written fails: its words removed, whole and in parts.
    unlabelled = _without_labels(note)
    for separator in ("≈", "≒", "＝", "=", "→", "->", "，", "；", "：", ":", "; ", ", "):
        unlabelled = " \n ".join(unlabelled.split(separator))
    candidates.extend(part for part in unlabelled.split(" \n ") if part.strip())
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
        issues.extend(GROUNDING_CHECKS.run("listed-identity-relabelled-private", self, content))
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
        # Symbol resolution is broader than price comparison. A session may hold
        # quotes for the primary listing and only non-price evidence for another
        # explicitly named instrument (for example issuer fundamentals). If claim
        # identity only sees price-comparable records, that second symbol becomes
        # invisible and its referenced evidence is later filtered under the
        # primary symbol. Keep numeric matching fail-closed, but let any observed
        # numeric evidence contribute its explicit symbol to claim resolution.
        symbol_records = [
            record
            for record in self._evidence
            if record.status == "observed"
            and record.value is not None
            and record.symbol
        ]
        # Preserve the existing price-derived document fallback. A report may
        # mention a secondary instrument only for fundamentals; that should make
        # explicit claims about the secondary resolvable without making otherwise
        # unattributed primary-listing figures ambiguous.
        document_symbol = self._symbol_for_claim(content, records)
        positions = _lines_with_offsets(content)
        line_symbols = [
            self._symbol_for_claim(line, symbol_records) for line, _ in positions
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
            declaration = block.match(figure.value, figure.percent, figure.digits)
            symbol = self._figure_symbol(
                content,
                figure,
                declaration,
                line_symbols,
                document_symbol,
                symbol_records,
            )
            if figure.shape == "bare" and not self._poses_as_price(
                figure, self._price_band(symbol, records)
            ):
                continue
            if declaration is not None:
                written = self._written_symbol(
                    content, figure, line_symbols, symbol_records
                )
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
                found = self._check_observed(figure, None, symbol, records)
                if block.present and found:
                    # Declared, but as a fraction where the answer writes a
                    # percent (or the reverse): still undeclared, since the
                    # two are different assertions — but say so, or the model
                    # reads "not declared" as a lie and repeats the draft.
                    other_unit = _declared_in_other_unit(block, figure)
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
                            **(
                                {
                                    "declared_as": other_unit.value_text,
                                    "declared_sign_differs": (other_unit.value < 0) != (figure.value < 0),
                                }
                                if other_unit
                                else {}
                            ),
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
            issues.extend(self._check_observed(figure, declaration, symbol, records))
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
        """Build one figure-scoped issue with value, role, span, symbol and reason."""
        issue = {
            "code": code,
            "value": figure.text,
            "role": role,
            "span": [figure.start, figure.end],
            "symbol": symbol,
            "reason": reason,
            "claim": figure.text,
            "message": f"{figure.text} {message}.",
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
            # "000001.SZ 平安银行": the cell names its instrument beside a name.
            written = _scan_symbols(figure.symbol)
            if len(written) == 1:
                return next(iter(written))
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

    def _referenced(
        self,
        ref: str,
        symbol: str | None,
        figure: Figure | None,
        *,
        pool_ambiguous: bool = False,
    ) -> tuple[list[EvidenceRecord], list[float]] | None:
        """The evidence named by an exact field, call+field, one call, or one tool.

        An exact evidence-field ref is accepted only when that field occurs in
        one call. When it repeats across calls, ``call_id::field`` is the
        unambiguous tightest scope. Otherwise a ``ref`` naming a call id or a
        tool name keeps the existing call/tool scope, and the only one that can
        ground a non-price figure (revenue, IC, volume). A backtest's output is
        also named by its run directory or file (:meth:`_artifact_scope`).
        Records of another symbol are dropped when the figure's symbol is
        known; a currency-marked figure keeps only money-denominated records, a
        percent only the others, less metadata counts.

        Args:
            ref: The declaration's ``ref``.
            symbol: The figure's resolved symbol, or None.
            figure: The figure whose shape narrows the kind, or None for the
                operands of a derivation.
            pool_ambiguous: Pool a field ref's sources even when they disagree.
                Only a derivation's anchors ask for it: an operand from either
                run is still an observation.

        Returns:
            ``(records, metric values)``, or None when ``ref`` names no field,
            call, tool, or backtest output.
        """
        key = (ref or "").strip()
        if not key:
            return None

        # A composite ref names one exact field from one exact call, or from
        # one backtest's output (``rp::sharpe``). This is the unambiguous form
        # when the same analysis field appears in more than one tool call.
        if "::" in key:
            call_id, field = (part.strip() for part in key.split("::", 1))
            if not call_id or not field:
                return [], []
            records, entries = self._field_sources(field, symbol)
            by_call = [record for record in records if record.call_id == call_id]
            metrics = [float(entry["value"]) for entry in entries if entry.get("call_id") == call_id]
            # Not a call: ``rp::sharpe`` names a field of one backtest's output,
            # ``rp::target_positions.csv`` or ``backtest::rp`` the output itself.
            records = by_call if by_call or metrics else self._artifact_scope(key) or []
        else:
            records, entries = self._field_sources(key, symbol)
            artifact_scope = None if records or entries else self._artifact_scope(key)
            if records or entries:
                if not pool_ambiguous and self._ambiguous_field_sources(key, symbol):
                    # Calls disagree on this field, so the ref cannot say
                    # which value it quotes (VaR at 95% vs 99%). Fail closed
                    # rather than pool them; the issue names the calls.
                    return [], []
                metrics = [float(entry["value"]) for entry in entries]
            elif artifact_scope is not None:
                # A backtest's run directory or one of its files: everything
                # that backtest observed there, and nothing another run did.
                records, metrics = artifact_scope, []
            else:
                records = [
                    record
                    for record in self._evidence
                    if key in (record.call_id, record.tool)
                    and record.status == "observed"
                    and record.value is not None
                ]
                metrics = [
                    float(entry["value"])
                    for entry in self._analysis_entries(symbol)
                    if key in (entry.get("call_id"), entry.get("tool"))
                    and entry.get("value") is not None
                ]
                if not records and not metrics:
                    # Preserve the legacy loose-ref contract: a ref such as a
                    # symbol that names no field/call/tool falls back to the
                    # ordinary evidence path. Ambiguous or composite field
                    # refs return earlier as an explicit empty scope instead.
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

    def _analysis_entries(self, symbol: str | None) -> list[dict[str, Any]]:
        """Scope metrics by explicit observed symbols recorded on their call.

        Symbol-less aggregate calls remain eligible. A multi-symbol call cannot
        attribute its otherwise unlabelled metric to one particular instrument.
        Symbol-labelled EvidenceRecords remain available through their own path.
        """
        if not symbol:
            return list(self._analysis_metrics)
        call_symbols: dict[str, set[str]] = {}
        for record in self._evidence:
            if record.symbol and record.status == "observed":
                call_symbols.setdefault(record.call_id, set()).add(record.symbol)
        return [
            entry for entry in self._analysis_metrics
            if not call_symbols.get(entry.get("call_id"))
            or call_symbols[entry.get("call_id")] == {symbol}
        ]

    def _field_sources(
        self, field: str, symbol: str | None
    ) -> tuple[list[EvidenceRecord], list[dict[str, Any]]]:
        """Observed values of the evidence field ``field`` names, for ``symbol``.

        ``field`` is a full path (``data.tail_risk.var_95``) or its trailing
        part (``var_95``, ``tail_risk.var_95``): a short ref used to fall
        through to the whole evidence pool, where a VaR 99% claim quoting the
        95% value found its match (#1444 review). Another symbol's records are
        dropped here, before any count of calls, so two instruments' closes do
        not make ``close`` ambiguous.
        """
        wanted = _index_normalized(field)

        def named(path: Any) -> bool:
            if not isinstance(path, str):
                return False
            path = _index_normalized(path)
            return path == wanted or path.endswith("." + wanted)

        records = [
            record
            for record in self._evidence
            if named(record.field)
            and record.status == "observed"
            and record.value is not None
            and (not symbol or not record.symbol or record.symbol == symbol)
        ]
        entries = [
            entry
            for entry in self._analysis_entries(symbol)
            if named(entry.get("field")) and entry.get("value") is not None
        ]
        return records, entries

    def _ambiguous_field_sources(self, field: str, symbol: str | None) -> list[str]:
        """The ``call::path`` sources a field-only ref cannot choose between.

        Ambiguous means more than one source AND more than one value among
        them: two runs of one call returning the same number leave nothing to
        choose. A source is a call and its full path, except that one backtest
        is one source (:meth:`_ref_source`). Each is written as the ref that
        names it.

        Returns:
            Sorted refs, or an empty list when the ref is exact.
        """
        if not field or "::" in field:
            return []
        records, entries = self._field_sources(field, symbol)
        sources = {
            (*self._ref_source(record.call_id, record.field, record.scope), float(record.value))
            for record in records
        }
        sources |= {
            (
                *self._ref_source(str(entry.get("call_id")), str(entry.get("field")), None),
                float(entry["value"]),
            )
            for entry in entries
        }
        if len({identity for identity, *_ in sources}) < 2 or len({value for *_, value in sources}) < 2:
            return []
        return sorted({label for _, label, _ in sources})

    def _ref_source(
        self, call_id: str, field: str, scope: str | None
    ) -> tuple[tuple[str, str], str]:
        """Which source one evidence value belongs to, and the ref that names it.

        One backtest is one observation: its run card, metrics file and risk
        X-ray each hold a ``max_drawdown``, and a ref matching several of them
        still names that one run. Two backtests are two sources, and so is one
        directory run twice (the earlier call keeps its own identity). A
        backtest's value is named through its run directory (``rp::sharpe``),
        which the model chose; anything else by call id and full path.

        Args:
            call_id: The call that returned the value.
            field: Its full evidence path.
            scope: The backtest run directory of a backtest output record.

        Returns:
            ``(identity, ref label)``.
        """
        if scope is None:
            owner = self._backtest_scopes.get(call_id)
            if owner is not None and self._scope_latest.get(owner) == call_id:
                scope = owner
        if scope is None:
            return (call_id, field), f"{call_id}::{field}"
        return ("scope", scope), f"{scope}::{field}" if scope else f"{call_id}::{field}"

    def _artifact_scope(self, key: str) -> list[EvidenceRecord] | None:
        """The backtest output a ref names by run directory or file, or None.

        Backtest output is named the way the model named the run: its run
        directory, which the model chose (``rp``, ``risk_parity``), as a path
        (``rp/artifacts/metrics.csv``, ``rp/metrics.csv``) or beside a file
        and a field (``risk_parity target_positions.csv``,
        ``backtest::rp``). The run directory is what makes the ref exact —
        two backtests hold two different Sharpes — so a ref naming several
        runs pools them, and a ref naming only a file pools that file across
        runs, like a ref naming the tool. A file or field the ref also names
        narrows the set when the run holds it and is ignored otherwise.

        Args:
            key: The declaration's ref, or one half of ``scope::field``.

        Returns:
            The observed backtest records the ref names, or None when it names
            no backtest run directory and no file one wrote.
        """
        owned = [
            record
            for record in self._evidence
            if record.artifact is not None
            and record.status == "observed"
            and record.value is not None
        ]
        if not owned:
            return None
        root = self.run_dir.resolve()
        chosen: dict[int, EvidenceRecord] = {}
        by_tool: dict[int, EvidenceRecord] = {}
        files: set[str] = set()
        fields: list[str] = []
        for token in _REF_TOKEN_RE.split(key):
            token = token.strip("`'\"")
            if not token:
                continue
            hits = _records_at(token, owned, root)
            if hits:
                chosen.update((id(record), record) for record in hits)
            elif token != key.strip() and any(record.tool == token for record in owned):
                # "backtest 两个运行": the tool name beside words. Beside a run
                # directory ("backtest::rp") it only says what the run is; a
                # ref that is the tool name alone keeps the tool scope in
                # ``_referenced``.
                by_tool.update((id(record), record) for record in owned if record.tool == token)
            elif "/" not in token and any(
                _file_stem(token) == _file_stem(record.artifact) for record in owned
            ):
                # A bare file name ("target_positions.csv"). A path that holds
                # none of this session's records names nothing: the active
                # run's copy may be another backtest's by now.
                files.add(_file_stem(token))
            else:
                fields.append(token)
        chosen = chosen or by_tool
        if not chosen and not files:
            return None
        selected = list(chosen.values()) or owned
        by_file = [record for record in selected if _file_stem(record.artifact) in files]
        selected = by_file or selected
        for token in fields:
            by_field = [
                record
                for record in selected
                if record.field == token or record.field.endswith("." + token)
            ]
            selected = by_field or selected
        return selected or None

    def _tail_risk_sources(
        self,
        records: Sequence[EvidenceRecord],
        entries: Iterable[Mapping[str, Any]] = (),
    ) -> list[tuple[str, float]]:
        """``(identity, value)`` for every tail-risk value among these sources.

        Identity is read off the field name (:func:`tail_risk_identity`), so
        ``var_95`` and ``es_95`` are two identities and ``cvar_99`` / ``es_99``
        are one.
        """
        sources: list[tuple[str, float]] = []
        for record in records:
            identity = tail_risk_identity(record.field)
            if identity and record.status == "observed" and record.value is not None:
                sources.append((identity, float(record.value)))
        for entry in entries:
            identity = tail_risk_identity(str(entry.get("field") or ""))
            if identity and entry.get("value") is not None:
                sources.append((identity, float(entry["value"])))
        return sources

    def _tail_risk_field_refs(
        self,
        records: Sequence[EvidenceRecord],
        entries: Iterable[Mapping[str, Any]] = (),
    ) -> list[str]:
        """Exact ``call_id::field`` (or ``run_dir::field``) refs for tail-risk evidence."""
        refs = {
            self._ref_source(record.call_id, record.field, record.scope)[1]
            for record in records
            if record.call_id
            and record.field
            and record.status == "observed"
            and record.value is not None
            and tail_risk_identity(record.field)
        }
        refs |= {
            self._ref_source(str(entry.get("call_id")), str(entry.get("field")), None)[1]
            for entry in entries
            if entry.get("call_id")
            and entry.get("field")
            and entry.get("value") is not None
            and tail_risk_identity(str(entry.get("field") or ""))
        }
        return sorted(refs)

    def _tool_field_ref_candidates(
        self, ref: str, symbol: str | None, figure: Figure | None = None
    ) -> list[str]:
        """Exact call refs for a mistaken tool_name::field declaration.

        With ``figure``, refs whose observed value matches it come first, most
        recent call first among equals; the list is capped. The hint never
        selects a call: the next draft must still declare the exact ref.
        """
        key = (ref or "").strip()
        if "::" not in key:
            return []
        scope, field = (part.strip() for part in key.split("::", 1))
        if not scope or not field:
            return []
        records, entries = self._field_sources(field, symbol)
        found: dict[str, list[float]] = {}
        for record in records:
            if record.tool == scope and record.call_id and record.field:
                found.setdefault(self._ref_source(record.call_id, record.field, record.scope)[1], []).append(
                    float(record.value)
                )
        for entry in entries:
            if entry.get("tool") == scope and entry.get("call_id") and entry.get("field"):
                found.setdefault(self._ref_source(str(entry.get("call_id")), str(entry.get("field")), None)[1], []).append(
                    float(entry["value"])
                )
        if figure is None:
            return sorted(found)
        recency = {item: index for index, item in enumerate(found)}
        ranked = sorted(
            found,
            key=lambda item: (
                not self._matches_evidence(figure, found[item], found[item]),
                -recency[item],
                item,
            ),
        )
        return ranked[:_MAX_CALL_REF_CANDIDATES]

    def _indexed_field_ref_candidates(
        self, ref: str, figure: Figure, symbol: str | None = None
    ) -> list[str]:
        """Exact ``call_id::path[i]`` refs for a ``call::field`` ref that selected no value.

        Two shapes of an unresolved ref are helped, both only from the call (or
        tool) the ref names:

        * the ref names a list field without its index: paths that equal the
          declared field once every collection index is dropped are offered;
        * the ref names a container (``data.groups.positive``): its numeric
          descendants that hold the figure's value are offered, and none
          otherwise. An index written in the ref narrows the container to that
          element.

        Refs whose value matches the figure come first. These are hints for the
        next draft; a ref is never resolved through them and a container ref
        authorizes nothing.
        """
        found: dict[str, float] = {}
        containers: set[str] = set()
        for key in (part.strip() for part in re.split(r"[;,]", ref or "")):
            if "::" not in key:
                continue
            scope, field = (part.strip() for part in key.split("::", 1))
            if not scope or not field:
                continue
            wanted = _index_normalized(field)
            bare = _INDEX_RE.sub("", wanted)
            below = re.compile(r"(?:^|\.)" + re.escape(wanted) + r"(?=[.\[])")
            for call_id, tool, path, value, record in (
                *(
                    (r.call_id, r.tool, r.field, r.value, r)
                    for r in self._evidence
                    if r.status == "observed"
                ),
                *(
                    (e.get("call_id"), e.get("tool"), e.get("field"), e.get("value"), None)
                    for e in self._analysis_metrics
                ),
            ):
                if not (
                    call_id
                    and isinstance(path, str)
                    and value is not None
                    and scope in (call_id, tool)
                ):
                    continue
                if record is not None:
                    if symbol and record.symbol and record.symbol != symbol:
                        continue
                    if not self._kind_fits(record, figure):
                        continue
                item = f"{call_id}::{path}"
                if below.search(_index_normalized(path)):
                    containers.add(item)
                    found[item] = float(value)
                elif _INDEX_RE.search(path) and not _INDEX_RE.search(wanted):
                    stripped = _INDEX_RE.sub("", path)
                    if stripped == bare or stripped.endswith("." + bare):
                        found[item] = float(value)
        matches = {
            item: self._matches_evidence(figure, [value], [value])
            for item, value in found.items()
        }
        # A container is answered only by the leaf that holds the figure.
        kept = [item for item in found if item not in containers or matches[item]]
        ranked = sorted(kept, key=lambda item: (not matches[item], item))
        cap = _MAX_CONTAINER_REF_CANDIDATES if containers else _MAX_INDEXED_REF_CANDIDATES
        return ranked[:cap]

    def _other_call_field_ref_candidates(
        self, ref: str, symbol: str | None, figure: Figure
    ) -> list[str]:
        """Same-field refs from other calls of the tool whose value matches ``figure``.

        A ``call_id::field`` ref that does not hold the figure may still name the
        right field of the wrong call (scope or period). Only calls of the same
        tool as the declared call, whose value for that field matches, are
        offered, most recent first. A hint only: the declared ref stays rejected
        and the next draft must name the exact ref itself.
        """
        found: dict[str, None] = {}
        for key in (part.strip() for part in re.split(r"[;,]", ref or "")):
            if "::" not in key:
                continue
            scope, field = (part.strip() for part in key.split("::", 1))
            tools = {r.tool for r in self._evidence if r.call_id == scope}
            tools |= {e.get("tool") for e in self._analysis_metrics if e.get("call_id") == scope}
            if not scope or not field or not tools:
                continue
            records, entries = self._field_sources(field, symbol)
            for call_id, tool, path, value, record in (
                *((r.call_id, r.tool, r.field, r.value, r) for r in records),
                *((e.get("call_id"), e.get("tool"), e.get("field"), e.get("value"), None) for e in entries),
            ):
                if (
                    call_id
                    and call_id != scope
                    and tool in tools
                    and isinstance(path, str)
                    and (record is None or self._kind_fits(record, figure))
                    and self._matches_evidence(figure, [float(value)], [float(value)])
                ):
                    found[f"{call_id}::{path}"] = None
        return list(reversed(found))[:_MAX_CALL_REF_CANDIDATES]

    @staticmethod
    def _kind_fits(record: EvidenceRecord, figure: Figure) -> bool:
        """Whether a record is of the kind ``figure`` can be grounded in.

        Mirrors the narrowing ``_referenced`` applies, so a hint never points at
        a leaf the next draft would still be rejected for.
        """
        if figure.column and record.field != figure.column:
            return False
        if figure.percent:
            return not _is_price_kind(record) and not _is_metadata_count_leaf(record.field)
        if figure.currency:
            return _is_price_kind(record)
        return True

    def _unknown_call_field_ref_candidates(
        self, ref: str, symbol: str | None, figure: Figure
    ) -> list[str]:
        """Exact ``call_id::path`` refs for a ``scope::field`` whose scope names nothing.

        A model that writes an alias (``p1::field``) instead of the call id it
        was given names no call, tool or run of this session, so the ref selects
        no evidence. This only lists where the field really lives, so the next
        draft can copy an exact ref; it grants nothing, and the figure stays
        rejected until it is re-declared with one of them. Refs whose value the
        figure matches come first; at most :data:`_MAX_CALL_REF_CANDIDATES` are
        returned. Candidates keep the same symbol and kind restrictions as a
        real field ref, so the correction cannot recommend an unusable ref.
        """
        key = (ref or "").strip()
        if "::" not in key:
            return []
        scope, field = (part.strip() for part in key.split("::", 1))
        if not scope or not field or self._names_session_source(scope):
            return []
        records, entries = self._field_sources(field, symbol)
        found: dict[str, list[float]] = {}
        money = bool(figure.currency and not figure.percent)
        for record in records:
            if record.call_id and record.field and self._kind_fits(record, figure):
                label = self._ref_source(record.call_id, record.field, record.scope)[1]
                found.setdefault(label, []).append(float(record.value))
        for entry in entries if not (money or figure.column) else ():
            if entry.get("call_id") and entry.get("field"):
                label = self._ref_source(str(entry["call_id"]), str(entry["field"]), None)[1]
                found.setdefault(label, []).append(float(entry["value"]))
        compatible = {
            label
            for label, values in found.items()
            if self._matches_evidence(figure, values, [] if money else values)
        }
        ranked = sorted(found, key=lambda label: (label not in compatible, label))
        return ranked[:_MAX_CALL_REF_CANDIDATES]

    def _names_session_source(self, name: str) -> bool:
        """Whether ``name`` is a call id, tool name or backtest run of this session."""
        return (
            any(name in (record.call_id, record.tool) for record in self._evidence)
            or any(name in (entry.get("call_id"), entry.get("tool")) for entry in self._analysis_metrics)
            or bool(self._artifact_scope(name))
        )

    def _tail_risk_ref_required(
        self,
        figure: Figure,
        records: Sequence[EvidenceRecord],
        entries: Iterable[Mapping[str, Any]] = (),
    ) -> list[str]:
        """Tail-risk identities this figure could be quoting, when there are several.

        #1425's remaining half, decided as a policy rather than patched: a
        session that observed more than one tail-risk identity cannot tell which
        one an undeclared or call-scoped figure means — the gate reads a
        number's shape, never the words "VaR 99%" beside it — so the figure has
        to name its field. A ref that names the field narrows the scope to one
        identity before this runs, so a declared figure never reaches here.

        Empty when the scope holds at most one identity (nothing to confuse) or
        when the figure matches none of the tail-risk values, which keeps every
        other kind of figure on exactly today's path.

        Returns:
            Sorted identities, or an empty list when no ref is required.
        """
        sources = self._tail_risk_sources(records, entries)
        if len({identity for identity, _ in sources}) < 2:
            return []
        return sorted(
            {
                identity
                for identity, value in sources
                if self._matches_evidence(figure, [value], [value])
            }
        )

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
        *,
        why: str = "a count cannot carry a currency mark",
    ) -> list[dict[str, Any]]:
        """Check a ``count`` that looks like a price as the observation it claims to be."""
        found = self._check_observed(figure, declaration, symbol, records)
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
            for entry in self._analysis_entries(symbol)
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
        *,
        legacy_direct: bool = False,
    ) -> bool:
        """Whether a figure equals evidence, at its own scale or a metric's.

        ``direct`` is compared literally. ``scaled`` absorbs fraction vs percent
        (0.182 vs 18.2%) and the sign of a fall (drawdown -0.094 quoted as 9.4%).
        Both are held to the digits the figure was written with
        (:meth:`_within_written_precision`); ``legacy_direct`` keeps the flat evidence
        band for ``direct`` when it is an undeclared price checked against prints.
        """
        if legacy_direct:
            if _close_any(figure.value, direct):
                return True
            if figure.scale != 1.0 and _close_any(figure.value * figure.scale, direct):
                return True
        elif any(
            self._within_written_precision(figure, figure.value, target)
            for target in direct
        ):
            return True
        elif figure.scale != 1.0 and any(
            self._within_written_precision(
                figure, figure.value * figure.scale, target, figure.scale
            )
            for target in direct
        ):
            return True
        magnitudes = [abs(target) for target in scaled]
        return any(
            self._within_written_precision(figure, candidate, target, unit)
            for candidate, unit in (
                (abs(figure.value), 1.0),
                (abs(figure.value) / 100.0, 0.01),
            )
            for target in magnitudes
        )

    @staticmethod
    def _within_written_precision(
        figure: Figure, candidate: float, target: float, unit: float = 1.0
    ) -> bool:
        """Whether a figure is ``target`` correctly rounded to the digits it was written with.

        Raw evidence uses the relative :data:`_TOLERANCE` band. A figure written
        with decimals uses :data:`figures.ROUNDED_BAND` (the same 0.5% cap),
        narrowed to half a unit of its last written decimal. A sufficiently
        precise rendering such as
        0.82467 -> 0.825 survive; 0.82 exceeds the 0.5% relative policy.
        A figure written without decimals keeps the raw relative band alone: an
        integer's precision is not known ("6,700" may be rounded to hundreds).

        Args:
            figure: The prose figure.
            candidate: The figure's value in the units being compared.
            target: The evidence value.
            unit: How many compared units one written unit is (0.01 when a percent
                is compared as a fraction).
        """
        written = figure.digits or figure.text
        band = abs(target) * (ROUNDED_BAND if "." in written else _TOLERANCE)
        if "." in written:
            band = min(band, _written_half_unit(written) * unit * (1 + 1e-9))
        return abs(candidate - target) <= max(band, 1e-9)

    def _check_observed(
        self,
        figure: Figure,
        declaration: Declaration | None,
        symbol: str | None,
        records: Sequence[EvidenceRecord],
    ) -> list[dict[str, Any]]:
        """An observed figure must appear in evidence of its own kind.

        A currency-marked figure is answered only by money-denominated values
        and a percent only by the rest; a table cell only by its column's field.
        """
        scoped = self._referenced(declaration.ref, symbol, figure) if declaration else None
        if scoped is not None:
            scoped_records, metric_values = scoped
            if (
                declaration is not None
                and not scoped_records
                and not metric_values
            ):
                call_field_candidates = self._tool_field_ref_candidates(
                    declaration.ref, symbol, figure
                )
                if call_field_candidates:
                    return [
                        self._figure_issue(
                            "numeric_claim_conflict",
                            figure,
                            "observed",
                            symbol,
                            "field_ref_needs_call_id",
                            f"is declared observed from {declaration.ref}, whose left side is "
                            "a tool name rather than one exact call id",
                            source_tool_call_ids=[declaration.ref],
                            ambiguous_sources=call_field_candidates,
                            field_ref_candidates=call_field_candidates,
                        )
                    ]
                unknown_scope_candidates = self._unknown_call_field_ref_candidates(
                    declaration.ref, symbol, figure
                )
                if unknown_scope_candidates:
                    return [
                        self._figure_issue(
                            "numeric_claim_conflict",
                            figure,
                            "observed",
                            symbol,
                            "unknown_call_id",
                            f"is declared observed from {declaration.ref}, whose left side "
                            "is not a call id, tool or run of this session",
                            source_tool_call_ids=[declaration.ref],
                            field_ref_candidates=unknown_scope_candidates,
                        )
                    ]
            values = [float(record.value) for record in scoped_records] + metric_values
            money = figure.currency and not figure.percent
            # A call- or tool-scoped ref pools every field that call returned,
            # so it cannot choose between the tail-risk identities in it (#1425).
            scoped_entries = [
                entry
                for entry in self._analysis_entries(symbol)
                if declaration.ref in (entry.get("call_id"), entry.get("tool"))
            ]
            tail_risk = self._tail_risk_ref_required(
                figure, scoped_records, scoped_entries
            )
            scoped_identities: list[str] = []
            if tail_risk:
                scoped_sources = self._tail_risk_sources(scoped_records, scoped_entries)
                scoped_identities = sorted({identity for identity, _ in scoped_sources})
                # Whatever else the call returned may still answer the figure.
                blocked = {
                    value for identity, value in scoped_sources if identity in tail_risk
                }
                values = [value for value in values if value not in blocked]
            if self._matches_evidence(figure, values, [] if money else values):
                return []
            if tail_risk:
                return [
                    self._figure_issue(
                        "numeric_claim_conflict",
                        figure,
                        "observed",
                        symbol,
                        "tail_risk_needs_field_ref",
                        f"is declared observed from {declaration.ref}, which returned "
                        f"{', '.join(scoped_identities)} and matches "
                        f"{', '.join(tail_risk)}; a tail-risk figure has to name the "
                        "field it quotes",
                        source_tool_call_ids=[declaration.ref],
                        ambiguous_sources=scoped_identities,
                        field_ref_candidates=self._tail_risk_field_refs(
                            scoped_records, scoped_entries
                        ),
                    )
                ]
            ambiguous = self._ambiguous_field_sources(declaration.ref, symbol)
            if ambiguous:
                return [
                    self._figure_issue(
                        "numeric_claim_conflict",
                        figure,
                        "observed",
                        symbol,
                        "ambiguous_field_ref",
                        f"is declared observed from {declaration.ref}, which names "
                        f"{', '.join(ambiguous)}, and they hold different values",
                        source_tool_call_ids=[declaration.ref],
                        ambiguous_sources=ambiguous,
                        field_ref_candidates=ambiguous,
                    )
                ]
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
                    field_ref_candidates=list(
                        dict.fromkeys(
                            [
                                *self._indexed_field_ref_candidates(declaration.ref, figure, symbol),
                                *self._other_call_field_ref_candidates(declaration.ref, symbol, figure),
                            ]
                        )
                    ),
                    observed_nearest=self._nearest_prints(figure, scoped_records, values),
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
            direct, scaled = prices + self._row_pool(symbol), self._metric_pool(symbol)
        # An undeclared tail-risk figure is matched against every tail-risk
        # value in the session, so it needs a field ref for the same reason a
        # call-scoped one does (#1425).
        session_records = [
            record
            for record in self._evidence
            if not symbol or not record.symbol or record.symbol == symbol
        ]
        tail_risk = self._tail_risk_ref_required(
            figure, session_records, self._analysis_entries(symbol)
        )
        session_identities: list[str] = []
        if tail_risk:
            session_sources = self._tail_risk_sources(
                session_records, self._analysis_entries(symbol)
            )
            session_identities = sorted({identity for identity, _ in session_sources})
            blocked = {
                value for identity, value in session_sources if identity in tail_risk
            }
            direct = [value for value in direct if value not in blocked]
            scaled = [value for value in scaled if value not in blocked]
        if not direct and not scaled and not tail_risk:
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
                )
            ]
        if self._matches_evidence(figure, direct, scaled, legacy_direct=True):
            return []
        if tail_risk:
            return [
                self._figure_issue(
                    "numeric_claim_conflict",
                    figure,
                    "observed",
                    symbol,
                    "tail_risk_needs_field_ref",
                    f"matches {', '.join(tail_risk)}, and this session observed "
                    f"{', '.join(session_identities)}, so the figure has to name "
                    "the field it quotes",
                    ambiguous_sources=session_identities,
                    field_ref_candidates=self._tail_risk_field_refs(
                        session_records, self._analysis_entries(symbol)
                    ),
                )
            ]
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
        # Two instruments' bars and no resolved symbol: arithmetic anchored on
        # the session's pools, or on one instrument's prints the ref names,
        # would look anchored with nothing to anchor it to. Only evidence that
        # belongs to no instrument, named by the ref, can anchor it then — a
        # difference between two backtests' Sharpes is a portfolio figure.
        unattributed = not symbol and len({record.symbol for record in records if record.symbol}) > 1
        anchors: list[float] = []
        if not unattributed:
            # A money-marked result is derived from money: an RSI or a volume
            # is not a price to take a discount of.
            anchors = self._price_pool(symbol, records) + self._row_pool(symbol, money_only=money)
            if not money:
                anchors += self._metric_pool(symbol)
        # Arithmetic across two runs needs both runs' values: a field ref that
        # names several sources anchors all of them instead of none.
        scoped = self._referenced(declaration.ref, symbol, None, pool_ambiguous=True)
        if scoped is not None:
            anchors.extend(
                float(record.value)
                for record in scoped[0]
                if (not money or _is_price_kind(record)) and not (unattributed and record.symbol)
            )
            if not money and not unattributed:
                anchors.extend(scoped[1])
        if not anchors:
            return "no_symbol" if unattributed else "no_evidence"

        # A formula's constants are parsed unsigned ("−0.2099 − (−0.2158)"
        # holds 0.2099 and 0.2158), so an operand is matched by magnitude, as
        # a figure is: without it no drawdown or loss could ever anchor.
        magnitudes = [abs(anchor) for anchor in anchors]

        def observed(operand: float) -> bool:
            return _close_any(abs(operand), magnitudes)

        if not any(observed(operand) for operand in operands):
            return "no_symbol" if unattributed else "formula_not_anchored"
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
        # "−1.51pp" beside "12.87% − 11.36%": the size is right and the formula
        # runs the other way. Still refused (the sign is part of the claim),
        # but said, or the model rewrites the number instead of the formula.
        reversed_sign = self._result_matches(figure, -result)
        return [
            self._figure_issue(
                "numeric_claim_conflict",
                figure,
                "derived",
                symbol,
                "derivation_result_mismatch",
                f"is declared derived, but its own formula evaluates to {shown}",
                derived_result=shown,
                **({"sign_reversed": True} if reversed_sign else {}),
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
                (
                    block.match(figure.value, figure.percent, figure.digits)
                    or _NO_DECLARATION
                ).role
                == "cited"
                for figure in carried
            ):
                continue
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
def _declared_in_other_unit(block: FiguresBlock, figure: Figure) -> Declaration | None:
    """A declaration holding ``figure`` as a fraction where it is a percent, or the reverse.

    It does not cover the figure (``block.match`` keeps the two apart); it
    only lets the correction say what the model did declare.
    """
    half_unit = _written_half_unit(figure.digits or figure.text)
    for declaration in block.declarations:
        if declaration.percent == figure.percent:
            continue
        in_figure_units = declaration.value * (100.0 if figure.percent else 0.01)
        # By size: a difference declared one way round and written the other
        # ("0.0151" for "−1.51pp") is still the value the model meant to name.
        if abs(abs(in_figure_units) - abs(figure.value)) <= half_unit * (1 + 1e-9):
            return declaration
    return None


#: What separates the parts of a free-form ref: ``backtest::rp``,
#: ``risk_parity target_positions.csv``, ``backtest(metrics.csv)``.
_REF_TOKEN_RE = re.compile(r"::?|[\s,，;；()（）\[\]]+")


def _file_stem(path: str) -> str:
    """A file's name up to its first dot, casefolded: ``target_positions`` for any spelling."""
    return str(path).rsplit("/", 1)[-1].split(".", 1)[0].casefold()


def _records_at(
    token: str, owned: Sequence[EvidenceRecord], root: Path
) -> list[EvidenceRecord]:
    """The backtest records a path-like ref token names.

    A directory or file relative to the run (or absolute) names what lies at
    or under it. A file named without its ``artifacts/`` segment
    (``rp/metrics.csv``) names that file anywhere under its directory, and
    ``rp/ew`` names both run directories.

    Args:
        token: One part of a ref.
        owned: Every observed backtest record.
        root: The ledger's resolved run directory.

    Returns:
        The records at that path, or an empty list.
    """
    path = Path(token)
    if not path.is_absolute():
        path = root / path
    try:
        relative = Path(os.path.normpath(path)).relative_to(root).as_posix()
    except ValueError:
        return []
    if relative in ("", "."):
        return []

    def under(artifact: str, prefix: str) -> bool:
        return artifact == prefix or artifact.startswith(prefix + "/")

    hits = [record for record in owned if under(record.artifact or "", relative)]
    if hits or "/" not in relative:
        return hits
    parent, _, name = relative.rpartition("/")
    hits = [
        record
        for record in owned
        if under(record.artifact or "", parent)
        and _file_stem(record.artifact or "") == _file_stem(name)
    ]
    if hits:
        return hits
    groups = [
        [record for record in owned if under(record.artifact or "", part)]
        for part in relative.split("/")
    ]
    return [record for group in groups for record in group] if all(groups) else []


_NO_DECLARATION = Declaration(
    index=0, value_text="", value=0.0, percent=False, role="observed", note="", ref=""
)
