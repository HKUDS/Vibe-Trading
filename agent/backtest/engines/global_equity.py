"""Global equity (US / HK / Canada / UK) backtest engine.

Market rules:
  US:
    - T+0, long/short allowed
    - Zero commission (retail brokers)
    - Fractional shares supported (round to 0.01)
    - Low slippage (high liquidity)
  HK:
    - T+0, long/short allowed
    - Stamp tax 0.1% bilateral + levies
    - Lot-size rounding (simplified to 100 shares)
    - Higher slippage than US
  Canada (TSX / TSX Venture):
    - Same-session round trips and long/short orders supported
    - Whole shares; odd and mixed lots remain executable
    - Broker commission and slippage are config-driven
    - Official TSX/TSXV price-increment grid is applied to fills
  UK (LSE, GBP/GBp-quoted lines only):
    - Same-session round trips and long/short orders supported
    - Whole shares
    - Config-driven slippage
    - SDRT charged on purchases

India (NSE/BSE) is handled by the dedicated ``backtest.engines.india_equity``
``IndiaEquityEngine`` (T+1 delivery, circuit bands, STT/stamp/GST stack).
"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

from backtest.engines.base import BaseEngine


class GlobalEquityEngine(BaseEngine):
    """US / HK / Canada / UK equity engine selected by *market*.

    Config keys:
      - slippage_us: default 0.0005
      - slippage_hk: default 0.001
      - hk_stamp_tax: default 0.001 (0.1% bilateral)
      - hk_commission: default 0.00015 (万1.5)
      - hk_levy: default 0.0000565 (SFC + FRC)
      - hk_settlement: default 0.00002 (CCASS)
      - slippage_ca: defaults to slippage_us
      - ca_commission: broker commission rate, default 0.0
      - slippage_uk: defaults to slippage_us
      - uk_stamp_tax: default 0.005 (0.5% Stamp Duty Reserve Tax on
        purchases only; chargeable on the buyer, paid on buying to close
        short positions too)
    """

    def __init__(self, config: dict, market: str = "us"):
        config = {**config, "leverage": config.get("leverage", 1.0)}
        super().__init__(config)
        self.market = market

        # US defaults
        self.slippage_us: float = config.get("slippage_us", 0.0005)
        # HK defaults
        self.slippage_hk: float = config.get("slippage_hk", 0.001)
        self.hk_stamp_tax: float = config.get("hk_stamp_tax", 0.001)
        self.hk_commission: float = config.get("hk_commission", 0.00015)
        self.hk_levy: float = config.get("hk_levy", 0.0000565)
        self.hk_settlement: float = config.get("hk_settlement", 0.00002)
        # Canada defaults. Commission varies by broker, so the model exposes a
        # rate instead of inventing an exchange-wide charge.
        self.slippage_ca: float = config.get("slippage_ca", self.slippage_us)
        self.ca_commission: float = config.get("ca_commission", 0.0)
        # UK defaults. LSE has no broker-commission model; the exchange-level
        # cost is SDRT: 0.5% on the buyer of Main Market equities, rounded to
        # the nearest penny (FA86/S99(13); exact ½p rounds up). Exemptions —
        # qualifying UCITS ETFs, AIM shares, gilts, new issues — are the
        # caller's concern; this engine applies the statutory Main Market rate.
        self.slippage_uk: float = config.get("slippage_uk", self.slippage_us)
        self.uk_stamp_tax: float = config.get("uk_stamp_tax", 0.005)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Allow same-session trading in both directions for every market."""
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """US: fractional; HK: 100-share lots; Canada/UK: whole shares.

        TSX and TSXV accept odd and mixed lots through dedicated facilities,
        so forcing every order to a board lot would reject valid retail trades.
        Canada and UK exchanges have no native fractional-share order, hence
        the whole-share floor.
        """
        if self.market == "hk":
            return max(int(raw_size / 100) * 100, 0)
        if self.market in {"ca", "uk"}:
            return float(math.floor(max(raw_size, 0.0)))
        return round(max(raw_size, 0.0), 2)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """US: zero; HK: stamp tax + levies; Canada: configured broker rate;
        UK: SDRT on the buyer only.

        ``direction`` is the order/position side (1=buy-long/short-cover,
        -1=sell/short). Trade side is direction on opens and -direction on
        closes (closing a long sells; covering a short buys). UK SDRT applies
        to purchases of every kind: opening long and buying to cover.
        """
        if self.market == "hk":
            notional = size * price
            comm = notional * self.hk_commission       # broker commission
            comm += notional * self.hk_stamp_tax       # stamp tax bilateral
            comm += notional * self.hk_levy            # SFC + FRC levies
            comm += notional * self.hk_settlement      # CCASS settlement
            return comm
        if self.market == "ca":
            return size * price * self.ca_commission
        if self.market == "uk":
            # SDRT is a purchase-side charge only: 0.5% of consideration on
            # the buyer, rounded to the nearest penny (FA86/S99(13); an exact
            # ½p rounds UP). Python's float round() is banker's rounding and
            # handles 1.005 inconsistently (-> 1.00), so use Decimal
            # ROUND_HALF_UP for the statutory direction.
            #
            # While open orders carry buyer/seller as the sign directly, a
            # CLOSE passes the *position* side: closing a long (direction=1)
            # is a sale, covering a short (direction=-1) is a purchase.
            trade_is_buy = direction > 0 if is_open else direction < 0
            if trade_is_buy:
                consideration = Decimal(str(size)) * Decimal(str(price))
                tax = consideration * Decimal(str(self.uk_stamp_tax))
                return float(tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            return 0.0
        # US: zero commission (SEC fee negligible)
        return 0.0

    def apply_slippage(self, price: float, direction: int) -> float:
        """Apply market slippage and Canada's official price-increment grid."""
        if self.market == "hk":
            rate = self.slippage_hk
        elif self.market == "ca":
            rate = self.slippage_ca
        elif self.market == "uk":
            rate = self.slippage_uk
        else:
            rate = self.slippage_us
        slipped = price * (1 + direction * rate)
        if self.market != "ca":
            return slipped

        # TSX/TSXV standard increments: $0.005 below $0.50, otherwise $0.01.
        # Round against the trader: buys/cover orders up, sells/shorts down.
        tick = 0.005 if slipped < 0.50 else 0.01
        units = slipped / tick
        if direction > 0:
            steps = math.ceil(units - 1e-12)
        elif direction < 0:
            steps = math.floor(units + 1e-12)
        else:
            steps = round(units)
        return round(steps * tick, 3 if tick == 0.005 else 2)
