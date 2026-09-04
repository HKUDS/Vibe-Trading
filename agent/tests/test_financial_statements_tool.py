"""Tests for financial_statements_tool: envelope shape, dispatch, isolation.

All HTTP is mocked at the functions the tool imports. A-share/HK route through
Eastmoney ``get_json`` / ``resolve_secid``; US routes through SEC EDGAR
``cik_for`` / ``get_company_facts``. No test touches a live endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.tools.financial_statements_tool import FinancialStatementsTool

# Eastmoney datacenter report success body: result.data is a list of rows.
_EM_PAYLOAD = {
    "result": {
        "data": [
            {"REPORT_DATE": "2024-12-31", "TOTAL_REVENUE": 383.0, "NETPROFIT": 96.0},
        ]
    }
}

# Eastmoney A-share report success body: two periods of flat rows.
_EM_A_PAYLOAD = {
    "result": {
        "data": [
            {"REPORT_DATE": "2024-12-31", "TOTAL_ASSETS": 100.0, "NETPROFIT": 12.0},
            {"REPORT_DATE": "2023-12-31", "TOTAL_ASSETS": 90.0, "NETPROFIT": 10.0},
        ]
    }
}

_SEC_FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "units": {
                    "USD": [
                        {
                            "end": "2023-09-30",
                            "val": 383285000000,
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "accn": "a1",
                        },
                        {
                            "end": "2024-09-28",
                            "val": 391035000000,
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "accn": "a2",
                        },
                    ]
                },
            },
            "NetIncomeLoss": {
                "label": "Net Income",
                "units": {
                    "USD": [
                        {
                            "end": "2024-06-29",
                            "val": 21448000000,
                            "fy": 2024,
                            "fp": "Q3",
                            "form": "10-Q",
                            "accn": "q3",
                        },
                        {
                            "end": "2024-09-28",
                            "val": 93736000000,
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "accn": "a2",
                        },
                    ]
                },
            },
            "Assets": {
                "label": "Assets",
                "units": {
                    "USD": [
                        {
                            "end": "2024-09-28",
                            "val": 364980000000,
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "accn": "a2",
                        },
                    ]
                },
            },
        }
    }
}


class TestSuccessEnvelope:
    """A resolvable symbol yields the ok envelope with parsed periods."""

    def test_a_share_uses_eastmoney_and_parses_periods(self):
        with patch(
            "src.tools.financial_statements_tool.resolve_secid",
            return_value="1.600519",
        ), patch(
            "src.tools.financial_statements_tool.get_json",
            return_value=_EM_A_PAYLOAD,
        ) as mock_get:
            text = FinancialStatementsTool().execute(
                code="600519.SH", statement="balance", period="annual"
            )

        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["market"] == "a_share"
        assert payload["source"] == "eastmoney"
        assert payload["statement"] == "balance"
        assert payload["period"] == "annual"
        assert "error" not in payload

        periods = payload["data"]["600519.SH"]["periods"]
        assert len(periods) == 2
        assert periods[0]["REPORT_DATE"] == "2024-12-31"

        # A-share balance sheet hits the A-share F10 report, filtered on the
        # dotted SECUCODE (not the bare SECURITY_CODE used for HK).
        sent_params = mock_get.call_args.kwargs["params"]
        assert sent_params["reportName"] == "RPT_F10_FINANCE_GBALANCE"
        assert 'SECUCODE="600519.SH"' in sent_params["filter"]
        assert "SECURITY_CODE" not in sent_params["filter"]

    def test_us_uses_sec_companyfacts(self):
        with patch(
            "src.tools.financial_statements_tool.resolve_secid",
        ) as mock_resolve, patch(
            "src.tools.financial_statements_tool.get_json",
        ) as mock_get, patch(
            "src.tools.financial_statements_tool.cik_for",
            return_value="0000320193",
        ) as mock_cik, patch(
            "src.tools.financial_statements_tool.get_company_facts",
            return_value=_SEC_FACTS,
        ) as mock_facts:
            text = FinancialStatementsTool().execute(
                code="AAPL.US", statement="income", period="annual"
            )

        mock_cik.assert_called_once_with("AAPL")
        mock_facts.assert_called_once_with("0000320193")
        mock_resolve.assert_not_called()
        mock_get.assert_not_called()

        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["market"] == "us"
        assert payload["source"] == "sec_edgar"

        periods = payload["data"]["AAPL.US"]["periods"]
        assert periods[0]["REPORT_DATE"] == "2024-09-28"
        assert periods[0]["FORM"] == "10-K"
        assert periods[0]["Revenues"] == 391035000000.0
        assert periods[0]["NetIncomeLoss"] == 93736000000.0
        assert periods[0]["_units"] == {
            "Revenues": "USD",
            "NetIncomeLoss": "USD",
        }

    def test_us_quarter_keeps_10q_points(self):
        with patch(
            "src.tools.financial_statements_tool.cik_for",
            return_value="0000320193",
        ), patch(
            "src.tools.financial_statements_tool.get_company_facts",
            return_value=_SEC_FACTS,
        ):
            text = FinancialStatementsTool().execute(
                code="AAPL.US", statement="income", period="quarter"
            )

        payload = json.loads(text)
        periods = payload["data"]["AAPL.US"]["periods"]
        dates = [row["REPORT_DATE"] for row in periods]
        assert "2024-06-29" in dates
        q3 = next(row for row in periods if row["REPORT_DATE"] == "2024-06-29")
        assert q3["FORM"] == "10-Q"
        assert q3["NetIncomeLoss"] == 21448000000.0

    def test_hk_indicators_use_hk_report_name(self):
        with patch(
            "src.tools.financial_statements_tool.resolve_secid",
            return_value="116.00700",
        ), patch(
            "src.tools.financial_statements_tool.get_json",
            return_value=_EM_PAYLOAD,
        ) as mock_get:
            FinancialStatementsTool().execute(
                code="00700.HK", statement="indicators", period="annual"
            )

        assert (
            mock_get.call_args.kwargs["params"]["reportName"]
            == "RPT_HKF10_FN_GMAININDICATOR"
        )


class TestAllFailedSurfacesError:
    """When the fetch fails for every requested code, the envelope is ok=false.

    The failure detail stays in the per-code result AND is mirrored to a
    top-level ``error`` so a nested fetch failure is never masked by a
    top-level ``ok: true``.
    """

    def test_http_failure_yields_top_level_ok_false(self):
        with patch(
            "src.tools.financial_statements_tool.resolve_secid",
            return_value="1.600519",
        ), patch(
            "src.tools.financial_statements_tool.get_json",
            side_effect=RuntimeError("HTTP 429"),
        ):
            text = FinancialStatementsTool().execute(
                code="600519.SH", statement="income"
            )

        payload = json.loads(text)
        assert payload["ok"] is False
        assert "429" in payload["error"]
        assert "429" in payload["data"]["600519.SH"]["error"]

    def test_unresolvable_us_symbol_yields_ok_false(self):
        with patch(
            "src.tools.financial_statements_tool.cik_for",
            return_value=None,
        ):
            text = FinancialStatementsTool().execute(code="ZZZZ.US")

        payload = json.loads(text)
        assert payload["ok"] is False
        assert payload["error"] == "ticker not found in SEC company table"
        assert payload["data"]["ZZZZ.US"]["error"] == "ticker not found in SEC company table"

    def test_empty_a_share_payload_yields_no_periods_but_ok_true(self):
        # An empty-but-well-formed payload is data (zero periods), not a fetch
        # failure, so the envelope stays ok=true.
        with patch(
            "src.tools.financial_statements_tool.resolve_secid",
            return_value="0.000001",
        ), patch(
            "src.tools.financial_statements_tool.get_json",
            return_value={"result": {}},
        ):
            text = FinancialStatementsTool().execute(code="000001.SZ")

        payload = json.loads(text)
        assert payload["ok"] is True
        assert "error" not in payload
        assert payload["data"]["000001.SZ"]["periods"] == []


class TestPeriodSelection:
    """Period is chosen client-side. Eastmoney's REPORT_TYPE is locale text
    (年报 / 一季报) or a market-specific string (2026/Q1), so no REPORT_TYPE
    filter is sent; 'annual' keeps fiscal-year-end rows, falling back to the
    full series when an issuer has no December year-end.
    """

    _MIXED = {
        "result": {
            "data": [
                {"REPORT_DATE": "2025-03-31 00:00:00", "TOTAL_ASSETS": 1},
                {"REPORT_DATE": "2024-12-31 00:00:00", "TOTAL_ASSETS": 2},
                {"REPORT_DATE": "2024-09-30 00:00:00", "TOTAL_ASSETS": 3},
                {"REPORT_DATE": "2023-12-31 00:00:00", "TOTAL_ASSETS": 4},
            ]
        }
    }
    _NO_YEAR_END = {
        "result": {
            "data": [
                {"REPORT_DATE": "2026-03-28 00:00:00", "TOTAL_ASSETS": 1},
                {"REPORT_DATE": "2025-09-28 00:00:00", "TOTAL_ASSETS": 2},
            ]
        }
    }

    def _run(self, payload, *, period, statement="balance",
             code="600519.SH", secid="1.600519"):
        with patch(
            "src.tools.financial_statements_tool.resolve_secid", return_value=secid,
        ), patch(
            "src.tools.financial_statements_tool.get_json", return_value=payload,
        ) as mock_get:
            text = FinancialStatementsTool().execute(
                code=code, statement=statement, period=period
            )
        return json.loads(text), mock_get

    def test_no_report_type_clause_in_filter(self):
        _, mock_get = self._run(self._MIXED, period="annual")
        assert "REPORT_TYPE" not in mock_get.call_args.kwargs["params"]["filter"]

    def test_annual_keeps_only_fiscal_year_end(self):
        payload, _ = self._run(self._MIXED, period="annual")
        dates = [p["REPORT_DATE"] for p in payload["data"]["600519.SH"]["periods"]]
        assert dates == ["2024-12-31 00:00:00", "2023-12-31 00:00:00"]

    def test_quarter_returns_full_series(self):
        payload, _ = self._run(self._MIXED, period="quarter")
        assert len(payload["data"]["600519.SH"]["periods"]) == 4

    def test_annual_falls_back_when_no_december_year_end(self):
        payload, _ = self._run(
            self._NO_YEAR_END, period="annual", code="00700.HK", secid="116.00700"
        )
        # No -12-31 row -> return the full series rather than drop all data.
        assert len(payload["data"]["00700.HK"]["periods"]) == 2

    def test_a_share_indicators_use_mainfinadata_report(self):
        _, mock_get = self._run(self._MIXED, period="annual", statement="indicators")
        assert (
            mock_get.call_args.kwargs["params"]["reportName"]
            == "RPT_F10_FINANCE_MAINFINADATA"
        )


class TestErrorEnvelope:
    """Input validation returns the ok=false envelope before any HTTP."""

    def test_missing_code_rejected(self):
        payload = json.loads(FinancialStatementsTool().execute())
        assert payload["ok"] is False
        assert "code" in payload["error"]

    def test_blank_code_rejected(self):
        payload = json.loads(FinancialStatementsTool().execute(code="   "))
        assert payload["ok"] is False

    def test_unknown_suffix_rejected(self):
        payload = json.loads(FinancialStatementsTool().execute(code="BTC-USDT"))
        assert payload["ok"] is False
        assert "suffix" in payload["error"]

    def test_invalid_statement_rejected(self):
        payload = json.loads(
            FinancialStatementsTool().execute(code="600519.SH", statement="equity")
        )
        assert payload["ok"] is False
        assert "statement" in payload["error"]

    def test_invalid_period_rejected(self):
        payload = json.loads(
            FinancialStatementsTool().execute(code="600519.SH", period="ttm")
        )
        assert payload["ok"] is False
        assert "period" in payload["error"]


class TestUKYahooStatements:
    """UK (.L) routes to Yahoo quoteSummary with flattened raw values."""

    _INCOME_PAYLOAD = {
        "incomeStatementHistory": {
            "maxAge": 1,
            "incomeStatementHistory": [
                {
                    "maxAge": 1,
                    "endDate": 1743379200,
                    "totalRevenue": {"raw": 37448000000, "fmt": "37.45B"},
                    "netIncome": {"raw": -4169000000, "fmt": "-4.17B"},
                    "currencyCode": "GBp",
                },
                {
                    "maxAge": 1,
                    "endDate": 1711843200,
                    "totalRevenue": {"raw": 32907000000, "fmt": "32.91B"},
                    "netIncome": {"raw": 1248000000, "fmt": "1.25B"},
                },
            ],
        }
    }

    def test_uk_income_annual_uses_annual_module(self) -> None:
        with patch(
            "src.tools.financial_statements_tool.yahoo_client.get_quote_summary",
            return_value=self._INCOME_PAYLOAD,
        ) as mock_qs:
            text = FinancialStatementsTool().execute(
                code="VOD.L", statement="income", period="annual"
            )

        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["source"] == "yahoo"
        assert payload["market"] == "uk"
        assert mock_qs.call_args.args == ("VOD.L", ["incomeStatementHistory"])
        periods = payload["data"]["VOD.L"]["periods"]
        assert periods[0]["endDate"] == 1743379200
        assert periods[0]["totalRevenue"] == 37448000000
        assert periods[0]["netIncome"] == -4169000000
        # Newest first.
        assert periods[0]["endDate"] > periods[1]["endDate"]

    def test_uk_income_quarter_uses_quarterly_module(self) -> None:
        quarterly = {
            "incomeStatementHistoryQuarterly": {
                "maxAge": 1,
                "incomeStatementHistory": [
                    {
                        "maxAge": 1,
                        "endDate": {"raw": 1743379200, "fmt": "2025-03-31"},
                        "totalRevenue": {"raw": 9361000000, "fmt": "9.36B"},
                    },
                ],
            }
        }
        with patch(
            "src.tools.financial_statements_tool.yahoo_client.get_quote_summary",
            return_value=quarterly,
        ) as mock_qs:
            payload = json.loads(
                FinancialStatementsTool().execute(
                    code="VOD.L", statement="income", period="quarter"
                )
            )

        assert payload["ok"] is True
        assert payload["period"] == "quarter"
        assert mock_qs.call_args.args == (
            "VOD.L",
            ["incomeStatementHistoryQuarterly"],
        )
        period_record = payload["data"]["VOD.L"]["periods"][0]
        # Quarterly endDate is a {raw, fmt} dict on Yahoo; flattened to int.
        assert period_record["endDate"] == 1743379200
        assert period_record["totalRevenue"] == 9361000000

    def test_uk_il_suffix_routes_to_yahoo(self) -> None:
        with patch(
            "src.tools.financial_statements_tool.yahoo_client.get_quote_summary",
            return_value=self._INCOME_PAYLOAD,
        ) as mock_qs:
            FinancialStatementsTool().execute(
                code="BARC.L", statement="income", period="annual"
            )
        assert mock_qs.call_args.args == ("BARC.L", ["incomeStatementHistory"])

    def test_uk_indicators_flatten_nested_blocks(self) -> None:
        payload = {
            "financialData": {
                "maxAge": 1,
                "totalRevenue": {"raw": 40461000704, "longFmt": "40,461,000,704"},
                "grossMargins": {"raw": 0.3147},
            },
            "defaultKeyStatistics": {
                "maxAge": 1,
                "returnOnEquity": {"raw": 0.00109},
                "trailingEps": {"raw": -0.17},
            },
        }
        with patch(
            "src.tools.financial_statements_tool.yahoo_client.get_quote_summary",
            return_value=payload,
        ) as mock_qs:
            text = FinancialStatementsTool().execute(
                code="VOD.L", statement="indicators", period="annual"
            )

        payload_out = json.loads(text)
        assert payload_out["ok"] is True
        assert mock_qs.call_args.args == (
            "VOD.L",
            ["financialData", "defaultKeyStatistics"],
        )
        record = payload_out["data"]["VOD.L"]["periods"][0]
        assert record["totalRevenue"] == 40461000704
        assert record["grossMargins"] == 0.3147
        assert record["returnOnEquity"] == 0.00109

    def test_uk_yahoo_failure_surfaces_ok_false(self) -> None:
        with patch(
            "src.tools.financial_statements_tool.yahoo_client.get_quote_summary",
            side_effect=RuntimeError("crumb expired"),
        ):
            text = FinancialStatementsTool().execute(
                code="VOD.L", statement="balance", period="annual"
            )
        payload = json.loads(text)
        assert payload["ok"] is False
        assert "crumb expired" in payload["error"]
        assert "crumb expired" in payload["data"]["VOD.L"]["error"]
