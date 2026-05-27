"""資料源與變換函式 registry — Stage 0 / Stage 1 共用。

SOURCE_REGISTRY：定義每個因子資料源的取資料函式與狀態。
TRANSFORM_REGISTRY：定義每個因子序列的轉換函式。

Stage 0 用此 registry 來驗證 LLM 提案的 data_source 與 transform 是否合法。
Stage 1 用此 registry 來取資料（fetcher）並套用轉換（transform）。
"""

from __future__ import annotations

import dataclasses
from typing import Callable, Literal

import pandas as pd

from lib.okx_data import fetch_candles, fetch_funding_history
from lib.ccxt_data import fetch_oi_history_bybit
from lib.coingecko_data import fetch_stablecoin_supply


# ---------------------------------------------------------------------------
# SourceSpec dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SourceSpec:
    fetcher: Callable | None          # None for unavailable sources
    status: Literal["available", "unavailable"]
    description: str
    category: str                     # matches FactorCandidate.category values


# ---------------------------------------------------------------------------
# SOURCE_REGISTRY
# ---------------------------------------------------------------------------

SOURCE_REGISTRY: dict[str, SourceSpec] = {
    # ── Available entries ──────────────────────────────────────────────────
    "okx_funding": SourceSpec(
        fetcher=fetch_funding_history,
        status="available",
        description="OKX 8h 資金費率歷史",
        category="funding",
    ),
    "okx_candles": SourceSpec(
        fetcher=fetch_candles,
        status="available",
        description="OKX 永續合約小時 K 線（close/volume）",
        category="basis",
    ),
    "bybit_oi": SourceSpec(
        fetcher=fetch_oi_history_bybit,
        status="available",
        description="Bybit 小時 OI 歷史（小時頻）",
        category="oi",
    ),
    "coingecko_stablecoin_supply": SourceSpec(
        fetcher=fetch_stablecoin_supply,
        status="available",
        description="CoinGecko USDT+USDC+DAI 加總市值（日頻，免費 API）",
        category="stablecoin",
    ),
    # ── Unavailable entries (for Change 2) ────────────────────────────────
    "coinglass_liq": SourceSpec(
        fetcher=None,
        status="unavailable",
        description="幣安＋OKX 清算量（需 Coinglass 付費 API）",
        category="oi",
    ),
    "glassnode_pub": SourceSpec(
        fetcher=None,
        status="unavailable",
        description="Glassnode 公開鏈上指標",
        category="oi",
    ),
    "deribit_skew": SourceSpec(
        fetcher=None,
        status="unavailable",
        description="Deribit 25-delta 期權 skew",
        category="basis",
    ),
    "alt_fng": SourceSpec(
        fetcher=None,
        status="unavailable",
        description="alternative.me 恐慌貪婪指數（日頻）",
        category="funding",
    ),
    "okx_orderbook": SourceSpec(
        fetcher=None,
        status="unavailable",
        description="OKX 訂單簿快照（bid/ask imbalance）",
        category="basis",
    ),
}


# ---------------------------------------------------------------------------
# TRANSFORM_REGISTRY
# ---------------------------------------------------------------------------
# Rolling window sizes note (8h funding period basis where applicable):
#   z_30d        → rolling(90)  — 30 days × 3 funding periods/day = 90 8h periods
#   z_90d        → rolling(270) — 90 days × 3 funding periods/day = 270 8h periods
#   ma 7d        → rolling(21)  — 7 days × 3 periods/day = 21 8h periods
#   ma 30d       → rolling(90)  — 30 days × 3 periods/day = 90 8h periods
#
# Hourly-basis transforms (operate on hourly candle close series):
#   momentum_24h   → pct_change(24)  — 24h price momentum
#   momentum_72h   → pct_change(72)  — 72h price momentum
#   rolling_vol_30d → rolling(720) std of log returns — 30d × 24h hourly vol

TRANSFORM_REGISTRY: dict[str, Callable[[pd.Series], pd.Series]] = {
    "raw":             lambda s: s,
    "z_30d":           lambda s: (s - s.rolling(90).mean()) / s.rolling(90).std().replace(0, float("nan")),
    "z_90d":           lambda s: (s - s.rolling(270).mean()) / s.rolling(270).std().replace(0, float("nan")),
    "pct_change_24h":  lambda s: s.pct_change(24),
    "ma_diff_7d_30d":  lambda s: s.rolling(21).mean() - s.rolling(90).mean(),
    "momentum_24h":    lambda s: s.pct_change(24),
    "momentum_72h":    lambda s: s.pct_change(72),
    "rolling_vol_30d": lambda s: s.pct_change().rolling(720).std(),
}
