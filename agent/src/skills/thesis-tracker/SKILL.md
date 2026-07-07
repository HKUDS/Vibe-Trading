---
name: thesis-tracker
category: strategy
description: "Buy-side discipline system. For each holding, maintain a written investment thesis — core thesis in 5 sentences, falsifiable assumptions, red lines, valuation anchors — and re-check it each quarter against new earnings/events. Scores thesis health 1-10 from assumption breakage and red-line triggers, and recommends hold / add / trim / exit. Use it right after buying a stock (to write the thesis) and every earnings season (to check it). Bridges the research→buy→monitor gap that most investors skip."
---

# Investment Thesis Tracker: Post-Buy Discipline

Track an investment thesis for a holding. First use on a company → build the thesis; later uses → quarterly check.

**Supported input**: company name (auto-decide build vs track); `company build` (force rebuild); `company quarterly check` (against latest earnings).

> "Buying is only the beginning. The real work is continuous tracking through the holding period." — Li Lu
>
> "When the facts change, I change my mind. What do you do, sir?" — Keynes

## Design Philosophy

Most investors' process is: research → buy → pray. Without systematic post-buy tracking, they: refuse to sell when they should ("wait, it'll come back"); panic-sell when they shouldn't ("down 20%, was I wrong?"); forget why they bought ("why did I buy this again?").

Buffett and Li Lu write down sell conditions **before** buying, then check the thesis each quarter.

## Step 1: Decide the Mode

Check whether a thesis file already exists (use `read_file` on `reports/{company}-thesis.md`): not found → **Build** (Mode A); found → **Track** (Mode B).

---

## Mode A: Build the Investment Thesis

### A0: Data Collection

Use `web_search` to get the current price, valuation (PE/PB/dividend yield), and latest financials. If a research report exists, `read_file` it first. Use `financial_rigor` (`command=verify_valuation`) to verify valuation, `financial_rigor` (`command=verify_market_cap`) to sanity-check market cap.

### A1: Core Thesis (must be writable in ≤200 words)

The thesis must answer 5 questions, one sentence each:

```
I bought {Company} at {price} because:
1. The essence of this business is ___, and I understand how it makes money.
2. Its moat is ___, and it's widening / stable.
3. Management is ___, trustworthy because ___.
4. The current price is a {discount}% to intrinsic value; the margin of safety comes from ___.
5. Even if I'm wrong, downside is contained because ___.
```

**If you can't fill 5 sentences, the thesis itself is flawed — the buy decision isn't clear enough.**

### A2: Core Assumptions List

Break the thesis into verifiable assumptions (3-7 typically; too few = shallow thinking, too many = unfocused):

| # | Core Assumption | How to verify | Frequency | Status |
|---|-----------------|---------------|-----------|--------|
| 1 | e.g. revenue growth stays >15% | Quarterly revenue growth | Quarterly | 🟢 Holding |
| 2 | e.g. gross margin stable >60% | Quarterly gross margin | Quarterly | 🟢 Holding |

### A3: Red Lines (triggering any one = must re-evaluate)

| # | Red-line condition | Severity | Action on trigger |
|---|--------------------|----------|-------------------|
| 1 | Management integrity problem (fraud, related-party) | Fatal | Exit immediately |
| 2 | Core business revenue down 2 consecutive quarters | Severe | Trim 50%, re-evaluate |
| 3 | Moat explicitly breached (competitor reaches parity) | Severe | Deep research, consider exit |
| 4 | Regulatory change fundamentally alters the business model | Severe | Re-value intrinsic value |
| 5 | Management large unplanned disposal | Warning | Investigate |
| 6 | **Macro trend reversal for this name's end-market** — e.g. demographic clock (population decline) for consumer/property/education names; consumption downgrade (居民边际消费下降); generational shift away from the category | Severe | Re-evaluate the long-term demand base; for consumer-dependent names, this is often a slow-moving but fatal headwind — assess whether the thesis still holds at a structurally lower growth path |

> The red line on macro trends (demographic clock / consumption / generational) is deliberately explicit: a value-investing thesis that picks a consumer name without weighing population decline and consumption-trend headwinds is incomplete. For non-consumer names (e.g. pure B2B industrial), this red line may be loose; for consumer/retail/education/property names, weight it heavily.

> Duan Yongping: "There are only three reasons to sell: 1. you got the buy wrong; 2. the fundamentals changed; 3. you found something better."

### A4: Valuation Anchors

| Metric | At buy | Optimistic target | Neutral target | Pessimistic |
|--------|--------|-------------------|-----------------|-------------|
| Price | | | | |
| PE (TTM) | | | | |
| Market cap | | | | |
| Intrinsic value estimate | | | | |
| Margin of safety | | | | |

### A5: Save the Thesis

Use `write_file` to write `reports/{company}-thesis.md`, including: build date, buy price and position, core thesis (5 sentences), assumptions list, red lines, valuation anchors, tracking table (empty initially).

---

## Mode B: Tracking Check

### B1: Read the Existing Thesis

Use `read_file` to load core thesis, assumptions, red lines, last check record.

### B2: Gather Latest Data

Use `web_search` / `get_stock_news` / `get_financial_statements`: ① latest earnings (if new quarter/year); ② recent material events (management, regulation, competition); ③ current price and valuation; ④ insider transactions (major shareholder changes).

### B3: Check Each Assumption

| # | Core Assumption | Last status | Latest evidence | Current status | Change |
|---|-----------------|-------------|-----------------|----------------|--------|
| 1 | Revenue growth >15% | 🟢 Holding | Q4 revenue growth 12% | 🟡 Weakening | ⚠️ |

Status definitions:
- 🟢 **Holding** — latest data supports
- 🟡 **Weakening** — still acceptable, but trend is unfavorable
- 🔴 **Impaired** — data clearly does not support
- ⚫ **Broken** — assumption has been overturned

### B4: Red-Line Check

Check each red line; any triggered → flag prominently in the report + clear action recommendation.

### B5: Valuation Update

Use `financial_rigor` (`command=verify_valuation`) to recompute PE/PB/ROE; compare against buy-time and last check:

| Metric | At buy | Last check | Current | Change |
|--------|--------|------------|---------|--------|
| Price | | | | |
| PE (TTM) | | | | |
| Intrinsic value estimate | | | | |
| Margin of safety | | | | |

### B6: Output the Tracking Report

Structure: ① Thesis health score (out of 10); ② Assumption check table; ③ Red-line check table; ④ Key changes this period (≤500 words); ⑤ Valuation update; ⑥ Conclusion and action; ⑦ Focus for next check.

**Health formula**: `10 - (⚫broken × 3) - (🔴impaired × 2) - (🟡weakening × 1) - (red-lines triggered × 5)`, min 1, max 10.

| Score | Meaning | Action |
|:-----:|---------|--------|
| 9-10 | All assumptions hold, thesis stronger than at buy | Consider adding |
| 7-8 | Core assumptions hold, some weakening | Continue holding |
| 5-6 | 1-2 assumptions impaired, core logic intact | Hold but raise alertness |
| 3-4 | Multiple assumptions impaired, foundation shaken | Consider trimming |
| 1-2 | Red line triggered or core assumption broken | Strongly consider exit |

**The conclusion must clearly answer**: ① Is the thesis still intact? (intact / weakening / impaired / broken); ② What to do? (add / hold / trim / exit); ③ Next check timing (next earnings / a specific event).

### B7: Update the Thesis File

Use `write_file` to append this check to the tracking table in `reports/{company}-thesis.md`:

| Check date | Health | Key change | Action |
|------------|:------:|------------|--------|
| 2026-04-09 | 7/10 | Revenue growth slowed to 12%, but margins improved | Hold |

---

## Key Principles

- **Write sell conditions before buying** — decisions made calmly beat decisions made in panic.
- **Assumptions must be verifiable** — "a great company" is not a thesis; "ROE>25% and stable" is.
- **Act when a red line triggers** — "let's wait and see" is how big losses happen.
- **Thesis breaking ≠ stock falling** — a 30% price drop doesn't force a sell; a broken thesis does.
- **Be honest about mistakes** — if the thesis was wrong, admit it; don't defend it to save face.
- **Weigh macro headwinds for consumer names** — demographic decline and consumption downgrade are slow but can be fatal for consumer/property/education theses; bake them into red lines, not just quarterly checks.
