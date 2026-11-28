"""Large observations remain usable without resending or refetching them."""

from src.tools.path_utils import FileRoots


from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.runtime import AgentRuntime
from src.product.result_artifacts import deliver_tool_result
from src.agent.tools import BaseTool, ToolRegistry
from src.config.limits import TOOL_RESULT_LIMIT
from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.tools.read_file_tool import ReadFileTool
import src.swarm.node as worker
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
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(ReadFileTool(roots=FileRoots.from_config(get_env_config().api)))
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
        registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    elif failure == 'write_failure':
        def fail(*args, **kwargs):
            raise OSError('disk full')
        monkeypatch.setattr('src.product.result_artifacts._write_original', fail)
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
    agent = AgentRuntime(registry=registry, llm=SimpleNamespace(), max_iterations=3)
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
    result = worker.run_node(
        policy=ToolPolicy.from_config(get_env_config()),
        agent_spec=SwarmAgentSpec(id='analyst', role='Analyst', system_prompt='Read evidence.',
                                  tools=['large_result_probe', 'read_file'], max_iterations=3),
        task=SwarmTask(id='t', agent_id='analyst', prompt_template='Read evidence.'),
        upstream_summaries={}, user_vars={}, run_dir=tmp_path,
    )
    assert result.status == 'completed'
    assert len(seen) == 2
    assert 'fixture-private-key' not in json.dumps(seen)


def _two_symbol_prices():
    return {
        'FIRST': [{'close': 7.25, 'date': f'row-{i}'} for i in range(1000)],
        'LAST': [{'close': 812.50, 'date': f'row-{i}'} for i in range(1000)],
        '_provenance': {'FIRST': {'quote_currency': 'EUR'}, 'LAST': {'quote_currency': 'JPY'}},
    }


@pytest.mark.parametrize('delivery', ['calculation', 'generic'])
def test_large_json_receipt_preserves_identity_without_spliced_prices(tmp_path, delivery):
    from src.product.result_artifacts import persist_calculation_result
    from src.tools.data_refs import resolve_data_refs

    payload = _two_symbol_prices()
    raw = json.dumps(payload)
    roots = FileRoots.from_config(get_env_config().api)
    if delivery == 'calculation':
        response = persist_calculation_result(raw, tmp_path, roots=roots)
    else:
        response = deliver_tool_result(raw, tmp_path, registry_with_reader())
    receipt = json.loads(response)
    assert len(response) <= TOOL_RESULT_LIMIT
    assert receipt['_provenance'] == payload['_provenance']
    # A head+tail text splice shows FIRST's prices beside LAST's as one series.
    assert '7.25' not in json.dumps(receipt.get('_preview'))
    assert '812.5' not in json.dumps(receipt.get('_preview'))
    outline = receipt['_preview']
    assert outline['type'] == 'object'
    assert outline['fields']['FIRST'] == {'type': 'array', 'length': 1000, 'items': {
        'type': 'object', 'fields': {'close': {'type': 'number'}, 'date': {'type': 'string'}}}}
    assert outline['fields']['LAST']['length'] == 1000
    assert json.loads(Path(receipt['_result_file']['path']).read_text()) == payload
    for name, expected in [('FIRST', 7.25), ('LAST', 812.50)]:
        value = resolve_data_refs({'__data_ref__': {
            'path': receipt['_result_file']['path'], 'pointer': f'/{name}',
            'column': 'close', 'select': 'last',
        }}, str(tmp_path), [], roots=roots)
        assert value == expected


def test_large_calculation_provenance_stays_bounded_without_losing_original(tmp_path):
    from src.product.result_artifacts import persist_calculation_result

    payload = {'_provenance': {'sources': ['A source entry' * 100] * 100}}
    response = persist_calculation_result(json.dumps(payload), tmp_path,
                                          roots=FileRoots.from_config(get_env_config().api))
    receipt = json.loads(response)
    assert len(response) <= TOOL_RESULT_LIMIT
    assert '_provenance' not in receipt
    assert '_metadata_location' in receipt
    assert json.loads(Path(receipt['_result_file']['path']).read_text()) == payload


def test_large_text_result_keeps_its_text_preview(tmp_path):
    raw = 'head line\n' + 'x' * (TOOL_RESULT_LIMIT * 2) + '\ntail line'
    receipt = json.loads(deliver_tool_result(raw, tmp_path, registry_with_reader()))
    assert receipt['_preview'].startswith('head line')
    assert receipt['_preview'].endswith('tail line')


def _numbered_source(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text(''.join(f'line {i:06d} ' + 'x' * 40 + '\n' for i in range(2000)))
    return source


@pytest.mark.parametrize('arguments', [{}, {'limit': 300}], ids=['size_cap', 'line_limit'])
def test_offloaded_partial_read_file_receipt_says_what_was_saved(tmp_path, arguments):
    source = _numbered_source(tmp_path)
    original = source.read_text()
    agent = AgentRuntime(registry=registry_with_reader(), llm=SimpleNamespace(), max_iterations=3)
    agent.memory.run_dir = str(tmp_path)
    messages, _ = _drive(agent, 'read_file', tmp_path, [{'path': 'source.txt', **arguments}])
    delivered = messages[-1]['content']
    assert len(delivered) <= TOOL_RESULT_LIMIT
    receipt = json.loads(delivered)
    saved = json.loads(Path(receipt['_result_file']['path']).read_text())
    assert saved['truncated'] is True
    # The receipt keeps the source path and truncation fields the read returned.
    assert receipt['path'] == str(source.resolve())
    assert receipt['truncated'] is True
    assert receipt['total_chars'] == len(original)
    assert original.startswith(saved['content'][:receipt['returned_chars']])
    assert receipt['returned_chars'] < len(original)
    if arguments:
        assert (receipt['returned_lines'], receipt['total_lines']) == (300, 2000)
    # It never claims the complete source was saved or is loadable as data.
    assert 'complete tool result' not in receipt['_delivery']
    assert '__data_ref__' not in receipt['_delivery']
    assert 'Do not refetch' not in receipt['_delivery']
    assert f"first {receipt['returned_chars']} of {len(original)} characters" in receipt['_delivery']


def test_offloaded_complete_read_file_receipt_keeps_the_source_path(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('y' * (TOOL_RESULT_LIMIT * 2))
    agent = AgentRuntime(registry=registry_with_reader(), llm=SimpleNamespace(), max_iterations=3)
    agent.memory.run_dir = str(tmp_path)
    messages, _ = _drive(agent, 'read_file', tmp_path, [{'path': 'source.txt'}])
    receipt = json.loads(messages[-1]['content'])
    assert receipt['path'] == str(source.resolve())
    assert 'truncated' not in receipt
    assert 'complete text of the source file' in receipt['_delivery']
    saved = json.loads(Path(receipt['_result_file']['path']).read_text())
    assert saved['content'] == source.read_text()


def test_other_tool_envelope_is_not_described_as_a_file_read(tmp_path):
    raw = json.dumps({'status': 'ok', 'path': 'another.json', 'content': 'x' * 15000, 'truncated': True})
    receipt = json.loads(deliver_tool_result(raw, tmp_path, registry_with_reader(), tool_name='other_tool'))
    assert 'path' not in receipt
    assert 'source file' not in receipt['_delivery']


def _registry(with_shell: bool):
    registry = registry_with_reader()
    if with_shell:
        from src.tools.bash_tool import BashTool

        registry.register(BashTool(sandbox=registry.policy.sandbox))
    return registry


@pytest.mark.parametrize('with_shell', [False, True], ids=['reader_only', 'with_shell'])
@pytest.mark.parametrize('arguments', [{}, {'limit': 300}], ids=['size_cap', 'line_limit'])
def test_offloaded_partial_read_file_receipt_continues_with_offset(tmp_path, arguments, with_shell):
    """The receipt names the read_file call that returns the next unread line.

    Args:
        tmp_path: Allowed directory containing the test file and result artifacts.
        arguments: Optional line limit for the read.
        with_shell: Whether the registry also offers a shell.
    """
    source = _numbered_source(tmp_path)
    lines = source.read_text().splitlines(keepends=True)
    agent = AgentRuntime(registry=_registry(with_shell), llm=SimpleNamespace(), max_iterations=3)
    agent.memory.run_dir = str(tmp_path)
    messages, _ = _drive(agent, 'read_file', tmp_path, [{'path': 'source.txt', **arguments}])
    receipt = json.loads(messages[-1]['content'])
    following = receipt['next_offset']
    assert following == receipt['returned_lines']
    assert f'offset={following}' in receipt['_delivery']
    assert 'no offset' not in receipt['_delivery']
    assert 'bash' not in receipt['_delivery']
    nxt, _ = _drive(agent, 'read_file', tmp_path, [{'path': 'source.txt', 'offset': following, **arguments}])
    body = json.loads(nxt[-1]['content'])
    if '_result_file' in body:
        body = json.loads(Path(body['_result_file']['path']).read_text())
    assert body['content'].startswith(lines[following])


def test_offloaded_json_read_carries_the_source_structure(tmp_path):
    """An offloaded JSON read supplies pointers into the original file.

    Args:
        tmp_path: Allowed directory containing the source and result artifacts.
    """
    source = tmp_path / 'records.json'
    rows = [{'id': i, 'value': i + .5} for i in range(2500)]
    payload = {
        'records/spot~': rows,
        'meta': {'source': 'fixture'},
        'notes': [{'body': 'x' * 500}, {'account_number': 'fixture-private-account'}],
    }
    source.write_text(json.dumps(payload))
    agent = AgentRuntime(registry=registry_with_reader(), llm=SimpleNamespace(), max_iterations=3)
    agent.memory.run_dir = str(tmp_path)
    messages, _ = _drive(agent, 'read_file', tmp_path, [{'path': 'records.json'}])
    delivered = messages[-1]['content']
    assert len(delivered) <= TOOL_RESULT_LIMIT
    receipt = json.loads(delivered)
    shape = receipt['_structure']
    assert shape['path'] == str(source.resolve()) == receipt['path']
    records, meta, notes = shape['fields']
    pointer = '/records~1spot~0'
    assert (records['pointer'], records['type'], records['length']) == (pointer, 'array', 2500)
    assert records['first_item_fields'] == ['id', 'value']
    assert records['boundary_samples'] == [
        {'pointer': f'{pointer}/0', 'value': rows[0]},
        {'pointer': f'{pointer}/2499', 'value': rows[2499]},
    ]
    assert meta == {'pointer': '/meta', 'type': 'object', 'length': 1}
    assert notes['boundary_samples'] == [
        {'pointer': '/notes/0'},
        {'pointer': '/notes/1', 'value': {'account_number': '[redacted]'}},
    ]
    assert 'fixture-private-account' not in delivered
    assert 'pointer' in receipt['_delivery'] and '_structure' in receipt['_delivery']
    selected, _ = _drive(agent, 'read_file', tmp_path, [{'path': shape['path'], 'pointer': f'{pointer}/2499'}])
    assert json.loads(json.loads(selected[-1]['content'])['content']) == rows[2499]


def test_small_or_text_read_carries_no_structure(tmp_path):
    """An inline JSON read and a text preview omit JSON navigation metadata.

    Args:
        tmp_path: Allowed directory for both source files.
    """
    source = tmp_path / 'small.json'
    source.write_text(json.dumps({'a': [1, 2]}))
    text = _numbered_source(tmp_path)
    tool = ReadFileTool(roots=FileRoots.from_config(get_env_config().api))
    assert '_structure' not in json.loads(tool.execute(path=str(source), run_dir=str(tmp_path)))
    assert '_structure' not in json.loads(tool.execute(path=str(text), run_dir=str(tmp_path)))


def test_offloaded_long_line_receipt_keeps_the_character_cursor(tmp_path):
    """An offloaded partial line advertises the character needed to resume it.

    Args:
        tmp_path: Allowed directory containing the source and result artifacts.
    """
    source = tmp_path / 'line.txt'
    source.write_text('x' * 50_010, encoding='utf-8')
    registry = registry_with_reader()
    arguments = {'path': source.name, 'run_dir': str(tmp_path)}
    raw = registry.execute('read_file', arguments)
    receipt = json.loads(deliver_tool_result(raw, tmp_path, registry, tool_name='read_file'))
    assert receipt['next_offset'] == 0
    assert receipt['next_char_offset'] == receipt['returned_chars']
    assert f'char_offset={receipt["next_char_offset"]}' in receipt['_delivery']
    last = json.loads(registry.execute('read_file', {
        **arguments, 'offset': receipt['next_offset'], 'char_offset': receipt['next_char_offset'],
    }))
    assert last['content'] == source.read_text(encoding='utf-8')[receipt['returned_chars']:]
