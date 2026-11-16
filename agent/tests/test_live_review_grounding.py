"""Sparse, two-sided regressions for failures captured in real model traces."""
import hashlib
import json

import pytest

from evals.grounding import GroundingLedger
from tests.test_grounding_backtest_outputs import _backtest, _declared, _read, _write_backtest


@pytest.mark.parametrize('unit,currency', [('USD', 'USD'), ('EUR', 'EUR'), ('USD/shares', 'USD')])
def test_statement_leaf_unit_is_scoped_money_not_a_quote(tmp_path, unit, currency):
    ledger = GroundingLedger(run_dir=tmp_path, user_message='Summarize filing')
    ledger.ingest_tool_result(tool_name='get_financial_statements', arguments={'code': 'TEST.US'},
        call_id='sec', success=True, result=json.dumps({'data': {'TEST.US': {'periods': [
            {'_units': {'Revenues': unit, 'Shares': 'shares'}, 'Revenues': 400000000.0, 'Shares': 700000000.0}
        ]}}}))
    ref = 'sec::data.TEST.US.periods[0].Revenues'
    def check(value, ref=ref):
        return ledger.validate_final_answer(_declared(f'Reported {value}.', f'400M | observed | filing amount | {ref}'))
    assert check(f'400.0 million {currency}').valid
    assert not check(f'408.0 million {currency}').valid
    assert not check('400.0 million JPY').valid
    assert not check('400000000%').valid
    assert not check(f'400.0 million {currency}', 'sec::data.TEST.US.periods[0].Shares').valid
    assert not ledger.validate_final_answer(f'Price is 400.0 million {currency}.').valid
    assert not ledger._comparable_price_records()


def _table_ledger(tmp_path):
    _write_backtest(tmp_path, {'trade_count': 103, 'sharpe': .48})
    path = tmp_path / 'artifacts/ohlcv_TEST.US.csv'
    path.write_text('trade_date,open,close\n2024-01-02,118.96,118.56\n2024-01-03,128.96,128.56\n')
    card = json.loads((tmp_path / 'run_card.json').read_text())
    card['artifacts'].append({'path': 'artifacts/ohlcv_TEST.US.csv', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (tmp_path / 'run_card.json').write_text(json.dumps(card))
    ledger = GroundingLedger(run_dir=tmp_path, user_message='Report backtest')
    _backtest(ledger, tmp_path, 'bt')
    return ledger, path


@pytest.mark.parametrize('reader', ['read_file', 'read_run_artifact'])
def test_only_shown_unchanged_engine_prices_can_ground_file_refs(tmp_path, reader):
    ledger, path = _table_ledger(tmp_path)
    def check(value, ref='artifacts/ohlcv_TEST.US.csv::close'):
        return ledger.validate_final_answer(_declared(f'Signal close was ${value:.2f}.', f'{value:.2f} | observed | signal close | {ref}'))
    assert not check(118.56).valid  # Not read yet.
    if reader == 'read_file':
        _read(ledger, path, 'shown', limit=2)
    else:
        ledger.ingest_tool_result(tool_name=reader, arguments={'run_dir': str(tmp_path)}, call_id='shown', success=True,
            result=json.dumps({'path': str(path), 'columns': ['trade_date', 'open', 'close'],
                               'rows': [['2024-01-02', 118.96, 118.56]]}))
    assert check(118.56).valid
    assert not check(120.56).valid
    assert not check(128.56).valid  # Unshown row is not evidence.
    assert not check(118.56, 'artifacts/ohlcv_TEST.US.csv::open').valid
    assert not ledger.validate_final_answer('Price was $118.56.').valid
    assert not ledger._comparable_price_records()
    # A later modified row cannot supply a new observation.
    path.write_text(path.read_text().replace('128.56', '138.56'))
    _read(ledger, path, 'modified')
    assert not check(138.56).valid


def test_wrong_artifact_ref_is_rejected_with_real_reference_to_copy(tmp_path):
    ledger, _ = _table_ledger(tmp_path)
    prose = '| Metric | Value |\n|---|---|\n| Trade count | 103 |'
    bad = ledger.validate_final_answer(_declared(prose, '103 | observed | trade count | rp/artifacts/metrics.csv'))
    assert not bad.valid
    assert bad.issues[0]['reason'] == 'unknown_artifact_ref'
    assert 'artifacts/metrics.csv::trade_count' in bad.issues[0]['field_ref_candidates']
    assert ledger.validate_final_answer(_declared(prose, '103 | observed | trade count | artifacts/metrics.csv::trade_count')).valid
    missing = ledger.validate_final_answer(_declared(prose, '.48 | observed | sharpe | artifacts/metrics.csv'))
    assert any('artifacts/metrics.csv::trade_count' in i.get('field_ref_candidates', []) for i in missing.issues)
    assert not ledger.validate_final_answer(_declared(prose.replace('103', '104'), '104 | observed | trade count | artifacts/metrics.csv::trade_count')).valid
