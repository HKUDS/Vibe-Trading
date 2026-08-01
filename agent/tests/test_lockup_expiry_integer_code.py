"""Test suite for LockupExpiryTool non-string symbol code handling."""

import json
import pytest
from src.tools.lockup_expiry_tool import LockupExpiryTool


def test_lockup_expiry_tool_integer_code_handling():
    """Verify LockupExpiryTool.execute handles integer stock codes without raising AttributeError on .strip()."""
    tool = LockupExpiryTool()
    res_str = tool.execute(code=600519)
    res = json.loads(res_str)
    assert res["ok"] is True
    assert res["data"]["code"] == "600519"
