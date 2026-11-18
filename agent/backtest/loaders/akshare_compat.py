"""Resolve AKShare history endpoints across its naming migration."""

# Prefer the new name even when a caller supplies the old name. SDK errors
# from calling the resolved endpoint are handled by the normal reader.
_CURRENT_NAMES = {
    "stock_zh_a_hist": "stock_zh_a_hist_em",
    "stock_us_hist": "stock_us_hist_em",
    "stock_hk_hist": "stock_hk_hist_em",
    "forex_hist_em": "fx_hist_em",
    "currency_boc_sina": "fx_boc_rate_sina",
}
_LEGACY_NAMES = {current: legacy for legacy, current in _CURRENT_NAMES.items()}


def history_endpoint(sdk, name):
    """Resolve an endpoint without retrying a failing data request.

    Args:
        sdk: Imported AKShare module.
        name: Current or legacy endpoint name.

    Returns:
        The SDK's endpoint callable.
    """
    current = _CURRENT_NAMES.get(name, name)
    legacy = _LEGACY_NAMES.get(current)
    if legacy is None:
        return getattr(sdk, current)
    endpoint = getattr(sdk, current, None)
    return endpoint if endpoint is not None else getattr(sdk, legacy)
