import numpy as np
import pytest
from src.quantlib.credit import cds_price


@pytest.mark.parametrize("tenor", [0.1, 0.6, 1.1, 1.25])
def test_cds_regular_coupon_dates_and_final_stub(tenor):
    frequency = 4
    regular = np.arange(1, int(np.ceil(tenor * frequency)), dtype=float) / frequency
    dates = np.r_[regular, tenor]
    lengths = np.diff(np.r_[0.0, dates])
    expected = float(np.sum(lengths * np.exp(-0.07 * dates)))
    actual = cds_price(
        0.0, tenor_years=tenor, risk_free_rate=0.07, payment_frequency=frequency
    )
    assert actual["rpv01"] == pytest.approx(expected, abs=1e-14)
    assert actual["premium_leg_pv"] == pytest.approx(0.01 * expected)


def test_quantlib_tool_prices_final_coupon_stub():
    import json
    from src.tools.quantlib_tool import QuantlibCallTool

    result = json.loads(
        QuantlibCallTool().execute(
            action="call",
            module="credit",
            function="cds_price",
            kwargs={"spread_bps": 0.0, "tenor_years": 0.6, "risk_free_rate": 0.07},
        )
    )
    expected = (
        0.25 * np.exp(-0.07 * 0.25)
        + 0.25 * np.exp(-0.07 * 0.5)
        + 0.1 * np.exp(-0.07 * 0.6)
    )
    assert result["ok"] is True
    assert result["result"]["rpv01"] == pytest.approx(expected)
