"""分钟级数据分析工具。

通过 OKX API 获取分钟 K 线，计算 VWAP/TWAP/成交量分布等日内指标。
仅供分析输出，不可用于回测引擎（仅支持日线）。
"""

from typing import Optional

import numpy as np
import pandas as pd






def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """计算累积 VWAP（成交量加权平均价）。

    Args:
        df: 包含 high/low/close/volume 列的 DataFrame。

    Returns:
        VWAP 序列。
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    return cum_tp_vol / cum_vol


def compute_twap(df: pd.DataFrame) -> pd.Series:
    """计算累积 TWAP（时间加权平均价）。

    Args:
        df: 包含 close 列的 DataFrame。

    Returns:
        TWAP 序列。
    """
    return df["close"].expanding().mean()


def volume_profile(df: pd.DataFrame, bins: int = 20) -> pd.DataFrame:
    """计算成交量分布（按价格区间）。

    Args:
        df: 包含 close/volume 列的 DataFrame。
        bins: 价格区间数量。

    Returns:
        DataFrame 含 price_range 和 volume 列。
    """
    price_bins = pd.cut(df["close"], bins=bins)
    vol_by_price = df.groupby(price_bins, observed=True)["volume"].sum()
    result = vol_by_price.reset_index()
    result.columns = ["price_range", "volume"]
    result["volume_pct"] = result["volume"] / result["volume"].sum() * 100
    return result.sort_values("volume", ascending=False)


def hourly_volume(df: pd.DataFrame) -> pd.DataFrame:
    """按小时聚合成交量。

    Args:
        df: 分钟级 DataFrame。

    Returns:
        小时级成交量汇总。
    """
    hourly = df.resample("1h")["volume"].sum()
    result = hourly.reset_index()
    result.columns = ["hour", "volume"]
    result["volume_pct"] = result["volume"] / result["volume"].sum() * 100
    return result
