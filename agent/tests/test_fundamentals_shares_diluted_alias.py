"""Regression tests for the ``shares_diluted`` basic-count fallback alias.

Zero-dilution filers (verified on XOM, CIK 0000034088: basic EPS == diluted
EPS in all 48 10-K/10-Q frames 2017-2024, no diluted-share concept tagged
after FY2013) present a single EPS share count and tag only
``WeightedAverageNumberOfSharesOutstandingBasic``. The alias is last in
``SEC_CONCEPT_MAP["shares_diluted"]`` so a diluted fact from the same filing
always wins the per-``period_end`` PIT dedupe; it only fills periods where no
diluted fact exists at all.

No test touches a live endpoint: ``cik_for`` / ``get_company_facts`` are
monkeypatched on the loader's SEC client module. The XOM-shaped payload comes
from ``tests/fixtures/sec/xom_like_companyfacts.json`` (real filed facts).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest.loaders import fundamentals_loader

_FIXTURE = (
    Path(__file__).parent / "fixtures" / "sec" / "xom_like_companyfacts.json"
)


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


def test_basic_count_fills_shares_diluted_when_no_diluted_concept_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xom_like = json.loads(_FIXTURE.read_text())

    shares = _load_shares(monkeypatch, xom_like, "2017-05-01", "2017-05-10")

    # PIT: nothing visible before the Q1 10-Q filing date, the real filed
    # basic count (4,223,000,000 shares, XOM 2017-03-31 frame) after it.
    assert pd.isna(shares.loc["2017-05-02"])
    assert shares.loc["2017-05-03"] == 4223000000
    assert shares.loc["2017-05-10"] == 4223000000


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


def test_earlier_filed_basic_count_is_pit_and_later_diluted_filing_does_not_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PIT keeps the first filed fact per period_end: a basic count filed in
    # the original 10-Q anchors the value, and a diluted count that only
    # appears in a later amendment never replaces it (pit=False research mode
    # would keep the latest filing instead — pinned in test_fundamentals_pit).
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

    assert shares.loc["2017-05-03"] == 990.0
    assert shares.loc["2017-08-02"] == 990.0
    assert shares.loc["2017-08-03"] == 990.0
    assert shares.loc["2017-08-10"] == 990.0


def test_no_share_concept_at_all_stays_nan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _facts({"Assets": [_share_row("2017-03-31", "2017-05-03", 1000.0)]})

    shares = _load_shares(monkeypatch, facts)

    assert shares.isna().all()
