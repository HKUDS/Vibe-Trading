"""Validate the pt-v2.0 request examples published in the paper-trade README.

The README shows two caller-owned portfolio payloads: explicit orders with a
pre-fill conversion and a closed market, and target weights with a rebalance
band. Both are extracted by their HTML markers and validated against the
packaged pt-v2.0 request schema and the published ``paper_trade_step`` oneOf.
This keeps the public examples machine-checkable without executing a step or
touching market data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade.portfolio import wire
from src.tools.paper_trade.portfolio.schema import load_portfolio_contract_schema
from src.tools.paper_trade.tool import PaperTradeStepTool

README_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "tools"
    / "paper_trade"
    / "README.md"
)
_EXAMPLE_RE = re.compile(
    r"<!-- pt-v2\.0-request: ([a-z0-9-]+) -->\s*```json\n(.*?)\n```",
    re.DOTALL,
)


def _examples() -> dict[str, dict]:
    text = README_PATH.read_text(encoding="utf-8")
    examples = {
        name: json.loads(block)
        for name, block in _EXAMPLE_RE.findall(text)
    }
    assert set(examples) == {"explicit-orders", "target-weights"}
    return examples


def _format_errors(name: str, errors: list) -> str:
    return "\n".join(
        f"{name}: {'/'.join(str(part) for part in error.path)}: {error.message}"
        for error in errors
    )


@pytest.mark.parametrize("name", ["explicit-orders", "target-weights"])
def test_readme_example_validates_against_the_packaged_request_schema(name: str) -> None:
    schema = load_portfolio_contract_schema("request")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    errors = sorted(
        validator.iter_errors(_examples()[name]),
        key=lambda error: list(error.path),
    )

    assert not errors, _format_errors(name, errors)


@pytest.mark.parametrize("name", ["explicit-orders", "target-weights"])
def test_readme_example_matches_one_published_tool_branch(name: str) -> None:
    validator = Draft202012Validator(
        PaperTradeStepTool.parameters,
        format_checker=FormatChecker(),
    )

    errors = sorted(
        validator.iter_errors(_examples()[name]),
        key=lambda error: list(error.path),
    )

    assert not errors, _format_errors(name, errors)


def test_readme_examples_choose_opposite_order_plan_branches() -> None:
    examples = _examples()

    assert "orders" in examples["explicit-orders"]
    assert "target_weights" not in examples["explicit-orders"]
    assert "target_weights" in examples["target-weights"]
    assert "orders" not in examples["target-weights"]


def test_error_detail_input_hash_matches_the_documented_wire_contract() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    payload = wire.build_error_payload(
        {"account_id": "portfolio-cross-market-01"},
        code="INVALID_REQUEST",
        reason="required_bucket_closed",
        path="sessions.hk.status",
        detail="required_bucket_closed",
        bucket_id="hk",
    )

    assert "; input_sha256=<64 lowercase hex>" in readme
    assert "not a top-level field" in readme
    assert payload["error"]["detail"].startswith("required_bucket_closed; input_sha256=")
    assert re.fullmatch(
        r"required_bucket_closed; input_sha256=[0-9a-f]{64}",
        payload["error"]["detail"],
    )
    assert "input_sha256" not in payload
    assert "hashes" not in payload


def test_required_list_publishes_every_schema_required_field() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    required = re.search(r"Required: (.*?)\n\n", readme, re.DOTALL)
    assert required is not None
    named = set(re.findall(r"`([a-z_]+)`", required.group(1)))
    schema = load_portfolio_contract_schema("request")

    assert set(schema["required"]) <= named
    assert {"interval", "fill_model"} <= named


def test_docs_state_the_actual_transport_boundary() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    for text in (readme, PaperTradeStepTool.description):
        assert "never a transport error" not in text
        assert "not a transport error" not in text
        assert "INTERNAL" in text
        assert "transport error" in text


def test_empty_detail_falls_back_to_reason_before_the_hash_suffix() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    payload = wire.build_error_payload(
        {"account_id": "portfolio-cross-market-01"},
        code="INVALID_REQUEST",
        reason="required_bucket_closed",
        path="sessions.hk.status",
    )

    assert "(just the marker when the message is empty)" not in readme
    assert "falls back to the error reason" in " ".join(readme.split())
    assert re.fullmatch(
        r"required_bucket_closed; input_sha256=[0-9a-f]{64}",
        payload["error"]["detail"],
    )


def test_mcp_module_docstring_publishes_the_live_tool_count() -> None:
    mcp_server = (Path(__file__).resolve().parents[1] / "mcp_server.py").read_text(
        encoding="utf-8"
    )

    assert "Surfaces 83 tools" in mcp_server
