"""Tests for the composable weight-constraint layer (Portfolio Studio step 2)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.constraints import (
    GroupExposure,
    MaxWeight,
    MinWeight,
    apply_constraints_frame,
    load_constraints,
)


def _frame(rows: dict, codes=("A", "B", "C", "D")) -> pd.DataFrame:
    """Build a signed weight frame from {date: [w...]} shorthand."""
    dates = pd.bdate_range("2025-01-01", periods=len(rows))
    data = [rows[k] for k in sorted(rows)]
    return pd.DataFrame(data, index=dates, columns=list(codes))


class TestMaxWeight:
    def test_clip_and_redistribute_pro_rata(self) -> None:
        w = MaxWeight(0.4).apply(np.array([0.7, 0.2, 0.1]), ["A", "B", "C"])
        assert w[0] == pytest.approx(0.4)
        # excess 0.3 goes to B and C in proportion 2:1
        assert w[1] == pytest.approx(0.2 + 0.3 * 2 / 3)
        assert w[2] == pytest.approx(0.1 + 0.3 * 1 / 3)
        assert w.sum() == pytest.approx(1.0)

    def test_redistribution_can_trigger_second_pass(self) -> None:
        w = MaxWeight(0.34).apply(np.array([0.8, 0.15, 0.05]), ["A", "B", "C"])
        assert np.all(w <= 0.34 + 1e-12)
        assert w.sum() == pytest.approx(1.0)

    def test_infeasible_cap_shrinks_gross(self) -> None:
        # 3 names at cap 0.2 can hold at most 0.6 of the book
        w = MaxWeight(0.2).apply(np.array([0.6, 0.3, 0.1]), ["A", "B", "C"])
        assert np.all(w == pytest.approx(0.2))
        assert w.sum() == pytest.approx(0.6)

    def test_noop_when_under_cap(self) -> None:
        src = np.array([0.3, 0.3, 0.4])
        w = MaxWeight(0.5).apply(src, ["A", "B", "C"])
        np.testing.assert_allclose(w, src)


class TestMinWeight:
    def test_lift_funded_by_largest(self) -> None:
        w = MinWeight(0.1).apply(np.array([0.85, 0.1, 0.05]), ["A", "B", "C"])
        assert w[2] == pytest.approx(0.1)
        assert w[1] == pytest.approx(0.1)
        assert w[0] == pytest.approx(0.8)
        assert w.sum() == pytest.approx(1.0)

    def test_infeasible_floor_degrades_to_equal(self) -> None:
        w = MinWeight(0.4).apply(np.array([0.5, 0.3, 0.2]), ["A", "B", "C"])
        np.testing.assert_allclose(w, np.full(3, 1.0 / 3.0))

    def test_zero_stays_zero(self) -> None:
        # handled at frame level, but the constraint itself must not invent weight
        w = MinWeight(0.2).apply(np.array([0.9, 0.1, 0.0]), ["A", "B", "C"])
        assert w[2] == pytest.approx(0.0)


class TestGroupExposure:
    def test_violating_group_scaled_pro_rata(self) -> None:
        con = GroupExposure({"A": "tech", "B": "tech", "C": "energy"}, {"tech": 0.5})
        w = con.apply(np.array([0.4, 0.3, 0.3]), ["A", "B", "C"])
        assert w[0] + w[1] == pytest.approx(0.5)
        assert w[0] / w[1] == pytest.approx(0.4 / 0.3)
        assert w[2] == pytest.approx(0.3)

    def test_compliant_group_untouched(self) -> None:
        con = GroupExposure({"A": "tech", "B": "tech"}, {"tech": 0.9})
        src = np.array([0.3, 0.2, 0.5])
        w = con.apply(src, ["A", "B", "C"])
        np.testing.assert_allclose(w, src)

    def test_unmapped_codes_unconstrained(self) -> None:
        con = GroupExposure({"A": "tech"}, {"tech": 0.3})
        w = con.apply(np.array([0.4, 0.6]), ["A", "OTHER"])
        assert w[0] == pytest.approx(0.3)
        assert w[1] == pytest.approx(0.6)


class TestLoadConstraints:
    def test_empty_by_default(self) -> None:
        assert load_constraints({}) == []
        assert load_constraints({"constraints": []}) == []

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown constraint type"):
            load_constraints({"constraints": [{"type": "nonsense"}]})

    def test_cap_validation(self) -> None:
        for bad in (0, -0.1, 1.5, True, "big", float("nan")):
            with pytest.raises(ValueError):
                load_constraints({"constraints": [{"type": "max_weight", "cap": bad}]})

    def test_missing_keys_rejected(self) -> None:
        with pytest.raises(ValueError, match="requires 'cap'"):
            load_constraints({"constraints": [{"type": "max_weight"}]})
        with pytest.raises(ValueError, match="requires 'floor'"):
            load_constraints({"constraints": [{"type": "min_weight"}]})

    def test_group_caps_must_reference_mapped_groups(self) -> None:
        with pytest.raises(ValueError, match="no mapped assets"):
            load_constraints({
                "constraints": [{
                    "type": "group_exposure",
                    "groups": {"A": "tech"},
                    "caps": {"energy": 0.5},
                }]
            })

    def test_constraints_not_a_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a list"):
            load_constraints({"constraints": {"type": "max_weight", "cap": 0.3}})


class TestApplyFrame:
    def test_signs_preserved(self) -> None:
        frame = _frame({"2025-01-01": [0.7, -0.2, 0.1, 0.0]})
        out = apply_constraints_frame(frame, load_constraints({
            "constraints": [{"type": "max_weight", "cap": 0.4}]
        }))
        assert out.iloc[0]["A"] == pytest.approx(0.4)
        assert out.iloc[0]["B"] < 0
        assert out.iloc[0]["C"] > 0
        assert out.iloc[0]["D"] == 0.0
        # gross exposure preserved through redistribution
        assert out.abs().sum(axis=1).iloc[0] == pytest.approx(1.0)

    def test_config_order_applies(self) -> None:
        frame = _frame({"2025-01-01": [0.5, 0.4, 0.1, 0.0]})
        cons = load_constraints({
            "constraints": [
                {"type": "max_weight", "cap": 0.45},
                {"type": "group_exposure", "groups": {"A": "x", "B": "x"}, "caps": {"x": 0.7}},
            ]
        })
        out = apply_constraints_frame(frame, cons)
        assert out.iloc[0]["A"] <= 0.45 + 1e-12
        assert out.iloc[0]["A"] + out.iloc[0]["B"] == pytest.approx(0.7)

    def test_empty_constraints_identity(self) -> None:
        frame = _frame({"2025-01-01": [0.5, -0.3, 0.2, 0.0]})
        out = apply_constraints_frame(frame, [])
        pd.testing.assert_frame_equal(out, frame)

    def test_per_date_independence(self) -> None:
        frame = _frame({
            "2025-01-01": [0.9, 0.1, 0.0, 0.0],
            "2025-01-02": [0.2, 0.2, 0.6, 0.0],
        })
        out = apply_constraints_frame(frame, load_constraints({
            "constraints": [{"type": "max_weight", "cap": 0.5}]
        }))
        assert out.iloc[0]["A"] == pytest.approx(0.5)
        assert out.iloc[1]["C"] == pytest.approx(0.5)

    def test_idempotent(self) -> None:
        frame = _frame({"2025-01-01": [0.7, 0.2, 0.1, 0.0]})
        cons = load_constraints({
            "constraints": [
                {"type": "max_weight", "cap": 0.4},
                {"type": "min_weight", "floor": 0.1},
            ]
        })
        once = apply_constraints_frame(frame, cons)
        twice = apply_constraints_frame(once, cons)
        pd.testing.assert_frame_equal(once, twice)


class TestEngineWiring:
    """The layer composes onto whatever optimizer the config selects."""

    def test_load_optimizer_applies_constraints(self) -> None:
        from backtest.engines.base import _load_optimizer

        n_days, n_assets = 120, 4
        rng = np.random.default_rng(0)
        dates = pd.bdate_range("2025-01-01", periods=n_days)
        codes = [f"A{i}" for i in range(n_assets)]
        ret = pd.DataFrame(
            rng.normal(0.001, 0.02, (n_days, n_assets)), index=dates, columns=codes
        )
        pos = pd.DataFrame(1.0, index=dates, columns=codes)

        config = {
            "optimizer": "equal_volatility",
            "constraints": [{"type": "max_weight", "cap": 0.4}],
        }
        opt_fn = _load_optimizer(config)
        out = opt_fn(ret, pos, dates)
        active_rows = out.index[out.abs().sum(axis=1) > 0]
        assert len(active_rows) > 0
        for dt in active_rows:
            assert (out.loc[dt].abs() <= 0.4 + 1e-9).all()

    def test_constraints_without_optimizer_warns_and_passes(self, capsys) -> None:
        from backtest.engines.base import _load_optimizer

        config = {"constraints": [{"type": "max_weight", "cap": 0.4}]}
        assert _load_optimizer(config) is None
        assert "constraints" in capsys.readouterr().out
