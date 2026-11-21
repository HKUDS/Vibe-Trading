"""Regression for the faster public Tencent HK endpoint."""

from datetime import datetime, timezone
from types import SimpleNamespace

from src.hk_data import service


def test_realtime_request_and_prefix(monkeypatch):
    values = [""] * 36
    for index, value in {
        2: "00700",
        3: "400.5",
        6: "1000",
        30: "2026/11/11 15:00:00",
        32: "-1.5",
    }.items():
        values[index] = value
    text = 'v_r_hk00700="' + "~".join(values) + '";'

    def get(url, **kwargs):
        assert url.endswith("q=r_hk00700")
        return SimpleNamespace(text=text, raise_for_status=lambda: None)

    monkeypatch.setattr(service, "throttled_get", get)
    quotes, errors = service._tencent(["00700.HK"], datetime.now(timezone.utc))
    assert not errors
    assert quotes[0]["endpoint"] == "r_hk"
    assert quotes[0]["volume"] == 1000
    assert quotes[0]["change_pct"] == -1.5
    assert quotes[0]["volume_unit"] is None
