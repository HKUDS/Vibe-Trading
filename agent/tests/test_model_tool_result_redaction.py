"""Credentials in shell-style results never reach model requests or caches."""

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import copy
import json
from types import SimpleNamespace

from src.agent.runtime import AgentRuntime
from src.agent.tools import BaseTool, ToolRegistry
from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask
import src.swarm.worker as worker
from tests.test_agent_loop_deterministic_cache import _drive


class _CredentialResult(BaseTool):
    name = 'credential_result_probe'
    description = 'Fixture result with ordinary financial data and a credential.'
    parameters = {'type': 'object', 'properties': {}}
    deterministic = True
    repeatable = True
    is_readonly = True

    def __init__(self, secret):
        self.secret = secret
        self.calls = 0

    def execute(self, **kwargs):
        self.calls += 1
        return json.dumps({'status': 'ok', 'stdout': f'TUSHARE_TOKEN={self.secret}\nclose=112.4 USD',
                           'data': {'close': 112.4, 'currency': 'USD'}, 'content': 'Financial evidence'})


def test_main_model_context_and_deterministic_replay_are_scrubbed(tmp_path):
    secret = 'fixture-only-private-value'
    tool = _CredentialResult(secret)
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(tool)
    agent = AgentRuntime(registry=registry, llm=SimpleNamespace(), max_iterations=3)
    agent.memory.run_dir = str(tmp_path)
    messages, records = _drive(agent, tool.name, tmp_path, [{}, {}])
    assert tool.calls == 1
    assert secret not in json.dumps([messages, records, list(agent.replay._called_identical.values())])
    for message in messages:
        payload = json.loads(message['content'])
        assert payload['data'] == {'close': 112.4, 'currency': 'USD'}
        assert payload['content'] == 'Financial evidence'
        assert 'TUSHARE_TOKEN=[redacted]' in payload['stdout']


def test_worker_model_request_and_persisted_conversation_are_scrubbed(tmp_path, monkeypatch):
    secret = 'fixture-only-worker-private-value'
    tool = _CredentialResult(secret)
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(tool)
    seen = []

    class Model:
        def stream_chat(self, messages, **kwargs):
            seen.append(copy.deepcopy(messages))
            if len(seen) == 1:
                return LLMResponse(tool_calls=[ToolCallRequest(id='read', name=tool.name, arguments={})])
            return LLMResponse(content='The requested financial evidence is collected and its source is retained. ' * 5)

        def close(self):
            pass

    monkeypatch.setattr(worker, 'ChatLLM', lambda **kwargs: Model())
    monkeypatch.setattr(worker, 'build_swarm_registry', lambda *args, **kwargs: registry)
    result = worker.run_worker(
        policy=ToolPolicy.from_config(get_env_config()),
        agent_spec=SwarmAgentSpec(id='analyst', role='Analyst', system_prompt='Read evidence.',
                                  tools=[tool.name], max_iterations=3),
        task=SwarmTask(id='t', agent_id='analyst', prompt_template='Read the evidence.'),
        upstream_summaries={}, user_vars={}, run_dir=tmp_path,
    )
    assert result.status == 'completed'
    assert len(seen) == 2
    assert secret not in json.dumps(seen)
    persisted = next(tmp_path.rglob('messages.json')).read_text()
    assert secret not in persisted
    output = next(m for m in seen[1] if m['role'] == 'tool')
    payload = json.loads(output['content'])
    assert payload['data'] == {'close': 112.4, 'currency': 'USD'}
    assert 'TUSHARE_TOKEN=[redacted]' in payload['stdout']
