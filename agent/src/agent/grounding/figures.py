"""The figures block, the shape of a number, and how the two are matched.

This is the gate's whole inference surface: it finds the model's ``figures``
declarations, classifies every prose number by SHAPE (date, symbol, list
marker, measurement, bare integer) and matches prose numbers to declarations.
It reads no natural-language word; roles are declared by the model and shape
is language-independent.

Numbers are read as a renderer shows them: invisible characters, Markdown
escapes, character references and look-alike separators are normalized first,
and every offset is mapped back to the original text.
"""

from __future__ import annotations

import html
import re
import string
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence

from src.agent.grounding.identity import _CANONICAL_SYMBOL_RE

#: The five roles a declaration may carry (spec §2).
ROLES = ("observed", "derived", "proposed", "cited", "count")

#: The info string that marks the declaration block.
BLOCK_LANGUAGE = "figures"

# SHAPE 1 — a number. Grouped thousands are one token and the lookbehind keeps
# an identifier's digits ("SMA20") out. The lookahead fences only digits, so
# "3.6pp" reads as 3.6 rather than backtracking to a bare "3".
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\d)"
)

# SHAPE 2 — dates, times and years: structure, never a measurement (spec §3).
# A year-less "08-10" is two bare integers and needs no mask.
_DATE_RE = re.compile(
    r"(?P<full>(?:19|20)\d{2}(?:\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*[日号]?"
    # A dotted date has both dots and no spacing: "2001.5 - 2002.5" is a range.
    r"|\.\d{1,2}\.\d{1,2}(?!\d|\.\d)))"
    # A year-less MM-DD / MM/DD; see _short_date_is_structural.
    r"|(?P<short>(?<![\d.])(?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12]\d|3[01])(?!\d|\.\d))"
    r"|(?<![\d.:])(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?![\d:]|\.\d)"
    # A month alone ("6月初"), a day, a day range ("8月17–18日") or a day list ("9月11/14日").
    r"|(?<![\d.])\d{1,2}\s*月(?:\s*\d{1,2}(?:\s*[-–—~～/、]\s*\d{1,2})*\s*[日号])?"
    r"|(?:19|20)\d{2}\s*年"
    # A bare year or compact YYYYMMDD loses to a measurement mark ("$2050").
    r"|(?P<soft>(?<![\d.])(?:19|20)\d{2}(?:(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))?(?!\d|\.\d))"
)

# SHAPE 3 — a line-leading list marker or numbered heading. The punctuation is
# required, so a line opening with a figure ("1.171 元是收盘价") is untouched.
_ORDINAL_RE = re.compile(r"(?m)^[^\S\n]*(?:#{1,6}[^\S\n]*)?\d{1,3}[.)、][^\S\n]+")

# SHAPE 5 — a table cell that only numbers its row ("1", "2.", "3)"), and a word
# inside a cell: two or more letters of any script ("12m mean return", "12个月").
# A glued unit letter ("25x", "25 倍") is not a word (#1471).
_INDEX_CELL_RE = re.compile(r"\d{1,3}[.)]?")
_CELL_WORD_RE = re.compile(r"[^\W\d_]{2,}")

# SHAPE 4 — a CommonMark fence line: at most three spaces of indent, a run of
# backticks or tildes, and the info string.
_FENCE_RE = re.compile(r"(?m)^ {0,3}(`{3,}|~{3,})(.*)$")

# Currency is a symbol set, not a vocabulary: a money character or ISO code
# touching a bare integer ("$100", "820 CNY") makes it measurement-shaped.
_CURRENCY_CHARS = frozenset("$¥￥€£₩₹元币圆镑円원")

_CURRENCY_CODES = frozenset(
    {
        "USD", "CNY", "CNH", "RMB", "HKD", "JPY", "EUR", "GBP", "KRW", "INR",
        "CAD", "AUD", "SGD", "TWD", "THB", "IRR", "IRT", "USDT", "USDC",
    }
)

_PERCENT_CHARS = "%％"

# Glued percentage-point and basis-point marks, and the percent each one is.
_POINT_MARKS = (("bps", 0.01), ("pp", 1.0), ("bp", 0.01))

# Magnitude marks glued to a figure ("24.6M", "2.4万"): a symbol set like the
# currency marks. They scale the comparison with evidence and never decide shape.
_MAGNITUDES = {"K": 1e3, "M": 1e6, "B": 1e9, "千": 1e3, "万": 1e4, "亿": 1e8}

# A CJK currency word is at most three characters (人民币); bounding the run
# keeps 元宵/元件, inside longer CJK runs, from reading as money.
_MAX_CURRENCY_WORD = 3

# What a renderer does not show, and look-alikes of a number's own separators.
_INVISIBLE = frozenset("\u200b\u200c\u200d\u2060\ufeff\u00ad")

_LOOKALIKES = {
    "\uff0e": ".", "\u066b": ".", "\u066c": ",", "\u2212": "-",
    "\u00a0": " ", "\u202f": " ", "\u2007": " ", "\u2009": " ",
}

_LINE_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")

_ESCAPABLE = frozenset(string.punctuation)


@dataclass(frozen=True)
class Declaration:
    """One parsed line of the model's figures block.

    ``value_text`` is the value's canonical spelling at its written precision,
    in percent units when it is a percent ("5200bp" → "52.00%").
    """

    index: int
    value_text: str
    value: float
    percent: bool
    role: str
    note: str
    ref: str


@dataclass(frozen=True)
class FiguresBlock:
    """The declaration blocks, or the absence of one.

    ``span`` is the first block's (streaming holds back from it); ``spans``
    covers every block, all of which are merged and stripped.
    """

    present: bool
    span: tuple[int, int] | None
    raw: str
    declarations: tuple[Declaration, ...]
    malformed: tuple[tuple[int, str], ...]
    spans: tuple[tuple[int, int], ...] = ()

    def match(self, value: float, percent: bool) -> Declaration | None:
        """Return the declaration covering ``value``, or None.

        Matching is numeric (tolerance 1e-9) and percent-ness must agree:
        ``37%`` and ``0.37`` are different assertions.

        Args:
            value: The prose figure's numeric value.
            percent: Whether the prose figure carries a percent sign.

        Returns:
            The first matching declaration, or None.
        """
        for declaration in self.declarations:
            if declaration.percent != percent:
                continue
            if abs(declaration.value - value) <= max(abs(value) * 1e-9, 1e-9):
                return declaration
        return None


@dataclass(frozen=True)
class Figure:
    """One number located in the prose, with the shape it was written in.

    ``text``, ``start`` and ``end`` are the original spelling and offsets.
    ``value`` is in percent units for a percent, pp or bp figure ("5200bp" is
    52.0, ``scale`` 1.0). ``digits`` and ``sign`` are the normalized reading
    ("0\\.888" → "0.888", "−5,13%" → "-", "5.13"), for precision and sign.
    """

    text: str
    value: float
    percent: bool
    start: int
    end: int
    line: int
    shape: str
    column: str | None = None
    date: str | None = None
    symbol: str | None = None
    scale: float = 1.0
    # A currency mark or ISO code touches the digits ("$2050", "0.95 元").
    currency: bool = False
    digits: str = ""
    sign: str = ""
    # The span a redaction replaces: the figure plus its glued currency and
    # magnitude marks ("HK$1.10", "0.95 元", "24.6M").
    extent: tuple[int, int] | None = None
    # The info string of the fenced block holding the figure, or None.
    fence: str | None = None


@dataclass(frozen=True)
class TableRow:
    """One Markdown table row and the column roles of its header."""

    line: int
    cells: tuple[tuple[str, int, int], ...]
    columns: dict[int, str]
    date_column: int | None
    symbol_column: int | None
    # Which table of the document the row belongs to, in document order.
    table: int = 0


@dataclass(frozen=True)
class _Normalized:
    """A document as a renderer shows its numbers, with offsets into the source."""

    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]
    size: int

    def start(self, index: int) -> int:
        """The source offset where normalized position ``index`` begins."""
        return self.starts[index] if index < len(self.starts) else self.size

    def end(self, index: int) -> int:
        """The source offset where a normalized span ending at ``index`` ends."""
        return self.ends[index - 1] if index > 0 else 0


@dataclass(frozen=True)
class _Token:
    """One number in normalized text: its span, sign and digits as written."""

    start: int
    end: int
    sign: str
    digits: str


# Header spellings binding a table column to an OHLC field: the table's own
# schema, like a tool field name, not prose inference (spec §4).
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

_SYMBOL_HEADERS = {"symbol", "ticker", "code", "标的", "代码", "证券代码"}


def _lines_with_offsets(content: str) -> list[tuple[str, int]]:
    """Return each line of ``content`` with its character offset in it."""
    positions: list[tuple[str, int]] = []
    cursor = 0
    for line in content.splitlines():
        start = content.find(line, cursor) if line else cursor
        if start < 0:
            start = cursor
        positions.append((line, start))
        cursor = start + len(line)
    return positions


def _entity(content: str, index: int) -> tuple[str, int] | None:
    """Decode the character reference (``&#46;``, ``&nbsp;``) at ``index``.

    Returns:
        ``(character, source width)``, or None when there is no reference or it
        would decode to a line break or control character.
    """
    semicolon = content.find(";", index + 2, index + 12)
    if semicolon < 0:
        return None
    piece = content[index : semicolon + 1]
    name = piece[1:-1]
    if name.startswith("#"):
        digits, allowed, base = name[1:], string.digits, 10
        if digits[:1] in ("x", "X"):
            digits, allowed, base = digits[1:], string.hexdigits, 16
        if not digits or any(char not in allowed for char in digits):
            return None
        code = int(digits, base)
        if not 0 < code <= 0x10FFFF or 0xD800 <= code <= 0xDFFF:
            return None
        char = chr(code)
    else:
        char = html.unescape(piece) if name.isascii() and name.isalnum() else piece
        if len(char) != 1:
            return None
    if char in _LINE_BREAKS or unicodedata.category(char) == "Cc":
        return None
    return char, len(piece)


def _glued_code(chars: Sequence[str]) -> bool:
    """Whether ``chars`` ends in an uppercase ISO code standing on its own ("CNY")."""
    run = 0
    while run < min(len(chars), 5) and chars[-1 - run].isascii() and chars[-1 - run].isupper():
        run += 1
    before = chars[-1 - run] if len(chars) > run else ""
    return (
        "".join(chars[len(chars) - run :]) in _CURRENCY_CODES
        and not (before.isalnum() or before == "_")
    )


def _normalize(content: str) -> _Normalized:
    """Read ``content`` as a renderer shows its numbers.

    Invisible characters are dropped; a backslash before ASCII punctuation and a
    character reference are resolved; "．" and "٫" read as a decimal point, "٬"
    as a group separator, "−" as a minus, no-break and figure spaces as spaces;
    an ISO code glued to digits ("CNY0.888") gets a space so the number is read
    whole. Line breaks are never introduced or removed.
    """
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    index = 0
    while index < len(content):
        char, width = content[index], 1
        if char == "\\" and content[index + 1 : index + 2] in _ESCAPABLE:
            char, width = content[index + 1], 2
        elif char == "&":
            char, width = _entity(content, index) or (char, width)
        if char in _INVISIBLE:
            index += width
            continue
        char = _LOOKALIKES.get(char, char)
        if char.isdigit() and _glued_code(chars):
            chars.append(" ")
            starts.append(index)
            ends.append(index)
        chars.append(char)
        starts.append(index)
        ends.append(index + width)
        index += width
    return _Normalized("".join(chars), tuple(starts), tuple(ends), len(content))


def _digit_run(text: str, index: int) -> str:
    """The run of digits starting at ``index``."""
    end = index
    while end < len(text) and text[end].isdigit():
        end += 1
    return text[index:end]


def _numbers(text: str) -> list[_Token]:
    """Every number in normalized text, with a decimal comma read as one (#1418).

    A comma is a decimal point when the integer part is exactly "0" ("0,666"),
    or when a one- or two-digit fraction carries a percent, pp/bp or currency
    mark ("12,5 %", "3,95 EUR", "€3,95"). A document that writes an unambiguous
    decimal comma anywhere and no unambiguous grouping ("1,234,567",
    "1,234.56") reads every single-comma number as a decimal, so "2,237" and
    "−5,132%" beside "1,57%" are 2.237 and −5.132%, not 2237 and −5132%.
    """
    comma_decimals = _writes_decimal_commas(text)
    tokens: list[_Token] = []
    cursor = 0
    for match in _NUMBER_RE.finditer(text):
        if match.start() < cursor:
            continue
        raw = match.group(0)
        sign = raw[0] if raw[0] in "+-" else ""
        body, end = raw[len(sign) :], match.end()
        if body.count(",") == 1 and "." not in body and (body.startswith("0,") or comma_decimals):
            body = body.replace(",", ".")
        elif body.isdigit() and text[end : end + 1] == ",":
            fraction = _digit_run(text, end + 1)
            stop = end + 1 + len(fraction)
            if fraction and (
                body == "0"
                or comma_decimals
                or (
                    len(fraction) <= 2
                    and (
                        _currency_before(text, match.start())
                        or _currency_after(text, stop)
                        or _percent_mark(text, stop)[0] > 0
                    )
                )
            ):
                body, end = f"{body}.{fraction}", stop
        tokens.append(_Token(match.start(), end, sign, body.replace(",", "")))
        cursor = end
    return tokens


def _writes_decimal_commas(text: str) -> bool:
    """Whether a document writes decimal commas and never a thousands grouping.

    Evidence for a decimal comma is unambiguous on its own: a "0," integer part,
    or a one- or two-digit fraction carrying a percent, pp/bp or currency mark
    ("1,57%", "3,95 EUR"). An unmarked "1,50" could be a list and proves nothing.
    Evidence for grouping is two or more comma groups or a grouped number with a
    dot fraction.
    """
    decimal, grouped = False, False
    for match in _NUMBER_RE.finditer(text):
        body = match.group(0).lstrip("+-")
        if body.count(",") >= 2 or ("," in body and "." in body):
            grouped = True
        elif body.startswith("0,"):
            decimal = True
        elif body.isdigit() and text[match.end() : match.end() + 1] == ",":
            fraction = _digit_run(text, match.end() + 1)
            stop = match.end() + 1 + len(fraction)
            if 1 <= len(fraction) <= 2 and (
                _currency_before(text, match.start())
                or _currency_after(text, stop)
                or _percent_mark(text, stop)[0] > 0
            ):
                decimal = True
    return decimal and not grouped


def _percent_mark(text: str, end: int) -> tuple[float, int]:
    """The percent a figure's trailing mark denotes, and where the mark ends.

    A percent sign may follow a space; ``pp`` / ``bp`` / ``bps`` must be glued
    and not run into a word ("3.6ppm" is not a percentage point).

    Returns:
        ``(1.0, end)`` for % and pp, ``(0.01, end)`` for bp, ``(0.0, end)``.
    """
    rest = text[end:]
    spaced = rest.lstrip(" \t")
    if spaced[:1] and spaced[0] in _PERCENT_CHARS:
        return 1.0, end + len(rest) - len(spaced) + 1
    for mark, unit in _POINT_MARKS:
        after = rest[len(mark) : len(mark) + 1]
        if rest[: len(mark)].casefold() == mark and not (after.isascii() and after.isalnum()):
            return unit, end + len(mark)
    return 0.0, end


def _reading(sign: str, digits: str, unit: float) -> tuple[float, str] | None:
    """A number's value and canonical spelling, in percent units for bp."""
    try:
        amount = Decimal(sign + digits)
    except InvalidOperation:
        return None
    if unit == 0.01:
        amount = amount.scaleb(-2)
    return float(amount), format(amount, "f")


def _fenced_blocks(content: str) -> list[tuple[int, int, str, tuple[int, int]]]:
    """Return ``(start, end, info, body)`` for every fenced block (CommonMark).

    A backtick opener's info string holds no backtick; a closer repeats the
    opener's character, at least as long, with nothing after it. An unterminated
    ``figures`` fence runs to the end, so a truncated answer keeps its
    declarations; any other unterminated fence is prose and its numbers are
    checked. A ``figures`` opener at least as long ends a search for a closer,
    so a stray opener cannot pair with the declaration block's closing fence.
    """
    fences = []
    for match in _FENCE_RE.finditer(content):
        marker, info = match.group(1), match.group(2).strip()
        if marker[0] == "`" and "`" in info:
            continue
        words = info.split()
        fences.append((match, marker, words[0].casefold() if words else "", not info))
    blocks: list[tuple[int, int, str, tuple[int, int]]] = []
    index = 0
    while index < len(fences):
        opener, marker, info, _ = fences[index]
        cursor, closer = index + 1, None
        while cursor < len(fences):
            candidate, other, other_info, bare = fences[cursor]
            if bare and other[0] == marker[0] and len(other) >= len(marker):
                closer = candidate
                break
            if other_info == BLOCK_LANGUAGE and len(other) >= len(marker):
                break
            cursor += 1
        if closer is not None:
            blocks.append((opener.start(), closer.end(), info, (opener.end(), closer.start())))
            index = cursor + 1
        elif info == BLOCK_LANGUAGE:
            stop = fences[cursor][0].start() if cursor < len(fences) else len(content)
            blocks.append((opener.start(), stop, info, (opener.end(), stop)))
            index = cursor
        else:
            index += 1
    return blocks


def _is_currency_word(run: str) -> bool:
    """Whether a CJK run is short enough to be a currency word and holds a money mark."""
    return len(run) <= _MAX_CURRENCY_WORD and any(char in _CURRENCY_CHARS for char in run)


def _is_currency_mark(word: str) -> bool:
    """Whether a declared value's decoration is empty or one currency mark.

    Accepts an ISO code ("USD"), a CJK currency word ("港元"), or money
    characters behind at most three letters ("$", "HK$", "NT$").
    """
    if not word or word.upper() in _CURRENCY_CODES:
        return True
    if all(_is_cjk(char) for char in word):
        return _is_currency_word(word)
    symbols = word.lstrip(string.ascii_letters)
    return (
        bool(symbols)
        and len(word) - len(symbols) <= 3
        and all(char in _CURRENCY_CHARS for char in symbols)
    )


def _parse_value(text: str) -> tuple[float, bool, str] | None:
    """Read a declared value: one number with its currency, magnitude and percent marks.

    Returns:
        ``(value, percent, canonical spelling)``, or None when the field is not
        exactly one number and its marks.
    """
    field = _normalize(text).text.strip()
    tokens = _numbers(field)
    if len(tokens) != 1:
        return None
    token = tokens[0]
    rest = field[token.end :].strip()
    if rest[:1] in _MAGNITUDES and not _is_currency_mark(rest):
        rest = rest[1:].lstrip()
    unit, consumed = _percent_mark(rest, 0)
    if not (
        _is_currency_mark(rest[consumed:].strip())
        and _is_currency_mark(field[: token.start].strip())
    ):
        return None
    reading = _reading(token.sign, token.digits, unit)
    if reading is None:
        return None
    value, canonical = reading
    return value, unit > 0, canonical + ("%" if unit > 0 else "")


def _is_header_or_rule(parts: Sequence[str]) -> bool:
    """Whether a block line is a ``value | role`` header or a Markdown separator row."""
    if len(parts) >= 2 and parts[0].casefold() == "value" and parts[1].casefold() == "role":
        return True
    cells = [part.replace(" ", "") for part in parts if part]
    return bool(cells) and all(set(cell) <= {"-", ":"} and "-" in cell for cell in cells)


def parse_figures_block(content: str) -> FiguresBlock:
    """Parse the model's ``figures`` blocks out of a draft.

    Parsing is lenient (full-width pipe, run-on spacing, missing ``ref``, a
    header or separator row, currency and unit marks on the value), but a line
    that cannot be read as ``value | role | note | ref`` is reported as
    malformed: a skipped declaration is a figure the gate never checked. Every
    ``figures`` fence contributes; ``span`` is the first one.

    Args:
        content: The candidate answer.

    Returns:
        The parsed block, or an absent one when the draft has no block.
    """
    blocks = [block for block in _fenced_blocks(content) if block[2] == BLOCK_LANGUAGE]
    if not blocks:
        return FiguresBlock(False, None, "", (), ())
    raw = "".join(content[start:end] for _, _, _, (start, end) in blocks)
    declarations: list[Declaration] = []
    malformed: list[tuple[int, str]] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip().replace("｜", "|")
        if not stripped:
            continue
        parts = stripped.split("|")
        if stripped.startswith("|"):
            parts = parts[1:]
        if len(parts) > 1 and stripped.endswith("|"):
            parts = parts[:-1]
        parts = [part.strip() for part in parts]
        if _is_header_or_rule(parts):
            continue
        parsed = _parse_value(parts[0]) if parts else None
        role = parts[1].casefold() if len(parts) > 1 else ""
        if parsed is None or role not in ROLES:
            malformed.append((number, line.strip()[:120]))
            continue
        value, percent, canonical = parsed
        declarations.append(
            Declaration(
                index=number,
                value_text=canonical,
                value=value,
                percent=percent,
                role=role,
                note=parts[2] if len(parts) > 2 else "",
                ref=parts[3] if len(parts) > 3 else "",
            )
        )
    return FiguresBlock(
        True,
        (blocks[0][0], blocks[0][1]),
        raw,
        tuple(declarations),
        tuple(malformed),
        tuple((start, end) for start, end, _, _ in blocks),
    )


def strip_figures_block(content: str, block: FiguresBlock) -> str:
    """Return the text to release: the draft without any declaration block."""
    spans = block.spans or ((block.span,) if block.span else ())
    text = content
    for start, end in sorted(spans, reverse=True):
        head, tail = text[:start].rstrip(), text[end:].lstrip()
        text = head + ("\n\n" if head and tail else "") + tail
    return text.strip() if spans else content


def _table_cells(line: str, offset: int) -> list[tuple[str, int, int]]:
    """Split one Markdown row into ``(text, start, end)`` cells."""
    if line.count("|") < 2:
        return []
    cells: list[tuple[str, int, int]] = []
    cursor = 0
    for piece in line.split("|"):
        start = cursor
        cursor += len(piece) + 1
        text = piece.strip()
        if not text:
            cells.append(("", offset + start, offset + start + len(piece)))
            continue
        lead = len(piece) - len(piece.lstrip())
        cells.append((text, offset + start + lead, offset + start + lead + len(text)))
    if cells and cells[0][0] == "":
        cells = cells[1:]
    if cells and cells[-1][0] == "":
        cells = cells[:-1]
    return cells


def _is_separator_row(cells: Sequence[tuple[str, int, int]]) -> bool:
    """Whether every cell is a Markdown alignment run (``---``, ``:--:``)."""
    if not cells:
        return False
    return all(
        text and set(text.replace(" ", "")) <= {"-", ":"} and "-" in text
        for text, _, _ in cells
    )


def table_rows(content: str) -> list[TableRow]:
    """Return every Markdown table row with its header's column roles.

    A table is a maximal run of lines with at least two pipes; its first line is
    the header, whose cells bind columns to OHLC fields, trade date and symbol.
    """
    positions = _lines_with_offsets(content)
    rows: list[TableRow] = []
    index = 0
    table = 0
    while index < len(positions):
        if positions[index][0].count("|") < 2:
            index += 1
            continue
        block_start = index
        while index < len(positions) and positions[index][0].count("|") >= 2:
            index += 1
        header = _table_cells(positions[block_start][0], positions[block_start][1])
        headers = [text.casefold() for text, _, _ in header]
        columns = {
            position: _TABLE_FIELD_ALIASES[name]
            for position, name in enumerate(headers)
            if name in _TABLE_FIELD_ALIASES
        }
        date_column = next(
            (position for position, name in enumerate(headers) if name in _DATE_HEADERS),
            None,
        )
        symbol_column = next(
            (position for position, name in enumerate(headers) if name in _SYMBOL_HEADERS),
            None,
        )
        for line_index in range(block_start + 1, index):
            cells = _table_cells(positions[line_index][0], positions[line_index][1])
            if not cells or _is_separator_row(cells):
                continue
            rows.append(
                TableRow(line_index, tuple(cells), columns, date_column, symbol_column, table)
            )
        table += 1
    return rows


def _code_before(head: str) -> str:
    """The uppercase ISO code ending ``head`` as a word of its own, or ""."""
    letters = head[len(head.rstrip(string.ascii_uppercase)) :]
    before = head[-len(letters) - 1 : -len(letters)] if letters else ""
    if letters in _CURRENCY_CODES and not (before.isalnum() or before == "_"):
        return letters
    return ""


def _currency_before(text: str, start: int) -> bool:
    """Whether a currency symbol or ISO code touches the number on its left."""
    head = text[:start].rstrip()
    return bool(head) and (head[-1] in _CURRENCY_CHARS or bool(_code_before(head)))


def _cjk_run(text: str) -> str:
    """The run of CJK ideographs ``text`` opens with."""
    end = 0
    while end < len(text) and _is_cjk(text[end]):
        end += 1
    return text[:end]


def _currency_after(text: str, end: int) -> bool:
    """Whether a currency symbol or ISO code touches the number on its right.

    A CJK run counts only when short enough to be a currency word: "美元" does,
    "元宵节后关注" does not.
    """
    tail = text[end:].lstrip()
    if not tail:
        return False
    if tail[0] in _CURRENCY_CHARS and not _is_cjk(tail[0]):
        return True
    if _is_cjk(tail[0]):
        return _is_currency_word(_cjk_run(tail))
    code = ""
    for char in tail:
        if not char.isascii() or not char.isalpha():
            break
        code += char
    return code.upper() in _CURRENCY_CODES


def magnitude_suffix(text: str, end: int) -> tuple[float, int]:
    """The magnitude mark glued to the right of a figure, if any.

    ``K`` / ``M`` / ``B`` count only when no further letter follows, so "5MB"
    and "3Mn" are not millions.

    Args:
        text: The document.
        end: Where the figure's digits end.

    Returns:
        ``(multiplier, end past the mark)``, or ``(1.0, end)`` without one.
    """
    mark = text[end : end + 1]
    if not mark or mark not in _MAGNITUDES:
        return 1.0, end
    after = text[end + 1 : end + 2]
    if mark.isascii() and after.isascii() and after.isalpha():
        return 1.0, end
    return _MAGNITUDES[mark], end + 1


def _currency_prefix_start(text: str, start: int) -> int:
    """Where a currency mark attached to the left of a figure begins ("HK$1.10", "USD 100")."""
    head = text[:start].rstrip(" \t")
    if head and head[-1] in _CURRENCY_CHARS and not _is_cjk(head[-1]):
        letters = len(head) - 1 - len(head[:-1].rstrip(string.ascii_uppercase))
        return len(head) - 1 - (letters if letters <= 3 else 0)
    code = _code_before(head)
    return len(head) - len(code) if code else start


def _currency_suffix_end(text: str, end: int) -> int:
    """Where a currency unit attached to the right of a figure ("0.95 元") ends.

    A compound unit (元/股, USD/share) is left whole, or its denominator would be
    left with nothing above it.
    """
    body = text[end:].lstrip(" \t")
    lead = len(text) - end - len(body)
    if not body:
        return end
    if _is_cjk(body[0]):
        run = _cjk_run(body)
        if not _is_currency_word(run):
            return end
    else:
        run = body[: len(body) - len(body.lstrip(string.ascii_letters))]
        if run.upper() not in _CURRENCY_CODES:
            return end
    if body[len(run) : len(run) + 1] in {"/", "／"}:
        return end
    return end + lead + len(run)


def _is_cjk(char: str) -> bool:
    """Whether a character is in the CJK ideograph range."""
    return "㐀" <= char <= "鿿"


# Statement-ending punctuation, the gate's only segmentation: it decides which
# instrument a figure is about (spec §4), never what it means. "." counts only
# before whitespace, so decimals and ticker suffixes stay in one segment.
_SEGMENT_BREAKS = frozenset("，,；;。、\n！!？?")


def segment_bounds(content: str, start: int, end: int) -> tuple[int, int]:
    """The punctuation-delimited stretch of text a figure sits in.

    Args:
        content: The whole answer.
        start: Where the figure starts.
        end: Where it ends.

    Returns:
        ``(segment start, segment end)`` in document offsets.
    """
    left = start
    while left > 0:
        char = content[left - 1]
        if char in _SEGMENT_BREAKS:
            break
        if char == "." and left < len(content) and content[left].isspace():
            break
        left -= 1
    right = end
    while right < len(content):
        char = content[right]
        if char in _SEGMENT_BREAKS:
            break
        if char == "." and right + 1 < len(content) and content[right + 1].isspace():
            break
        right += 1
    return left, right


def _within(span: tuple[int, int], spans: Iterable[tuple[int, int]]) -> bool:
    """Whether ``span`` sits inside any of ``spans``."""
    return any(start <= span[0] and span[1] <= end for start, end in spans)


def _short_date_is_structural(content: str, match: re.Match[str], full_dates: Sequence[re.Match[str]]) -> bool:
    """Whether a year-less ``MM-DD`` is a date rather than an integer range.

    Zero padding ("09-14") is how dates are written and ranges are not. An
    unpadded one ("10-14") counts only when a full date opens the same table
    cell or line ("2026-10-11 / 10-14"), because "| 11-12 |" may be a price range.

    Args:
        content: The candidate answer.
        match: A ``_DATE_RE`` match of the ``short`` branch.
        full_dates: Every match of the ``full`` branch.

    Returns:
        True when the digits are structure.
    """
    month, day = match.group("short")[:2], match.group("short")[3:]
    if month.startswith("0") or day.startswith("0"):
        return True
    segment = max(content.rfind("\n", 0, match.start()), content.rfind("|", 0, match.start())) + 1
    return any(segment <= full.start() and full.end() <= match.start() for full in full_dates)


def _index_cells(rows: Sequence[TableRow]) -> set[tuple[int, int]]:
    """Spans of the cells of a column that only numbers its table's rows (#1471).

    A column whose numbered cells read 1, 2, 3 … in row order is the table's
    index. No price or metric takes that shape, and cutting it turned a ranking
    into a column of omission marks. A cell without a digit ("—", "Total") is
    skipped; one numbered row proves no sequence, so it takes two. A column the
    header binds to an OHLC field is never an index.

    Args:
        rows: Every table row of the document.

    Returns:
        ``(start, end)`` of each index cell.
    """
    tables: dict[int, list[TableRow]] = {}
    for row in rows:
        tables.setdefault(row.table, []).append(row)
    spans: set[tuple[int, int]] = set()
    for body in tables.values():
        for position in range(max(len(row.cells) for row in body)):
            if position in body[0].columns:
                continue
            numbered = [
                row.cells[position]
                for row in body
                if position < len(row.cells) and any(char.isdigit() for char in row.cells[position][0])
            ]
            if len(numbered) < 2 or not all(_INDEX_CELL_RE.fullmatch(text) for text, _, _ in numbered):
                continue
            if [int(text.rstrip(".)")) for text, _, _ in numbered] == list(range(1, len(numbered) + 1)):
                spans.update((start, end) for _, start, end in numbered)
    return spans


def scan_figures(content: str, block: FiguresBlock) -> list[Figure]:
    """Locate and classify every number in the prose of a draft (spec §3).

    * ``exempt`` — a date, time, security-code digits, line-leading ordinal,
      a table's row-number column or anything fenced; a bare year, compact date
      or a table date/symbol cell only while it carries no decimal point,
      percent or currency mark (and a year not under a price column).
    * ``measured`` — a decimal point, percent / pp / bp, touching currency mark
      or a table cell that holds a number and no word: the shape a fabricated
      price or metric takes.
    * ``bare`` — a plain integer (counts, horizons, window lengths), in prose or
      beside words in a table cell ("12m mean return"): unchecked. A cell under
      an OHLC column stays measured whatever else it holds.

    Args:
        content: The candidate answer.
        block: The parsed figures block (its spans are exempt).

    Returns:
        Every number in document order, each with its original span and shape.
    """
    view = _normalize(content)
    text = view.text
    line_of: list[tuple[int, int, int]] = [
        (start, start + len(line), index)
        for index, (line, start) in enumerate(_lines_with_offsets(content))
    ]
    fences = _fenced_blocks(content)
    # A fence tagged with a language holds code; an untagged one is how a model
    # sets off a plan or a quote, so its numbers are read as prose.
    hard: list[tuple[int, int]] = [(start, end) for start, end, info, _ in fences if info]
    soft: list[tuple[int, int]] = []
    dates = list(_DATE_RE.finditer(text))
    full_dates = [match for match in dates if match.group("full")]
    for match in dates:
        if match.group("short") and not _short_date_is_structural(text, match, full_dates):
            continue
        span = (view.start(match.start()), view.end(match.end()))
        (soft if match.group("soft") else hard).append(span)
    for pattern in (_CANONICAL_SYMBOL_RE, _ORDINAL_RE):
        hard.extend(
            (view.start(match.start()), view.end(match.end()))
            for match in pattern.finditer(text)
        )
    rows = table_rows(content)
    cells = [
        (start, end, row, position)
        for row in rows
        for position, (_, start, end) in enumerate(row.cells)
    ]
    index_cells = _index_cells(rows)

    figures: list[Figure] = []
    for token in _numbers(text):
        unit, unit_end = _percent_mark(text, token.end)
        reading = _reading(token.sign, token.digits, unit)
        if reading is None:
            continue
        percent = unit > 0
        start, digits_end, end = view.start(token.start), view.end(token.end), view.end(unit_end)
        cell = next((entry for entry in cells if entry[0] <= start and end <= entry[1]), None)
        row, position = (cell[2], cell[3]) if cell else (None, None)
        structural = row is not None and position in (row.date_column, row.symbol_column)
        currency = _currency_before(text, token.start) or _currency_after(text, token.end)
        marked = percent or currency or "." in token.digits
        # A cell that also holds a word is prose set in a table: its plain
        # integer is a count or a horizon, as it would be in a sentence (#1471).
        worded = (
            row is not None
            and position not in row.columns
            and _CELL_WORD_RE.search(row.cells[position][0]) is not None
        )
        if _within((start, digits_end), hard) or (cell is not None and cell[:2] in index_cells):
            shape = "exempt"
        elif structural or _within((start, digits_end), soft):
            priced = row is not None and not structural and position in row.columns
            shape = "measured" if marked or priced else "exempt"
        elif marked or (row is not None and not worded):
            shape = "measured"
        else:
            shape = "bare"
        column = date_value = symbol_value = None
        if row is not None and not structural:
            column = row.columns.get(position)
            if row.date_column is not None and row.date_column < len(row.cells):
                date_value = row.cells[row.date_column][0] or None
            if row.symbol_column is not None and row.symbol_column < len(row.cells):
                symbol_value = row.cells[row.symbol_column][0] or None
        mark_end = _currency_suffix_end(text, magnitude_suffix(text, unit_end)[1])
        figures.append(
            Figure(
                text=content[start:end],
                value=reading[0],
                percent=percent,
                start=start,
                end=end,
                line=next((index for low, high, index in line_of if low <= start <= high), 0),
                shape=shape,
                column=column,
                date=date_value,
                symbol=symbol_value,
                scale=1.0 if percent else magnitude_suffix(text, token.end)[0],
                currency=currency,
                digits=token.digits,
                sign=token.sign,
                extent=(view.start(_currency_prefix_start(text, token.start)), view.end(mark_end)),
                fence=next(
                    (info for low, high, info, _ in fences if low <= start and digits_end <= high),
                    None,
                ),
            )
        )
    return figures
