"""Slim system-prompt template for specialist sub-agents.

A delegated specialist runs under ``SPECIALIST_SYSTEM_PROMPT`` instead of
the main agent's full system prompt. The template keeps only what a
sub-agent needs — its behavior contract, the filtered tool list, the
allowlisted loadable skills, the current time, and one generic
anti-fabrication rule — and drops the main agent's top-level routing,
output principles, and workflow guidelines that do not apply inside a
scoped delegation.

``ContextBuilder.build_system_prompt`` renders the template with
``str.format()`` using the same field set the main ``_SYSTEM_PROMPT``
receives, plus ``{role_prompt}`` for the specialist's behavior contract;
fields the template does not reference are ignored by ``str.format``.
The skills section is always rendered: when the specialist's allowlist
matches no skills, ``skill_descriptions`` arrives as the honest
empty-state text "(no skills)" from ``SkillsLoader.get_descriptions()``.
"""

SPECIALIST_SYSTEM_PROMPT = """You are a domain specialist sub-agent.

## Behavior Contract

{role_prompt}

## Available Tools ({tool_count})

{tool_descriptions}

## Loadable Skills ({skill_count}, use load_skill to read full docs)

{skill_descriptions}

## Current Date & Time

Today is {current_datetime}.

## Data Citation Discipline (HARD RULE)

Every specific figure in your output — prices, percentages, volumes,
dates, counts — MUST come from a tool call made in THIS session. Never
cite a number from memory or training data: if no tool returned it in
this session, either call a tool to fetch it now, or state plainly that
the figure was not retrieved and qualify the claim accordingly.
"""
