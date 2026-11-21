---
name: financial-facts
description: Save an issuer's structured financial statements as a cited financial-facts/v1 research artifact when the user explicitly requests machine-readable facts.
category: analysis
---

# Structured financial facts

Use this skill only for an explicit request for structured issuer financial statements or a versioned financial-facts artifact. Investigate the issuer with the available source tools, then call `save_financial_research_artifact` with a JSON object following `financial-facts/v1`. Use `save_research_artifact` for narrative research revisions.

## Evidence contract

Include original issuer or regulatory HTTPS document URLs, exact statement sections or pages, reporting currency and unit, accounting scope, and ISO period dates. Use duration start/end for income flows and instant as-of dates for balance-sheet stocks. Do not duplicate the same stock when a quarter and fiscal year end share an instant. Distinguish reported and derived metrics. For derived values, include the formula and operands.

Never invent missing figures. Use `partial` or `unavailable` when evidence is inadequate. For an explicit matrix of periods and metrics, enumerate expected cells first and investigate every cell. Represent missing requested cells as `verification_status: unavailable`, `value: null`, `source_id: null`, and `source_section: null`, with a definition explaining whether the filing was not retrieved, the metric was absent, or the search failed. Do not mark uninvestigated cells verified. Do not invent reporting dates. If the date cannot be established, disclose the coverage gap in the narrative. Store one fact for duplicate quarter and year-end balance-sheet instants and explain their shared identity in the summary.

Before saving, check required fact keys and date fields, then report requested-versus-saved coverage and unresolved cells. Call `save_financial_research_artifact` before claiming persistence. If it returns an error, report the error and do not claim success. The tool validates structure, not the accuracy or authenticity of cited statements. A `verified` label is an evidence assertion and is not an independent audit.
