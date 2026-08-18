"""Conservative read/write classification for XtQuant operations."""

from src.live.classification import ToolClass

QMT_TOOL_CLASS: dict[str, ToolClass] = {
    "start": ToolClass.READ,
    "connect": ToolClass.READ,
    "subscribe": ToolClass.READ,
    "query_stock_asset": ToolClass.READ,
    "query_stock_positions": ToolClass.READ,
    "query_stock_orders": ToolClass.READ,
    "query_stock_trades": ToolClass.READ,
    "get_full_tick": ToolClass.READ,
    "get_market_data_ex": ToolClass.READ,
    "download_history_data": ToolClass.READ,
    "order_stock": ToolClass.WRITE,
    "cancel_order_stock": ToolClass.WRITE,
}

