# Instructions for AI Coding Agents

These instructions apply throughout this repository.

1. Read `HQATL_MANIFEST.md` and `docs/HQATL_MASTER_REQUIREMENTS.md` before modifying anything.
2. HQATL is separate from Paperclip AI. Do not mention, integrate, import, modify, or design around Paperclip AI. Do not include DARWIN Zero.
3. Never commit credentials. Keep secrets out of source, prompts, logs, screenshots, and documentation.
4. Never enable live execution without a separate, explicit, human-approved task.
5. Preserve existing Vibe functionality unless an approved requirement explicitly replaces it.
6. Distinguish executable capabilities from prompt-only descriptions. Never present a prompt description as implemented behavior.
7. Avoid look-ahead bias in research, signals, tests, labels, and datasets.
8. Confirmed signals must use completed bars unless explicitly marked provisional.
9. Do not duplicate backend calculations in the frontend.
10. Analytical and backtesting calculations must share the same implementation.
11. All new analytical calculations require tests.
12. Every confidence result must explain its contributing, opposing, and missing evidence. No black-box scores.
13. Keep primary and alternate Elliott counts separate.
14. Keep Fibonacci projections and statistical projections separate.
15. Keep data-provider-specific logic outside strategy and analytical logic.
16. Do not claim a capability is implemented without auditing executable code and relevant tests.
17. Stop after completing the explicitly assigned phase. Do not begin a later phase without approval.
