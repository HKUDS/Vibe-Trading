"""Smart Money Concepts (ICT) 信号引擎。

基于 smartmoneyconcepts 库实现机构交易学派的核心分析：
- 结构突破 (BOS) / 性质转变 (ChoCH)
- 公允价值缺口 (FVG)

信号逻辑：ChoCH 优先触发方向，BOS 确认，FVG 同向过滤。
"""

from typing import Dict, Optional

# smartmoneyconcepts prints emoji on import. The backtest runner already sets
# PYTHONIOENCODING=utf-8 for strategy code; to run this demo directly on
# Windows, set PYTHONIOENCODING=utf-8 in the shell first.

import numpy as np
import pandas as pd
from smartmoneyconcepts import smc




class SignalEngine:
    """Smart Money Concepts 信号引擎。

    基于 BOS/ChoCH 结构信号 + FVG 过滤，生成做多/做空/观望信号。

    Attributes:
        swing_length: Swing 高低点检测窗口大小。
        close_break: BOS/ChoCH 是否需要收盘价突破确认。

    Example:
        >>> engine = SignalEngine(swing_length=50)
        >>> signals = engine.generate({"BTC-USDT": df})
        >>> print(signals["BTC-USDT"].value_counts())
    """

    def __init__(self, swing_length: int = 10, close_break: bool = True):
        """初始化 SMC 信号引擎。

        Args:
            swing_length: Swing 高低点检测窗口，值越大检测到的结构越少但越可靠。
            close_break: 是否要求收盘价突破才算有效 BOS/ChoCH。
        """
        self.swing_length = swing_length
        self.close_break = close_break

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """根据 Smart Money Concepts 生成交易信号。

        Args:
            data_map: 标的代码到 OHLCV DataFrame 的映射。
                DataFrame 需包含 open/high/low/close/volume 列，index 为 datetime。

        Returns:
            标的代码到信号 Series 的映射（1=做多, -1=做空, 0=观望）。
        """
        result = {}
        for code, df in data_map.items():
            signal = pd.Series(0, index=df.index)

            ohlc = df[["open", "high", "low", "close", "volume"]].copy()
            ohlc.columns = ["open", "high", "low", "close", "volume"]

            min_bars = self.swing_length * 2
            if len(ohlc) < min_bars:
                print(f"  {code} K线不足 {min_bars} 根，跳过")
                result[code] = signal
                continue

            try:
                signal = self._compute_signal(ohlc, df.index)
            except Exception as e:
                print(f"  {code} SMC计算异常: {e}")

            result[code] = signal
        return result

    def _compute_signal(
        self, ohlc: pd.DataFrame, original_index: pd.Index
    ) -> pd.Series:
        """对单个标的计算 SMC 信号。

        Args:
            ohlc: 标准化的 OHLCV DataFrame。
            original_index: 原始 DataFrame 的 index，用于对齐输出。

        Returns:
            信号 Series（1=做多, -1=做空, 0=观望）。
        """
        signal = pd.Series(0, index=original_index)

        # 1) Swing 高低点检测
        swing_hl = smc.swing_highs_lows(ohlc, swing_length=self.swing_length)

        # 2) BOS / ChoCH 结构突破检测
        bos_choch = smc.bos_choch(
            ohlc, swing_highs_lows=swing_hl, close_break=self.close_break
        )

        # 3) FVG 公允价值缺口检测
        fvg = smc.fvg(ohlc)

        # 提取信号列（NaN 填 0）
        bos_val = bos_choch["BOS"].fillna(0).astype(int)
        choch_val = bos_choch["CHOCH"].fillna(0).astype(int)
        fvg_val = fvg["FVG"].fillna(0).astype(int)

        # 结构信号：ChoCH 优先，BOS 补充
        structure = choch_val.where(choch_val != 0, bos_val)

        # FVG 过滤：只在 FVG 同向或中性时出信号
        buy = (structure == 1) & (fvg_val >= 0)
        sell = (structure == -1) & (fvg_val <= 0)

        raw_signal = buy.astype(int) - sell.astype(int)
        signal[:] = raw_signal.values

        return signal
