# Integration / live-API smoke tests

These tests **call the real provider API** and require credentials. They are
opt-in only — the default `pytest agent/tests/` run skips them.

## What they cover

For Anthropic Claude (PR #105), three real-network smokes:

1. **Basic chat** — round-trip a single user message through
   `LANGCHAIN_PROVIDER=anthropic`, assert non-empty text content, assert
   `usage_metadata` is populated.
2. **Agent-loop tool call** — bind one trivial tool, ask Claude to call it,
   assert `response.tool_calls` is populated and `finish_reason="tool_calls"`.
3. **Extended thinking** — set `LANGCHAIN_REASONING_EFFORT=medium`, send a
   prompt that benefits from reasoning, assert the response carries a
   non-empty `reasoning_content` in `additional_kwargs`.

Each test is `pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"))`. CI
does not need to set the key — the tests just skip.

## Running them locally

```bash
# 1. Have a working install (see top-level README Path B).
source .venv/bin/activate
pip install -e .

# 2. Export your key.
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Run the smoke harness.
python -m pytest agent/tests/integration/ -v -m "" --no-header
```

The `-m ""` is intentional — it disables any default marker filter the
project pytest config might apply. Each smoke prints the model used and a
short snippet of the response so the output is grep-friendly.

## Cost

Approx **<$0.05 / full run** at Sonnet 4.6 prices (the default model used
by the smokes). Haiku 4.5 is even cheaper. Extended thinking adds a
`budget_tokens` charge of 4096 tokens for the medium tier (≈ $0.06).

## When to run

- Before merging any change to `agent/src/providers/llm.py` or
  `agent/src/providers/chat.py` that affects the Anthropic adapter.
- When upgrading `langchain-anthropic`.
- Before a release that touches provider plumbing.

CI runs the mock-only suite (`agent/tests/test_anthropic_provider.py`)
which exercises every code path with the HTTP boundary stubbed; the live
smokes catch breakage in the contract between our wrapper and the actual
Anthropic API.
