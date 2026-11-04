"""Explicit opt-ins for the optional Gildata research integrations."""

from typing import Literal, get_args

from src.config.accessor import get_env_config

GildataFeature = Literal[
    "fin_query",
    "stock_selection",
    "symbol_search",
    "shannon",
    "market_quotes",
    "fund_nav",
    "macro_series",
    "announcements",
    "broker_reports",
]
FEATURES_ENV = "VIBE_TRADING_GILDATA_FEATURES"


def selected_features() -> list[GildataFeature]:
    """Return recognized, individually selected features in settings order."""
    selected = {name.strip() for name in get_env_config().data.gildata_features.split(",")}
    return [name for name in get_args(GildataFeature) if name in selected]


def feature_available(feature: GildataFeature) -> bool:
    """Check the current credential and opt-in before using a vendor capability."""
    data = get_env_config().data
    return data.gildata_token.strip() not in {"", "your-gildata-token"} and feature in selected_features()
