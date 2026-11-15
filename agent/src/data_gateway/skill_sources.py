"""Bounded SDK reads for bundled research examples and reference snippets.

Prefer the existing tools/market-data facade for normalized bars and supported
research capabilities. These adapters preserve vendor schemas for additional
fields, without introducing an SDK executor, cache or credential store.
"""

from .reads import managed_reader


class _TushareReader:
    def __init__(self, token):
        self._token = token

    def __getattr__(self, endpoint):
        if endpoint.startswith("_"):
            raise AttributeError(endpoint)

        @managed_reader
        def query(*args, **kwargs):
            import tushare as ts
            from src.config.accessor import get_env_config

            token = self._token or get_env_config().data.tushare_token or ts.get_token()
            return getattr(ts.pro_api(token), endpoint)(*args, **kwargs)

        return query


def tushare_client(token=None):
    """Return a lazy read client; each Pro query enters shared acquisition.

    Args:
        token: Existing authorized token. Omission uses configured/SDK credentials.

    Returns:
        A read client with the Pro endpoint names and original result schemas.
    """
    return _TushareReader(token)


@managed_reader
def tushare_bar(*args, **kwargs):
    """Read the SDK's adjusted bars inside the shared source budget."""
    import tushare as ts

    kwargs.setdefault("api", tushare_client())
    return ts.pro_bar(*args, **kwargs)


@managed_reader
def akshare_query(endpoint, **kwargs):
    """Read a named AKShare data endpoint, retaining its vendor column names."""
    import akshare

    if not endpoint.isidentifier() or endpoint.startswith("_"):
        raise ValueError("Expected a public AKShare data endpoint")
    return getattr(akshare, endpoint)(**kwargs)


@managed_reader
def yahoo_download(*args, **kwargs):
    """Read Yahoo's DataFrame schema without an independent SDK thread pool."""
    import yfinance

    return yfinance.download(*args, **{**kwargs, "threads": False})


class _YahooReader:
    # These are materialized data fields used in bundled research examples.
    # Do not return lazy SDK objects (e.g. funds_data) that fetch after the slot
    # is released. For additional fields, use a managed_reader that materializes
    # its complete result inside the callback.
    _fields = frozenset(
        {
            "info",
            "fast_info",
            "financials",
            "quarterly_financials",
            "balance_sheet",
            "cashflow",
            "earnings",
            "dividends",
            "splits",
            "actions",
            "institutional_holders",
            "major_holders",
            "insider_transactions",
            "earnings_dates",
            "earnings_history",
        }
    )

    def __init__(self, symbol):
        self._symbol = symbol

    def __getattr__(self, field):
        if field not in self._fields:
            raise AttributeError(f"{field}: use a managed_reader to materialize additional Yahoo data")

        @managed_reader
        def fetch():
            import yfinance

            value = getattr(yfinance.Ticker(self._symbol), field)
            return dict(value) if field == "fast_info" else value

        return fetch()


def yahoo_ticker(symbol):
    """Return a research reader whose lazy property reads also enter the gateway."""
    return _YahooReader(symbol)
