"""Exact user windows affect acquisition; explicit warmup retains calculation history."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from src.agent.data_window import UserDataWindow
from src.agent.loop import AgentLoop
from src.agent.tools import ToolRegistry
from src.tools.market_data_tool import MarketDataTool
from src.tools.technical_indicator_tool import TechnicalIndicatorTool
from tests.test_agent_loop_deterministic_cache import _drive

PROMPT = 'AAPL.US、00700.HK 在 2026-11-12 至 2026-11-13 的收盘价，保存 CSV'
ARGS = dict(codes=['AAPL.US'], start_date='2026-11-10', end_date='2026-11-13', max_rows=0)


@pytest.mark.parametrize('separator', ['至', '到', 'to', 'through', '–', '..', '～'])
def test_explicit_literal_range(separator):
    window = UserDataWindow.parse(PROMPT.replace('至', separator))
    assert window.start == '2026-11-12' and window.end == '2026-11-13'
    args = {**ARGS, 'end_date': '2026-11-16'}
    normalized = window.normalize(args)
    assert normalized['start_date'] == '2026-11-12'
    assert normalized['end_date'] == '2026-11-13'
    assert args['start_date'] == '2026-11-10'  # No mutation of signed model messages.


@pytest.mark.parametrize('message', [
    'AAPL.US 最近两天', 'AAPL.US 2026-11-12 and 2026-11-13',
    'AAPL.US 2026-11-12 至 2026-11-13；00700.HK 2026-10-01 至 2026-10-03',
    'AAPL.US 2026-02-30 至 2026-03-02', 'AAPL.US 2026-11-13 至 2026-11-12',
    'Apple 2026-11-12 至 2026-11-13',
])
def test_ambiguous_invalid_and_multiwindow_requests_are_not_guessed(message):
    assert UserDataWindow.parse(message) is None


@pytest.mark.parametrize('change', [
    {'start_date':'2026-11-12'},
    {'start_date':'2026-11-13'},  # A partition inside the requested interval.
    {'start_date':'2025-11-12','end_date':'2025-11-13'},  # Disjoint comparison.
    {'codes':['TD.TO']}, {'codes':['AAPL.US','TD.TO']},
    {'start_date':'2026-02-30'}, {'start_date':'2026-11-14'},
    {'start_date':None}, {'codes':'AAPL.US'},
])
def test_no_unrelated_range_or_invalid_argument_rewriting(change):
    args = {**ARGS, **change}
    assert UserDataWindow.parse(PROMPT).normalize(args) is args


def test_normalized_hk_alias_and_case():
    args = {**ARGS, 'codes':['700.hk']}
    assert UserDataWindow.parse(PROMPT).normalize(args)['start_date']=='2026-11-12'


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('VIBE_TRADING_ALLOWED_RUN_ROOTS', str(tmp_path))
    seen=[]
    def fetch(**kwargs):
        seen.append(kwargs)
        days=pd.date_range(kwargs['start_date'],kwargs['end_date'])
        return json.dumps({'AAPL.US':[{'trade_date':str(d.date()),'close':(d.day-9)*10} for d in days]})
    monkeypatch.setattr('src.tools.market_data_tool.fetch_market_data_json',fetch)
    registry=ToolRegistry()
    registry.register(MarketDataTool())
    agent=AgentLoop(registry=registry,llm=SimpleNamespace())
    agent.memory.run_dir=str(tmp_path)
    agent._user_data_window=UserDataWindow.parse(PROMPT)
    return agent, seen, tmp_path


def test_actual_tool_boundary_fetches_only_user_dates_and_records_correction(runtime):
    agent, seen, path=runtime
    messages,trace=_drive(agent,'get_market_data',path,[ARGS])
    assert len(seen)==1 and seen[0]['start_date']=='2026-11-12'
    assert seen[0]['end_date']=='2026-11-13'
    out=json.loads(messages[-1]['content'])
    assert [r['trade_date'] for r in out['AAPL.US']]==['2026-11-12','2026-11-13']
    assert out['_csv_file']['rows']==2
    assert out['_request_window']['normalization']['model_start']=='2026-11-10'
    assert any(r['type']=='data_window_normalized' for r in trace)
    assert not any(r.get('status')=='error' for r in trace)
    assert len(messages)==1 and messages[0]['tool_call_id']=='call_1'


def test_explicit_warmup_preserves_prefix_and_valid_rolling_calculation(runtime):
    agent,seen,path=runtime
    messages,_=_drive(agent,'get_market_data',path,[{**ARGS,'warmup_start_date':'2026-11-10'}])
    assert seen[0]['start_date']=='2026-11-10'
    out=json.loads(messages[-1]['content'])
    assert out['_request_window']['analysis_start']=='2026-11-12'
    assert out['_request_window']['acquisition_start']=='2026-11-10'
    assert out['_csv_file']['rows']==4
    frame=pd.DataFrame(out['AAPL.US']).set_index('trade_date')
    assert frame.close.rolling(3).mean().loc['2026-11-12']==20
    assert pd.isna(frame.loc['2026-11-12':].close.rolling(3).mean().iloc[0])


@pytest.mark.parametrize('warmup',[True,'bad','2026-02-30','2026-11-12','2026-11-14'])
def test_invalid_warmup_never_fetches(runtime,warmup):
    agent,seen,path=runtime
    messages,_=_drive(agent,'get_market_data',path,[{**ARGS,'warmup_start_date':warmup}])
    assert not seen and json.loads(messages[-1]['content'])['ok'] is False


def test_standalone_market_tool_has_no_inferred_user_range(runtime):
    _,seen,path=runtime
    MarketDataTool().execute(**ARGS,run_dir=str(path))
    assert seen[0]['start_date']=='2026-11-10'


def test_technical_indicator_lookback_is_not_clipped(runtime,monkeypatch):
    agent,_,path=runtime
    fetch=Mock(return_value={'AAPL.US':pd.DataFrame({'close':range(1,161),'volume':range(1,161)},index=pd.date_range('2026-06-07',periods=160))})
    monkeypatch.setattr('src.tools.technical_indicator_tool.fetch_market_data',fetch)
    agent.registry.register(TechnicalIndicatorTool())
    messages,_=_drive(agent,'technical_indicators',path,[{'symbol':'AAPL.US','end_date':'2026-11-13','lookback':120}])
    assert fetch.call_count==1
    assert fetch.call_args.kwargs['start_date']<'2026-11-12'
    assert fetch.call_args.kwargs['max_rows']==0
    assert json.loads(messages[-1]['content'])['ok'] is True


def test_mcp_forwards_explicit_warmup(monkeypatch):
    import mcp_server
    registry=Mock()
    monkeypatch.setattr(mcp_server,'_get_registry',lambda:registry)
    fn=getattr(mcp_server.get_market_data,'fn',None) or getattr(mcp_server.get_market_data,'__wrapped__',mcp_server.get_market_data)
    fn(codes=['AAPL.US'],start_date='2026-11-12',end_date='2026-11-13',warmup_start_date='2026-11-10')
    args=registry.execute.call_args.args[1]
    assert args['start_date']=='2026-11-12' and args['warmup_start_date']=='2026-11-10'
