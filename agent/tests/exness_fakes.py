"""Shared synthetic fakes for the Exness connector tests (no real broker data)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from src.trading.connectors.exness._client import ExnessConfig

RFC8032_HEX = (
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
GATEWAY = "https://gw-test.exness-api.com"
ACCESS_POINT = "https://ap-test.exness.com"
ACCOUNT = "123456"


class FakeResponse:
    """Minimal ``requests.Response`` stand-in."""

    def __init__(self, status_code: int, payload: Any = None, *, text: str | None = None,
                 headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        if text is not None:
            self.text = text
        else:
            self.text = json.dumps(payload) if payload is not None else ""
        self.content = self.text.encode("utf-8")

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class FakeTransport:
    """Route ``(METHOD, path?query)`` to canned responses; record every call.

    Unexpected requests raise ``AssertionError`` so a test fails loudly when the
    connector touches an endpoint it should not (e.g. an order POST behind a
    refused gate). A list value is consumed in order (for polling).
    """

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = dict(routes)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        parts = urlsplit(url)
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        self.calls.append({"method": method.upper(), "url": url, "target": target,
                           "host": f"{parts.scheme}://{parts.netloc}", **kwargs})
        key = (method.upper(), target)
        if key not in self.routes:
            raise AssertionError(f"unexpected request {key}")
        value = self.routes[key]
        if isinstance(value, list):
            if not value:
                raise AssertionError(f"route exhausted {key}")
            return value.pop(0) if len(value) > 1 else value[0]
        return value

    def targets(self, method: str | None = None) -> list[str]:
        return [c["target"] for c in self.calls if method is None or c["method"] == method]


def discovery_route() -> dict[tuple[str, str], FakeResponse]:
    return {
        ("GET", f"/v1/trading/access-point?account_id={ACCOUNT}"): FakeResponse(
            200, {"access_point": ACCESS_POINT, "account_id": ACCOUNT}
        )
    }


def make_config(**overrides: Any) -> ExnessConfig:
    data: dict[str, Any] = {
        "api_key": "exnsk-synthetic-example",
        "private_key": RFC8032_HEX,
        "account_id": ACCOUNT,
        "gateway_url": GATEWAY,
        "profile": "live-readonly",
        "operation_wait_seconds": 0,
    }
    data.update(overrides)
    return ExnessConfig.from_mapping(data)
