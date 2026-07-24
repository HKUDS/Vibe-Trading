"""DuckDB storage helpers."""

from src.tw_quant.db.connection import connect_database
from src.tw_quant.db.migrations import migrate

__all__ = ["connect_database", "migrate"]
