"""Tests for the KIS (한국투자증권) direct-SDK trading connector.

Mirrors ``test_sdk_connectors.py``: exercises profile registration, the
genuine structural paper/live host separation, config resolution, read/write
classification, secret redaction, and service dispatch degrading cleanly when
nothing is configured — no live credentials or network access required.
"""

from __future__ import annotations

import pytest

from src.live.classification import ToolClass
from src.trading import profiles, service
from src.trading.connectors.kis import sdk as kis
from src.trading.connectors.kis.classification import KIS_TOOL_CLASS

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Profile registration
# --------------------------------------------------------------------------- #


def test_kis_sdk_profiles_registered() -> None:
    ids = {p.id for p in profiles.list_profiles()}
    assert {"kis-paper-sdk", "kis-paper-trade", "kis-live-sdk-readonly"} <= ids


def test_kis_live_profile_is_readonly_broker_sdk() -> None:
    profile = profiles.profile_by_id("kis-live-sdk-readonly")
    assert profile.connector == "kis"
    assert profile.environment == "live"
    assert profile.transport == "broker_sdk"
    assert profile.readonly is True
    assert not any(".place" in cap or "requires_mandate" in cap for cap in profile.capabilities)


def test_kis_paper_trade_profile_allows_order_placement() -> None:
    profile = profiles.profile_by_id("kis-paper-trade")
    assert profile.environment == "paper"
    assert profile.readonly is False
    assert "orders.place" in profile.capabilities


# --------------------------------------------------------------------------- #
# Genuine structural paper/live host separation
# --------------------------------------------------------------------------- #


def test_kis_base_url_differs_by_environment() -> None:
    paper = kis.KISConfig(profile="paper")
    live = kis.KISConfig(profile="live-readonly")
    assert paper.base_url != live.base_url
    assert "vts" in paper.base_url  # 모의투자 (paper) host
    assert paper.base_url.endswith(":29443")
    assert live.base_url.endswith(":9443")


def test_kis_order_tr_id_differs_by_environment_and_side() -> None:
    assert kis._TR_ORDER_BUY["paper"] != kis._TR_ORDER_BUY["live"]
    assert kis._TR_ORDER_BUY["paper"] != kis._TR_ORDER_SELL["paper"]


def test_kis_invalid_profile_rejected() -> None:
    with pytest.raises(kis.KISConfigError):
        kis.KISConfig.from_mapping({"profile": "live"})  # only paper/live-readonly


def test_kis_profile_override_is_not_forwarded() -> None:
    """A caller-supplied override must never flip paper -> live: only the
    profile's own declared config may set ``profile`` (see the note beside
    ``_OVERRIDE_KEYS``)."""
    assert "profile" not in kis._OVERRIDE_KEYS
    cfg = kis.build_config({"profile": "paper"}, {"profile": "live-readonly", "app_key": "k"})
    assert cfg.profile == "paper"
    assert cfg.app_key == "k"  # allowlisted keys still pass through


class _FakeResponse:
    def __init__(self, url: str, headers_sent: dict, json_body: dict, response_headers: dict | None = None):
        self.url = url
        self.headers_sent = headers_sent
        self._json = json_body
        self.status_code = 200
        self.headers = response_headers or {"tr_cont": "D"}

    def json(self):
        return self._json


def test_kis_requests_pin_host_and_tr_id_by_environment(monkeypatch) -> None:
    """The order path must hit the real per-environment host with the matching
    TR_ID -- pinned directly, not inferred from other passing tests."""
    calls = []

    def fake_request(method, url, *, headers, params=None, json=None, timeout=None):
        calls.append({"method": method, "url": url, "headers": headers})
        return _FakeResponse(url, headers, {"rt_cd": "0", "output": {"ODNO": "1", "KRX_FWDG_ORD_ORGNO": "b"}})

    monkeypatch.setattr(kis, "_access_token", lambda cfg: "tok")
    monkeypatch.setattr(kis.requests, "request", fake_request)

    paper_cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    kis.place_order(paper_cfg, symbol="005930", side="buy", quantity=1)

    assert len(calls) == 1
    assert calls[0]["url"].startswith("https://openapivts.koreainvestment.com:29443")
    assert calls[0]["headers"]["tr_id"] == kis._TR_ORDER_BUY["paper"]


def test_kis_live_readonly_config_never_reaches_the_paper_order_call(monkeypatch) -> None:
    """The structural guard must stop a live-readonly config before any
    request is built -- so it can never resolve to the live host/TR_ID here."""
    calls = []
    monkeypatch.setattr(kis.requests, "request", lambda *a, **k: calls.append(1))

    live_cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="live-readonly")
    result = kis.place_order(live_cfg, symbol="005930", side="buy", quantity=1)

    assert result["status"] == "error"
    assert result["error"] == kis._LIVE_ORDER_ERROR
    assert calls == []


# --------------------------------------------------------------------------- #
# Order validation
# --------------------------------------------------------------------------- #


def test_kis_place_order_validates_before_any_request() -> None:
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    missing_qty = kis.place_order(cfg, symbol="005930", side="buy")
    bad_side = kis.place_order(cfg, symbol="005930", side="hold", quantity=10)
    missing_limit_price = kis.place_order(cfg, symbol="005930", side="buy", quantity=10, order_type="limit")
    notional_rejected = kis.place_order(cfg, symbol="005930", side="buy", notional=100_000)
    assert missing_qty["status"] == "error"
    assert bad_side["status"] == "error"
    assert missing_limit_price["status"] == "error"
    assert notional_rejected["status"] == "error"
    assert "notional" in notional_rejected["error"]


def test_kis_place_order_rejects_fractional_quantity_and_price() -> None:
    """int() truncation must not silently turn 2.5 shares into an ok 2-share
    order, or drop the fraction of a limit price."""
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    fractional_qty = kis.place_order(cfg, symbol="005930", side="buy", quantity=2.5)
    fractional_price = kis.place_order(
        cfg, symbol="005930", side="buy", quantity=1, order_type="limit", limit_price=70500.5
    )
    assert fractional_qty["status"] == "error"
    assert fractional_price["status"] == "error"


def test_kis_cancel_order_rejects_fractional_sub_share_quantity() -> None:
    """0.5 must not silently truncate to 0 and flip into a full-quantity cancel."""
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    result = kis.cancel_order(cfg, "ORD1", order_branch="00001", quantity=0.5)
    assert result["status"] == "error"


def test_kis_cancel_order_looks_up_branch_when_omitted(monkeypatch) -> None:
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    monkeypatch.setattr(
        kis,
        "get_open_orders",
        lambda cfg, **k: {"open_orders": [{"order_id": "123", "order_branch": "00099"}], "executions": []},
    )
    captured = {}

    def fake_post(cfg, path, *, tr_id, body):
        captured.update(body)
        return {"rt_cd": "0"}

    monkeypatch.setattr(kis, "_post", fake_post)
    result = kis.cancel_order(cfg, "123")
    assert result["status"] == "ok"
    assert captured["KRX_FWDG_ORD_ORGNO"] == "00099"
    assert captured["EXCG_ID_DVSN_CD"] == kis._EXCHANGE_ID_KRX


def test_kis_cancel_order_errors_clearly_when_branch_cannot_be_found(monkeypatch) -> None:
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    monkeypatch.setattr(kis, "get_open_orders", lambda cfg, **k: {"open_orders": [], "executions": []})
    result = kis.cancel_order(cfg, "no-such-order")
    assert result["status"] == "error"
    assert "order_branch" in result["error"]


def test_kis_order_methods_refuse_live_config_before_anything_else() -> None:
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="live-readonly")
    placed = kis.place_order(cfg, symbol="005930", side="buy", quantity=1)
    cancelled = kis.cancel_order(cfg, "1", order_branch="b")
    assert placed == {"status": "error", "error": kis._LIVE_ORDER_ERROR}
    assert cancelled == {"status": "error", "error": kis._LIVE_ORDER_ERROR}


def test_kis_get_paginated_follows_tr_cont_until_the_final_page(monkeypatch) -> None:
    """A 'more data' tr_cont must fetch the next page and merge its rows;
    a larger account's positions must not be cut off after the first page."""
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    pages = [
        ({"output1": [{"n": 1}], "ctx_area_fk100": "fk1", "ctx_area_nk100": "nk1"}, {"tr_cont": "F"}),
        ({"output1": [{"n": 2}], "ctx_area_fk100": "fk2", "ctx_area_nk100": "nk2"}, {"tr_cont": "M"}),
        ({"output1": [{"n": 3}]}, {"tr_cont": "D"}),
    ]

    def fake_request(cfg, method, path, *, tr_id, params=None, body=None, tr_cont=""):
        return pages.pop(0)

    monkeypatch.setattr(kis, "_request", fake_request)
    merged = kis._get_paginated(cfg, "/some/path", tr_id="X", params={"CTX_AREA_FK100": "", "CTX_AREA_NK100": ""})
    assert [row["n"] for row in merged["output1"]] == [1, 2, 3]


def test_kis_get_historical_bars_limit_zero_returns_no_bars(monkeypatch) -> None:
    cfg = kis.KISConfig(app_key="k", app_secret="s", account_no="12345678", profile="paper")
    monkeypatch.setattr(
        kis,
        "_get",
        lambda *a, **k: {"output2": [{"stck_bsop_date": "20260101", "stck_clpr": "100"}]},
    )
    result = kis.get_historical_bars("005930", config=cfg, limit=0)
    assert result["bars"] == []


# --------------------------------------------------------------------------- #
# Redaction / service dispatch / classification
# --------------------------------------------------------------------------- #


def test_kis_redacts_app_secret() -> None:
    cfg = kis.KISConfig(app_key="APPKEY123456", app_secret="topsecret", account_no="12345678")
    pub = kis._public_config(cfg)
    assert "topsecret" not in str(pub)
    assert pub["app_key"].endswith("***")
    assert pub["app_secret"] == "***redacted***"


def test_kis_service_unconfigured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(kis, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("kis-paper-sdk")
    assert result["status"] == "error"
    assert result["connector"] == "kis"
    assert result["transport"] == "broker_sdk"


def test_kis_order_ops_classified_write() -> None:
    for name in ("place_order", "cancel_order"):
        assert KIS_TOOL_CLASS[name] is ToolClass.WRITE
    for name in ("get_positions", "get_account_snapshot"):
        assert KIS_TOOL_CLASS[name] is ToolClass.READ
