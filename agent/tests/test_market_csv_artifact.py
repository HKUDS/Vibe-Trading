"""CSV export reuses observations, preserves provenance and respects artifact bounds."""

import csv
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.config.limits import TOOL_RESULT_LIMIT
from src.tools.market_data_tool import MarketDataTool
import src.tools.market_data_tool as market


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('VIBE_TRADING_ALLOWED_RUN_ROOTS', str(tmp_path))
    payload = {
        'AAPL.US': [{'trade_date': '2026-11-12T00:00:00', 'close': 123.123456789, 'volume': 1.25}],
        '7203.T': {'rows': 300, 'returned': 1, 'truncated': True,
                   'data': [{'trade_date': '2026-11-13T00:00:00', 'close': 3408, 'volume': None}]},
        '_provenance': {'AAPL.US': {'source': 'yahoo', 'quote_currency': 'USD', 'adjustment': 'split_dividend', 'volume_unit': 'shares'},
                        '7203.T': {'source': 'fixture,"quoted"\nsource', 'quote_currency': 'JPY', 'adjustment': 'raw'}},
        '_unresolved': ['BHP.AX'], '_diagnostics': {'BHP.AX': [{'reason': 'unsupported_market'}]},
    }
    fetch = Mock(side_effect=lambda **kw: json.dumps(payload))
    monkeypatch.setattr(market, 'fetch_market_data_json', fetch)
    args = dict(codes=['AAPL.US', '7203.T', 'BHP.AX'], start_date='2026-11-12', end_date='2026-11-13', run_dir=str(tmp_path))
    return payload, fetch, args


def call(args, **kw):
    return json.loads(MarketDataTool().execute(**{**args, **kw}))


def test_csv_has_exact_rows_and_provenance_without_refetch(setup):
    payload, fetch, args = setup
    out = call(args)
    fetch.assert_called_once()
    assert 'export_csv' not in fetch.call_args.kwargs
    ref = out['_csv_file']
    path = Path(ref['path'])
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == ref['rows'] == 2
    assert list(rows[0]) == ref['columns']
    assert rows[0]['close'] == '123.123456789' and rows[0]['volume'] == '1.25'
    assert rows[0]['currency'] == 'USD' and rows[0]['sampled'] == 'False'
    assert rows[1]['currency'] == 'JPY' and rows[1]['sampled'] == 'True'
    assert rows[1]['source'] == payload['_provenance']['7203.T']['source']
    assert rows[1]['volume_unit'] == rows[1]['volume'] == rows[1]['timezone'] == ''
    assert ref['sampled'] is True
    assert list(csv.DictReader(ref['preview_csv'].splitlines(keepends=True))) == rows
    assert ref['preview_rows'] == 2
    assert ref['bytes'] == path.stat().st_size
    assert ref['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert out['_unresolved'] == ['BHP.AX'] and '_data_layout' in out
    original = json.loads(Path(out['_result_file']['path']).read_text())
    assert original['AAPL.US'] == payload['AAPL.US']


def test_explicit_opt_out_does_not_create_csv(setup):
    _, _, args = setup
    assert '_csv_file' not in call(args, export_csv=False)
    assert not list(Path(args['run_dir']).rglob('*.csv'))


@pytest.mark.parametrize('value', ['true', 1, None])
def test_invalid_export_does_not_fetch(setup, value):
    _, fetch, args = setup
    assert call(args, export_csv=value)['ok'] is False
    fetch.assert_not_called()


def test_export_requires_authorized_workspace_before_fetch(setup, tmp_path):
    _, fetch, args = setup
    assert call(args, export_csv=True, run_dir=None)['ok'] is False
    assert call(args, export_csv=True, run_dir=str(tmp_path.parent / 'outside'))['ok'] is False
    fetch.assert_not_called()


def test_large_response_keeps_csv_schema_and_sampling_diagnostics(setup):
    payload, _, args = setup
    payload['AAPL.US'] *= 300
    out = MarketDataTool().execute(**args, export_csv=True)
    assert len(out) <= TOOL_RESULT_LIMIT
    receipt = json.loads(out)
    assert '_preview' in receipt and '_data_layout' in receipt
    assert receipt['_csv_file']['rows'] == 301
    assert receipt['_unresolved'] == ['BHP.AX']


def test_changed_csv_is_not_overwritten_or_claimed(setup):
    _, _, args = setup
    first = call(args, export_csv=True)
    path = Path(first['_csv_file']['path'])
    assert call(args, export_csv=True)['_csv_file'] == first['_csv_file']
    path.write_text('user edit')
    out = call(args, export_csv=True)
    assert '_csv_file' not in out and 'modified' in out['_csv_error']
    assert path.read_text() == 'user edit'
    assert not list(path.parent.glob('.bars-*'))


def test_escaping_csv_symlink_is_refused(setup, tmp_path):
    _, _, args = setup
    out = call(args, export_csv=False)
    path = Path(out['_result_file']['path']).with_name('bars.csv')
    outside = tmp_path.parent / (tmp_path.name + '-outside.csv')
    path.symlink_to(outside)
    out = call(args, export_csv=True)
    assert '_csv_file' not in out and 'escapes' in out['_csv_error']
    assert not outside.exists()


def test_disk_failure_preserves_json_and_reports_export_failure(setup, monkeypatch):
    _, _, args = setup
    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr('src.data_gateway.bar_artifact.os.link', fail)
    out = call(args, export_csv=True)
    assert '_result_file' in out and '_csv_file' not in out
    assert out['_csv_error'] == 'disk full'
    assert not list(Path(args['run_dir']).rglob('.bars-*'))


def test_mcp_forwards_export_csv(setup, monkeypatch):
    import mcp_server
    _, _, args = setup
    registry = Mock()
    monkeypatch.setattr(mcp_server, '_get_registry', lambda: registry)
    fn = getattr(mcp_server.get_market_data, 'fn', None) or getattr(mcp_server.get_market_data, '__wrapped__', mcp_server.get_market_data)
    fn(**args, export_csv=True)
    assert registry.execute.call_args.args[1]['export_csv'] is True
    assert registry.execute.call_args.args[1]['run_dir'] == args['run_dir']
