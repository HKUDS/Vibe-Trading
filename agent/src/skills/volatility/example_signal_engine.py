"""波动率策略信号引擎。

基于历史波动率（HV）百分位排名进行均值回归交易：
低波区间做多等待扩张，高波区间做空等待收缩。纯 pandas 实现。
"""

from typing import Dict

import numpy as np
import pandas as pd


def compute_hv(close: pd.Series, window: int = 20, annualize: int = 252) -> pd.Series:
    """计算年化历史波动率。

    Args:
        close: 收盘价序列。
        window: 波动率计算窗口。
        annualize: 年化系数（A股252，加密365）。

    Returns:
        年化历史波动率序列。
    """
    returns = close.pct_change(fill_method=None)
    return returns.rolling(window).std() * np.sqrt(annualize)


def compute_hv_percentile(hv: pd.Series, lookback: int = 120) -> pd.Series:
    """计算 HV 的滚动百分位排名。

    Args:
        hv: 历史波动率序列。
        lookback: 百分位排名回看期。

    Returns:
        百分位值（0-100）。
    """
    return hv.rolling(lookback).rank(pct=True) * 100


class SignalEngine:
    """波动率均值回归信号引擎。

    计算历史波动率的百分位排名，低波做多、高波做空。

    Attributes:
        hv_window: HV 计算窗口。
        lookback: 百分位排名回看期。
        low_pct: 低波阈值（百分位）。
        high_pct: 高波阈值（百分位）。
        annualize: 年化系数。

    Example:
        >>> engine = SignalEngine(hv_window=20, lookback=120)
        >>> signals = engine.generate({"BTC-USDT": df})
        >>> signals["BTC-USDT"].value_counts()
    """

    def __init__(
        self,
        hv_window: int = 20,
        lookback: int = 120,
        low_pct: float = 20.0,
        high_pct: float = 80.0,
        annualize: int = 252,
    ):
        """初始化波动率引擎。

        Args:
            hv_window: HV 计算窗口。
            lookback: 百分位排名回看期。
            low_pct: 低波阈值（百分位）。
            high_pct: 高波阈值（百分位）。
            annualize: 年化系数（A股252，加密365）。
        """
        self.hv_window = hv_window
        self.lookback = lookback
        self.low_pct = low_pct
        self.high_pct = high_pct
        self.annualize = annualize

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """根据波动率百分位生成交易信号。

        Args:
            data_map: 标的代码到 OHLCV DataFrame 的映射。

        Returns:
            标的代码到信号 Series 的映射（1=做多, -1=做空, 0=观望）。
        """
        result = {}
        for code, df in data_map.items():
            result[code] = self._generate_one(df)
        return result

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        """对单个标的生成波动率信号。

        Args:
            df: OHLCV DataFrame。

        Returns:
            信号 Series。
        """
        close = df["close"]
        hv = compute_hv(close, self.hv_window, self.annualize)
        pct = compute_hv_percentile(hv, self.lookback)

        signal = pd.Series(0, index=df.index)
        signal[pct < self.low_pct] = 1     # 低波做多
        signal[pct > self.high_pct] = -1   # 高波做空
        return signal.fillna(0).astype(int)
