"""Unadjusted execution bars, separate from research return-series loaders."""

from backtest.loaders.tencent_loader import DataLoader as TencentLoader


class TencentRawLoader:
    """Read Tencent's raw endpoint without polluting the adjusted-price cache."""

    name = "tencent_raw"

    def fetch(self, codes, start_date, end_date, *, interval="1D"):
        if interval != "1D":
            raise ValueError("Paper execution requires daily bars")
        loader = TencentLoader()
        result = {}
        for code in codes:
            frame = loader._fetch_one(
                code, start_date, end_date, forward_adjusted=False
            )
            if frame is not None and not frame.empty:
                frame.attrs["adjustment"] = "raw"
                result[code] = frame
        return result
