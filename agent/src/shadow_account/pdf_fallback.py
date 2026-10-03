"""Shadow Account — pure-Python PDF fallback renderer.

weasyprint renders the faithful PDF, but it needs system libraries
(pango/cairo) that pip cannot install, so hosts without them used to get
HTML-only reports. This module renders the same section payload with
reportlab platypus: identical data, intentionally simpler layout. All
reportlab imports stay inside functions so importing this module costs
nothing on hosts that never need the fallback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from xml.sax.saxutils import escape

from .fonts import system_cjk_candidates

logger = logging.getLogger(__name__)

# reportlab's TTFont only understands TrueType-flavored fonts. The first
# candidate that registers wins; .ttc files are tried with subfontIndex=0.
_FONT_FAMILY = "VibeShadowCJK"
_font_ready: bool = False  # probe ran; says nothing about what it found
_font_family: str = _FONT_FAMILY  # family actually usable after the probe


def _ensure_font() -> str:
    """Register a CJK-capable TTF once and return the family name to use."""
    global _font_ready, _font_family
    if _font_ready:
        return _font_family

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    bundled = Path(__file__).parent / "assets" / "VibeCJK-Regular.ttf"
    for path in [bundled, *system_cjk_candidates()]:
        try:
            pdfmetrics.registerFont(TTFont(_FONT_FAMILY, str(path), subfontIndex=0))
        except Exception:
            continue
        _font_ready = True
        _font_family = _FONT_FAMILY
        return _font_family

    # An unembedded CID face can parse correctly yet render as a blank page
    # in viewers without an Asian language pack. Never return such a PDF.
    raise RuntimeError("No embeddable CJK font found; reinstall the package's bundled font asset")


def _file_uri_to_path(uri: str) -> Path | None:
    """Convert a file:// URI back to a local path, or None if not a file URI."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    return Path(url2pathname(unquote(parsed.path)))


def _signed(value: float, digits: int = 2) -> str:
    return f"{value:+.{digits}f}"


def _colored(value: float, text: str) -> str:
    color = "#1f7a3a" if value > 0 else "#c0392b" if value < 0 else "#444444"
    return f'<font color="{color}">{escape(text)}</font>'


def render_pdf_reportlab(
    *,
    sections: dict[str, Any],
    charts: dict[str, str],
    market_labels: dict[str, str],
    reason_labels: dict[str, str],
    pdf_path: Path,
) -> None:
    """Render the 8-section shadow report to ``pdf_path`` via reportlab.

    Raises on any failure; the caller decides whether to fall back to
    HTML-only output.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    family = _ensure_font()

    def style(name: str, size: int, leading: float, **kw: Any) -> ParagraphStyle:
        return ParagraphStyle(
            name, fontName=family, fontSize=size, leading=leading, **kw
        )

    h1 = style("h1", 22, 27, spaceAfter=4 * mm, keepWithNext=True)
    h2 = style(
        "h2",
        13,
        17,
        spaceBefore=6 * mm,
        spaceAfter=2.5 * mm,
        textColor=colors.HexColor("#1a1a2e"),
        keepWithNext=True,
    )
    body = style("body", 9.5, 14)
    muted = style("muted", 8.5, 12, textColor=colors.HexColor("#777777"))
    eyebrow = style("eyebrow", 10, 13, textColor=colors.HexColor("#777777"))
    big = style("big", 20, 24, spaceBefore=2 * mm, spaceAfter=1 * mm)
    cell = style("cell", 8.5, 11)
    header_cell = style("hcell", 8.5, 11, textColor=colors.white)

    page_width = A4[0] - 30 * mm

    def para(text: str, st: ParagraphStyle = cell) -> Paragraph:
        # Caller passes raw strings; markup is only added by _colored.
        return Paragraph(escape(text), st)

    def make_table(
        header: list[str], rows: list[list[Any]], widths: list[float] | None = None
    ) -> Table:
        data: list[list[Any]] = []
        if header:
            data.append([Paragraph(escape(h), header_cell) for h in header])
        for row in rows:
            data.append([c if isinstance(c, Paragraph) else para(str(c)) for c in row])
        col_widths = [w * page_width for w in widths] if widths else None
        table = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
        style_rules = [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if header:
            style_rules += [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f7f7fa")],
                ),
            ]
        else:
            style_rules.append(
                (
                    "ROWBACKGROUNDS",
                    (0, 0),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f7f7fa")],
                )
            )
        table.setStyle(TableStyle(style_rules))
        return table

    def chart_image(key: str) -> Image | None:
        uri = charts.get(key)
        if not uri:
            return None
        path = _file_uri_to_path(uri)
        if path is None or not path.exists():
            return None
        from reportlab.lib.utils import ImageReader

        width_px, height_px = ImageReader(str(path)).getSize()
        height = page_width * height_px / width_px
        return Image(str(path), width=page_width, height=height)

    profile = sections["profile"]
    attribution = sections["attribution"]
    shadow_pnl = sections["shadow_pnl"]
    real_pnl = sections["real_pnl"]
    delta_pnl = sections["delta_pnl"]

    def market_label(code: str) -> str:
        return market_labels.get(code, code)

    story: list[Any] = []

    # Cover
    story.append(Paragraph("Shadow Account Report", eyebrow))
    story.append(Paragraph("You vs Your Shadow", h1))
    story.append(para(f"{profile.shadow_id} | {profile.created_at}", muted))
    story.append(Spacer(1, 3 * mm))
    story.append(para("Delta PnL", muted))
    if delta_pnl is not None:
        story.append(Paragraph(_colored(delta_pnl, _signed(delta_pnl)), big))
        story.append(para(f"Shadow {shadow_pnl:.2f} | Real {real_pnl:.2f}", muted))
    else:
        story.append(
            para(
                "unavailable - the shadow backtest produced no usable metrics, "
                "so no comparison is shown",
                muted,
            )
        )
    story.append(Spacer(1, 2 * mm))
    story.append(
        para(
            "Research use only - not investment advice. "
            f"Data window: {profile.date_range[0]} -> {profile.date_range[1]}",
            muted,
        )
    )

    # 1. Profile
    story.append(Paragraph("1. Your Shadow Profile", h2))
    story.append(para(profile.profile_text, body))
    story.append(Spacer(1, 1.5 * mm))
    facts = [
        [
            "Profitable roundtrips",
            f"{profile.profitable_roundtrips} / {profile.total_roundtrips}",
        ],
        ["Primary market", market_label(profile.source_market)],
        [
            "Holding median / p75",
            f"{profile.typical_holding_days[0]:.1f}d / {profile.typical_holding_days[1]:.1f}d",
        ],
        [
            "Preferred markets",
            ", ".join(market_label(m) for m in profile.preferred_markets),
        ],
    ]
    story.append(make_table([], facts, widths=[0.3, 0.7]))

    # 2. Rules
    story.append(Paragraph("2. Shadow Rules", h2))
    rule_rows = [
        [
            r.rule_id,
            para(r.human_text),
            str(r.support_count),
            f"{r.coverage_rate * 100:.0f}%",
            f"{r.holding_days_range[0]}-{r.holding_days_range[1]}d",
        ]
        for r in profile.rules
    ]
    story.append(
        make_table(
            ["ID", "Rule", "Support", "Coverage", "Holding"],
            rule_rows,
            widths=[0.08, 0.56, 0.12, 0.12, 0.12],
        )
    )

    # 3. Combined backtest
    story.append(Paragraph("3. Shadow Backtest - Combined", h2))
    img = chart_image("equity_curve")
    if img is not None:
        story.append(img)
    combined_error = sections.get("combined_error") or ""
    if combined_error:
        story.append(para(f"Backtest warning: {combined_error}", muted))
    combined_metrics = sections["combined_metrics"]
    if combined_metrics:
        story.append(
            make_table(
                [],
                [[k, f"{v:.4f}"] for k, v in combined_metrics.items()],
                widths=[0.5, 0.5],
            )
        )
    else:
        story.append(
            para("Backtest produced no usable metrics (see warning above).", muted)
        )

    # 4. Per-market backtest
    story.append(Paragraph("4. Shadow Backtest - By Market", h2))
    img = chart_image("per_market_bar")
    if img is not None:
        story.append(img)
    market_rows = [
        [
            market_label(market),
            f"{metrics.get('sharpe', 0.0):.2f}",
            f"{metrics.get('annual_return', 0.0) * 100:.2f}%",
            f"{metrics.get('max_drawdown', 0.0) * 100:.2f}%",
        ]
        for market, metrics in sections["per_market_metrics"].items()
    ]
    story.append(
        make_table(
            ["Market", "Sharpe", "Annual", "Max Drawdown"],
            market_rows,
            widths=[0.4, 0.2, 0.2, 0.2],
        )
    )

    # 5. Delta attribution
    story.append(Paragraph("5. You vs Shadow - Delta Attribution", h2))
    if shadow_pnl is not None:
        lede = (
            f"Shadow PnL {_colored(shadow_pnl, _signed(shadow_pnl))}, "
            f"your real PnL {_colored(real_pnl, _signed(real_pnl))}, "
            f"delta {_colored(delta_pnl, _signed(delta_pnl))}."
        )
        story.append(Paragraph(lede, body))
    else:
        story.append(
            para(
                "The shadow backtest did not produce usable metrics, so Shadow PnL, "
                "delta, and the attribution below are not computed for this run.",
                muted,
            )
        )
    img = chart_image("attribution_waterfall")
    if img is not None:
        story.append(img)

    def attr_row(label: str, value: float) -> list[Any]:
        return [label, Paragraph(_colored(value, _signed(value)), cell)]

    story.append(
        make_table(
            [],
            [
                attr_row("Noise trades", attribution.noise_trades_pnl),
                attr_row("Early exit (winners)", attribution.early_exit_pnl),
                attr_row("Late exit (losers)", attribution.late_exit_pnl),
                attr_row("Overtrading", attribution.overtrading_pnl),
                attr_row("Missed signals (residual)", attribution.missed_signals_pnl),
            ],
            widths=[0.5, 0.5],
        )
    )
    if attribution.excluded_currencies:
        excluded = ", ".join(
            f"{count} in {currency}"
            for currency, count in attribution.excluded_currencies.items()
        )
        story.append(
            para(
                "Real PnL above covers the shadow pool's settlement currency only. "
                "There is no FX translation layer, so roundtrips settling elsewhere "
                f"are excluded rather than summed against it: {excluded}.",
                muted,
            )
        )

    # 6. Counterfactual top 5
    story.append(Paragraph("6. Counterfactual Top 5", h2))
    if attribution.counterfactual_trades:
        cf_rows = [
            [
                str(i),
                t["symbol"],
                str(t["buy_dt"])[:10],
                str(t["sell_dt"])[:10],
                f"{t['hold_days']:.1f}d",
                Paragraph(_colored(t["pnl"], _signed(t["pnl"])), cell),
                Paragraph(_colored(t["impact"], _signed(t["impact"])), cell),
                para(reason_labels.get(t["reason"], t["reason"])),
            ]
            for i, t in enumerate(attribution.counterfactual_trades, start=1)
        ]
        story.append(
            make_table(
                ["#", "Symbol", "Buy", "Sell", "Hold", "Real PnL", "Impact", "Reason"],
                cf_rows,
                widths=[0.05, 0.13, 0.13, 0.13, 0.09, 0.13, 0.13, 0.21],
            )
        )
    else:
        story.append(
            para(
                "No material counterfactual trades - every roundtrip falls inside the shadow rules.",
                muted,
            )
        )

    # 7. Today's signals
    story.append(Paragraph("7. Today's Signal Scan", h2))
    today_signals = sections["today_signals"]
    if today_signals:
        signal_rows = [
            [
                s["symbol"],
                market_label(s["market"]),
                s["rule_id"],
                para(str(s["reason"])),
            ]
            for s in today_signals
        ]
        story.append(
            make_table(
                ["Symbol", "Market", "Rule", "Reason"],
                signal_rows,
                widths=[0.16, 0.2, 0.12, 0.52],
            )
        )
    else:
        story.append(para("No shadow-matching symbols today (or scan skipped).", muted))
    story.append(
        para("For research reference only - not a buy/sell recommendation.", muted)
    )

    # 8. Caveats
    story.append(Paragraph("8. Confidence &amp; Caveats", h2))
    caveats = [
        f"Sample size: {profile.profitable_roundtrips} profitable roundtrips support {len(profile.rules)} rule(s).",
        "Backtest assumptions: slippage/fees use engine defaults; cross-market annualization uses calendar days.",
        "Style decay: rules reflect the user's historical window and may not hold in future regimes.",
        "Red line: this report is research-only and never routes to any live trading system.",
    ]
    for caveat in caveats:
        story.append(para(f"• {caveat}", body))

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Shadow Account Report - {profile.shadow_id}",
    )
    doc.build(story)
