"""Brazilian official datasets: parsers, store, loader and agent tool.

Fixtures are synthetic files in the published layouts (B3 COTAHIST fixed
width, CVM ``;`` CSVs, BCB JSON, Tesouro CSV). No network.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import pytest

from src.br_data import cotahist, cvm_companies, cvm_funds, tesouro
from src.br_data._download import br_date, to_float
from src.br_data.store import connect, init_db
from tests.loader_contract import assert_loader_contract


def _cotahist_line(day: str, ticker: str, tpmerc: int, close_cents: int, *,
                   bdi: str = "02", factor: int = 1, qty: int = 1000) -> str:
    """Build one 245-char COTAHIST type-01 record."""
    fields = [
        "01", day, bdi.ljust(2), ticker.ljust(12), f"{tpmerc:03d}", "PETROBRAS".ljust(12),
        "PN      N2".ljust(10), " " * 3, "R$".ljust(4),
        f"{close_cents - 10:013d}", f"{close_cents + 20:013d}", f"{close_cents - 30:013d}",
        f"{close_cents:013d}", f"{close_cents:013d}", f"{close_cents - 1:013d}", f"{close_cents + 1:013d}",
        f"{150:05d}", f"{qty:018d}", f"{qty * close_cents:018d}", f"{0:013d}", "0", "99991231",
        f"{factor:07d}", f"{0:013d}", "BRPETRACNPR6", "123",
    ]
    line = "".join(fields)
    assert len(line) == 245, len(line)
    return line


def _zip(name: str, text: str, encoding: str = "latin-1") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(name, text.encode(encoding))
    return buf.getvalue()


@pytest.fixture()
def store(tmp_path, monkeypatch):
    path = tmp_path / "br.db"
    monkeypatch.setenv("VIBE_BR_DATA_DB", str(path))
    from src.config import accessor

    if hasattr(accessor, "reset_env_config"):
        accessor.reset_env_config()
    monkeypatch.setattr("src.br_data.store.db_path", lambda: path)
    init_db(path)
    return path


def _cotahist_body() -> str:
    lines = [
        "00COTAHIST.2025BOVESPA 20250103" + " " * 214,
        _cotahist_line("20250102", "PETR4", 10, 3712),
        _cotahist_line("20250103", "PETR4", 10, 3750),
        _cotahist_line("20250103", "PETR4F", 20, 3751, bdi="96"),
        _cotahist_line("20250103", "XPTO3", 10, 150000, factor=1000),
        "99COTAHIST.2025BOVESPA 20250103" + " " * 214,
    ]
    return "\n".join(lines)


def test_cotahist_record_is_parsed_with_implied_decimals_and_factor() -> None:
    records = list(cotahist.parse_text(_cotahist_body()))
    assert len(records) == 4
    first = dict(zip(cotahist._COLUMNS, records[0]))
    assert first["trade_date"] == "2025-01-02"
    assert first["ticker"] == "PETR4"
    assert first["market_type"] == 10
    assert first["close"] == pytest.approx(37.12)
    assert first["high"] == pytest.approx(37.32)
    assert first["volume"] == 1000
    assert first["turnover"] == pytest.approx(37120.0)
    assert first["expiry"] is None
    assert first["isin"] == "BRPETRACNPR6"
    per_thousand = dict(zip(cotahist._COLUMNS, records[3]))
    assert per_thousand["close"] == pytest.approx(1.5)


def test_cotahist_sync_downloads_years_then_daily_files(store, monkeypatch) -> None:
    calls: list[str] = []
    yearly = _zip("COTAHIST_A2025.TXT", _cotahist_body())
    daily = _zip("COTAHIST_D06012025.TXT", _cotahist_line("20250106", "PETR4", 10, 3800))

    def fake_fetch(url: str, host_key: str):
        calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("COTAHIST_A2025.ZIP"):
            return yearly
        if url.endswith("COTAHIST_D06012025.ZIP"):
            return daily
        return None

    monkeypatch.setattr(cotahist, "fetch_bytes", fake_fetch)
    with connect(store, write=True) as conn:
        rows = cotahist.sync(conn, 2024, date(2025, 1, 7))
    assert rows == 5
    assert calls[:2] == ["COTAHIST_A2024.ZIP", "COTAHIST_A2025.ZIP"]
    assert "COTAHIST_D06012025.ZIP" in calls and "COTAHIST_D07012025.ZIP" in calls

    from backtest.loaders.b3_cotahist_loader import DataLoader, map_symbol

    assert map_symbol("PETR4F.SA") == ("PETR4F", 20)
    loader = DataLoader()
    assert loader.is_available()
    frames = loader.fetch(["PETR4.SA", "PETR4F.SA", "NONE3.SA"], "2025-01-01", "2025-01-31")
    assert set(frames) == {"PETR4.SA", "PETR4F.SA"}
    petr = frames["PETR4.SA"]
    assert_loader_contract(petr, context="b3_cotahist PETR4.SA")
    assert list(petr["close"]) == pytest.approx([37.12, 37.50, 38.00])
    assert petr.attrs["quote_currency"] == "BRL"


def test_cvm_fund_daily_accepts_both_layouts(store) -> None:
    new_layout = (
        "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;ID_SUBCLASSE;DT_COMPTC;VL_TOTAL;VL_QUOTA;"
        "VL_PATRIM_LIQ;CAPTC_DIA;RESG_DIA;NR_COTST\n"
        "CLASSES - FIF;00.017.024/0001-53;;2025-01-02;100.5;1.2345;1000000.10;0;10.5;42\n"
        "CLASSES - FIF;00.017.024/0001-53;;2025-01-03;100.5;1.2400;1000100.10;5;0;43\n"
    )
    old_layout = (
        "TP_FUNDO;CNPJ_FUNDO;DT_COMPTC;VL_TOTAL;VL_QUOTA;VL_PATRIM_LIQ;CAPTC_DIA;RESG_DIA;NR_COTST\n"
        "FI;11.111.111/0001-11;2020-06-30;1;2,5;3;0;0;7\n"
    )
    with connect(store, write=True) as conn:
        assert cvm_funds.ingest_daily_zip(conn, _zip("inf_diario_fi_202501.csv", new_layout)) == 2
        assert cvm_funds.ingest_daily_zip(conn, _zip("inf_diario_fi_2020.csv", old_layout)) == 1
        register = (
            "TP_FUNDO;CNPJ_FUNDO;DENOM_SOCIAL;SIT;CLASSE;GESTOR;ADMIN;RENTAB_FUNDO;DT_INI_ATIV\n"
            "FI;00.017.024/0001-53;FUNDO TESTE RENDA FIXA;EM FUNCIONAMENTO NORMAL;Renda Fixa;"
            "GESTORA X;ADMIN Y;CDI;2001-01-01\n"
        )
        conn.executemany(cvm_funds._UPSERT_FUND, list(cvm_funds.parse_register(register)))
    with connect(store) as conn:
        row = conn.execute("SELECT * FROM cvm_fund_daily WHERE cnpj='00017024000153' ORDER BY trade_date").fetchall()
        assert [r["quota"] for r in row] == [1.2345, 1.24]
        assert row[1]["holders"] == 43
        old = conn.execute("SELECT quota FROM cvm_fund_daily WHERE cnpj='11111111000111'").fetchone()
        assert old["quota"] == 2.5


def test_cvm_fund_monthly_sync_marks_only_settled_months(store, monkeypatch) -> None:
    body = "CNPJ_FUNDO_CLASSE;DT_COMPTC;VL_QUOTA\n00.000.000/0001-91;2025-01-02;1\n"
    seen: list[str] = []

    def fake_fetch(url: str, host_key: str):
        seen.append(url.rsplit("/", 1)[-1])
        return _zip("x.csv", body) if "inf_diario_fi_2025" in url else None

    monkeypatch.setattr(cvm_funds, "fetch_bytes", fake_fetch)
    with connect(store, write=True) as conn:
        cvm_funds.sync_daily(conn, 2025, date(2025, 3, 10))
        done = {r[0] for r in conn.execute("SELECT item FROM sync_log WHERE source='cvm_fund_daily'")}
    assert done == {"202501"}
    assert seen == ["inf_diario_fi_202501.zip", "inf_diario_fi_202502.zip", "inf_diario_fi_202503.zip"]


def test_cvm_statements_keep_latest_version_and_scale(store) -> None:
    header = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;"
              "DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA\n")
    body = header + (
        "33.000.167/0001-01;2024-12-31;1;PETROBRAS;9512;DF Consolidado;REAL;MIL;ÚLTIMO;2024-01-01;2024-12-31;3.01;Receita;490000000;S\n"
        "33.000.167/0001-01;2024-12-31;1;PETROBRAS;9512;DF Consolidado;REAL;MIL;PENÚLTIMO;2023-01-01;2023-12-31;3.01;Receita;510000000;S\n"
        "33.000.167/0001-01;2024-12-31;2;PETROBRAS;9512;DF Consolidado;REAL;MIL;ÚLTIMO;2024-01-01;2024-12-31;3.01;Receita;491000000;S\n"
    )
    with connect(store, write=True) as conn:
        rows = cvm_companies.ingest_statements_zip(
            conn, _zip("dfp_cia_aberta_DRE_con_2024.csv", body, "latin-1"), "DFP")
        assert rows == 2
        conn.executemany("INSERT OR REPLACE INTO cvm_company_tickers VALUES (?, ?)",
                         list(cvm_companies.parse_tickers(
                             "CNPJ_Companhia;Codigo_Negociacao\n33.000.167/0001-01;PETR4\n")))
    with connect(store) as conn:
        stored = conn.execute("SELECT statement, value, version FROM cvm_statements").fetchall()
    assert [(r["statement"], r["value"], r["version"]) for r in stored] == [("DRE", 491000000000.0, 2)]


def test_tesouro_and_number_helpers() -> None:
    body = ("Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
            "PU Compra Manha;PU Venda Manha;PU Base Manha\n"
            "Tesouro IPCA+;15/05/2035;02/01/2025;7,12;7,24;2.345,67;2.300,01;2.299,99\n")
    rows = list(tesouro.parse(body))
    assert rows == [("Tesouro IPCA+", "2035-05-15", "2025-01-02", 7.12, 7.24, 2345.67, 2300.01, 2299.99)]
    assert to_float("1.234,5") == 1234.5 and to_float("12.5") == 12.5 and to_float("") is None
    assert br_date("31/12/2024") == "2024-12-31" and br_date("2024-12-31") == "2024-12-31"


def test_agent_tool_reads_the_store(store, monkeypatch) -> None:
    monkeypatch.setattr(cotahist, "fetch_bytes",
                        lambda url, host_key: _zip("a.txt", _cotahist_body()) if "A2025" in url else None)
    with connect(store, write=True) as conn:
        cotahist.sync(conn, 2025, date(2025, 1, 3))
        conn.execute("INSERT INTO bcb_series VALUES (12, '2025-01-02', 0.045)")
        conn.execute("INSERT INTO cvm_companies VALUES ('33000167000101','9512','PETROLEO BRASILEIRO','PETROBRAS','ATIVO','Petróleo')")
        conn.execute("INSERT INTO cvm_company_tickers VALUES ('PETR4','33000167000101')")

    from src.tools.br_market_data_tool import BrMarketDataTool

    tool = BrMarketDataTool()
    quotes = json.loads(tool.execute(action="quotes", tickers=["PETR4.SA"], start_date="2025-01-01", end_date="2025-01-31"))
    assert quotes["ok"] and [r["close"] for r in quotes["data"]["rows"]] == pytest.approx([37.12, 37.50])
    macro = json.loads(tool.execute(action="macro", series="cdi", start_date="2025-01-01", end_date="2025-01-31"))
    assert macro["data"]["rows"] == [{"date": "2025-01-02", "value": 0.045}]
    found = json.loads(tool.execute(action="search", query="petrobras"))
    assert found["data"]["companies"][0]["tickers"] == "PETR4"
    assert "PETR4" in {r["ticker"] for r in found["data"]["tickers"]}
    assert not json.loads(tool.execute(action="fund", cnpj="123"))["ok"]
    assert not json.loads(tool.execute(action="nope"))["ok"]
    status = json.loads(tool.execute(action="status"))
    assert status["data"]["rows"][0]["rows"] == 4


def test_financial_statements_read_cvm_store_then_fall_back_to_yahoo(store, monkeypatch) -> None:
    from src.tools import financial_statements_tool as fst

    with connect(store, write=True) as conn:
        conn.execute("INSERT INTO cvm_company_tickers VALUES ('PETR4', '33000167000101')")
        conn.executemany(
            "INSERT INTO cvm_statements VALUES (?, 'DFP', 'DRE', ?, ?, ?, ?, ?, 1)",
            [
                ("33000167000101", "2024-12-31", "2024-01-01", "3.01", "Receita", 491e9),
                ("33000167000101", "2023-12-31", "2023-01-01", "3.01", "Receita", 511e9),
            ],
        )
    calls: list[str] = []
    monkeypatch.setattr(fst, "_fetch_yahoo_statement",
                        lambda code, **kw: calls.append(code) or {"periods": [{"endDate": "2024"}]})

    income = json.loads(fst.FinancialStatementsTool().execute(code="PETR4.SA", statement="income"))
    assert income["ok"] and income["source"] == "cvm" and income["market"] == "br"
    periods = income["data"]["PETR4.SA"]["periods"]
    assert [p["period_end"] for p in periods] == ["2024-12-31", "2023-12-31"]
    assert periods[0]["3.01 Receita"] == 491e9
    assert calls == []

    # Not synced for this company / no indicator block in CVM -> Yahoo.
    other = json.loads(fst.FinancialStatementsTool().execute(code="VALE3.SA", statement="income"))
    indicators = json.loads(fst.FinancialStatementsTool().execute(code="PETR4.SA"))
    assert other["source"] == "yahoo" and indicators["source"] == "yahoo"
    assert calls == ["VALE3.SA", "PETR4.SA"]


def test_stock_news_routes_b3_symbols_to_yahoo_with_full_symbol(monkeypatch) -> None:
    from src.tools import stock_news_tool as snt

    queries: list[str] = []
    monkeypatch.setattr(snt, "_fetch_yahoo_news", lambda query, limit: queries.append(query) or [])
    out = json.loads(snt.StockNewsTool().execute(code="petr4.sa", scope="stock"))
    assert out["ok"] and out["market"] == "br" and out["source"] == "yahoo"
    assert queries == ["PETR4.SA"]

@pytest.mark.parametrize('currency', ['CR$', 'US$', ''])
def test_cotahist_does_not_relabel_other_currencies_as_brl(currency):
    line = _cotahist_line('20250103', 'TEST3', 10, 1000)
    line = line[:52] + currency.ljust(4) + line[56:]
    assert cotahist.parse_record(line) is None


def test_cotahist_rejects_missing_prices_and_quotation_factor():
    line = _cotahist_line('20250103', 'TEST3', 10, 1000)
    assert cotahist.parse_record(line[:108] + ' ' * 13 + line[121:]) is None
    assert cotahist.parse_record(line[:210] + '0000000' + line[217:]) is None


def test_bad_numeric_and_calendar_cells_are_not_fabricated():
    assert to_float('NaN') is None
    assert to_float('Infinity') is None
    assert br_date('2025-02-31') is None


def test_fund_subclasses_do_not_form_one_return_series(store):
    from src.tools.br_market_data_tool import BrMarketDataTool
    with connect(store, write=True) as conn:
        conn.executemany(
            'INSERT INTO cvm_fund_daily (cnpj, trade_date, subclass, quota) VALUES (?, ?, ?, ?)',
            [('00000000000001', '2025-01-02', 'A', 1),
             ('00000000000001', '2025-01-03', 'B', 100)],
        )
    result = json.loads(BrMarketDataTool().execute(action='fund', cnpj='00000000000001',
                                                start_date='2025-01-01', end_date='2025-01-04'))
    assert result['ok']
    assert len(result['data']['rows']) == 2
    assert 'quota_return' not in result['data']


def test_br_tool_rejects_bad_dates_and_preserves_result_limit():
    from src.tools.br_market_data_tool import _dates, _envelope, TOOL_RESULT_LIMIT
    with pytest.raises(ValueError):
        _dates({'start_date': '2025-03-01', 'end_date': '2025-02-01'})
    result = _envelope('search', [], {'companies': [{'name': 'x' * (TOOL_RESULT_LIMIT * 2)}]})
    assert len(result) <= TOOL_RESULT_LIMIT
    assert json.loads(result)['ok'] is False


def test_br_quotes_keep_per_symbol_brl_evidence(store, tmp_path):
    from evals.grounding import GroundingLedger
    from src.tools.br_market_data_tool import BrMarketDataTool
    with connect(store, write=True) as conn:
        cotahist.ingest_zip(conn, _zip('quotes.txt', '\n'.join([
            _cotahist_line('20250103', 'TEST3', 10, 1000),
            _cotahist_line('20250103', 'MOCK4', 10, 2000),
        ])))
    args = {'action': 'quotes', 'tickers': ['TEST3', 'MOCK4'],
            'start_date': '2025-01-03', 'end_date': '2025-01-03'}
    payload = BrMarketDataTool().execute(**args)
    ledger = GroundingLedger(run_dir=tmp_path, user_message='Compare TEST3.SA and MOCK4.SA prices')
    ledger.ingest_tool_result(tool_name='get_br_market_data', arguments=args,
                             result=payload, call_id='b3', success=True)
    closes = [r for r in ledger._evidence if r.field == 'close']
    assert {(r.symbol, r.value, r.currency, r.timestamp, r.tool) for r in closes} == {
        ('TEST3.SA', 10., 'BRL', '2025-01-03', 'get_br_market_data'),
        ('MOCK4.SA', 20., 'BRL', '2025-01-03', 'get_br_market_data'),
    }
    assert ledger.validate_final_answer('Source: b3_cotahist. TEST3.SA closed at BRL 10.00. MOCK4.SA closed at BRL 20.00.').valid
    assert not ledger.validate_final_answer('Source: b3_cotahist. TEST3.SA closed at BRL 20.00.').valid
    malformed = json.loads(payload)
    malformed['data']['currency'] = 'USD'
    refused = GroundingLedger(run_dir=tmp_path/'refused', user_message='TEST3.SA price')
    refused.ingest_tool_result(tool_name='get_br_market_data', arguments=args,
                              result=json.dumps(malformed), call_id='bad', success=True)
    assert not refused._evidence


def test_brl_alias_is_unambiguous():
    from evals.grounding import GroundingLedger
    assert GroundingLedger._currency_is_surfaced("BRL", "R$ 10.00")
    assert GroundingLedger._currency_is_surfaced("BRL", "10 reais")
    assert not GroundingLedger._currency_is_surfaced("BRL", "These are real observed prices")


# ---------------------------------------------------------------------------
# scheduler-unification T9: the daily sync as protected internal system job.
# Append-only section — the existing tests above are untouched. Imports are
# function-level, matching this file's style (module-level imports here would
# trip ruff E402). The root conftest's autouse _reset_env_config fixture
# snapshots os.environ and resets the config cache around every test.
# ---------------------------------------------------------------------------

BR_JOB_ID = "system:br-data-sync"


def _set_env(monkeypatch, **vars):
    """setenv + config-cache reset (T8's test_memory_consolidation_job pattern)."""
    for key, value in vars.items():
        monkeypatch.setenv(key, value)
    from src.config.accessor import reset_env_config

    reset_env_config()


def _br_store(tmp_path):
    from src.scheduled_research.store import ScheduledResearchJobStore

    return ScheduledResearchJobStore(path=tmp_path / "jobs.json")


def _production_br_spec():
    from src.scheduling.system_jobs import system_job_specs

    matches = [s for s in system_job_specs() if s.id == BR_JOB_ID]
    assert len(matches) == 1, f"expected exactly one {BR_JOB_ID} spec, got {matches}"
    return matches[0]


def test_next_run_parses_hhmm_into_cron_fields():
    """The repurposed parser: "HH:MM" -> (minute, hour), strict on garbage."""
    from src.br_data.sync import _next_run

    assert _next_run("21:30") == (30, 21)
    assert _next_run("07:05") == (5, 7)
    assert _next_run("00:00") == (0, 0)
    assert _next_run("23:59") == (59, 23)
    for bad in ("25:99", "", "abc", "24:00", "12:60", "21:30:00", "21"):
        with pytest.raises(ValueError):
            _next_run(bad)


def test_daily_cron_from_env_derives_cron_from_sync_time(monkeypatch):
    from src.br_data.scheduling import daily_cron_from_env

    _set_env(monkeypatch, VIBE_BR_SYNC_TIME="21:30")
    assert daily_cron_from_env() == "30 21 * * *"
    _set_env(monkeypatch, VIBE_BR_SYNC_TIME="07:05")
    assert daily_cron_from_env() == "5 7 * * *"
    _set_env(monkeypatch, VIBE_BR_SYNC_TIME="00:00")
    assert daily_cron_from_env() == "0 0 * * *"


def test_daily_cron_from_env_invalid_values_fall_back_without_raising(monkeypatch, caplog):
    """Plan T9 pinned choice: invalid -> default cron + warning, never raise."""
    import logging

    from src.br_data.scheduling import DEFAULT_DAILY_CRON, daily_cron_from_env

    assert DEFAULT_DAILY_CRON == "30 21 * * *"
    for bad in ("25:99", "", "abc", "24:00", "12:60"):
        _set_env(monkeypatch, VIBE_BR_SYNC_TIME=bad)
        with caplog.at_level(logging.WARNING, logger="src.br_data.scheduling"):
            assert daily_cron_from_env() == "30 21 * * *"
        assert "VIBE_BR_SYNC_TIME" in caplog.text
        caplog.clear()


def test_sync_flag_defaults_false_and_gates_seeding(monkeypatch, tmp_path):
    """QA (a) direction: flag off (default) -> no row, store file never created."""
    from src.br_data.scheduling import sync_job_enabled
    from src.config.accessor import get_env_config
    from src.scheduling.system_jobs import ensure_system_jobs

    monkeypatch.delenv("VIBE_BR_SYNC_ENABLED", raising=False)
    monkeypatch.delenv("VT_MEMORY_CONSOLIDATION", raising=False)
    from src.config.accessor import reset_env_config

    reset_env_config()
    assert get_env_config().data.vibe_br_sync_enabled is False
    assert sync_job_enabled() is False

    store = _br_store(tmp_path)
    report = ensure_system_jobs(store, now_fn=lambda: 1000)
    assert BR_JOB_ID in report.skipped_disabled
    assert BR_JOB_ID not in report.seeded
    assert store.get(BR_JOB_ID) is None
    assert not store.path.exists()


def test_flag_on_seeds_br_sync_row_with_spec_fields(monkeypatch, tmp_path):
    from src.br_data.scheduling import sync_job_enabled
    from src.scheduled_research.models import JobStatus
    from src.scheduling.registry import is_registered, resolve_internal
    from src.scheduling.system_jobs import ensure_system_jobs
    from src.scheduling.triggers import next_due

    monkeypatch.delenv("VT_MEMORY_CONSOLIDATION", raising=False)
    _set_env(monkeypatch, VIBE_BR_SYNC_ENABLED="1")
    assert sync_job_enabled() is True

    spec = _production_br_spec()
    assert spec.source_type == "system"
    assert spec.executor_kind == "internal"
    assert spec.internal_callable == "br_data.run_sync"
    assert spec.timezone == "America/Sao_Paulo"  # the sync.TZ key, reused
    assert spec.prompt == ""
    assert spec.enabled_predicate is sync_job_enabled
    assert is_registered("br_data.run_sync") is True
    # The registered entry is a literal wrapper with a deferred domain import:
    # calling it must delegate to the real sync entry point.
    calls = []
    monkeypatch.setattr(
        "src.br_data.sync.run_sync", lambda *a, **k: calls.append("fired") or {}
    )
    resolve_internal("br_data.run_sync")()
    assert calls == ["fired"]

    store = _br_store(tmp_path)
    report = ensure_system_jobs(store, now_fn=lambda: 1000)
    assert report.seeded == (BR_JOB_ID,)
    job = store.get(BR_JOB_ID)
    assert job is not None
    assert job.source_type == "system"
    assert job.executor_kind == "internal"
    assert job.internal_callable == "br_data.run_sync"
    assert job.schedule == spec.resolved_schedule()
    assert job.timezone == "America/Sao_Paulo"
    assert job.status == JobStatus.PENDING
    # cron + tz seeds the NEXT São Paulo slot, not "now"
    assert job.next_run_at == next_due(spec.resolved_schedule(), 1000, spec.timezone)
    assert job.next_run_at > 1000


def _run_due_internal_job(tmp_path, monkeypatch, fake_run_sync):
    """Seed with the flag on, make the row due, tick once, drain, return store."""
    import asyncio

    from src.scheduled_research.executor import ScheduledResearchExecutor
    from src.scheduling import registry
    from src.scheduling.registry import resolve_internal
    from src.scheduling.system_jobs import ensure_system_jobs

    monkeypatch.delenv("VT_MEMORY_CONSOLIDATION", raising=False)
    _set_env(monkeypatch, VIBE_BR_SYNC_ENABLED="1")
    store = _br_store(tmp_path)
    report = ensure_system_jobs(store, now_fn=lambda: 1000)
    assert report.seeded == (BR_JOB_ID,)
    jobs = store.load()
    jobs[BR_JOB_ID].next_run_at = 1200  # make it due for the tick below
    store.save(jobs)

    # Fake the callable behind the PRODUCTION registry key (auto-restored);
    # resolution still goes through the real allowlist dict.
    monkeypatch.setitem(registry._INTERNAL_CALLABLES, "br_data.run_sync", fake_run_sync)

    prompt_calls = []

    async def dispatch(job):
        prompt_calls.append(job.id)

    async def scenario():
        executor = ScheduledResearchExecutor(
            store, dispatch, internal_dispatcher=lambda j: resolve_internal(j.internal_callable),
            now_fn=lambda: 1500,
        )
        await executor.tick(1500)
        tasks = list(executor._internal._tasks)
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=30)

    asyncio.run(scenario())
    assert prompt_calls == []  # internal jobs never prompt-dispatch
    return store


def test_due_internal_job_calls_run_sync_exactly_once(tmp_path, monkeypatch):
    """QA happy: due tick -> supervisor -> to_thread -> run_sync once, COMPLETED."""
    from src.scheduled_research.models import JobStatus
    from src.scheduling.triggers import next_due

    calls = []

    def fake_run_sync():
        calls.append("fired")
        return {"db": "fake"}

    store = _run_due_internal_job(tmp_path, monkeypatch, fake_run_sync)

    assert calls == ["fired"]  # EXACTLY once
    saved = store.get(BR_JOB_ID)
    assert saved is not None
    assert saved.status == JobStatus.COMPLETED
    assert saved.failure_kind is None
    assert saved.last_run_at == 1500  # completion time (internal path)
    spec = _production_br_spec()
    assert saved.next_run_at == next_due(spec.resolved_schedule(), 1500, spec.timezone)


def test_run_sync_exception_lands_in_dispatch_failure_path(tmp_path, monkeypatch):
    """QA failure (b): a raising callable -> failure_kind='dispatch', bounded
    backoff retry (PENDING, consecutive_failures=1) — the kernel never stalls."""
    from src.scheduled_research.models import JobStatus

    def exploding_run_sync():
        raise RuntimeError("boom")

    store = _run_due_internal_job(tmp_path, monkeypatch, exploding_run_sync)

    saved = store.get(BR_JOB_ID)
    assert saved is not None
    assert saved.status == JobStatus.PENDING  # retry scheduled, not terminal
    assert saved.failure_kind == "dispatch"
    assert saved.consecutive_failures == 1
    assert "boom" in (saved.last_error or "")
    assert saved.next_run_at > 1500


def test_daemon_prints_migration_notice_and_returns_zero(capsys):
    """Retired daemon: bounded return, exit code 0 (compose restart: unless-stopped
    would crash-loop on non-zero), notice names the job and both env vars."""
    from src.br_data.__main__ import main
    from src.br_data.sync import run_daemon

    assert run_daemon() == 0
    assert run_daemon(["cotahist"]) == 0  # legacy arg accepted and ignored
    assert main(["daemon"]) == 0
    out = capsys.readouterr().out
    assert "system:br-data-sync" in out
    assert "VIBE_BR_SYNC_ENABLED" in out
    assert "VIBE_BR_SYNC_TIME" in out


def test_sync_module_has_no_unbounded_loop():
    """Acceptance grep pinned as a test: the daemon loop is gone for good."""
    from pathlib import Path

    from src.br_data import sync as sync_mod

    source = Path(sync_mod.__file__).read_text(encoding="utf-8")
    assert "while True" not in source
