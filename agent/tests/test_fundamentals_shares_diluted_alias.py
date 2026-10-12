"""Basic shares cannot silently fill a missing diluted-share observation."""

from __future__ import annotations


import pandas as pd
import pytest

from backtest.loaders import fundamentals_loader

def _facts(concept_rows: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    return {
        "facts": {
            "us-gaap": {
                concept: {"units": {"shares": rows}}
                for concept, rows in concept_rows.items()
            }
        }
    }


def _share_row(end: str, filed: str, value: float, *, form: str = "10-Q") -> dict[str, object]:
    start = (pd.Timestamp(end) - pd.Timedelta(days=91)).strftime("%Y-%m-%d")
    return {"start": start, "end": end, "filed": filed, "val": value, "form": form}


def _patch_sec(
    monkeypatch: pytest.MonkeyPatch,
    facts_by_symbol: dict[str, dict[str, object]],
) -> None:
    def cik_for(symbol: str) -> str | None:
        return f"CIK-{symbol}" if symbol in facts_by_symbol else None

    def get_company_facts(cik: str) -> dict[str, object]:
        symbol = cik.removeprefix("CIK-")
        return facts_by_symbol[symbol]

    monkeypatch.setattr(fundamentals_loader.sec_edgar_client, "cik_for", cik_for)
    monkeypatch.setattr(
        fundamentals_loader.sec_edgar_client,
        "get_company_facts",
        get_company_facts,
    )


def _load_shares(
    monkeypatch: pytest.MonkeyPatch,
    facts: dict[str, object],
    start: str = "2017-05-01",
    end: str = "2017-05-10",
) -> pd.Series:
    _patch_sec(monkeypatch, {"AAA": facts})
    index = pd.date_range(start, end, freq="D")
    panel = fundamentals_loader.load_fundamental_panel(
        ["AAA"],
        ["shares_diluted"],
        start,
        end,
        freq="quarterly",
        index=index,
    )
    return panel["shares_diluted"]["AAA"]


def test_basic_count_does_not_fill_missing_diluted_shares(monkeypatch):
    facts = _facts({"WeightedAverageNumberOfSharesOutstandingBasic": [
        _share_row("2017-03-31", "2017-05-03", 1000.0)
    ]})
    # Even equal rounded EPS is not proof that share counts are identical.
    facts["facts"]["us-gaap"].update({
        name: {"units": {"USD/shares": [_share_row("2017-03-31", "2017-05-03", 1.0)]}}
        for name in ("EarningsPerShareBasic", "EarningsPerShareDiluted")
    })
    assert _load_shares(monkeypatch, facts).isna().all()


def test_diluted_concept_wins_over_basic_from_the_same_filing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _facts(
        {
            "WeightedAverageNumberOfDilutedSharesOutstanding": [
                _share_row("2017-03-31", "2017-05-03", 1000.0)
            ],
            "WeightedAverageNumberOfSharesOutstandingBasic": [
                _share_row("2017-03-31", "2017-05-03", 990.0)
            ],
        }
    )

    shares = _load_shares(monkeypatch, facts)

    assert shares.loc["2017-05-10"] == 1000.0


def test_diluted_shares_only_appear_on_their_own_filing_date(monkeypatch):
    facts = _facts(
        {
            "WeightedAverageNumberOfSharesOutstandingBasic": [
                _share_row("2017-03-31", "2017-05-03", 990.0)
            ],
            "WeightedAverageNumberOfDilutedSharesOutstanding": [
                _share_row("2017-03-31", "2017-08-03", 1000.0)
            ],
        }
    )

    shares = _load_shares(monkeypatch, facts, "2017-05-01", "2017-08-10")

    assert pd.isna(shares.loc["2017-05-03"])
    assert pd.isna(shares.loc["2017-08-02"])
    assert shares.loc["2017-08-03"] == 1000.0
    assert shares.loc["2017-08-10"] == 1000.0


def test_no_share_concept_at_all_stays_nan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _facts({"Assets": [_share_row("2017-03-31", "2017-05-03", 1000.0)]})

    shares = _load_shares(monkeypatch, facts)

    assert shares.isna().all()
