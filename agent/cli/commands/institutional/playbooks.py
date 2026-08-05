"""Playbook definitions for the institutional research slash commands.

Pure data — this module imports nothing from :mod:`cli`, so
:mod:`cli.commands.slash_router` can pull the command specs at its own import
time without a circular import.

Each :class:`Playbook` carries four things that make the command more than a
prompt forwarder:

1. ``steps`` — an ordered execution skeleton where every step names its
   inputs, the computation, and the artifact it must produce.
2. ``worked_example`` — a fully arithmetic-consistent numeric walkthrough.
   Every number below was computed and reconciled by hand; the totals tie out
   (the Brinson decomposition sums exactly to the active return, the earnings
   bridge sums exactly to the EPS delta). Both the user and the agent can
   reproduce them, which is what makes the skeleton checkable.
3. ``tools`` — the real registered tool names the agent should reach for.
   Verified against ``src/tools/*`` (``get_financial_statements``,
   ``get_stock_profile``, ``get_market_data``, ``get_sec_filings``,
   ``get_macro_series``, ``screen_market``, ``get_stock_news``,
   ``get_research_reports``, ``portfolio_risk_xray``).
4. ``gap_policy`` — what to do when a number cannot be fetched. The shared
   default forbids filling gaps from model memory.

Numbers in the worked examples are illustrative teaching figures, not
quotes for any real security.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    """One step of a playbook's execution skeleton.

    Attributes:
        title: Short imperative label, e.g. ``"Fix the peer set"``.
        inputs: What the step consumes (data, prior-step artifacts).
        compute: The transformation to perform.
        output: The artifact the step must produce before moving on.
    """

    title: str
    inputs: str
    compute: str
    output: str


@dataclass(frozen=True)
class Playbook:
    """A single institutional workflow exposed as a slash command.

    Attributes:
        slug: Slash command keyword, without the leading ``/``.
        summary: One-line description shown in ``/help`` and the typeahead.
        usage: Usage line, e.g. ``"/dcf <ticker> [horizon=5y] [wacc=9%]"``.
        examples: Concrete invocations to show when arguments are missing.
        ask: Friendly follow-up question printed when arguments are missing.
        objective: One sentence stating what a finished run delivers.
        steps: Ordered execution skeleton.
        worked_example: Pre-rendered lines of the numeric walkthrough.
        tools: Registered tool names the agent should prefer.
        aliases: Extra keywords resolving to this command.
    """

    slug: str
    summary: str
    usage: str
    examples: tuple[str, ...]
    ask: str
    objective: str
    steps: tuple[Step, ...]
    worked_example: tuple[str, ...]
    tools: tuple[str, ...]
    aliases: tuple[str, ...] = ()

    @property
    def handler_module(self) -> str:
        """Dotted path of the module exposing ``run(ctx, *args)``."""
        return f"cli.commands.institutional.{self.slug}"


# Shared policy text. Every playbook ships both blocks so the rule travels with
# the prompt rather than living only in a system prompt the user cannot see.
GAP_POLICY: tuple[str, ...] = (
    "Every figure must carry its source: the tool call and the fiscal period it",
    "came from. If a figure cannot be fetched, do NOT substitute a remembered or",
    "typical value. Instead: (a) name the missing item explicitly, (b) mark it",
    "MISSING in the table, (c) continue the analysis with the evidence actually",
    "retrieved, and (d) state which conclusions are now unsupported. A partial",
    "analysis with named holes is the correct deliverable; a complete-looking",
    "analysis with invented inputs is not.",
)

NOT_ADVICE: str = (
    "This is research tooling, not investment advice, and not a recommendation "
    "to buy or sell any security. Outputs are analytical artifacts to be "
    "reviewed by the user."
)


_COMPS = Playbook(
    slug="comps",
    summary="Comparable company analysis (peer multiples -> implied range)",
    usage="/comps <ticker> [peer ...] [--asof YYYY-MM-DD]",
    examples=("/comps AAPL", "/comps 0700.HK 9988.HK BABA", "/comps NVDA AMD AVGO TSM"),
    ask="Which company should I run comps on? Peers are optional — I will build the peer set if you omit them.",
    objective=(
        "Produce a peer multiple table, the subject's premium/discount versus the "
        "peer median, and an implied value RANGE with the operating reason for the gap."
    ),
    steps=(
        Step(
            title="Fix the peer set",
            inputs="Subject ticker; user-supplied peers, or screen_market by sector and size when none are given.",
            compute=(
                "Keep names that share the subject's revenue driver and sit inside a "
                "0.25x-4x market-cap band. Reject everything else."
            ),
            output="Peer table listing each INCLUDED name with its inclusion reason, and each REJECTED name with its rejection reason.",
        ),
        Step(
            title="Pull the raw inputs",
            inputs="get_stock_profile + get_financial_statements (latest annual and quarterly) for the subject and every peer.",
            compute=(
                "Enterprise value = market cap + total debt - cash. Then EV/Sales, "
                "EV/EBITDA and P/E on trailing-twelve-month figures."
            ),
            output="One row per name, every cell tagged with the fiscal period it was taken from.",
        ),
        Step(
            title="Normalize",
            inputs="The raw multiple table from step 2.",
            compute=(
                "Mark negative or non-meaningful EBITDA / earnings as 'nm' — never as "
                "zero, and never dropped silently. Then compute the median and the "
                "25th/75th percentile per multiple."
            ),
            output="Peer median + interquartile range, plus the COUNT of names actually used in each column.",
        ),
        Step(
            title="Position the subject",
            inputs="Subject multiples versus the peer median.",
            compute="Premium/discount in percent for each multiple.",
            output=(
                "One verdict line per multiple, plus the two operating metrics "
                "(revenue growth, margin) that explain the largest gap. A discount is "
                "not a conclusion until it is explained."
            ),
        ),
        Step(
            title="Implied value range",
            inputs="Peer 25th / median / 75th percentile multiple x the subject's own metric.",
            compute="Implied EV -> minus net debt -> implied equity -> divide by diluted shares.",
            output="A RANGE with the spot price marked inside or outside it. Never a single point estimate.",
        ),
    ),
    worked_example=(
        "Subject: TTM revenue 4,000 | TTM EBITDA 800 (20.0% margin) | debt 900 |",
        "cash 400 (net debt 500) | 250m diluted shares | price 22.00",
        "",
        "  market cap = 250 x 22.00                     = 5,500",
        "  EV         = 5,500 + 900 - 400               = 6,000",
        "  EV/EBITDA  = 6,000 / 800                     = 7.50x",
        "",
        "Peer EV/EBITDA sorted: 8.00, 9.20, 10.40, 11.60  (n=4, 0 marked nm)",
        "  P25    = 8.00 + 0.75 x (9.20 - 8.00)         = 8.90x",
        "  median = 9.20 + 0.50 x (10.40 - 9.20)        = 9.80x",
        "  P75    = 10.40 + 0.25 x (11.60 - 10.40)      = 10.70x",
        "",
        "Position: 7.50 / 9.80 - 1                      = -23.5% (discount)",
        "",
        "Implied equity value per share (EV - net debt 500, / 250 shares):",
        "  at P25    8.90 x 800 = 7,120 -> 6,620        = 26.48",
        "  at median 9.80 x 800 = 7,840 -> 7,340        = 29.36",
        "  at P75   10.70 x 800 = 8,560 -> 8,060        = 32.24",
        "  spot 22.00 sits BELOW the P25 case; median implies +33.5%",
        "",
        "Step 4 verdict (the part that is actually analysis):",
        "  subject revenue growth 4% vs peer median 11%. A -23.5% EV/EBITDA",
        "  discount on 7pp less growth is roughly the fair penalty, so the",
        "  gap is EXPLAINED, not an opportunity. The comp set only becomes a",
        "  buy case if the growth gap is closing — check the last 4 quarters",
        "  of year-over-year revenue before concluding anything.",
    ),
    tools=("get_stock_profile", "get_financial_statements", "screen_market", "get_market_data"),
    aliases=("peers",),
)


_DCF = Playbook(
    slug="dcf",
    summary="Discounted cash flow valuation with sensitivity grid",
    usage="/dcf <ticker> [horizon=5] [wacc=9%] [g=2.5%]",
    examples=("/dcf MSFT", "/dcf 600519.SH horizon=10 g=3%", "/dcf TSLA wacc=11%"),
    ask="Which company should I value? Optionally pass horizon, wacc and terminal growth, e.g. /dcf MSFT horizon=5 wacc=9% g=2.5%.",
    objective=(
        "Produce an unlevered DCF: value per share, the terminal-value share of "
        "enterprise value, an exit-multiple cross-check, and a WACC x g sensitivity grid."
    ),
    steps=(
        Step(
            title="Anchor the base year",
            inputs="get_financial_statements — last 3 fiscal years plus trailing twelve months. get_sec_filings for the 10-K when a line item is ambiguous.",
            compute="Revenue, EBIT, effective tax rate, D&A, capex, change in net working capital. Then unlevered FCF = EBIT x (1 - tax) + D&A - capex - dNWC.",
            output="Base-year FCF with every line traced to a specific filing period.",
        ),
        Step(
            title="Set the drivers",
            inputs="History from step 1, plus management guidance if get_stock_news or get_sec_filings surfaces it.",
            compute="Revenue growth path, EBIT margin path, capex and D&A as a percent of revenue converging by the final year, dNWC as a percent of the revenue increment.",
            output="A driver table where every cell is labelled FILED, GUIDED, or ASSUMPTION. No unlabelled numbers.",
        ),
        Step(
            title="Discount rate",
            inputs="get_macro_series for the risk-free rate (e.g. DGS10); beta, equity risk premium, cost of debt, target debt weight.",
            compute="WACC = E/V x (rf + beta x ERP) + D/V x kd x (1 - tax).",
            output="WACC with each input tagged sourced or assumed. The equity risk premium is ALWAYS an assumption — say so.",
        ),
        Step(
            title="Terminal value, computed two ways",
            inputs="Final-year FCF and final-year EBITDA.",
            compute="Gordon growth TV = FCF_N x (1+g) / (WACC - g), with g capped at long-run nominal GDP. Separately, exit-multiple TV = EV/EBITDA x EBITDA_N.",
            output="Both terminal values, the implied exit multiple from the Gordon method, and whether it falls inside the peer range from /comps.",
        ),
        Step(
            title="Bridge to value per share",
            inputs="Discounted explicit-horizon FCF plus discounted terminal value.",
            compute="Enterprise value - net debt + non-operating assets - minority interest = equity value; divide by diluted shares.",
            output="Value per share, percent versus spot, and the terminal-value share of EV.",
        ),
        Step(
            title="Sensitivity, then the honest read",
            inputs="Base case from step 5.",
            compute="3x3 grid: WACC +/-100bp and terminal g +/-50bp.",
            output="The grid, the single driver that moves value most, and the WACC/g pair the CURRENT market price implies. That last number is the useful one.",
        ),
    ),
    worked_example=(
        "Base year: revenue 1,000 | EBIT margin 15% | tax 25% | D&A 60 | capex 80 | dNWC 10",
        "  FCF0 = 150 x 0.75 + 60 - 80 - 10             = 82.5",
        "Drivers: revenue +8%/yr for 5y | margin flat 15% | D&A 6% of revenue",
        "         capex 8% of revenue | dNWC 10% of the revenue increment",
        "",
        "  yr  revenue    EBIT   NOPAT    D&A   capex   dNWC     FCF    DF@9%      PV",
        "   1    1,080   162.0   121.5   64.8    86.4    8.0    91.9   0.9174   84.31",
        "   2    1,166   175.0   131.2   70.0    93.3    8.6    99.3   0.8417   83.54",
        "   3    1,260   189.0   141.7   75.6   100.8    9.3   107.2   0.7722   82.77",
        "   4    1,360   204.1   153.1   81.6   108.8   10.1   115.8   0.7084   82.02",
        "   5    1,469   220.4   165.3   88.2   117.6   10.9   125.0   0.6499   81.26",
        "                                              sum PV(FCF)   =   413.9",
        "",
        "Terminal value, g = 2.5%: (carry the unrounded FCF5 = 125.03, not the",
        "displayed 125.0 — rounding the terminal driver moves EV by ~0.4)",
        "  TV     = 125.03 x 1.025 / (0.09 - 0.025)     = 1,971.6",
        "  PV(TV) = 1,971.6 x 0.6499                    = 1,281.4",
        "  EV     = 413.9 + 1,281.4                     = 1,695.3",
        "  equity = 1,695.3 - net debt 200              = 1,495.3",
        "  per share, 100m shares                       = 14.95   (spot 12.50, +19.6%)",
        "",
        "Two mandatory cross-checks:",
        "  TV share of EV = 1,281.4 / 1,695.3           = 75.6%",
        "    -> above ~75% the answer IS the terminal assumption, so the exit",
        "       multiple check below carries the conclusion, not the 5y forecast.",
        "  implied exit EV/EBITDA = 1,971.6 / (220.4 + 88.2 = 308.6) = 6.39x",
        "    -> inside a 6-9x peer range, so the Gordon g is not smuggling in",
        "       a re-rating. If it landed at 14x, the model would be broken.",
        "",
        "Sensitivity corners (value per share):",
        "  WACC 8.0%, g 2.5%: PV(FCF) 425.5 + PV(TV) 1,586.0 -> equity 1,811.5 = 18.12",
        "  WACC 9.0%, g 2.5%: base case                                        = 14.95",
        "  WACC 10.0%, g 2.0%: PV(FCF) 402.8 + PV(TV) 989.8 -> equity 1,192.6  = 11.93",
        "",
        "The deliverable is NOT 'worth 14.95'. It is: the market's 12.50 sits",
        "just above the WACC 10% / g 2.0% corner, so the price is already",
        "discounting a ~10% cost of capital and near-zero real terminal growth.",
        "The question to research next is whether that is too harsh.",
    ),
    tools=("get_financial_statements", "get_sec_filings", "get_macro_series", "get_stock_profile"),
)


_ATTRIB = Playbook(
    slug="attrib",
    summary="Brinson-Fachler attribution (allocation vs selection)",
    usage="/attrib <portfolio-or-holdings> [--benchmark SPY] [--from YYYY-MM-DD] [--to YYYY-MM-DD]",
    examples=(
        "/attrib my portfolio --benchmark SPY --from 2026-01-01",
        "/attrib AAPL:0.3 MSFT:0.4 XOM:0.3 --benchmark SPY",
        "/attrib holdings.csv --benchmark 000300.SH",
    ),
    ask="Which portfolio should I attribute, and against which benchmark? e.g. /attrib holdings.csv --benchmark SPY --from 2026-01-01",
    objective=(
        "Decompose active return into allocation, selection and interaction per "
        "sector, reconcile the decomposition to the total active return, and state "
        "whether the alpha came from the source the mandate promised."
    ),
    steps=(
        Step(
            title="Fix the weights",
            inputs="Portfolio holdings and weights at the START of the window; benchmark weights; a sector map for both.",
            compute="Normalize both weight vectors to 100%. Assign every name a sector.",
            output="Two weight vectors that each sum to 100%, plus the unclassified residual named explicitly rather than dumped into 'Other'.",
        ),
        Step(
            title="Get returns",
            inputs="get_market_data over the window for every holding, every benchmark constituent (or the benchmark's own sector series), and the benchmark itself.",
            compute="Sector return = weight-averaged constituent return, computed separately for the portfolio (Rp_i) and the benchmark (Rb_i).",
            output="Rp_i and Rb_i per sector, plus total Rp and Rb.",
        ),
        Step(
            title="Decompose",
            inputs="Weights from step 1 and returns from step 2.",
            compute=(
                "Per sector i:  allocation = (wp_i - wb_i) x (Rb_i - Rb); "
                "selection = wb_i x (Rp_i - Rb_i); "
                "interaction = (wp_i - wb_i) x (Rp_i - Rb_i)."
            ),
            output="A per-sector table with the three effects and their column totals.",
        ),
        Step(
            title="Reconcile — this step is a gate",
            inputs="Column totals from step 3 and the total active return Rp - Rb.",
            compute="sum(allocation + selection + interaction) versus (Rp - Rb).",
            output=(
                "The residual. If it exceeds 1bp, STOP and report the gap and its "
                "likely cause (intra-period trades, cash, corporate actions, FX). Do "
                "not present an attribution table that does not tie out."
            ),
        ),
        Step(
            title="Attribute the residual",
            inputs="The gap from step 4 plus the trade log if available.",
            compute="Split into trading/timing, cash drag, and FX translation.",
            output="Each named with a number. Whatever remains is reported as unexplained — never absorbed into selection.",
        ),
        Step(
            title="Mandate verdict",
            inputs="The allocation-versus-selection split.",
            compute="Share of active return from each source.",
            output="A one-line verdict on whether the return came from the skill the mandate is paid for, and whether the top contributor is repeatable or a single lucky tilt.",
        ),
    ),
    worked_example=(
        "Benchmark:  Tech wb 50%, Rb 10.0% | Health wb 30%, Rb 4.0% | Energy wb 20%, Rb -2.0%",
        "Portfolio:  Tech wp 60%, Rp 12.0% | Health wp 30%, Rp 3.0% | Energy wp 10%, Rp -1.0%",
        "",
        "  Rb = 0.50x10.0 + 0.30x4.0 + 0.20x(-2.0)      = 5.80%",
        "  Rp = 0.60x12.0 + 0.30x3.0 + 0.10x(-1.0)      = 8.00%",
        "  active return                                = +2.20%",
        "",
        "  sector    alloc (wp-wb)(Rb_i-Rb)   selection wb(Rp_i-Rb_i)   interaction",
        "  Tech      (0.10)(10.0-5.80)=+0.420  (0.50)(12.0-10.0)=+1.000   +0.200",
        "  Health    (0.00)(4.0-5.80) = 0.000  (0.30)(3.0- 4.0)=-0.300    0.000",
        "  Energy    (-0.10)(-2.0-5.80)=+0.780 (0.20)(-1.0-(-2.0))=+0.200 -0.100",
        "  total                       +1.200                    +0.900   +0.100",
        "",
        "  reconciliation: 1.200 + 0.900 + 0.100        = 2.200 = active   PASS",
        "",
        "Step 6 verdict (the part that is actually analysis):",
        "  55% of the +220bp is ALLOCATION, and +78bp of that is a single",
        "  Energy underweight in a sector that fell 2%. Selection contributed",
        "  +90bp, of which +100bp is Tech stock picking partly given back by",
        "  -30bp in Health. For a stock-selection mandate this is an OFF-MANDATE",
        "  quarter: the headline beat is mostly one sector tilt, which is one",
        "  decision, not a repeatable process. Report it that way.",
    ),
    tools=("get_market_data", "portfolio_risk_xray", "get_sector_info", "get_stock_profile"),
    aliases=("attribution",),
)


_MEMO = Playbook(
    slug="memo",
    summary="Investment memo — thesis, variant view, scenarios, kill criteria",
    usage="/memo <ticker> [long|short] [horizon=12m]",
    examples=("/memo NVDA long", "/memo BABA short horizon=6m", "/memo 005930.KS"),
    ask="Which company should the memo cover? Optionally say long or short and a horizon, e.g. /memo NVDA long horizon=12m.",
    objective=(
        "Produce a decision-ready memo: a one-sentence thesis, the variant view, "
        "probability-weighted scenarios, falsifiable kill criteria, and the "
        "quarterly monitoring set."
    ),
    steps=(
        Step(
            title="Thesis and variant view",
            inputs="get_research_reports and get_stock_news for what consensus currently believes.",
            compute="State consensus in one sentence, your view in one sentence, and the specific fact or mechanism that separates them.",
            output="If you cannot name what you believe that consensus does not, there is no memo — say so and stop.",
        ),
        Step(
            title="Business and unit economics",
            inputs="get_stock_profile, get_financial_statements, get_sec_filings (segment disclosure).",
            compute="Revenue drivers (volume x price x mix), contribution margin, what one marginal unit earns and how that trends.",
            output="A driver tree where the top line decomposes into things that can be independently observed.",
        ),
        Step(
            title="The numbers",
            inputs="Three years of history plus your forecast.",
            compute="Growth, margins, returns on capital, cash conversion, leverage.",
            output="A table where each historical cell cites a filing period and each forecast cell cites the step-2 driver it comes from.",
        ),
        Step(
            title="Valuation with two independent anchors",
            inputs="A /dcf run and a /comps run.",
            compute="Bear / base / bull value per share, with an explicit probability on each. Expected value = sum(probability x value).",
            output="The three cases, the expected value, the upside/downside skew, and the break-even probability of the base case.",
        ),
        Step(
            title="What kills it",
            inputs="The driver tree from step 2.",
            compute="Three risks, each expressed as an observable metric with a numeric threshold.",
            output="'Thesis is wrong if X falls below Y for two consecutive quarters' — falsifiable. 'Competition may intensify' is not a risk, it is filler.",
        ),
        Step(
            title="Monitoring set",
            inputs="Step 5 thresholds.",
            compute="Pick the three datapoints that move first when the thesis breaks.",
            output="Three metrics, their release cadence, their current value, and the exit trigger.",
        ),
    ),
    worked_example=(
        "Step 4 scenario math, spot 12.50:",
        "",
        "  case    prob    value/share   source",
        "  bear    25%          9.00     comps at peer P25 on trough EBITDA",
        "  base    50%         15.00     DCF, WACC 9.0%, g 2.5%",
        "  bull    25%         22.00     DCF, margin path to 19% by year 5",
        "",
        "  expected value = 0.25x9.00 + 0.50x15.00 + 0.25x22.00",
        "                 = 2.25 + 7.50 + 5.50           = 15.25   (+22.0% vs spot)",
        "  downside = 9.00/12.50 - 1                     = -28.0%",
        "  upside   = 22.00/12.50 - 1                    = +76.0%",
        "  skew     = 76.0 / 28.0                        = 2.7 : 1",
        "",
        "  break-even test — hold bear at 25% and solve for the bull weight p",
        "  that makes expected value equal the 12.50 spot:",
        "    2.25 + (0.75 - p)x15.00 + p x 22.00 = 12.50",
        "    13.50 + 7.00p = 12.50   ->   p = -0.14",
        "",
        "  A NEGATIVE break-even weight means even with zero probability on the",
        "  bull case the expected value (2.25 + 0.75x15.00 = 13.50) still clears",
        "  the spot price. So the position does not depend on the bull case at",
        "  all — it depends entirely on the base case being right. That redirects",
        "  the remaining work: stop arguing the upside, stress-test the 15.00.",
        "  Concretely, the base case fails if the 15% EBIT margin is not held;",
        "  at 12% margin the same DCF gives roughly 11.60, below spot.",
    ),
    tools=(
        "get_financial_statements",
        "get_sec_filings",
        "get_stock_profile",
        "get_research_reports",
        "get_stock_news",
    ),
)


_EARNINGS = Playbook(
    slug="earnings",
    summary="Earnings review — surprise bridge from revenue to EPS",
    usage="/earnings <ticker> [quarter=Q3-2026]",
    examples=("/earnings AAPL", "/earnings MSFT quarter=Q2-2026", "/earnings 0700.HK"),
    ask="Whose earnings should I review? e.g. /earnings AAPL quarter=Q3-2026 (quarter defaults to the most recent report).",
    objective=(
        "Turn a headline beat or miss into a line-by-line bridge, separate the "
        "recurring operating surprise from the non-recurring one, and state what "
        "actually changed in the model."
    ),
    steps=(
        Step(
            title="Pull the print",
            inputs="get_financial_statements for the latest quarter; get_sec_filings for the 8-K / 10-Q; get_stock_news or get_research_reports for the consensus figure.",
            compute="Line up actual versus consensus for revenue, gross margin, opex, tax rate, share count, EPS.",
            output="A two-column table. The consensus column is tagged SOURCED or ASSUMPTION — a remembered consensus number is an ASSUMPTION and must be labelled one.",
        ),
        Step(
            title="Build the bridge",
            inputs="The step-1 table.",
            compute=(
                "Walk from consensus EPS to actual EPS ONE variable at a time, holding "
                "the others at consensus, then re-baselining after each step. Order: "
                "revenue, gross margin, opex, below-the-line, tax rate, share count."
            ),
            output="A bridge whose steps sum EXACTLY to actual EPS minus consensus EPS. If it does not sum, a variable is missing — find it before writing anything.",
        ),
        Step(
            title="Grade the quality",
            inputs="The bridge.",
            compute="Split each step into recurring operating (volume, price, mix, structural cost) and non-recurring (one-off tax items, buybacks, FX, asset sales, legal reversals).",
            output="Operating-only surprise versus headline surprise, as a number and as a percentage of the headline.",
        ),
        Step(
            title="Guidance delta",
            inputs="New guidance versus prior guidance versus consensus for the year.",
            compute="Implied remainder of the year = full-year guide minus reported year-to-date.",
            output="Whether the implied remainder is an acceleration or a quiet cut hidden by a strong quarter already banked.",
        ),
        Step(
            title="What changed in the model",
            inputs="Steps 3 and 4.",
            compute="The three inputs whose forward path you now revise, and the resulting change in fair value.",
            output="Old fair value, new fair value, and the single line item responsible for most of the change.",
        ),
    ),
    worked_example=(
        "Consensus: revenue 1,000 | GM 60.0% | opex 400 | interest -20 | tax 25%",
        "           | 100.0m shares -> EPS 1.35",
        "Actual:    revenue 1,050 | GM 58.5% | opex 405 | interest -20 | tax 22%",
        "           |  99.0m shares -> EPS 1.49",
        "",
        "Bridge, one variable at a time, re-baselining after each step:",
        "  start (consensus)                                        EPS 1.3500",
        "  + revenue 1,000 -> 1,050 at 60% GM   GP 630, NI 157.50    EPS 1.5750   +0.2250",
        "  + GM 60.0% -> 58.5%                  GP 614.25, NI 145.69 EPS 1.4569   -0.1181",
        "  + opex 400 -> 405                    NI 141.94            EPS 1.4194   -0.0375",
        "  + tax 25% -> 22%                     NI 147.62            EPS 1.4762   +0.0568",
        "  + shares 100.0m -> 99.0m             NI 147.62            EPS 1.4911   +0.0149",
        "  sum of steps = 0.2250-0.1181-0.0375+0.0568+0.0149        = +0.1411",
        "  check: 1.4911 - 1.3500                                   = +0.1411  PASS",
        "",
        "Step 3 quality grade (the part that is actually analysis):",
        "  recurring operating  = +0.2250 - 0.1181 - 0.0375         = +0.0694",
        "  non-recurring        = +0.0568 (one-off R&D tax credit)",
        "                       + 0.0149 (buyback)                  = +0.0717",
        "  non-recurring share of the headline beat = 0.0717/0.1411 = 50.8%",
        "",
        "  So 'beat by 14 cents on a 5% revenue beat' is really a 7-cent",
        "  operating beat. The 5% volume upside was half given back by a 150bp",
        "  mix-driven gross margin decline — that mix shift is the datapoint",
        "  that changes the model, not the EPS headline. Check whether the",
        "  lower-margin revenue is a one-quarter mix accident or the new run rate.",
    ),
    tools=(
        "get_financial_statements",
        "get_sec_filings",
        "get_stock_news",
        "get_research_reports",
        "get_market_data",
    ),
)


_SCREEN = Playbook(
    slug="screen",
    summary="Systematic idea screen — hypothesis, funnel, survivor queue",
    usage="/screen <hypothesis or criteria> [--universe sp500|csi300|...]",
    examples=(
        "/screen quality compounders trading below 15x FCF --universe sp500",
        "/screen ROIC > 12% and net debt/EBITDA < 2 --universe csi300",
        "/screen oversold industrials with rising order books",
    ),
    ask="What should I screen for? Give me the economic hypothesis or the hard criteria, e.g. /screen quality compounders below 15x FCF --universe sp500",
    objective=(
        "Turn a hypothesis into hard thresholds, run the screen, publish the funnel "
        "count at every filter, and hand back a de-duplicated research queue with an "
        "honest false-positive caveat."
    ),
    steps=(
        Step(
            title="State the hypothesis first",
            inputs="The user's words.",
            compute="Write the economic mechanism in one sentence BEFORE choosing any threshold, so the filters are derived from the idea rather than reverse-engineered from a pretty result.",
            output="One sentence. If the hypothesis cannot be stated without referring to the metrics, it is a data-mining exercise — label it as one.",
        ),
        Step(
            title="Translate to hard criteria",
            inputs="The hypothesis.",
            compute="Each clause becomes a metric with a numeric threshold and a direction. Every threshold gets a one-line justification.",
            output="A criteria table: metric, operator, threshold, why this number.",
        ),
        Step(
            title="Run the funnel",
            inputs="screen_market over the stated universe, then get_financial_statements for any criterion the screener cannot express.",
            compute="Apply filters in order, from cheapest and most eliminating to most expensive.",
            output="The FUNNEL: the surviving count after every single filter. A screen that only reports the final list is unreviewable.",
        ),
        Step(
            title="Data-completeness pass",
            inputs="The survivor list.",
            compute="Drop names missing an input for a binding criterion.",
            output="Names dropped for missing data are listed SEPARATELY from names dropped for failing a test. Conflating the two silently biases the result toward well-covered large caps.",
        ),
        Step(
            title="De-duplicate by driver",
            inputs="Survivors.",
            compute="Group names sharing one underlying driver (same commodity, same customer, same rate sensitivity).",
            output="One representative per cluster plus the cluster members, so the queue is not five bets on one macro variable.",
        ),
        Step(
            title="Hand back a queue, not a portfolio",
            inputs="The de-duplicated survivors.",
            compute="For each name: the single metric it is weakest on, and the one question to answer first.",
            output=(
                "A ranked research queue plus a threshold-sensitivity caveat stated in "
                "numbers: re-run the funnel with each threshold loosened one notch and "
                "report how much of the survivor set is an artifact of where the lines "
                "were drawn. Never quote a per-name false-positive rate — a deterministic "
                "screen is not a hypothesis test and has none."
            ),
        ),
    ),
    worked_example=(
        "Hypothesis: 'Businesses that earn well above their cost of capital and",
        "are not levered can reinvest through a downturn; the market underpays",
        "for that when the free cash flow yield is already high.'",
        "",
        "Criteria and funnel (universe: 3,200 listed names):",
        "  filter                                  surviving   removed",
        "  start                                       3,200",
        "  market cap >= 2.0bn (liquidity)                812    -2,388",
        "  ROIC >= 12% (above cost of capital)            245      -567",
        "  net debt/EBITDA <= 2.0 (survives a downturn)    96      -149",
        "  FCF yield >= 5% (the underpayment)              31       -65",
        "  data-completeness pass (step 4)                 19       -12  MISSING DATA",
        "  de-duplicate by driver (step 5)                  6       -13  same driver",
        "",
        "  the 12 dropped for missing data are listed by name and by which",
        "  field was absent; they are NOT counted as failures.",
        "  the 13 collapsed names are 6 semis-cycle, 4 US housing, 3 freight.",
        "",
        "Step 6 caveat, stated in numbers rather than hedged in prose:",
        "  A screen is a deterministic filter on observed data, so there is no",
        "  per-name 'false positive rate' to quote — the selection risk lives in",
        "  the CHOICE of the 4 thresholds, not in the 3,200 rows. Size it that way:",
        "  the funnel keeps 31/3,200 = 0.97% of the universe, so moving any one",
        "  threshold by a notch (ROIC 12% -> 10%, FCF yield 5% -> 4%) is what to",
        "  report. Here that widens 31 -> 74, i.e. 58% of the survivor set is an",
        "  artifact of where the lines were drawn rather than a stable property.",
        "  So the screen cannot establish that these 6 names are good; it can only",
        "  establish that they are worth the next 6 hours. Treat the output as a",
        "  research queue and require an out-of-sample or fundamental confirmation",
        "  before any of it becomes a position.",
    ),
    tools=("screen_market", "get_financial_statements", "get_stock_profile", "iwencai_search"),
    aliases=("screener",),
)


PLAYBOOKS: tuple[Playbook, ...] = (_COMPS, _DCF, _ATTRIB, _MEMO, _EARNINGS, _SCREEN)

PLAYBOOKS_BY_SLUG: dict[str, Playbook] = {pb.slug: pb for pb in PLAYBOOKS}


__all__ = [
    "GAP_POLICY",
    "NOT_ADVICE",
    "PLAYBOOKS",
    "PLAYBOOKS_BY_SLUG",
    "Playbook",
    "Step",
]
