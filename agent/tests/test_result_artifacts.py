"""Large observations remain usable without resending or refetching them."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.loop import AgentLoop
from src.agent.result_artifacts import deliver_tool_result
from src.agent.tools import BaseTool, ToolRegistry
from src.config.limits import TOOL_RESULT_LIMIT
from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.tools.read_file_tool import ReadFileTool
import src.swarm.worker as worker
from tests.test_agent_loop_deterministic_cache import _drive


@pytest.fixture(autouse=True)
def allow_task_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))


def large_result():
    return json.dumps({
        'status': 'ok', '_provenance': {'source': 'fixture', 'quote_currency': 'USD'},
        'TUSHARE_TOKEN': 'fixture-private-key',
        'AAPL': {'rows': 900, 'returned': 800, 'truncated': True,
                 'data': [{'date': f'row-{i}', 'close': i + .125,
                           'note': 'quoted "field"\n中文'} for i in range(800)]},
    }, ensure_ascii=False)


def registry_with_reader():
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    return registry


def test_complete_json_and_every_readable_part(tmp_path):
    registry = registry_with_reader()
    raw = large_result()
    delivered = deliver_tool_result(raw, tmp_path, registry)
    assert len(delivered) <= TOOL_RESULT_LIMIT
    receipt = json.loads(delivered)
    assert receipt['_provenance']['source'] == 'fixture'
    artifact = receipt['_result_file']
    original = Path(artifact['path']).read_text()
    assert 'fixture-private-key' not in original + delivered
    parsed = json.loads(original)
    assert parsed['AAPL'] == json.loads(raw)['AAPL']
    parts = []
    for index in range(1, artifact['part_count'] + 1):
        part = registry.execute('read_file', {
            'path': str(Path(artifact['parts_dir']) / f'{index}.txt'),
            'run_dir': str(tmp_path),
        })
        assert len(part) <= TOOL_RESULT_LIMIT
        parts.append(json.loads(part)['content'])
    assert ''.join(parts) == original
    assert deliver_tool_result(raw, tmp_path, registry) == delivered


@pytest.mark.parametrize('failure', ['no_reader', 'write_failure', 'symlink', 'modified'])
def test_unavailable_artifact_is_not_claimed(tmp_path, monkeypatch, failure):
    registry = registry_with_reader()
    if failure == 'no_reader':
        registry = ToolRegistry()
    elif failure == 'write_failure':
        def fail(*args, **kwargs):
            raise OSError('disk full')
        monkeypatch.setattr('src.agent.result_artifacts._write_original', fail)
    elif failure == 'symlink':
        outside = tmp_path.parent / f'{tmp_path.name}-outside'
        outside.mkdir()
        (tmp_path / 'tool-results').symlink_to(outside, target_is_directory=True)
    else:
        receipt = json.loads(deliver_tool_result(large_result(), tmp_path, registry))
        Path(receipt['_result_file']['path']).write_text('changed by another writer')
    result = deliver_tool_result(large_result(), tmp_path, registry)
    assert 'TRUNCATED:' in result
    assert '_result_file' not in result
    assert 'fixture-private-key' not in result
    if failure == 'symlink':
        assert not list(outside.iterdir())
    if failure == 'modified':
        assert Path(receipt['_result_file']['path']).read_text() == 'changed by another writer'


def test_unencodable_result_falls_back_to_truncation(tmp_path):
    # An upstream payload that cut an emoji in half keeps a lone surrogate
    # through json.dumps(ensure_ascii=False); hashing it must not escape.
    raw = large_result()[:-1] + ', "title": "\ud83d"}'
    result = deliver_tool_result(raw, tmp_path, registry_with_reader())
    assert 'TRUNCATED:' in result
    assert '_result_file' not in result


class _LargeResult(BaseTool):
    name = 'large_result_probe'
    description = 'Test large observation delivery.'
    parameters = {'type': 'object', 'properties': {}}
    deterministic = True
    repeatable = True
    is_readonly = True

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def execute(self, **kwargs):
        self.calls += 1
        return self.result


def test_main_fresh_and_cached_results_use_same_complete_file(tmp_path):
    registry = registry_with_reader()
    tool = _LargeResult(large_result())
    registry.register(tool)
    agent = AgentLoop(registry=registry, llm=SimpleNamespace(), max_iterations=3)
    agent.memory.run_dir = str(tmp_path)
    messages, _ = _drive(agent, tool.name, tmp_path, [{}, {}])
    assert tool.calls == 1
    paths = [json.loads(message['content'])['_result_file']['path'] for message in messages]
    assert len(set(paths)) == 1
    assert len(json.loads(Path(paths[0]).read_text())['AAPL']['data']) == 800


def test_worker_model_can_recover_complete_result(tmp_path, monkeypatch):
    registry = registry_with_reader()
    registry.register(_LargeResult(large_result()))
    seen = []

    class Model:
        def stream_chat(self, messages, **kwargs):
            seen.append(copy.deepcopy(messages))
            if len(seen) == 1:
                return LLMResponse(tool_calls=[ToolCallRequest(
                    id='large', name='large_result_probe', arguments={})])
            receipt = json.loads(next(m['content'] for m in messages if m['role'] == 'tool'))
            data = json.loads(Path(receipt['_result_file']['path']).read_text())
            assert data['AAPL']['data'][-1]['close'] == 799.125
            assert data['AAPL']['truncated'] is True
            return LLMResponse(content='The requested source observations are available in full, with source sampling retained. ' * 5)

        def close(self):
            pass

    monkeypatch.setattr(worker, 'ChatLLM', lambda **kwargs: Model())
    monkeypatch.setattr(worker, 'build_swarm_registry', lambda *args, **kwargs: registry)
    result = worker.run_worker(
        agent_spec=SwarmAgentSpec(id='analyst', role='Analyst', system_prompt='Read evidence.',
                                  tools=['large_result_probe', 'read_file'], max_iterations=3),
        task=SwarmTask(id='t', agent_id='analyst', prompt_template='Read evidence.'),
        upstream_summaries={}, user_vars={}, run_dir=tmp_path,
    )
    assert result.status == 'completed'
    assert len(seen) == 2
    assert 'fixture-private-key' not in json.dumps(seen)
