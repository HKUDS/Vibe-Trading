"""Download helpers shared by the Brazilian dataset syncs."""

from __future__ import annotations

import io
import logging
import zipfile
import math
from datetime import datetime
from typing import Optional

from backtest.loaders._http import throttled_get

logger = logging.getLogger(__name__)

_MIN_INTERVAL_S = 1.0
_TIMEOUT_S = 300.0


def fetch_bytes(url: str, host_key: str) -> Optional[bytes]:
    """GET ``url``; ``None`` on 404 (file not published), raise on other errors."""
    response = throttled_get(url, host_key=host_key, min_interval=_MIN_INTERVAL_S, timeout=_TIMEOUT_S)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def zip_members(payload: bytes) -> dict[str, bytes]:
    """Return ``{member name: bytes}`` for every file inside a ZIP payload."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return {
            info.filename: archive.read(info)
            for info in archive.infolist()
            if not info.is_dir()
        }


def decode_text(raw: bytes) -> str:
    """Decode a CVM/B3 text file (UTF-8 when valid, else Latin-1)."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def to_float(value: str | None) -> Optional[float]:
    """Parse ``1234.56`` or Brazilian ``1.234,56``; blank -> ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def br_date(value: str | None) -> Optional[str]:
    """``dd/mm/yyyy`` or ``yyyy-mm-dd`` -> ``yyyy-mm-dd``; anything else -> ``None``."""
    if not value:
        return None
    text = str(value).strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def digits(value: str | None) -> str:
    """Keep only the digits (CNPJ normalization)."""
    return "".join(ch for ch in str(value or "") if ch.isdigit())
