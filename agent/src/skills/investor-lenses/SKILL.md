---
name: investor-lenses
description: Named investor reasoning frameworks packaged as reusable analytical lenses — 12 lenses (deep value, quality franchise, inversion, scuttlebutt growth, GARP, cycle positioning, debt cycle, forensic short, cost drag, right-business, weak-system contrarian, three questions) that stack on top of evidence already gathered, each with ordered priority signals, hard disqualifiers, and documented failure modes.
category: analysis
---

# Investor Lenses

## What a lens is

A lens is a **reasoning procedure**: a fixed, ordered set of questions plus explicit
veto rules, distilled from one investor's publicly published methodology. It is
applied *after* the evidence exists — it does not gather data and does not care
where the data came from.

The value of a lens is that it is **opinionated and therefore falsifiable**. A lens
tells you, before you look at the answer, which signals it ranks first and which
facts make it walk away. Two lenses disagreeing on the same evidence is the
product, not a bug: the disagreement localizes exactly which assumption the
decision rests on.

## What a lens is NOT

- **Not investment advice.** Every lens output is an analytical exercise.
- **Not the named person's opinion.** Each lens is a reconstruction, in our own
  words, of a methodology that investor has described publicly. It is not written
  by them, not endorsed by them, and may diverge from what they would say today.
- **Not a universal truth test.** A lens verdict is conditional on the lens.
  "Fails the Graham lens" and "bad investment" are different statements.
- **Not a ranking of masters.** No lens is more correct than another; each has a
  domain where it is sharp and a domain where it is reliably wrong.

## The five-step run

1. **Freeze the evidence.** Write down what is known *before* choosing the lens —
   financials, prices, disclosures, timelines. A lens applied to evidence collected
   after the lens was chosen is circular.
2. **Choose by the situation, never by the answer you want.** Use the selection
   table below. If you are picking the lens because you already know its verdict,
   stop.
3. **Walk the priority signals in order.** Each lens orders its signals for a
   reason. Do not jump to the signal you have the best data on.
4. **Hit a hard disqualifier → stop and report the veto.** Disqualifiers are not
   weighted against positives. They end the run under that lens.
5. **Run the misuse check, then emit under the output contract.** Every lens file
   lists the regimes where it fails. State explicitly whether the current case sits
   in one of them.

## Lens index

| Lens | Style | Sharpest on | Blindest on | File |
| --- | --- | --- | --- | --- |
| Statistical deep value (Graham) | Value / balance sheet | Cheap, boring, asset-heavy, wide-basket | Asset-light compounders; single names | [graham-deep-value](investor-lenses/references/graham-deep-value.md) |
| Quality franchise (Buffett) | Quality / durability | Durable consumer & toll-road economics | Fast-changing tech; deep cyclicals | [buffett-quality-franchise](investor-lenses/references/buffett-quality-franchise.md) |
| Inversion (Munger) | Risk / pre-mortem | Finding the way this dies | Sizing an opportunity; timing | [munger-inversion](investor-lenses/references/munger-inversion.md) |
| Scuttlebutt growth (Fisher) | Growth / qualitative | Product & channel truth vs. reported numbers | Anything you cannot reach people about | [fisher-scuttlebutt](investor-lenses/references/fisher-scuttlebutt.md) |
| GARP by category (Lynch) | Growth at a price | Mid-cap earnings compounding; retail-visible businesses | Financials; commodity cyclicals | [lynch-garp](investor-lenses/references/lynch-garp.md) |
| Cycle positioning (Marks) | Contrarian / risk-first | Where we are in the greed–fear cycle | Single-company fundamentals | [marks-cycle-position](investor-lenses/references/marks-cycle-position.md) |
| Debt cycle & uncorrelated bets (Dalio) | Macro / allocation | Rates, currency, liquidity regime; portfolio shape | Stock picking | [dalio-debt-cycle](investor-lenses/references/dalio-debt-cycle.md) |
| Forensic short (Chanos) | Short / accounting | Accounting distortion, value traps, structural decline | Longs; anything you must be right about *soon* | [chanos-forensic-short](investor-lenses/references/chanos-forensic-short.md) |
| Cost drag & mean reversion (Bogle) | Allocation / cost | Whether the *activity itself* is worth its cost | Individual security selection | [bogle-cost-drag](investor-lenses/references/bogle-cost-drag.md) |
| Right business, right people (Duan Yongping / 段永平) | Quality / concentration | Founder-led A-share, HK and US-listed China names | Diversified baskets; turnarounds | [duan-right-business](investor-lenses/references/duan-right-business.md) |
| Weak-system contrarian (Feng Liu / 冯柳) | Contrarian / positioning | A-share names beaten down by known bad news | Momentum regimes; names with unresolved fraud risk | [fengliu-weak-system](investor-lenses/references/fengliu-weak-system.md) |
| Three questions (Qiu Guolu / 邱国鹭) | Value / industry structure | A-share and HK industry structure and pricing power | Early-stage, structure-not-yet-formed industries | [qiuguolu-three-questions](investor-lenses/references/qiuguolu-three-questions.md) |

## Choosing a lens

| Situation | Start with | Then stack |
| --- | --- | --- |
| "Is this cheap enough?" on an asset-heavy or out-of-favour name | Graham | Munger, Qiu Guolu |
| "Is this a great business?" on a stable franchise | Buffett | Duan Yongping, Munger |
| "The story is wonderful, is it real?" | Fisher | Chanos, Munger |
| "It's grown 5 years, is the multiple sane?" | Lynch | Buffett, Qiu Guolu |
| "Is the market euphoric or despairing right now?" | Marks | Dalio |
| "What does the rates / currency / liquidity regime do to this?" | Dalio | Marks |
| "The accounting smells" | Chanos | Munger, Fisher |
| "Should we be picking at all, or just allocating?" | Bogle | Marks |
| A-share name down 50% on known bad news | Feng Liu | Chanos, Qiu Guolu |
| A-share / HK industry with consolidating competitive structure | Qiu Guolu | Buffett, Duan Yongping |
| Founder-controlled company, governance is the swing factor | Duan Yongping | Munger, Chanos |

## Stacking protocol

Stacking is where lenses earn most of their value, but only under discipline.

- **Two or three lenses. Never more.** Beyond three the output degenerates into a
  survey and the disagreements stop being legible.
- **Choose lenses that can actually disagree.** Buffett + Duan Yongping mostly
  agree by construction; that stack is decoration. Buffett + Chanos, or Feng Liu +
  Munger, produce real tension.
- **Run each lens independently before comparing.** Do not let lens 2 read lens 1's
  verdict. Cross-contaminated lenses collapse into one lens.
- **Classify every disagreement** into exactly one root cause:
  - *Horizon* — same facts, different holding period (10-year certainty vs. next
    two quarters).
  - *Caliber* — the two lenses are measuring different quantities (owner earnings
    vs. reported net income; EV vs. market cap).
  - *Risk preference* — same expected value, different tolerance for the left tail.
  - *Information* — one lens needs a fact nobody has. Say which fact.
- **Never average the verdicts.** A 2-to-1 split among lenses is not evidence of
  anything; lenses are not voters and they are not independent samples. Report the
  split and its root cause instead.
- **Report the losing lens's strongest point verbatim.** If it cannot be stated
  fairly, the stack was not run honestly.

## Anti-patterns

- **Lens shopping** — running lenses until one agrees with the pre-existing
  conclusion, then reporting only that one. If a lens is run, it is reported.
- **Lens as authority** — "Buffett would buy this" is a claim about a person and is
  unsupportable. "Under a quality-franchise lens, this passes the moat test and
  fails the price test" is a claim about a procedure and is checkable.
- **Biography instead of procedure** — quoting temperament, anecdotes or life story
  in place of walking the signal list.
- **Silent disqualifier** — noticing a hard veto and continuing to score anyway
  because the rest of the picture is attractive.
- **Lens applied out of market** — a US-designed lens dropped onto an A-share name
  without adjusting for what the disclosure regime actually reveals. Each lens file
  carries a market-fit note; read it.
- **Retrofitting the evidence** — going back to collect exactly the data the chosen
  lens rewards, after choosing the lens.

## Output contract (binding on every lens)

Any output produced under this skill must contain, in this order:

1. **Lens name and one-line statement of what it optimizes for.**
2. **Verdict, explicitly framework-conditional** — phrased "under this framework,
   …", never as a flat assertion about the security.
3. **The ordered signal walk** — each priority signal, the evidence found, and
   whether it passed. Missing evidence is written as *missing*, never inferred.
4. **Disqualifier check** — every hard veto listed and marked triggered / not
   triggered / unknown.
5. **Misuse check** — whether the current case sits in a regime where this lens is
   documented to fail.
6. **Falsifiers** — the two or three observations that would flip the verdict, each
   concrete enough that someone could go check it.
7. **Confidence with its limiting factor** — "medium, limited by the absence of
   segment-level disclosure", not a bare number.
8. **The standing disclaimer**: this is an analytical framework, not investment
   advice, and the verdict is conditional on the framework used.
