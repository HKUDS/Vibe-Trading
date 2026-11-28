"""Worker evidence survives ordinary batches and remains readable under pressure."""

from src.tools.path_utils import FileRoots


from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import copy
import json

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.config.limits import truncate_tool_result
from src.session.thread import ThreadLog
from src.swarm.context import NodeContext
from src.swarm.models import SwarmAgentSpec, SwarmTask
import src.swarm.node as worker
from src.tools.read_file_tool import ReadFileTool


class _EvidenceTool(BaseTool):
    def __init__(self, name):
        self.name = name

    def execute(self, **kwargs):
        return json.dumps({'status': 'ok', 'observed': self.name, 'detail': 'actual evidence ' * 50})


def test_entire_batch_reaches_the_next_model_request(tmp_path, monkeypatch):
    names = ['get_financial_statements', 'get_fund_flow', 'get_margin_trading',
             'get_research_reports', 'get_stock_news', 'a', 'b', 'c', 'd', 'e']
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    for name in names:
        registry.register(_EvidenceTool(name))
    seen = []

    class Model:
        def stream_chat(self, messages, **kwargs):
            seen.append(copy.deepcopy(messages))
            if len(seen) == 1:
                return LLMResponse(tool_calls=[ToolCallRequest(id=n, name=n, arguments={}) for n in names])
            return LLMResponse(content='The evidence was collected for all requested dimensions. ' * 5)

        def close(self):
            pass

    monkeypatch.setattr(worker, 'ChatLLM', lambda **kwargs: Model())
    monkeypatch.setattr(worker, 'build_swarm_registry', lambda *args, **kwargs: registry)
    result = worker.run_node(
        policy=ToolPolicy.from_config(get_env_config()),
        agent_spec=SwarmAgentSpec(id='analyst', role='Analyst', system_prompt='Read all evidence.',
                                  tools=names, max_iterations=3),
        task=SwarmTask(id='t', agent_id='analyst', prompt_template='Review the company.'),
        upstream_summaries={}, user_vars={}, run_dir=tmp_path,
    )
    assert result.status == 'completed'
    outputs = [m for m in seen[1] if m['role'] == 'tool']
    assert len(outputs) == 10
    assert [json.loads(m['content'])['observed'] for m in outputs] == names


def _pressured(tmp_path, *, can_read=True):
    context = NodeContext(model='deepseek-v4-pro', artifact_dir=tmp_path, can_read_files=can_read)
    context.max_tokens = 12_000
    messages = [{'role': 'system', 'content': 'Analyze the supplied observations.'}]
    for i in range(4):
        messages.append({'role': 'tool', 'tool_call_id': f'old-{i}', 'name': 'probe',
                         'content': f'old observation {i} ' + 'x' * 16_000})
    context.observe(messages, [], {'input_tokens': 19_000})
    for i in range(2):
        messages.append({'role': 'tool', 'tool_call_id': f'new-{i}', 'name': 'probe',
                         'content': 'fresh observation ' + 'y' * 1_000})
        context.pending.add(f'new-{i}')
    return context, messages


def test_pressure_saves_old_results_and_keeps_the_fresh_batch(tmp_path, monkeypatch):
    monkeypatch.setenv('VIBE_TRADING_ALLOWED_RUN_ROOTS', str(tmp_path))
    context, messages = _pressured(tmp_path)
    originals = {m['tool_call_id']: m['content'] for m in messages[1:]}
    receipts = context.compact(messages, [])
    assert receipts
    assert context.tokens(messages, []) <= context.budget(messages, []).micro_at
    for receipt in receipts:
        assert receipt['tool_call_id'].startswith('old-')
        parts = []
        for path in receipt['paths']:
            read = json.loads(truncate_tool_result(ReadFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path=path, run_dir=str(tmp_path))))
            assert read['status'] == 'ok'
            parts.append(read['content'])
        assert ''.join(parts) == originals[receipt['tool_call_id']]
    assert messages[-1].get('content') == originals['new-1']
    assert messages[-2]['content'] == originals['new-0']
    assert context.compact(messages, []) == []


@pytest.mark.parametrize('cause', ['no-reader', 'write-failure'])
def test_unrecoverable_results_are_never_discarded(tmp_path, monkeypatch, cause):
    context, messages = _pressured(tmp_path, can_read=cause != 'no-reader')
    before = copy.deepcopy(messages)
    if cause == 'write-failure':
        def refuse(*args, **kwargs):
            raise OSError('unwritable')
        monkeypatch.setattr('src.product.result_artifacts._write_original', refuse)
    assert context.compact(messages, []) == []
    assert messages == before
    assert context.tokens(messages, []) > context.budget(messages, []).total


def test_real_usage_and_schema_growth_are_counted(tmp_path):
    context = NodeContext(model='deepseek-v4-pro', artifact_dir=tmp_path, can_read_files=False)
    messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'q'}]
    schemas = [{'type': 'function', 'description': 'large schema ' * 500}]
    assert context.tokens(messages, schemas) > context.tokens(messages, []) + 1000
    context.observe(messages, schemas, {'input_tokens': 150_000})
    assert context.tokens(messages, schemas) == 150_000
    assert context.tokens(messages, []) < 150_000
    context.max_tokens = 100_000
    assert context.tokens(messages, schemas) > context.budget(messages, schemas).total


def test_result_parts_survive_json_escaping_and_redact_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv('VIBE_TRADING_ALLOWED_RUN_ROOTS', str(tmp_path))
    from src.tools.redaction import redact_tool_result
    context, messages = _pressured(tmp_path)
    messages[1]['content'] = json.dumps({'api_key': 'private-value', 'evidence': '\\"\n' * 5000})
    original = redact_tool_result(messages[1]['content'])
    receipts = context.compact(messages, [])
    saved = next(r for r in receipts if r['tool_call_id'] == 'old-0')
    parts = [json.loads(truncate_tool_result(ReadFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path=p, run_dir=str(tmp_path))))['content']
             for p in saved['paths']]
    assert ''.join(parts) == original
    assert 'private-value' not in ''.join(parts)


def test_context_file_symlink_cannot_redirect_writes(tmp_path):
    context, messages = _pressured(tmp_path / 'worker')
    context.artifact_dir.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (context.artifact_dir / 'context-results').symlink_to(outside, target_is_directory=True)
    before = copy.deepcopy(messages)
    assert context.compact(messages, []) == []
    assert messages == before
    assert list(outside.iterdir()) == []


def test_worker_refuses_over_budget_request_without_discarding_fresh_results(tmp_path, monkeypatch):
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(_EvidenceTool('probe'))
    calls = []

    class Model:
        def stream_chat(self, messages, **kwargs):
            calls.append(copy.deepcopy(messages))
            return LLMResponse(tool_calls=[ToolCallRequest(id='fresh', name='probe', arguments={})],
                               usage_metadata={'input_tokens': 999_999, 'output_tokens': 10})

        def close(self):
            pass

    monkeypatch.setattr(worker, 'ChatLLM', lambda **kwargs: Model())
    monkeypatch.setattr(worker, 'build_swarm_registry', lambda *args, **kwargs: registry)
    result = worker.run_node(
        policy=ToolPolicy.from_config(get_env_config()),
        agent_spec=SwarmAgentSpec(id='a', role='Analyst', system_prompt='Analyze.', tools=['probe'], max_iterations=3),
        task=SwarmTask(id='t', agent_id='a', prompt_template='Read.'),
        upstream_summaries={}, user_vars={}, run_dir=tmp_path,
    )
    assert len(calls) == 1
    assert result.status == 'token_limit'
    messages = [item for item in ThreadLog(next(tmp_path.rglob('thread.jsonl'))).read() if item.type == 'tool_result']
    assert json.loads(messages[-1].get('content'))['observed'] == 'probe'


@pytest.mark.parametrize('tools', [['get_market_data'], ['write_file']])
def test_prompt_names_actual_iteration_budget(tools):
    spec = SwarmAgentSpec(id='a', role='Analyst', system_prompt='Analyze.', tools=tools, max_iterations=7)
    prompt = worker.build_worker_prompt(spec, {}, '')
    assert 'at most 7 model iterations' in prompt
    assert 'HARD LIMIT of 20 tool calls' not in prompt


def test_prompt_asks_for_the_language_of_the_users_request_not_the_template():
    spec = SwarmAgentSpec(id='a', role='Analyst', system_prompt='Analyze.', tools=['write_file'], max_iterations=3)
    prompt = worker.build_worker_prompt(spec, {}, '')
    assert "language of the user's own request" in prompt
    assert "task's language" not in prompt
