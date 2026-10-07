
# ============================================================
# 中文名称: GTJA Alpha #177
# 简要说明: 国泰君安191短周期交易型alpha因子第177号，详见公式定义。
# 典型用途: 在A股市场经中性化处理后用于选股或股指期货日内交易。
# ============================================================
"""GTJA Alpha 177 (Guotai Junan, 2017-06-15).

Formula (report appendix; source linked in gtja191/LICENSE.md):
    ((20-HIGHDAY(HIGH,20))/20)*100

HIGHDAY/LOWDAY count bars since the extreme: today is 0, not 1.
The report does not specify ties; this port chooses the most recent extreme.
Reversing each complete window makes that convention independent of the
optional bottleneck backend used by the shared ts_argmax/ts_argmin operators.
"""
from __future__ import annotations

import numpy as np

ALPHA_ID = "gtja191_177"

__alpha_meta__ = {
    'id': 'gtja191_177',
    'theme': ['momentum'],
    'formula_latex': '((20-highday(h,20))/20)*100',
    'columns_required': ['close', 'high'],
    'extras_required': [],
    'universe': ['equity_cn'],
    'frequency': ['1d'],
    'decay_horizon': 20,
    'min_warmup_bars': 20,
    'notes': 'Days since the most recent extreme; today=0. Ties choose the latest bar (port policy).',
}


def compute(panel):
    """Compute gtja191_177.

    Args:
        panel: dict[str, pd.DataFrame] with at least the required columns.

    Returns:
        pd.DataFrame with index = panel["close"].index, columns = panel["close"].columns.
    """
    highday = panel["high"].rolling(20, min_periods=20).apply(
        lambda window: np.argmax(window[::-1]), raw=True
    )
    return (20.0 - highday) / 20.0 * 100.0
