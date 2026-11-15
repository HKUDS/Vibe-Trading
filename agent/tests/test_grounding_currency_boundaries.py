"""Currency identity survives magnitude marks without inventing word matches."""
import json

import pytest

from evals.grounding import GroundingLedger
from evals.grounding.figures import parse_figures_block, scan_figures


@pytest.mark.parametrize(('text', 'code'), [
    ('Value 2.5B JPY.', 'JPY'),
    ('Value 2.5亿 CNY.', 'CNY'),
    ('Value CHF 2.5.', 'CHF'),
    ('Value NZD 2.5.', 'NZD'),
    ('Value ₩2.5.', 'KRW'),
    ('Value ₹2.5.', 'INR'),
    ('Value 2.5 美元素描', None),
])
def test_currency_shape_boundaries(text, code):
    [figure] = scan_figures(text, parse_figures_block(text))
    assert figure.currency_code == code


@pytest.mark.parametrize(('unit', 'claim', 'valid'), [
    ('USD', '2.5B USD', True),
    ('USD', '2.5B JPY', False),
    ('CHF', 'CHF 2,500,000,000', True),
    ('CHF', 'USD 2,500,000,000', False),
    ('THB', 'THB 2,500,000,000', True),
    ('shares', 'USD 2,500,000,000', False),
])
def test_sec_currency_units_and_scaled_claims(tmp_path, unit, claim, valid):
    ledger = GroundingLedger(run_dir=tmp_path, user_message='Analyze HE.US debt')
    ledger.ingest_tool_result(
        tool_name='get_sec_filings', arguments={'ticker': 'HE'}, call_id='sec1', success=True,
        result=json.dumps({'ok': True, 'market': 'US', 'source': 'sec_edgar', 'data': {
            'ticker': 'HE', 'metric': {'unit': unit, 'points': [{'val': 2500000000}]}}}),
    )
    declared = '2.5B' if '2.5B' in claim else '2500000000'
    answer = f'HE.US debt: {claim}.\n```figures\n{declared} | observed | debt | sec1\n```'
    verdict = ledger.validate_final_answer(answer)
    assert verdict.valid is valid, verdict.issues
