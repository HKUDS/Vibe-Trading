"""Shared, lazy local market-data gateway. No connection or worker at import."""

import atexit
import threading
from .config import Config
from .service import MarketDataGateway

_instance = None
_lock = threading.Lock()


def get_gateway() -> MarketDataGateway:
    """Return the process-wide gateway shared by API, tools and CLI."""
    global _instance
    with _lock:
        if _instance is None:
            _instance = MarketDataGateway(Config.from_env())
            atexit.register(_instance.close)
        return _instance
