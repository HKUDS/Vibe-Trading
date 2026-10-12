"""A successor keeps current filings and inherits dated predecessor facts."""
from copy import deepcopy

from backtest.loaders import sec_edgar_client as sec


def test_successor_facts_include_only_pre_change_history(monkeypatch):
    def facts(cik, rows):
        return {"cik": cik, "facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}
    old_row = {"end": "2024-12-31", "filed": "2025-02-01", "val": 100}
    subsidiary_row = {"end": "2026-09-30", "filed": "2026-11-01", "val": 1}
    new_row = {"end": "2026-09-30", "filed": "2026-11-01", "val": 200}
    current = facts(2115436, [new_row])
    original = deepcopy(current)
    old = facts(34088, [old_row, subsidiary_row])
    urls = []
    def fetch(url):
        urls.append(url)
        return old if '0000034088' in url else current
    monkeypatch.setattr(sec, '_sec_get_json', fetch)
    monkeypatch.setattr(sec, '_ticker_map', lambda: {'XOM': '0002115436'})
    assert sec.cik_for('XOM.US') == '0002115436'
    result = sec.get_company_facts(sec.cik_for('XOM'))
    assert result['cik'] == 2115436
    assert result['facts']['us-gaap']['Revenues']['units']['USD'] == [new_row, old_row]
    assert current == original
    assert len(urls) == 2
