"""Tests for etf_holdings_tool: routing, parsing, as-of honesty, degradation.

Every fixture below is a trimmed copy of a real payload captured from the live
endpoint, and all HTTP is mocked at the module's two transport seams
(:func:`_sec_get_text` / :func:`_em_get_text`) plus the shared Eastmoney JSON
helper, so no test touches the network.

The regressions these tests exist for:

* N-PORT's ``repPdEnd`` is the fund's fiscal year end, not the report period.
  IVV's amendment carries ``repPdEnd`` 2026-03-31 with ``repPdDate``
  2025-09-30, so reading the wrong tag stamps September holdings with a March
  date — and picking the newest *filed* document returns that September
  portfolio when a March one exists.
* On the A-share side the whole portfolio is only ever disclosed by the interim
  and annual reports, and Eastmoney serves a June/December period from the
  quarterly data until that report is published — identically shaped, an order
  of magnitude less complete. ``_JJCC_2026`` is the live 2026-06-30 payload for
  510300: fifteen rows totalling 23.26% of net assets, on a period end whose
  calendar month says "interim report". Nothing may call that a full portfolio.
* The table merges a second disclosure: a starred ``序号`` is a position taken
  from the *issuer's* top-10 float holders, not from the fund's report.
* Eastmoney emits rows whose 相关资讯 cell is never closed. Requiring ``</td>``
  merges it with the next cell and shifts every later column left by one, which
  reported 510500's share count for 400174 中天3 (1,877.51) as a 1877.51%
  weight — one row inflating the fund's disclosed total to 1972.86%.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import src.tools.etf_holdings_tool as etf
from src.tools.etf_holdings_tool import EtfHoldingsTool

# ── Fixtures shaped exactly like the live payloads ───────────────────────────

_SERIES_CSV = (
    "﻿Reporting File Number,CIK Number,Entity Name,Entity Org Type,Series ID,"
    "Series Name,Class ID,Class Name,Class Ticker,Address_1,Address_2,City,State,Zip Code\n"
    "811-09729,0001100663,iSHARES TRUST,30,S000004310,iShares Core S&P 500 ETF,"
    "C000012040,iShares Core S&P 500 ETF,IVV,400 HOWARD STREET,,SAN FRANCISCO,CA,94105\n"
    "811-09729,0001100663,iSHARES TRUST,30,S000004354,iShares Semiconductor ETF,"
    "C000012084,iShares Semiconductor ETF,SOXX,400 HOWARD STREET,,SAN FRANCISCO,CA,94105\n"
    "811-00001,0000000001,NO TICKER TRUST,30,S000000001,Unlisted Series,C000000001,"
    "Class A,,1 MAIN ST,,NEW YORK,NY,10001\n"
)

_ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <company-info><cik>0001100663</cik><conformed-name>iSHARES TRUST</conformed-name></company-info>
  <entry>
    <content type="text/xml">
      <accession-number>0002071691-26-015790</accession-number>
      <filing-date>2026-07-13</filing-date>
      <filing-type>NPORT-P/A</filing-type>
    </content>
  </entry>
  <entry>
    <content type="text/xml">
      <accession-number>0002071691-26-012459</accession-number>
      <filing-date>2026-05-28</filing-date>
      <filing-type>NPORT-P</filing-type>
    </content>
  </entry>
</feed>
"""

# The amendment was filed later but covers an earlier period.
_FTS = json.dumps(
    {
        "hits": {
            "total": {"value": 2, "relation": "eq"},
            "hits": [
                {
                    "_id": "0002071691-26-015790:primary_doc.xml",
                    "_source": {"period_ending": "2025-09-30", "file_date": "2026-07-13"},
                },
                {
                    "_id": "0002071691-26-012459:primary_doc.xml",
                    "_source": {"period_ending": "2026-03-31", "file_date": "2026-05-28"},
                },
            ],
        }
    }
)


def _nport(series_id: str, rep_pd_date: str, rep_pd_end: str) -> str:
    """Build an N-PORT document with two holdings, real tag names and namespace."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <headerData><submissionType>NPORT-P</submissionType></headerData>
  <formData>
    <genInfo>
      <regName>iShares Trust</regName>
      <seriesName>iShares Core S&amp;P 500 ETF</seriesName>
      <seriesId>{series_id}</seriesId>
      <repPdEnd>{rep_pd_end}</repPdEnd>
      <repPdDate>{rep_pd_date}</repPdDate>
    </genInfo>
    <fundInfo>
      <totAssets>721570012380.01</totAssets>
      <netAssets>720543356320.99</netAssets>
    </fundInfo>
    <invstOrSecs>
      <invstOrSec>
        <name>NVIDIA Corp.</name>
        <title>NVIDIA Corp.</title>
        <cusip>67066G104</cusip>
        <identifiers><isin value="US67066G1040"/><other otherDesc="x" value="y"/></identifiers>
        <balance>312526688.00000000</balance>
        <units>NS</units>
        <curCd>USD</curCd>
        <valUSD>54504654387.20000000</valUSD>
        <pctVal>7.564382338558</pctVal>
        <payoffProfile>Long</payoffProfile>
        <assetCat>EC</assetCat>
        <invCountry>US</invCountry>
      </invstOrSec>
      <invstOrSec>
        <name>CBRE Group, Inc.</name>
        <cusip>12504L109</cusip>
        <identifiers><isin value="US12504L1098"/></identifiers>
        <valUSD>506139381.54000000</valUSD>
        <pctVal>0.070244125783</pctVal>
        <assetCat>EC</assetCat>
      </invstOrSec>
    </invstOrSecs>
  </formData>
</edgarSubmission>
"""


_FUND_NAME = "沪深300ETF华泰柏瑞"


def _cn_row(
    seq: str,
    code: str,
    market: str,
    name: str,
    pct: str,
    shares: str,
    value: str,
    *,
    close_info_cell: bool = True,
) -> str:
    """One holdings row in Eastmoney's live seven-column markup.

    Args:
        seq: The 序号 cell; a trailing ``*`` marks an issuer cross-referenced row.
        code: Six-digit stock code.
        market: Eastmoney market prefix — ``"1"`` Shanghai, ``"0"`` Shenzhen.
        name: Stock name.
        pct: 占净值比例 cell text, e.g. ``"7.29%"``.
        shares: 持股数 cell text in 万股.
        value: 持仓市值 cell text in 万元.
        close_info_cell: When ``False``, omit the 相关资讯 cell's ``</td>``, the
            way the live payload does for 510500's 400174 line.
    """
    link = f"//quote.eastmoney.com/unify/r/{market}.{code}"
    info = "<td class='xglj'><a href='#'>股吧</a><a href='#'>行情</a>"
    if close_info_cell:
        info += "</td>"
    return (
        f"<tr><td>{seq}</td><td><a href='{link}'>{code}</a></td>"
        f"<td class='tol'><a href='{link}'>{name}</a></td>{info}"
        f"<td class='tor'>{pct}</td><td class='tor'>{shares}</td>"
        f"<td class='tor'>{value}</td></tr>"
    )


def _cn_block(label: str, as_of: str, rows: list[str], *, expandable: bool) -> str:
    """One report period's ``boxitem`` fragment.

    Args:
        label: The 季度 label, e.g. ``"2025年4季度股票投资明细"``.
        as_of: Period end as ``YYYY-MM-DD``.
        rows: Rendered ``<tr>`` rows.
        expandable: Whether the "显示全部持仓明细" control is still present,
            which is how the live payload says it is withholding rows.
    """
    control = "显示全部持仓明细>>" if expandable else "收起持仓明细>>"
    return (
        "<div class='box'><div class='boxitem w790'><h4 class='t'><label class='left'>"
        f"<a title='{_FUND_NAME}' href='#'>{_FUND_NAME}</a>&nbsp;&nbsp;{label}</label>"
        "<label class='right lab2 xq505'>&nbsp;&nbsp;来源：天天基金&nbsp;&nbsp;截止至："
        f"<font class='px12'>{as_of}</font></label></h4><div class='space0'></div>"
        "<table class='w782 comm tzxq t2'><thead><tr><th class='first'>序号</th>"
        "<th>股票代码</th><th>股票名称</th><th class='xglj'>相关资讯</th>"
        "<th>占净值<br />比例</th><th class='cgs'>持股数<br />（万股）</th>"
        "<th class='last ccs'>持仓市值<br />（万元）</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table><div class='hide' id='gpdmList'>1.600519,</div>"
        f"<div class='tfoot'><a onclick='LoadMore(this,6,LoadStockPos)'>{control}</a>"
        "</div></div></div></div>"
    )


def _jjcc(*blocks: str, curyear: int = 2026) -> str:
    """Wrap period blocks in the ``var apidata={...}`` envelope the endpoint returns."""
    footnote = (
        "<div style='padding:5px 10px'>注：加*号代表进入上市公司的十大流通股东"
        "却没有进入单只基金前十大重仓股的个股。</div>"
    )
    return (
        'var apidata={ content:"'
        + "".join(blocks)
        + footnote
        + f'",arryear:[2026,2025],curyear:{curyear}}};'
    )


# 2026-06-30 as the live endpoint serves it on 2026-08-04: the interim report is
# not due until 08-31, so the period end says "interim" while the rows are the
# quarterly top-10 index plus top-5 active — 15 rows, 23.26% of net assets.
_Q2_2026_ROWS = [
    _cn_row(str(i + 1), f"60000{i}", "1", f"大盘股{i}", "2.00%", "100.00", "12,000.00")
    for i in range(10)
] + [
    _cn_row(str(i + 11), f"68800{i}", "1", f"新股{i}", "0.652%", "1.00", "80.00")
    for i in range(5)
]

_JJCC_2026 = _jjcc(
    _cn_block("2026年2季度股票投资明细", "2026-06-30", _Q2_2026_ROWS, expandable=False),
    _cn_block(
        "2026年1季度股票投资明细",
        "2026-03-31",
        [
            _cn_row("1", "600519", "1", "贵州茅台", "7.29%", "121.09", "143,549.56"),
            _cn_row("2", "300750", "0", "宁德时代", "4.99%", "2,059.75", "98,332.49"),
        ],
        expandable=True,
    ),
)

# 2025-12-31 once the annual report is out: twenty fund-reported rows, past the
# fifteen a quarterly report may carry, summing to 97.96% of net assets.
_ANNUAL_2025_ROWS = [
    _cn_row("1", "600519", "1", "贵州茅台", "7.29%", "121.09", "143,549.56"),
    _cn_row("2", "300750", "0", "宁德时代", "4.99%", "2,059.75", "98,332.49"),
] + [
    _cn_row(str(i + 3), f"60100{i}", "1", f"成分股{i}", "4.76%", "500.00", "60,000.00")
    for i in range(18)
]

_JJCC_2025 = _jjcc(
    _cn_block("2025年4季度股票投资明细", "2025-12-31", _ANNUAL_2025_ROWS, expandable=False),
    _cn_block(
        "2025年3季度股票投资明细",
        "2025-09-30",
        [_cn_row("1", "600519", "1", "贵州茅台", "8.10%", "100.00", "120,000.00")],
        expandable=True,
    ),
    curyear=2025,
)

_PREFIX = "华泰柏瑞沪深300交易型开放式指数证券投资基金"

# type=3 is the periodic-report shelf. The 摘要 editions are companions to the
# full report and carry no portfolio schedule, so they must not be read as one.
_JJGG = json.dumps(
    {
        "Data": [
            {"TITLE": f"{_PREFIX}2026年第2季度报告", "PUBLISHDATEDesc": "2026-07-21"},
            {"TITLE": f"{_PREFIX}2025年年度报告", "PUBLISHDATEDesc": "2026-03-31"},
            {"TITLE": f"{_PREFIX}2025年年度报告摘要", "PUBLISHDATEDesc": "2026-03-31"},
            {"TITLE": f"{_PREFIX}2025年中期报告", "PUBLISHDATEDesc": "2025-08-30"},
        ],
        "ErrCode": 0,
        "TotalCount": 4,
    },
    ensure_ascii=False,
)


def _em_router(url, *, params, referer):
    """Serve the Eastmoney fixtures by URL and requested year, as the live host does."""
    if url == etf._EM_ANNOUNCEMENT_URL:
        return _JJGG
    return _JJCC_2025 if str(params.get("year")) == "2025" else _JJCC_2026

_QUOTE = {
    "data": {
        "f43": 2.983,
        "f57": "510050",
        "f58": "上证50ETF华夏",
        "f86": 1785831111,
        "f116": 22902480112.128004,
        "f117": 22902480112.128004,
    }
}


def _list_page(page: int) -> dict:
    """Two-row pages of the Eastmoney ETF universe, total 3."""
    rows = [
        [{"f12": "518880", "f13": 1, "f14": "黄金ETF华安", "f20": 9.2e10, "f297": 20260804},
         {"f12": "159915", "f13": 0, "f14": "创业板ETF易方达", "f20": 7.1e10, "f297": 20260804}],
        [{"f12": "588170", "f13": 1, "f14": "科创半导体ETF华夏", "f20": 3.9e10, "f297": 20260804}],
    ]
    return {"data": {"total": 3, "diff": rows[page - 1] if page <= len(rows) else []}}


@pytest.fixture(autouse=True)
def _clear_caches():
    """Reset the process-wide memoized indexes between tests."""
    etf._US_INDEX_CACHE = None
    etf._CN_LIST_CACHE = None
    yield
    etf._US_INDEX_CACHE = None
    etf._CN_LIST_CACHE = None


def _sec_router(url, params=None):
    """Serve the SEC fixtures by URL, mirroring the live endpoint layout."""
    if "series-class" in url:
        return _SERIES_CSV
    if "browse-edgar" in url:
        return _ATOM
    if "search-index" in url:
        return _FTS
    if "015790" in url:
        return _nport("S000004310", "2025-09-30", "2026-03-31")
    return _nport("S000004310", "2026-03-31", "2026-03-31")


class TestMarketRouting:
    """Symbols and queries reach the intended market path."""

    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("510050.SH", "CN"),
            ("159915.sz", "CN"),
            ("510050", "CN"),
            ("IVV", "US"),
            ("SOXX", "US"),
            ("BRK.B", "US"),
        ],
    )
    def test_symbol_classification(self, symbol, expected):
        assert etf._classify_market(symbol) == expected

    def test_han_query_routes_to_a_share(self):
        # The SEC index holds no Chinese fund names, so a Han query must not be
        # answered with a confident "no matches" from the US path.
        assert etf._classify_query_market("黄金") == "CN"
        assert etf._classify_query_market("semiconductor") == "US"

    def test_bare_six_digit_code_resolves_to_an_exchange(self):
        assert etf._cn_code_and_secid("510050") == ("510050", "1.510050")
        assert etf._cn_code_and_secid("159915") == ("159915", "0.159915")
        assert etf._cn_code_and_secid("123456")[1] is None

    def test_explicit_market_overrides_detection(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="lookup", query="510050", market="US"))
        assert payload["market"] == "US"


class TestUsHoldings:
    """N-PORT parsing, period selection and the as-of contract."""

    def test_report_period_comes_from_rep_pd_date_not_rep_pd_end(self):
        parsed = etf._parse_nport(_nport("S000004310", "2025-09-30", "2026-03-31"))
        assert parsed["as_of"] == "2025-09-30"
        assert parsed["fiscal_year_end"] == "2026-03-31"

    def test_newest_period_wins_over_newest_filing_date(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="IVV", top_n=5))
        assert payload["ok"] is True
        # The amendment was filed 2026-07-13 but covers 2025-09-30; the answer
        # must be the 2026-03-31 original.
        assert payload["as_of"] == "2026-03-31"
        assert payload["data"]["filing"]["accession"] == "0002071691-26-012459"
        assert payload["data"]["filing"]["period_source"] == "edgar_full_text_index"

    def test_falls_back_to_filing_order_when_periods_unknown(self):
        chosen = etf._select_nport_filing(
            [
                {"form": "NPORT-P/A", "accession": "A", "filing_date": "2026-07-13"},
                {"form": "NPORT-P", "accession": "B", "filing_date": "2026-05-28"},
            ],
            {},
        )
        assert chosen["accession"] == "A"
        assert chosen["period_source"] == "filing_order"

    def test_a_filing_the_index_cannot_date_is_counted_not_silently_skipped(self):
        # EDGAR's full-text index lags the filing feed, so the newest NPORT-P
        # can be listed with no period yet. Ranking by period drops it, which
        # would answer with last quarter's portfolio and look authoritative.
        thin_fts = json.dumps(
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "0002071691-26-012459:primary_doc.xml",
                            "_source": {"period_ending": "2026-03-31"},
                        }
                    ]
                }
            }
        )

        def router(url, params=None):
            return thin_fts if "search-index" in url else _sec_router(url, params)

        with patch.object(etf, "_sec_get_text", side_effect=router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="IVV"))
        assert payload["data"]["filing"]["candidates_without_period"] == 1
        assert "WARNING" in payload["notes"]

    def test_a_fully_indexed_filing_list_carries_no_warning(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="IVV"))
        assert payload["data"]["filing"]["candidates_without_period"] == 0
        assert "WARNING" not in payload["notes"]

    def test_envelope_carries_lag_coverage_and_full_portfolio_count(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="ivv", top_n=1))
        assert payload["coverage"] == "full_portfolio"
        assert payload["data"]["filing"]["disclosure_lag_days"] == 58
        assert payload["data"]["holdings_in_filing"] == 2
        assert payload["data"]["fund"]["net_assets_usd"] == 720543356320.99

    def test_holdings_are_ranked_by_weight_and_omit_absent_fields(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="IVV"))
        holdings = payload["data"]["holdings"]
        assert [h["name"] for h in holdings] == ["NVIDIA Corp.", "CBRE Group, Inc."]
        assert holdings[0]["pct_of_net_assets"] == 7.564382338558
        assert holdings[0]["isin"] == "US67066G1040"
        # The second holding reports no balance/units; those keys are absent
        # rather than defaulted to zero.
        assert "balance" not in holdings[1]
        assert "ticker" not in holdings[0]

    def test_series_mismatch_refuses_to_attribute_the_filing(self):
        def router(url, params=None):
            if "primary_doc" in url:
                return _nport("S000099999", "2026-03-31", "2026-03-31")
            return _sec_router(url, params)

        with patch.object(etf, "_sec_get_text", side_effect=router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="IVV"))
        assert payload["ok"] is False
        assert "S000099999" in payload["error"]

    def test_unlisted_ticker_names_the_uit_gap(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="SPY"))
        assert payload["ok"] is False
        assert "SPY" in payload["error"]

    def test_document_url_drops_cik_padding_and_accession_dashes(self):
        assert etf._nport_document_url("0001100663", "0002071691-26-012459") == (
            "https://www.sec.gov/Archives/edgar/data/1100663/"
            "000207169126012459/primary_doc.xml"
        )

    def test_large_portfolio_is_paged_not_truncated(self):
        many = "".join(
            f"<invstOrSec><name>Holding {i}</name><cusip>{i:09d}</cusip>"
            f"<valUSD>1000.0</valUSD><pctVal>{100 - i * 0.1}</pctVal>"
            f"<assetCat>EC</assetCat><invCountry>US</invCountry>"
            f"<payoffProfile>Long</payoffProfile><curCd>USD</curCd>"
            f"<units>NS</units><balance>10.0</balance></invstOrSec>"
            for i in range(150)
        )
        doc = _nport("S000004310", "2026-03-31", "2026-03-31").replace(
            "</invstOrSecs>", many + "</invstOrSecs>"
        )

        def router(url, params=None):
            return doc if "primary_doc" in url else _sec_router(url, params)

        with patch.object(etf, "_sec_get_text", side_effect=router):
            text = EtfHoldingsTool().execute(mode="holdings", symbol="IVV", top_n=200)
        payload = json.loads(text)
        assert len(text) <= 10_000
        assert payload["paging"]["complete"] is False
        assert payload["paging"]["next_offset"] == payload["paging"]["returned"]
        assert payload["data"]["holdings_in_filing"] == 152


class TestUsLookup:
    """Ticker/name search over the SEC series-class index."""

    def test_exact_ticker_ranks_first_and_name_search_works(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="lookup", query="semiconductor"))
        assert payload["market"] == "US"
        assert payload["data"]["matches"][0]["ticker"] == "SOXX"
        assert payload["data"]["matches"][0]["series_id"] == "S000004354"

    def test_missing_fields_are_declared_never_estimated(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="lookup", query="IVV"))
        assert "expense_ratio" in payload["missing_fields"]
        assert "expense_ratio" not in payload["data"]["matches"][0]
        assert payload["as_of"] == {"index_year": etf.date.today().year}

    def test_rows_without_a_ticker_are_dropped(self):
        records = etf._parse_series_index(_SERIES_CSV)
        assert {r["ticker"] for r in records} == {"IVV", "SOXX"}

    def test_etf_share_classes_outrank_mutual_fund_classes_on_a_theme_query(self):
        # Live check: "semiconductor" matches 31 classes, and in filer order the
        # first eight are Fidelity mutual fund classes, so an unranked default
        # page of ten never reaches SOXX/SMH/XSD.
        csv_body = (
            _SERIES_CSV
            + "811-03010,0000315700,FIDELITY ADVISOR SERIES VII,30,S000005327,"
            "Fidelity Advisor Semiconductors Fund,C000014549,Class A,FELAX,"
            "245 SUMMER STREET,,BOSTON,MA,02210\n"
            # VOO's ETF-ness is only visible in the class name.
            "811-02652,0000036405,VANGUARD INDEX FUNDS,30,S000002839,"
            "Vanguard 500 Semiconductor Index Fund,C000092055,ETF Shares,VOO,"
            "PO BOX 2600,V26,VALLEY FORGE,PA,19482\n"
        )

        def router(url, params=None):
            return csv_body if "series-class" in url else _sec_router(url, params)

        with patch.object(etf, "_sec_get_text", side_effect=router):
            payload = json.loads(
                EtfHoldingsTool().execute(mode="lookup", query="semiconductor", limit=3)
            )
        assert [m["ticker"] for m in payload["data"]["matches"]] == ["SOXX", "VOO", "FELAX"]

    def test_a_row_with_more_fields_than_the_header_does_not_kill_the_index(self):
        # csv.DictReader files the overflow under a None key as a *list*; the
        # whole US path used to die on ``.strip()`` if the SEC ever emitted one.
        records = etf._parse_series_index(
            _SERIES_CSV + "811-1,0000000002,STRAY TRUST,30,S000000002,Stray ETF,"
            "C000000002,Class A,STRY,1 MAIN ST,,NEW YORK,NY,10001,extra,extra2\n"
        )
        assert {r["ticker"] for r in records} == {"IVV", "SOXX", "STRY"}

    def test_index_falls_back_to_the_previous_year(self):
        seen: list[str] = []

        def router(url, params=None):
            seen.append(url)
            if f"{etf.date.today().year}.csv" in url:
                raise RuntimeError("404 not posted yet")
            return _SERIES_CSV

        with patch.object(etf, "_sec_get_text", side_effect=router):
            year, records = etf._us_series_index()
        assert year == etf.date.today().year - 1
        assert len(records) == 2
        assert len(seen) == 2


class TestCnHoldings:
    """Eastmoney fund-archive parsing and its disclosed-coverage honesty."""

    def test_latest_period_is_parsed_with_its_own_as_of(self):
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="510300.SH"))
        assert payload["ok"] is True
        assert payload["market"] == "CN"
        assert payload["as_of"] == "2026-06-30"
        assert payload["data"]["report_label"] == "2026年2季度股票投资明细"
        assert payload["data"]["fund"]["name"] == _FUND_NAME

    def test_units_are_rescaled_from_ten_thousands_and_exchange_inferred(self):
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(
                EtfHoldingsTool().execute(mode="holdings", symbol="510300", year=2025)
            )
        first, second = payload["data"]["holdings"][:2]
        assert first == {
            "symbol": "600519.SH",
            "disclosure_source": "fund_report",
            "name": "贵州茅台",
            "pct_of_net_assets": 7.29,
            "shares": 1210900.0,
            "market_value_cny": 1435495600.0,
        }
        # Market prefix 0 in the quote link means Shenzhen.
        assert second["symbol"] == "300750.SZ"

    def test_a_june_period_served_from_quarterly_data_is_not_called_full(self):
        # The regression: 2026-06-30 is an interim period end, but on 2026-08-04
        # the interim report is not due yet and Eastmoney answers it with the
        # quarterly rows. Reading the calendar month alone would publish 15 rows
        # covering 23.26% of net assets as the fund's complete portfolio.
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="510300.SH"))
        assert payload["as_of"] == "2026-06-30"
        assert payload["coverage"] == "top_n_disclosed"
        assert payload["data"]["holdings_in_period"] == 15
        assert payload["data"]["pct_of_net_assets_disclosed"] == 23.26
        assert "full_portfolio" in payload["missing_fields"]

    def test_a_partial_answer_names_the_full_portfolio_it_is_not(self):
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="510300.SH"))
        assert payload["data"]["full_portfolio_available"] == {
            "as_of": "2025-12-31",
            "report": f"{_PREFIX}2025年年度报告",
            "published": "2026-03-31",
        }
        assert "disclosure='full'" in payload["notes"]

    def test_full_walks_back_a_year_and_returns_the_complete_portfolio(self):
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(
                EtfHoldingsTool().execute(
                    mode="holdings", symbol="510300.SH", disclosure="full", top_n=100
                )
            )
        assert payload["as_of"] == "2025-12-31"
        assert payload["coverage"] == "full_portfolio"
        assert payload["data"]["holdings_in_period"] == 20
        assert payload["data"]["pct_of_net_assets_disclosed"] == 97.96
        assert payload["data"]["full_portfolio_available"] is None
        assert "full_portfolio" not in payload["missing_fields"]

    def test_the_lookback_asks_for_each_year_at_most_once(self):
        # A year contributes both its interim and its annual report, and one
        # request serves the whole year, so an undeduplicated candidate list
        # burns the fetch budget asking for 2025 twice.
        years: list[str] = []

        def router(url, *, params, referer):
            if url == etf._EM_ANNOUNCEMENT_URL:
                return _JJGG
            years.append(str(params.get("year")))
            return _JJCC_2025 if str(params.get("year")) == "2025" else _JJCC_2026

        with patch.object(etf, "_em_get_text", side_effect=router):
            payload = json.loads(
                EtfHoldingsTool().execute(
                    mode="holdings", symbol="510300.SH", disclosure="full"
                )
            )
        # The index lists 2025-12-31 and 2025-06-30; both name the same year.
        assert years == ["", "2025"]
        assert payload["as_of"] == "2025-12-31"

    def test_full_reports_the_filing_and_its_real_publication_lag(self):
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(
                EtfHoldingsTool().execute(
                    mode="holdings", symbol="510300.SH", disclosure="full"
                )
            )
        # 2025-12-31 -> published 2026-03-31 is 90 days, taken from the
        # announcement index rather than assumed from the filing deadline.
        assert payload["data"]["disclosure"] == {
            "requested": "full",
            "report": f"{_PREFIX}2025年年度报告",
            "report_published": "2026-03-31",
            "report_confirmed": True,
            "disclosure_lag_days": 90,
        }

    def test_a_period_still_offering_more_rows_is_never_full(self):
        # The 2025-09-30 block keeps its "显示全部持仓明细" control, so rows are
        # being withheld and no claim of completeness can be made about it.
        period = etf._parse_cn_period(_JJCC_2025.split("<div class='boxitem")[2])
        assert period["expandable"] is True
        etf._annotate_cn_period(period, {"2025-09-30": {"report": "x", "published": "y"}})
        assert period["coverage"] == "top_n_disclosed"

    def test_announcement_index_contradicting_the_period_blocks_the_full_claim(self):
        # Twenty expanded rows on a December period, but the index is readable
        # and holds no annual report for it — only the interim one. That is a
        # contradiction rather than an unknown, so fail closed.
        no_annual = json.dumps(
            {
                "Data": [
                    {"TITLE": f"{_PREFIX}2025年中期报告", "PUBLISHDATEDesc": "2025-08-30"},
                    {"TITLE": f"{_PREFIX}2025年第4季度报告", "PUBLISHDATEDesc": "2026-01-22"},
                ],
                "ErrCode": 0,
            },
            ensure_ascii=False,
        )

        def router(url, *, params, referer):
            return no_annual if url == etf._EM_ANNOUNCEMENT_URL else _JJCC_2025

        with patch.object(etf, "_em_get_text", side_effect=router):
            payload = json.loads(
                EtfHoldingsTool().execute(mode="holdings", symbol="510300.SH", year=2025)
            )
        assert payload["as_of"] == "2025-12-31"
        assert payload["coverage"] == "top_n_disclosed"
        assert payload["data"]["disclosure"]["report_confirmed"] is False

    def test_an_unreachable_announcement_index_says_so_instead_of_going_quiet(self):
        def router(url, *, params, referer):
            if url == etf._EM_ANNOUNCEMENT_URL:
                raise RuntimeError("edge dropped the connection")
            return _JJCC_2025

        with patch.object(etf, "_em_get_text", side_effect=router):
            payload = json.loads(
                EtfHoldingsTool().execute(mode="holdings", symbol="510300.SH", year=2025)
            )
        # The structural evidence still stands on its own, but the filing behind
        # it is unconfirmed and the answer has to admit that.
        assert payload["coverage"] == "full_portfolio"
        assert payload["data"]["disclosure"]["report_confirmed"] is None
        assert payload["data"]["disclosure"]["disclosure_lag_days"] is None
        assert "could not be confirmed" in payload["notes"]

    def test_announcement_index_rejects_the_request_without_crashing(self):
        # No Referer -> 200 with ErrCode -999 and Data as an empty *string*,
        # which a naive list walk would blow up on.
        refused = json.dumps({"Data": "", "ErrCode": -999, "ErrMsg": "", "TotalCount": 0})

        def router(url, *, params, referer):
            return refused if url == etf._EM_ANNOUNCEMENT_URL else _JJCC_2025

        with patch.object(etf, "_em_get_text", side_effect=router):
            assert etf._cn_periodic_reports("510300") == {}

    def test_report_abstracts_are_not_read_as_the_full_report(self):
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            reports = etf._cn_periodic_reports("510300")
        assert reports == {
            "2025-12-31": {"report": f"{_PREFIX}2025年年度报告", "published": "2026-03-31"},
            "2025-06-30": {"report": f"{_PREFIX}2025年中期报告", "published": "2025-08-30"},
        }

    def test_issuer_cross_referenced_rows_are_labelled_and_kept_out_of_the_total(self):
        # Eastmoney's own footnote: a starred 序号 is a position disclosed by the
        # ISSUER's top-10 float holders, not by the fund's report. Counting it in
        # the disclosed percentage would overstate what the filing covers.
        rows = [
            _cn_row("1", "600519", "1", "贵州茅台", "7.29%", "121.09", "143,549.56"),
            _cn_row("11*", "600036", "1", "招商银行", "1.50%", "500.00", "20,000.00"),
        ]
        period = etf._parse_cn_period(
            _cn_block("2026年1季度股票投资明细", "2026-03-31", rows, expandable=False).split(
                "<div class='boxitem"
            )[1]
        )
        assert [h["disclosure_source"] for h in period["holdings"]] == [
            "fund_report",
            "issuer_top10_float_holders",
        ]
        assert period["fund_report_holdings"] == 1
        assert period["cross_referenced_holdings"] == 1
        assert period["pct_of_net_assets_disclosed"] == 7.29
        assert period["pct_of_net_assets_cross_referenced"] == 1.5

    def test_cross_reference_mode_expands_every_quarter(self):
        seen: list[str] = []

        def router(url, *, params, referer):
            if url == etf._EM_ANNOUNCEMENT_URL:
                return _JJGG
            seen.append(params["month"])
            return _JJCC_2026

        with patch.object(etf, "_em_get_text", side_effect=router):
            EtfHoldingsTool().execute(
                mode="holdings", symbol="510300.SH", disclosure="cross_reference"
            )
        assert seen == ["3,6,9,12"]

    def test_default_modes_expand_only_the_full_disclosure_periods(self):
        seen: list[str] = []

        def router(url, *, params, referer):
            if url == etf._EM_ANNOUNCEMENT_URL:
                return _JJGG
            seen.append(params["month"])
            return _JJCC_2026

        with patch.object(etf, "_em_get_text", side_effect=router):
            EtfHoldingsTool().execute(mode="holdings", symbol="510300.SH")
        assert seen == ["6,12"]

    def test_an_unclosed_info_cell_does_not_shift_the_columns(self):
        # Live regression: 510500's 2025 annual report leaves the 相关资讯 cell
        # of 400174 中天3 unclosed. Merging it with the next cell read the share
        # count as the weight, turning 0.00% into 1877.51% and the fund's
        # disclosed total into 1972.86%.
        row = _cn_row(
            "501", "400174", "1", "中天3", "0.00%", "1,877.51", "262.85",
            close_info_cell=False,
        )
        period = etf._parse_cn_period(
            _cn_block("2025年4季度股票投资明细", "2025-12-31", [row], expandable=False).split(
                "<div class='boxitem"
            )[1]
        )
        assert period["unparseable_rows"] == 0
        assert period["holdings"][0]["pct_of_net_assets"] == 0.0
        assert period["holdings"][0]["shares"] == 18775100.0
        assert period["holdings"][0]["market_value_cny"] == 2628500.0

    def test_a_row_the_header_cannot_explain_is_dropped_and_counted(self):
        good = _cn_row("1", "600519", "1", "贵州茅台", "7.29%", "121.09", "143,549.56")
        # An extra trailing cell leaves the column map pointing at the wrong
        # values; reporting it would file one column's number under another's.
        wrong_width = good.replace("</tr>", "<td class='tor'>stray</td></tr>")
        period = etf._parse_cn_period(
            _cn_block(
                "2025年4季度股票投资明细", "2025-12-31", [good, wrong_width], expandable=False
            ).split("<div class='boxitem")[1]
        )
        assert len(period["holdings"]) == 1
        assert period["unparseable_rows"] == 1

    def test_dropped_rows_are_surfaced_in_the_answer_not_swallowed(self):
        broken = _JJCC_2025.replace(
            "<td class='tor'>60,000.00</td></tr>",
            "<td class='tor'>60,000.00</td><td>stray</td></tr>",
            1,
        )

        def router(url, *, params, referer):
            return _JJGG if url == etf._EM_ANNOUNCEMENT_URL else broken

        with patch.object(etf, "_em_get_text", side_effect=router):
            payload = json.loads(
                EtfHoldingsTool().execute(mode="holdings", symbol="510300.SH", year=2025)
            )
        assert payload["data"]["unparseable_rows"] == 1
        assert "WARNING" in payload["notes"]

    def test_every_period_carries_its_own_coverage_verdict(self):
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(
                EtfHoldingsTool().execute(
                    mode="holdings", symbol="510300.SH", disclosure="full"
                )
            )
        assert payload["data"]["available_periods"] == [
            {
                "as_of": "2025-12-31",
                "report_label": "2025年4季度股票投资明细",
                "coverage": "full_portfolio",
                "holdings_in_period": 20,
                "pct_of_net_assets_disclosed": 97.96,
            },
            {
                "as_of": "2025-09-30",
                "report_label": "2025年3季度股票投资明细",
                "coverage": "top_n_disclosed",
                "holdings_in_period": 1,
                "pct_of_net_assets_disclosed": 8.1,
            },
        ]

    def test_full_refuses_rather_than_passing_off_a_partial_book(self):
        def router(url, *, params, referer):
            return _JJGG if url == etf._EM_ANNOUNCEMENT_URL else _JJCC_2026

        with patch.object(etf, "_em_get_text", side_effect=router):
            payload = json.loads(
                EtfHoldingsTool().execute(
                    mode="holdings", symbol="510300.SH", disclosure="full", year=2026
                )
            )
        assert payload["ok"] is False
        assert "no fully-disclosed portfolio" in payload["error"]
        assert "2025-12-31" in payload["error"]

    def test_column_positions_are_read_from_the_header_not_assumed(self):
        # A six-column period: no 相关资讯 column, so fixed indices would slip.
        block = (
            "<div class='boxitem w790'><h4 class='t'><label class='left'>"
            f"<a title='{_FUND_NAME}' href='#'>{_FUND_NAME}</a>&nbsp;&nbsp;"
            "2026年1季度股票投资明细</label><label class='right'>截止至："
            "<font class='px12'>2026-03-31</font></label></h4>"
            "<table class='w782 comm tzxq'><thead><tr><th>序号</th><th>股票代码</th>"
            "<th>股票名称</th><th>占净值<br />比例</th><th>持股数<br />（万股）</th>"
            "<th>持仓市值<br />（万元）</th></tr></thead><tbody>"
            "<tr><td>1</td><td><a href='//quote.eastmoney.com/unify/r/1.600519'>600519</a>"
            "</td><td class='tol'>贵州茅台</td><td class='tor'>8.10%</td>"
            "<td class='tor'>100.00</td><td class='tor'>120,000.00</td></tr>"
            "</tbody></table></div>"
        )
        period = etf._parse_cn_period(block)
        assert period["as_of"] == "2026-03-31"
        assert period["holdings"][0]["pct_of_net_assets"] == 8.10
        assert period["holdings"][0]["market_value_cny"] == 1200000000.0

    def test_newest_period_wins_even_if_the_server_reorders_the_blocks(self):
        # The answer's as_of must come from the dates in the payload, not from
        # the position Eastmoney happened to put the block in.
        reordered = _jjcc(
            _cn_block(
                "2026年1季度股票投资明细",
                "2026-03-31",
                [_cn_row("1", "600519", "1", "贵州茅台", "8.10%", "100.00", "120,000.00")],
                expandable=True,
            ),
            _cn_block("2026年2季度股票投资明细", "2026-06-30", _Q2_2026_ROWS, expandable=False),
        )

        def router(url, *, params, referer):
            return _JJGG if url == etf._EM_ANNOUNCEMENT_URL else reordered

        with patch.object(etf, "_em_get_text", side_effect=router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="510300.SH"))
        assert payload["as_of"] == "2026-06-30"
        assert payload["data"]["holdings_in_period"] == 15

    def test_requested_year_is_never_echoed_as_the_period(self):
        # The endpoint silently ignores an unavailable year and answers with the
        # current one, so the payload's own date must win.
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(
                EtfHoldingsTool().execute(mode="holdings", symbol="510300.SH", year=2099)
            )
        assert payload["as_of"] == "2026-06-30"

    def test_referer_is_sent_because_the_endpoint_404s_without_one(self):
        seen: dict[str, str] = {}

        def router(url, *, params, referer):
            seen[url] = referer
            return _JJGG if url == etf._EM_ANNOUNCEMENT_URL else _JJCC_2026

        with patch.object(etf, "_em_get_text", side_effect=router):
            EtfHoldingsTool().execute(mode="holdings", symbol="510300.SH")
        assert seen[etf._EM_HOLDINGS_URL] == "https://fundf10.eastmoney.com/ccmx_510300.html"
        # The announcement API answers ErrCode -999 without one.
        assert seen[etf._EM_ANNOUNCEMENT_URL] == (
            "https://fundf10.eastmoney.com/jjgg_510300_3.html"
        )

    def test_empty_payload_is_an_error_not_an_empty_portfolio(self):
        def router(url, *, params, referer):
            if url == etf._EM_ANNOUNCEMENT_URL:
                return _JJGG
            return 'var apidata={ content:"",arryear:[]};'

        with patch.object(etf, "_em_get_text", side_effect=router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="518880.SH"))
        assert payload["ok"] is False
        assert "no stock-holding detail" in payload["error"]


class TestCnLookup:
    """A-share fund search by code and by keyword."""

    def test_code_lookup_uses_the_single_quote_endpoint(self):
        with patch.object(etf, "_em_push_json", return_value=_QUOTE) as mock_json:
            payload = json.loads(EtfHoldingsTool().execute(mode="lookup", query="510050"))
        assert mock_json.call_args[0][0] == etf._EM_QUOTE_PATH
        match = payload["data"]["matches"][0]
        assert match["name"] == "上证50ETF华夏"
        assert match["fund_size_cny"] == 22902480112.128004
        assert payload["as_of"].startswith("2026-08-04T")

    def test_keyword_lookup_scans_the_paged_universe(self):
        with patch.object(etf, "_em_push_json", side_effect=lambda p, q: _list_page(int(q["pn"]))):
            payload = json.loads(EtfHoldingsTool().execute(mode="lookup", query="黄金"))
        assert payload["universe_complete"] is True
        assert payload["data"]["matches"] == [
            {
                "symbol": "518880.SH",
                "code": "518880",
                "name": "黄金ETF华安",
                "total_market_cap_cny": 9.2e10,
                "quote_date": "2026-08-04",
            }
        ]

    def test_partial_universe_is_flagged_and_not_cached(self):
        calls = {"n": 0}

        def flaky(path, params):
            calls["n"] += 1
            if int(params["pn"]) == 1:
                return _list_page(1)
            raise RuntimeError("edge dropped the connection")

        with patch.object(etf, "_em_push_json", side_effect=flaky):
            payload = json.loads(EtfHoldingsTool().execute(mode="lookup", query="半导体"))
        assert payload["universe_complete"] is False
        assert "PARTIAL" in payload["notes"]
        assert etf._CN_LIST_CACHE is None

    def test_first_page_failure_surfaces_as_an_error(self):
        with patch.object(etf, "_em_push_json", side_effect=RuntimeError("boom")):
            payload = json.loads(EtfHoldingsTool().execute(mode="lookup", query="黄金"))
        assert payload["ok"] is False
        assert "ETF universe" in payload["error"]

    def test_quote_host_fallback_tries_the_next_edge(self):
        attempted: list[str] = []

        def flaky(url, params=None):
            attempted.append(url)
            if url.startswith(f"https://{etf._EM_QUOTE_HOSTS[0]}"):
                raise RuntimeError("remote end closed connection")
            return _QUOTE

        with patch.object(etf, "get_json", side_effect=flaky):
            result = etf._em_push_json(etf._EM_QUOTE_PATH, {"secid": "1.510050"})
        assert result == _QUOTE
        assert len(attempted) == 2


class TestArgumentValidation:
    """Bad input yields the error envelope rather than an exception."""

    @pytest.mark.parametrize(
        "kwargs,fragment",
        [
            ({}, "mode must be one of"),
            ({"mode": "nope"}, "mode must be one of"),
            ({"mode": "lookup"}, "'query' is required"),
            ({"mode": "lookup", "query": "   "}, "'query' is required"),
            ({"mode": "holdings"}, "'symbol' is required"),
            ({"mode": "holdings", "symbol": "IVV", "market": "MARS"}, "market must be one of"),
            ({"mode": "holdings", "symbol": "510050", "year": "2025"}, "year must be an integer"),
            (
                {"mode": "holdings", "symbol": "510050", "disclosure": "everything"},
                "disclosure must be one of",
            ),
            ({"mode": "lookup", "query": "IVV", "offset": "x"}, "offset must be an integer"),
        ],
    )
    def test_invalid_arguments(self, kwargs, fragment):
        payload = json.loads(EtfHoldingsTool().execute(**kwargs))
        assert payload["ok"] is False
        assert fragment in payload["error"]

    @pytest.mark.parametrize(
        "value,expected",
        [(None, 25), (0, 1), (-5, 1), (10_000, 6000), ("30", 30), ("junk", 25)],
    )
    def test_top_n_is_clamped(self, value, expected):
        assert etf._clamp(value, 25, etf._MAX_TOP_N) == expected

    def test_top_n_ceiling_clears_a_real_full_portfolio(self):
        # Measured on the live 2025 annual reports: 510500 → 541, 159845 → 1044,
        # and the CSI-2000 tracker 159531 → 2031 holdings. A ceiling at or below
        # any of those hands back a truncated book still labelled
        # ``full_portfolio``, so it has to clear the largest one with headroom.
        assert etf._MAX_TOP_N >= 2031

    def test_a_top_n_cut_full_portfolio_says_it_was_cut(self):
        # The regression: top_n slices the period's rows before paging, so
        # paging reports the slice as its total and a caller who pages to
        # ``complete`` sees nothing to suggest rows were withheld — a complete
        # portfolio silently served as a partial one. Measured live on 159531,
        # whose 2031-row annual report came back as 1000 rows still labelled
        # ``full_portfolio`` with paging.total 1000.
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(
                EtfHoldingsTool().execute(
                    mode="holdings", symbol="510300.SH", disclosure="full", top_n=5
                )
            )
        assert payload["coverage"] == "full_portfolio"
        assert payload["data"]["holdings_in_period"] == 20
        assert payload["data"]["holdings_withheld_by_top_n"] == 15
        assert payload["paging"]["total"] == 5
        # The caller is told the whole book is not in hand, both ways.
        assert "full_portfolio" in payload["missing_fields"]
        assert "cut 15 of this period's 20 disclosed rows" in payload["notes"]

    def test_an_untruncated_full_portfolio_reports_nothing_withheld(self):
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(
                EtfHoldingsTool().execute(
                    mode="holdings", symbol="510300.SH", disclosure="full", top_n=100
                )
            )
        assert payload["data"]["holdings_withheld_by_top_n"] == 0
        assert "full_portfolio" not in payload["missing_fields"]
        assert "top_n=" not in payload["notes"]

    @pytest.mark.parametrize("value", ["FULL", "Full", " full "])
    def test_disclosure_is_case_and_space_insensitive(self, value):
        with patch.object(etf, "_em_get_text", side_effect=_em_router):
            payload = json.loads(
                EtfHoldingsTool().execute(
                    mode="holdings", symbol="510300.SH", disclosure=value
                )
            )
        assert payload["ok"] is True
        assert payload["coverage"] == "full_portfolio"

    @pytest.mark.parametrize("value", ["us", "US", "Us"])
    def test_market_override_is_case_insensitive(self, value):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(
                EtfHoldingsTool().execute(mode="lookup", query="510050", market=value)
            )
        assert payload["market"] == "US"

    def test_tool_contract(self):
        tool = EtfHoldingsTool()
        assert tool.name == "etf_holdings"
        assert tool.is_readonly is True
        assert tool.check_available() is True
        assert tool.parameters["required"] == ["mode"]
        assert json.dumps(tool.to_openai_schema())
