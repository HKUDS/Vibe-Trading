"""Test suite for LockupExpiryTool non-string symbol code handling."""

import json
import pytest
from src.tools.lockup_expiry_tool import LockupExpiryTool


def test_lockup_expiry_tool_integer_code_handling(monkeypatch: pytest.MonkeyPatch):
    """Verify LockupExpiryTool.execute handles integer stock codes without raising AttributeError on .strip()."""
    canned = {
        "result": {
            "data": [
                {
                    "SECURITY_CODE": "600519",
                    "SECURITY_NAME_ABBR": "MT",
                    "FREE_DATE": "2026-01-02",
                    "FREE_SHARES_TYPE": "1",
                    "FREE_SHARES": "100",
                    "ABLE_FREE_SHARES": "80",
                    "LIFT_MARKET_CAP": "1000",
                }
            ]
        }
    }
    monkeypatch.setattr(
        "src.tools.lockup_expiry_tool.eastmoney_client.get_json",
        lambda *args, **kwargs: canned,
    )
    tool = LockupExpiryTool()
    res_str = tool.execute(code=600519)
    res = json.loads(res_str)
    assert res["ok"] is True
    assert res["data"]["code"] == "600519"
