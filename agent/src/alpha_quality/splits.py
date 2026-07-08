from __future__ import annotations

import pandas as pd

from src.alpha_quality.model import SplitConfig


def split_frame(frame: pd.DataFrame, split_config: SplitConfig, split: str) -> pd.DataFrame:
    mask = split_config.mask_for(frame.index, split)  # type: ignore[arg-type]
    return frame.loc[mask]
