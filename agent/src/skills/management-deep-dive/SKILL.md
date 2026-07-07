---
name: management-deep-dive
category: analysis
description: "Deep management assessment — the 'buying a stock is buying a person' layer. For a company or a named executive, evaluate integrity (promise-vs-delivery tracking, crisis behavior, stakeholder treatment), ability (strategic foresight, execution, capital-allocation record) and governance (equity structure, compensation, related-party deals). Outputs a weighted score across integrity / ability / capital-allocation / governance plus Duan Yongping's 3-question verdict ('would you hand this person your money for 10 years'). Use when standard research leaves management quality uncertain, or when management IS the investment thesis."
---

# Management Deep Dive: Buying a Stock Is Buying a Person

Deep management research on a company (or `person company`).

> "Buying a stock is buying a person. Find someone you trust, then hold long-term." — Duan Yongping
>
> "To judge management, look at what they do when no one is watching." — Buffett

## Design Philosophy

Most analysis stops at the surface: résumé, shareholding, compensation. But Buffett spends time talking with management, Li Lu says investing is fundamentally investing in people, Duan Yongping says buying a stock is buying a person.

AI can't have dinner with management, but it can via public information: ① **track whether words match deeds** (promises vs delivery); ② **analyze the return of every major capital-allocation decision**; ③ **infer character from decisions made in hard times**; ④ **cross-check via employee / merchant / customer feedback**.

Use when: standard research leaves management score uncertain (★★★ or below), or when management is the core investment logic.

## Step 1: Identify Key People

Use `web_search` / `get_stock_profile` / `get_sec_filings`:

| Role | Name | Tenure | Background | Shareholding/options |
|------|------|--------|------------|----------------------|
| CEO/Chairman | | | | |
| CFO | | | | |
| Founder (if not in role) | | | | |
| Actual controller (if different from CEO) | | | | |
| Other key executives | | | | |

**Distinguish "who decides" from "whose name is on the title"** — some founders remain the soul even after stepping down.

Then gather four data categories (sequentially via `web_search` + `get_stock_news` + `get_financial_statements` + `get_sec_filings`, or `run_swarm`): ① CEO public statements and prediction record; ② capital-allocation decisions (M&A / buybacks / dividends / new business); ③ governance and compensation; ④ side validation (employee / customer / industry reputation).

## Step 2: CEO Circle of Competence

### Strategic Foresight

Use `web_search` to collect the CEO's public statements over the past 5 years (shareholder letters, calls, interviews, social media); extract their judgments:

| Time | CEO's judgment/prediction | Actual outcome | Accuracy |
|------|---------------------------|----------------|----------|
| | "We believe market X will..." | X actually... | ✅/❌ |

Key questions: Has the CEO made correct calls ahead of the market? Stayed calm when everyone was bullish? Is their industry understanding independent or following the crowd?

### Execution

| Dimension | Assessment | Evidence |
|-----------|-----------|----------|
| Strategy-to-execution | Did they do what they said? | |
| Organization | Can they attract and retain talent? | |
| Crisis handling | How do they respond to difficulty? | |
| Iteration speed | How fast do they correct mistakes? | |

## Step 3: Integrity Assessment (most important)

> Buffett: "We look for three qualities: integrity, intelligence, and energy. Without the first, the other two will kill you."

### Promise-vs-Delivery Tracking

Extract specific commitments from the past 3 years (calls, letters, interviews) via `get_sec_filings` / `web_search` / `get_stock_news`:

| # | Time | Commitment | Occasion | Delivery | Rating |
|---|------|-----------|----------|----------|--------|
| 1 | | "X business profitable in 2025" | 2024 annual call | | ✅/⚠️/❌ |

| Delivery rate | Rating |
|:-------------:|--------|
| >80% | Excellent — does what it says |
| 60-80% | Acceptable — right direction, execution gaps |
| 40-60% | Concerning — over-promises, under-delivers |
| <40% | Serious problem — untrustworthy |

### Behavior in Hard Times

Search for major crises (price crash, earnings miss, regulatory shock, competition); analyze management's response: proactive comms or hiding? Internal attribution or blaming external? Used the crisis to do the hard right thing or to pander short-term?

### Treatment of Stakeholders

| Stakeholder | Attitude | Evidence | Rating |
|-------------|----------|----------|--------|
| Shareholders | Respect/ignore/exploit | | |
| Employees | Treat well/exploit/ignore | | |
| Customers/users | Customer-first/short-term extract | | |
| Merchants/suppliers | Fair/extreme price pressure | | |
| Regulator/society | Compliant/corner-cutting | | |

## Step 4: Capital Allocation

Buffett's most-valued ability — **for every dollar earned, how much does management turn it into?**

Search past 5 years of capital decisions (`web_search` / `get_financial_statements`); score each:

**M&A record**: time / target / amount / strategic logic / after-the-fact return / score(1-5)

**Buybacks** (use `financial_rigor` `command=verify_valuation` to check PE at buyback time vs now): time / amount / avg price / PE then / retrospective / score(1-5)

**Dividends**: year / amount / payout ratio / vs FCF / sustainable

**New business investment**: time / area / cumulative spend / status / return / score(1-5)

### Capital Allocation Score

| Dimension | Score(1-5) | Notes |
|-----------|:---------:|-------|
| M&A discipline | | Right price? Integration? |
| Buyback timing | | Buy low, stop high? |
| Dividend rationality | | Payout vs FCF? |
| New business | | Success rate? Stop-loss discipline? |
| Cash management | | Reasonable reserves? Hoarding? |
| **Overall** | | |

## Step 5: Governance

### Equity Structure

| Item | Detail | Risk |
|------|--------|------|
| Dual-class / super-voting? | | |
| Founder/controller stake? | | |
| VIE structure? | | |
| Independent directors truly independent? | | |
| Recent major-holder changes? | | |

### Compensation

| Executive | Total annual comp | % of net income | vs peers | Reasonable? |
|-----------|-------------------|-----------------|----------|-------------|

Is incentive aligned with long-term shareholders or encouraging short-term behavior?

### Related-Party Transactions

| Related party | Transaction | Amount | Arm's length? | Risk |
|---------------|------------|--------|---------------|------|

## Step 6: Side Validation

AI can't meet face-to-face, but cross-check via public channels:

- **Employee view**: `web_search` for Glassdoor ratings, discussions (mark platforms requiring login as "user can supplement") — culture, management rating, intensity, compensation, growth.
- **Customer/merchant view**: App Store ratings, complaints, merchant forums.
- **Industry reputation**: peer and insider views on this management.

## Step 7: Post-CEO Scenario

> Buffett: "A great company should be one that a fool can run — because eventually one will."

- If the CEO left tomorrow, would the company run normally?
- How deep is the management team? A clear successor?
- Is the competitive advantage dependent on the CEO personally or on organization/system?
- Have past management transitions been smooth?

## Step 8: Output

Structure: ① Key people overview; ② Integrity (delivery rate + hard times + stakeholders); ③ Ability (foresight + execution + capital allocation); ④ Governance; ⑤ Side validation; ⑥ Overall score and verdict.

### Overall Score

| Dimension | Weight | Score(1-5) | Weighted |
|-----------|:------:|:---------:|:--------:|
| Integrity | 35% | | |
| Strategy & execution | 25% | | |
| Capital allocation | 25% | | |
| Governance | 15% | | |
| **Total** | 100% | | |

### Duan Yongping's 3 Questions

1. Is this person **honest**? (truthful, doesn't take advantage of shareholders)
2. Is this person **capable**? (strategic foresight + execution + capital allocation)
3. Would you hand this person your money for **10 years**?

All three "yes" = ★★★★★; first two "yes" = ★★★★; only the first "yes" = ★★★; first is "no" = ★ (don't invest).

## Step 9: Save

Use `write_file` to `reports/{company}-management-{YYYYMMDD}.md`. Then `report_audit` (`extract` → verify → `verdict`) as a quality gate on the numbers.

## Key Principles

- **Integrity is a veto** — ability can be learned; character can't be fixed.
- **Watch behavior, not words** — what they say doesn't matter; what they do does.
- **Truth shows in hard times** — everyone's a good CEO in a tailwind.
- **Capital allocation is the ultimate exam** — making money is easy; allocating it well is hard.
- **Don't fall in love with management** — stay objective; even someone you admire can make big mistakes.
