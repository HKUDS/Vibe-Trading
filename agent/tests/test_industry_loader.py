"""PIT contract for ``backtest.loaders.industry_loader``.

Every test injects a fake tushare API — no network. The behaviours pinned here
are the ones a silent bug would ruin: ``in_date`` inclusive / ``out_date``
exclusive membership boundaries, later-``in_date``-wins on overlapping rows,
the 2000-row truncation guard's per-L1 refetch, placeholder-token rejection,
graceful degradation on provider failure, and the never-invent-a-label rule
(unmapped symbols stay NaN).
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from backtest.loaders.industry_loader import (
    load_industry_frame,
    load_industry_frame_with_coverage,
    validate_industry_params,
)

_INDEX = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
_SYMBOLS = ["600000.SH", "000001.SZ"]


def _row(
    ts_code: str,
    l1_name: str,
    in_date: str,
    out_date: str | None = None,
    *,
    l2_name: str = "L2-default",
    l3_name: str = "L3-default",
) -> dict[str, Any]:
    return {
        "l1_code": f"800-{l1_name}",
        "l1_name": l1_name,
        "l2_code": f"801-{l2_name}",
        "l2_name": l2_name,
        "l3_code": f"802-{l3_name}",
        "l3_name": l3_name,
        "ts_code": ts_code,
        "name": ts_code.split(".")[0],
        "in_date": in_date,
        "out_date": out_date,
        "is_new": "Y" if out_date is None else "N",
    }


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class _FakeApi:
    """Serves a fixed membership snapshot; records every call.

    Mirrors the real endpoint's ``is_new`` filtering (server default "Y"):
    rows carry is_new = "Y" when out_date is null, "N" otherwise.
    """

    def __init__(self, snapshot: pd.DataFrame | Exception) -> None:
        self.snapshot = snapshot
        self.calls: list[dict[str, Any]] = []

    def index_member_all(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(kwargs)
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return _filter_is_new(self.snapshot, kwargs)


def _filter_is_new(frame: pd.DataFrame, kwargs: dict[str, Any]) -> pd.DataFrame:
    is_new = kwargs.get("is_new")
    if is_new is not None and "is_new" in getattr(frame, "columns", []):
        return frame[frame["is_new"] == is_new]
    return frame


def _load(api: Any, symbols: list[str] | None = None, **kwargs: Any) -> pd.DataFrame:
    return load_industry_frame(
        symbols=symbols or _SYMBOLS,
        start="2024-01-01",
        end="2024-01-04",
        index=_INDEX,
        api=api,
        **kwargs,
    )


# ------------------------------------------------------------- PIT boundaries


def test_in_date_is_inclusive() -> None:
    api = _FakeApi(_frame([_row("600000.SH", "银行", "20240102")]))

    frame = _load(api)

    assert pd.isna(frame.loc["2024-01-01", "600000.SH"])
    assert frame.loc["2024-01-02", "600000.SH"] == "银行"
    assert frame.loc["2024-01-04", "600000.SH"] == "银行"  # null out_date = current


def test_out_date_is_exclusive() -> None:
    api = _FakeApi(_frame([_row("600000.SH", "银行", "20240101", "20240103")]))

    frame = _load(api)

    assert frame.loc["2024-01-01", "600000.SH"] == "银行"
    assert frame.loc["2024-01-02", "600000.SH"] == "银行"
    assert pd.isna(frame.loc["2024-01-03", "600000.SH"])
    assert pd.isna(frame.loc["2024-01-04", "600000.SH"])


def test_historical_membership_applies_only_inside_its_interval() -> None:
    """A closed row labels the past; the open row labels the present."""
    api = _FakeApi(
        _frame(
            [
                _row("600000.SH", "旧行业", "20230101", "20240103"),
                _row("600000.SH", "新行业", "20240103"),
            ]
        )
    )

    frame = _load(api)

    assert frame.loc["2024-01-01", "600000.SH"] == "旧行业"
    assert frame.loc["2024-01-02", "600000.SH"] == "旧行业"
    assert frame.loc["2024-01-03", "600000.SH"] == "新行业"
    assert frame.loc["2024-01-04", "600000.SH"] == "新行业"


def test_overlapping_rows_resolve_to_the_later_in_date() -> None:
    api = _FakeApi(
        _frame(
            [
                _row("600000.SH", "A", "20240101"),
                _row("600000.SH", "B", "20240103"),
            ]
        )
    )

    frame = _load(api)

    assert frame.loc["2024-01-02", "600000.SH"] == "A"
    assert frame.loc["2024-01-03", "600000.SH"] == "B"
    assert frame.loc["2024-01-04", "600000.SH"] == "B"


def test_row_order_does_not_change_the_winner() -> None:
    rows = [_row("600000.SH", "A", "20240101"), _row("600000.SH", "B", "20240103")]
    forward = _load(_FakeApi(_frame(rows)))
    reversed_ = _load(_FakeApi(_frame(list(reversed(rows)))))

    pd.testing.assert_frame_equal(forward, reversed_)


# ---------------------------------------------------------------- never invent


def test_unmapped_symbols_and_dates_stay_nan() -> None:
    api = _FakeApi(_frame([_row("600000.SH", "银行", "20240101")]))

    frame, coverage = load_industry_frame_with_coverage(
        symbols=_SYMBOLS, start="2024-01-01", end="2024-01-04", index=_INDEX, api=api
    )

    assert frame["000001.SZ"].isna().all()
    assert list(frame.columns) == _SYMBOLS
    assert list(frame.index) == list(_INDEX)
    assert coverage == pytest.approx(0.5)


def test_rows_with_a_blank_label_are_dropped_not_defaulted() -> None:
    api = _FakeApi(
        _frame(
            [
                _row("600000.SH", None, "20240101"),
                {"ts_code": "000001.SZ", "l1_name": "银行", "in_date": None, "out_date": None},
            ]
        )
    )

    frame, coverage = load_industry_frame_with_coverage(
        symbols=_SYMBOLS, start="2024-01-01", end="2024-01-04", index=_INDEX, api=api
    )

    assert frame.isna().all().all()
    assert coverage == 0.0


def test_level_selects_the_name_column() -> None:
    api = _FakeApi(
        _frame([_row("600000.SH", "L1x", "20240101", l2_name="L2x", l3_name="L3x")])
    )

    assert _load(api, level="L1").loc["2024-01-01", "600000.SH"] == "L1x"
    assert _load(api, level="L2").loc["2024-01-01", "600000.SH"] == "L2x"
    assert _load(api, level="L3").loc["2024-01-01", "600000.SH"] == "L3x"


# ------------------------------------------------------------ validation gate


@pytest.mark.parametrize("level", ["L0", "l1", "L4", ""])
def test_invalid_level_raises(level: str) -> None:
    with pytest.raises(ValueError, match="unsupported industry level"):
        validate_industry_params(level, "SW2021")


@pytest.mark.parametrize("src", ["", "   "])
def test_empty_src_raises(src: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        validate_industry_params("L1", src)


def test_invalid_level_raises_through_the_loader() -> None:
    with pytest.raises(ValueError, match="unsupported industry level"):
        _load(_FakeApi(_frame([])), level="L9")


# ------------------------------------------------------------ truncation guard


def test_exactly_2000_rows_triggers_the_per_l1_refetch() -> None:
    """A snapshot at the documented cap is treated as truncated and refetched."""
    truncated = _frame([_row(f"99999{i}.SZ", "填充", "20240101") for i in range(2000)])
    real_a = _frame([_row("600000.SH", "银行", "20240101")])
    real_b = _frame([_row("000001.SZ", "非银金融", "20240101")])

    class _TruncatingApi:
        def __init__(self) -> None:
            self.member_calls: list[dict[str, Any]] = []
            self.classify_calls: list[dict[str, Any]] = []

        def index_member_all(self, **kwargs: Any) -> pd.DataFrame:
            self.member_calls.append(kwargs)
            if "l1_code" not in kwargs:
                return _filter_is_new(truncated, kwargs)
            return _filter_is_new(
                {"801780.SI": real_a, "801790.SI": real_b}[kwargs["l1_code"]], kwargs
            )

        def index_classify(self, **kwargs: Any) -> pd.DataFrame:
            self.classify_calls.append(kwargs)
            return pd.DataFrame(
                {"index_code": ["801780.SI", "801790.SI"], "industry_name": ["银行", "非银金融"]}
            )

    api = _TruncatingApi()
    frame = _load(api)

    assert api.classify_calls == [{"level": "L1", "src": "SW2021"}]
    assert [call.get("l1_code") for call in api.member_calls] == [
        None,
        "801780.SI",
        "801790.SI",
        None,
    ]
    assert frame.loc["2024-01-01", "600000.SH"] == "银行"
    assert frame.loc["2024-01-01", "000001.SZ"] == "非银金融"


def test_below_the_cap_snapshot_is_used_as_is() -> None:
    snapshot = _frame([_row("600000.SH", "银行", "20240101")])
    api = _FakeApi(snapshot)

    frame = _load(api)

    assert api.calls == [{"is_new": "Y"}, {"is_new": "N"}]
    assert frame.loc["2024-01-01", "600000.SH"] == "银行"


def test_src_is_never_passed_to_index_member_all() -> None:
    """Pins the live-verified endpoint quirk: an undocumented ``src`` param
    silently empties the index_member_all response (0 rows, HTTP 200)."""
    api = _FakeApi(_frame([_row("600000.SH", "银行", "20240101")]))

    _load(api, src="SW2021")

    assert api.calls, "expected index_member_all to be called"
    for call in api.calls:
        assert "src" not in call


# ------------------------------------------------------------- failure paths


def test_provider_exception_degrades_to_an_all_none_frame() -> None:
    api = _FakeApi(RuntimeError("provider down"))

    frame, coverage = load_industry_frame_with_coverage(
        symbols=_SYMBOLS, start="2024-01-01", end="2024-01-04", index=_INDEX, api=api
    )

    assert frame.shape == (len(_INDEX), len(_SYMBOLS))
    assert frame.isna().all().all()
    assert coverage == 0.0


def test_empty_snapshot_degrades_to_an_all_none_frame() -> None:
    frame = _load(_FakeApi(_frame([])))

    assert frame.isna().all().all()


def test_snapshot_missing_pit_columns_degrades_to_an_all_none_frame() -> None:
    """A payload without in_date/out_date cannot establish membership — degrade, never guess."""
    frame = _load(_FakeApi(pd.DataFrame({"ts_code": ["600000.SH"], "l1_name": ["银行"]})))

    assert frame.isna().all().all()


def test_placeholder_token_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "")
    monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(pro_api=lambda _token: None))

    with pytest.raises(RuntimeError, match="TUSHARE_TOKEN not configured"):
        load_industry_frame(
            symbols=_SYMBOLS, start="2024-01-01", end="2024-01-04", index=_INDEX
        )
