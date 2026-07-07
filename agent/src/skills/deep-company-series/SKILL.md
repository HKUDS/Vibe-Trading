---
name: deep-company-series
category: analysis
description: "Write a publication-grade 8-part deep-dive series on a single company (~120k words total): cognitive reset / moat / profit engine / hidden assets / era variable (e.g. AI) / financials Buffett-style / management / valuation+redlines. The core IP is NOT writing but REVISING — a strict fact-check checklist catches pseudo-precision (probability-weighted expectations, third-party MAU discrepancies, linear extrapolation), absolute language, and cross-article number inconsistencies that most finance long-forms violate. Each piece stands alone but shares one valuation/management/price framework. Use when the user wants textbook-level depth on one company for public publishing (a single research report or earnings note is NOT this — use investment-research / earnings-review instead)."
---

# Deep-Company Series: An 8-Part Deep Dive on One Company

Write an 8-part deep-dive series (~120k words total) on a single company, from cognitive reset to a decision framework. **The core IP is not "writing well" but "revising strictly" — most finance long-form violates this skill's fact-check standard.**

## 1. When to Use

The user wants "textbook-level" deep research on a company, published as a **series of long-form articles**. Distinct from a single research report:
- 8 parts, ~120k words, full loop from cognitive reset to a decision framework
- Each part stands alone (shareable singly) but shares one valuation / management / price framework
- Written for readers willing to spend 90 minutes understanding one company

**Not for**: a single research report, earnings note, sector study — use other skills (fundamentals / earnings / sector).

## 2. Series Template (8 Parts)

| # | Title template | Core question | Words |
|---|----------------|---------------|-------|
| 01 | You think you understand X — you don't | Cognitive reset: break 3 common illusions | 4,000-5,000 |
| 02 | X's moat — `{one-line business essence}` | Is the moat deep; will it be there in 5/10 years | 6,000-8,000 |
| 03 | X's biggest profit engine — `{most profitable business}` | What is the core business; why it persists | 6,000-8,000 |
| 04 | The other company hidden on X's balance sheet — `{hidden asset}` | Investment portfolio / subsidiary / hidden value | 8,000-10,000 |
| 05 | In the AI (or current narrative) era, is X a winner or loser | Era variable: decompose the impact by business | 8,000-10,000 |
| 06 | Reading X's financials the Buffett way | Financial depth: gross margin / FCF / ROE / SBC | 8,000-10,000 |
| 07 | `{management quote}` — is X's management worth entrusting | Capital-allocation discipline + integrity test + succession | 8,000-10,000 |
| 08 | At what price to buy, what signal to sell (finale) | DCF 3-scenario + red lines + position framework | 10,000-12,000 |

Plus `00-series-overview.md` as an index (unpublished).

## 3. Writing Style

### Voice
- **Direct, sharp, no filler** — open with a number or a counterintuitive claim
- **Value-investing frame** — Buffett/Munger/Duan Yongping/Li Lu lenses woven in (no name-dropping)
- **No preset stance** — data first, logic next, conclusion last
- **Show both sides** — every core judgment carries a "but on the other hand..."
- **Mobile preview** — the first 18-20 characters must stand alone

### Banned Words

| Banned | Why | Replace with |
|--------|-----|--------------|
| obviously / inevitably / certainly | Subjective absolutism | "the data shows" / "evidence suggests" |
| I think / I feel | Subjective tone | cut, or "under this framework" |
| textbook-level / brilliant | Hype adjectives | describe the concrete fact |
| severely mismatched / severely undervalued | Strong subjective | give the specific discount % |
| perfect / flawless | One-sided | add the counter-observation |

### Title Style
- Hook with a **contrast number** or a **counter-consensus claim** ("15 years, 7 failed challenges"; "salary 42.92M = 0.0017% of profit")
- Neutral subtitle summarizing content
- **Avoid hype metaphors**: "the next Buffett", "the X of China", "GOAT" — all banned

## 4. Strict Fact-Check Checklist (the Core IP)

### "Pseudo-precision" traps to watch for before writing

1. **Probability-weighted expected value**: `30% × A + 50% × B + 20% × C = expected +X%` is almost always garbage — the probabilities are pure subjective, giving readers false precision. **List scenarios + triggers + direction only; do not compute a weighted expectation.**
2. **Third-party MAU/share estimates**: QuestMobile / 七麦 / CBNData differ hugely (2-3× at the same point). **Use only the two most-credible as anchors; describe the rest qualitatively.**
3. **Linear extrapolation of historical growth**: `2025 +33% × 5y CAGR → 2030 X` is financial illiteracy. **Use scenario assumptions + high/low ranges; never a promise.**
4. **Undisclosed shareholding**: unlisted-company stakes are never publicly disclosed. **Give a range, mark "unknowable".**
5. **Strong attribution**: "competitor failed because of X." List multiple causes; **this article does no single attribution.**

### The 7 mandatory revision checks

```
□ 1. Cross-article number consistency: market cap, Non-IFRS net income, key holding % aligned across the series
□ 2. Caliber labeling: Non-IFRS / GAAP / Non-IFRS-SBC / FCF — which is used, clear throughout
□ 3. Double-counting scan: consolidated subs are NOT in the "investment portfolio"; SOTP doesn't count them twice
□ 4. Peer-comparison fairness: don't compare "core-business PE (cash + portfolio stripped)" with "peer PE (not stripped)"
□ 5. Probability-weighted expectations deleted (see above)
□ 6. Absolute language softened: grep "obviously|inevitably|severely|textbook|perfect"
□ 7. Third-party data sourced: every non-filing data point followed by "(source: X)"
```

### Known hard-error risks (list before writing)

- Historical return multiples: use cumulative-invested basis (e.g. Riot 33×, not 58×)
- Shareholding %: use the latest filing/financial-app basis (e.g. Tencent's Meituan stake changes with disposals)
- "Distribution accounting": treated as disposal gain under IFRIC 17, recognized on declaration date
- Share count rebounds: SBC granted in clusters at year-start can lift share count short-term

## 5. Execution

### Phase 1: Research (before writing 01-02)

1. `get_financial_statements` — last 5 years of annuals, latest quarterly
2. `get_research_reports` / `web_search` — at least 3 independent sell-side reports (find consensus + dissent)
3. Optional: `run_swarm` (e.g. equity_research_team or value_investing_committee) to generate an internal research draft
4. **Confirm the 8-part core theses with the user** (avoid writing the wrong direction)

### Phase 2: Writing (01→08 in order, no skipping)

- After each part, `write_file` to `reports/{company}/《Understanding {company}》/0X-XX.md`
- Don't publish immediately — wait for user review
- Revise on feedback

### Phase 3: Cross-Article Consistency Scan (after all 8)

This is the key differentiator. Use tools to scan:

1. `read_file` each part + `report_audit` (`command=extract`) to pull numbers (market cap, net income, holding %, PE) from each
2. **Cross-check the same number across parts** — use `financial_rigor` (`command=cross_validate`) to cross-validate the same metric's values across articles; flag >1% deviation as a caliber mismatch
3. `read_file` checks: is each term (FBS, SBC, Non-IFRS) defined at first use; do "see part 06" references actually resolve; do recaps match body numbers
4. Absolute-language scan: grep "obviously|inevitably|severely|perfect" and soften each

### Phase 4: Pre-publish Final Check

- `report_audit` (`command=verdict`) as a gate on each part: extract numbers → verify → PASS/FAIL
- Confirm all numbers are traceable, no pseudo-precision, no absolutism

## 6. Revision-Feedback Handling

### 1. Verify facts first (don't just change)
If the user says "X is wrong", use `get_financial_statements` / `web_search` to cross-check the original; present "user's number vs what I found vs what I used".

### 2. Grade the revision

| Grade | Type | Handle |
|-------|------|--------|
| 🔥 Hard error | wrong number / attribution / caliber | Must fix |
| ⚠️ Subjective | strong subjective word / hype metaphor | Soften or cut |
| 🔬 Granularity | source label, caliber refinement | Balance against readability |
| ❓ Unreliable | large third-party discrepancies | **Deleting is safer than editing** |

### 3. Cascade check after a fix
Before fixing one spot, think "where else is this number/concept referenced":
- Market cap changed → cascade to PE / core-business PE / discount / FCF yield
- Holding % changed → fix TOP-10 sort + historical holding table + disposal list
- Caliber changed → fix first definition + later references + recap

## 7. What This Skill Does NOT Do

- **Does not make investment decisions for the reader** — every part ends with "not investment advice"
- **Does not predict prices** — only "scenarios + triggers"
- **Does not compute a weighted "expected annualized return"** — subjective probability misleads
- **Does not write "famous investor X also holds"** — using someone else's holding to back your judgment is anti-value-investing
- **Does not force all 8 parts** — if a part lacks enough standalone content (e.g. management isn't distinctive), merge it or reduce the count

---

**One-liner**: writing an "Understanding X" series is about **revising strictly, not writing well** — most finance long-form dies from pseudo-precise numbers, subjective weighted expectations, and absolute language. This skill exists to flag all those traps before writing and sweep them clean after (`report_audit` + `financial_rigor.cross_validate`).
