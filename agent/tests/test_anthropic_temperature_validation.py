"""Field-specific validation retries must not remove unrelated sampling options."""

import asyncio

import pytest

from src.providers import llm


@pytest.mark.parametrize("message", [
    "max_tokens: Extra inputs are not permitted; request temperature=0",
    "temperature must be a number; metadata: Extra inputs are not permitted",
    "temperature: extra inputs require a different schema",
])
def test_other_validation_failures_do_not_poison_temperature_cache(message):
    class Provider:
        model = "validation-counterexample"
        calls = 0

        def _generate(self, *args):
            self.calls += 1
            raise RuntimeError(message)

    instance = llm._make_temperature_safe_anthropic(Provider)()
    key = llm._endpoint_model(instance)
    llm._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(key)
    try:
        with pytest.raises(RuntimeError, match=".*"):
            instance._generate([])
        assert instance.calls == 1
        assert key not in llm._ANTHROPIC_TEMPERATURE_UNSUPPORTED
    finally:
        llm._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(key)


@pytest.mark.parametrize("method", ["_generate", "_agenerate", "_stream", "_astream"])
@pytest.mark.parametrize("partial", [False, True])
def test_validation_retry_paths_preserve_stream_boundary(method, partial):
    if partial and method in {"_generate", "_agenerate"}:
        pytest.skip("partial output applies only to streams")

    class Provider:
        model = "validation-retry-paths"

        def __init__(self):
            self.calls = []

        def _get_request_payload(self):
            return {"temperature": 0, "extra_body": {"temperature": 0, "other": "keep"}}

        def _attempt(self):
            payload = self._get_request_payload()
            self.calls.append(payload)
            if "temperature" in payload:
                raise RuntimeError("temperature: Extra inputs are not permitted")
            return "ok"

        def _generate(self):
            return self._attempt()

        async def _agenerate(self):
            return self._attempt()

        def _stream(self):
            if partial:
                yield "already emitted"
            yield self._attempt()

        async def _astream(self):
            if partial:
                yield "already emitted"
            yield self._attempt()

    instance = llm._make_temperature_safe_anthropic(Provider)()
    key = llm._endpoint_model(instance)
    llm._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(key)
    output = []

    async def run_async():
        if method == "_astream":
            async for item in instance._astream():
                output.append(item)
        else:
            output.append(await instance._agenerate())

    def run():
        if method in {"_astream", "_agenerate"}:
            asyncio.run(run_async())
        elif method == "_stream":
            output.extend(instance._stream())
        else:
            output.append(instance._generate())

    try:
        if partial:
            with pytest.raises(RuntimeError, match="Extra inputs"):
                run()
            assert output == ["already emitted"]
            assert len(instance.calls) == 1
            assert key not in llm._ANTHROPIC_TEMPERATURE_UNSUPPORTED
        else:
            run()
            assert output == ["ok"]
            assert len(instance.calls) == 2
            assert instance.calls[-1] == {"extra_body": {"other": "keep"}}
            run()
            assert len(instance.calls) == 3
    finally:
        llm._ANTHROPIC_TEMPERATURE_UNSUPPORTED.discard(key)
