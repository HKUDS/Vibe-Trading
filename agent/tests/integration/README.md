# Integration / live smoke tests

These tests **call out to a real provider** and require credentials. They
are opt-in only — the default `pytest agent/tests/` run skips them.

## Claude Code (Pro/Max subscription)

`test_claude_code_smoke.py` exercises `LANGCHAIN_PROVIDER=claude-code` end
to end through the real `claude-agent-sdk` against the user's Claude Code
subscription. No API key is required, but the user must have:

1. Run `claude login` at some point.
2. Installed the optional dependency: `pip install 'vibe-trading-ai[claude-code]'`
   (or `pip install claude-agent-sdk`).

To enable the smoke, export an opt-in flag (so accidental CI checkouts
don't fire it):

```bash
export VIBE_TRADING_CLAUDE_CODE_SMOKE=1
python -m pytest agent/tests/integration/test_claude_code_smoke.py -v -s --no-header
```

Without `VIBE_TRADING_CLAUDE_CODE_SMOKE=1` the test skips cleanly.

The smoke prints the actual response text and the SDK's usage block to
stdout via `print(...)` — capture-friendly for attaching to a PR.

## Why isn't this a unit test?

Mocking the SDK is already covered in `agent/tests/test_claude_code_provider.py`.
The smoke is the only place that verifies our adapter actually matches the
real SDK's runtime shape — message types, content blocks, stop_reason
strings. It guards against drift when `claude-agent-sdk` releases a new
version.
