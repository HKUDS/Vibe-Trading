"""The Agent-facing ``paper_trade_step`` schema is one ``oneOf``.

The tool publishes two structurally disjoint request branches:

* ``legacy`` — the pt-v1.1/v1.2/v1.3 single-market envelope, whose required
  arguments stay exactly ``account_id/market/account_state/from_date/to_date``
  and whose optional ``mode`` is the constant ``single``;
* ``portfolio`` — the packaged pt-v2.0 cross-market request, inlined with local
  ``$defs`` so the published schema is self-contained.

The tests drive a real Draft 2020-12 validator, assert that each valid payload
matches exactly one branch, and pin the failure cases the discriminator must
keep rejecting (missing legacy arguments, missing portfolio arguments and a
hybrid payload spanning both surfaces).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade.portfolio.schema import load_portfolio_contract_schema
from src.tools.paper_trade.tool import PaperTradeStepTool
from tests.paper_trade_portfolio_fixture import valid_portfolio_payload

_LEGACY_REQUIRED = [
    "account_id",
    "market",
    "account_state",
    "from_date",
    "to_date",
]
_LEGACY_ONLY_FIELDS = {"market", "account_state", "from_date", "to_date"}
_UNSET = object()


def _parameters() -> dict[str, Any]:
    return PaperTradeStepTool.parameters


def _branches() -> dict[str, dict[str, Any]]:
    branches = _parameters()["oneOf"]
    return {
        "legacy": next(
            branch
            for branch in branches
            if branch["properties"]["mode"].get("const") == "single"
        ),
        "portfolio": next(
            branch
            for branch in branches
            if branch["properties"]["mode"].get("const") == "portfolio"
        ),
    }


def _branch_errors(branch: dict[str, Any], payload: Any) -> list[Any]:
    # Branch refs are rooted at the published document, so validate each branch
    # with the published root $defs in scope.
    published = dict(_parameters())
    scoped = {
        "$schema": published.get(
            "$schema", "https://json-schema.org/draft/2020-12/schema"
        ),
        "type": "object",
        "$defs": published.get("$defs", {}),
        **branch,
    }
    return list(
        Draft202012Validator(scoped, format_checker=FormatChecker()).iter_errors(
            payload
        )
    )


def _matching_modes(payload: Any) -> list[str]:
    return [
        mode
        for mode, branch in _branches().items()
        if not _branch_errors(branch, payload)
    ]


def _errors(payload: Any) -> list[Any]:
    return list(
        Draft202012Validator(
            _parameters(), format_checker=FormatChecker()
        ).iter_errors(payload)
    )


def _legacy_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "account_id": "legacy-agent-account",
        "market": "cn_a",
        "account_state": {"cash": 100000.0, "positions": []},
        "from_date": "2026-10-20",
        "to_date": "2026-10-20",
        "orders": [],
    }
    payload.update(overrides)
    return payload


def _iter_refs(node: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                refs.append(value)
            else:
                refs.extend(_iter_refs(value))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_iter_refs(item))
    return refs


def _contains_key(node: Any, key: str) -> bool:
    if isinstance(node, dict):
        return key in node or any(_contains_key(value, key) for value in node.values())
    if isinstance(node, list):
        return any(_contains_key(item, key) for item in node)
    return False


def _resolve_pointer(document: Any, ref: str) -> Any:
    node = document
    for token in ref.removeprefix("#/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        node = node[token] if isinstance(node, dict) else node[int(token)]
    return node


# ── published shape ──


def test_published_schema_is_a_valid_object_one_of() -> None:
    parameters = _parameters()

    assert parameters["type"] == "object"
    assert isinstance(parameters["oneOf"], list)
    assert len(parameters["oneOf"]) == 2
    assert "anyOf" not in parameters
    assert not _contains_key(parameters, "anyOf")
    Draft202012Validator.check_schema(parameters)


def test_published_schema_is_self_contained() -> None:
    refs = _iter_refs(_parameters())

    assert refs, "the portfolio branch must use local $defs references"
    assert all(ref.startswith("#/") for ref in refs), refs
    for ref in refs:
        assert _resolve_pointer(_parameters(), ref) is not None


def test_mode_constant_is_the_branch_discriminator() -> None:
    legacy = _branches()["legacy"]
    portfolio = _branches()["portfolio"]

    assert legacy["properties"]["mode"]["const"] == "single"
    assert "mode" not in legacy["required"]
    assert portfolio["properties"]["mode"]["const"] == "portfolio"
    assert "mode" in portfolio["required"]


def test_legacy_branch_retains_required_arguments() -> None:
    legacy = _branches()["legacy"]

    assert legacy["type"] == "object"
    assert legacy["required"] == _LEGACY_REQUIRED
    assert set(legacy["properties"]["market"]["enum"]) == {"cn_a", "hk", "us"}
    assert legacy["properties"]["interval"]["enum"] == ["1d", "5m"]
    assert legacy["properties"]["fill_model"]["enum"] == ["all_or_none", "volume_share"]
    assert "additionalProperties" not in legacy


def test_portfolio_branch_uses_the_packaged_v2_request_schema() -> None:
    packaged = load_portfolio_contract_schema("request")
    published = _branches()["portfolio"]

    expected = {
        key: value
        for key, value in packaged.items()
        if key not in {"$id", "$schema", "$defs"}
    }
    assert published == expected
    assert _parameters()["$defs"] == packaged["$defs"]


def test_portfolio_branch_does_not_require_legacy_arguments() -> None:
    legacy = _branches()["legacy"]
    portfolio = _branches()["portfolio"]

    assert set(legacy["required"]) == set(_LEGACY_REQUIRED)
    assert _LEGACY_ONLY_FIELDS.isdisjoint(portfolio["required"])
    for field in _LEGACY_ONLY_FIELDS:
        assert field not in portfolio["properties"]


def test_to_openai_schema_preserves_the_published_parameters() -> None:
    tool = PaperTradeStepTool()
    schema = tool.to_openai_schema()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "paper_trade_step"
    assert schema["function"]["description"] == PaperTradeStepTool.description
    assert schema["function"]["parameters"] is PaperTradeStepTool.parameters
    json.dumps(schema)


# ── happy: each branch validates exactly once ──


@pytest.mark.parametrize("mode", [_UNSET, "single"])
def test_legacy_payload_validates_exactly_once_against_the_legacy_branch(
    mode: object,
) -> None:
    payload = _legacy_payload()
    if mode is not _UNSET:
        payload["mode"] = mode

    assert _errors(payload) == []
    assert _matching_modes(payload) == ["legacy"]


def test_portfolio_payload_validates_exactly_once_against_the_v2_branch() -> None:
    payload = valid_portfolio_payload()

    assert _errors(payload) == []
    assert _matching_modes(payload) == ["portfolio"]


# ── failure: missing required arguments ──


@pytest.mark.parametrize("missing", ["market", "account_state"])
def test_legacy_payload_missing_a_required_argument_is_rejected(missing: str) -> None:
    payload = _legacy_payload()
    del payload[missing]

    assert _errors(payload) != []
    assert _matching_modes(payload) == []


@pytest.mark.parametrize("missing", ["base_currency", "portfolio_state"])
def test_portfolio_payload_missing_a_required_argument_is_rejected(
    missing: str,
) -> None:
    payload = valid_portfolio_payload()
    del payload[missing]

    assert _errors(payload) != []
    assert _matching_modes(payload) == []


def test_payload_spanning_both_branches_is_rejected() -> None:
    # A portfolio envelope carrying the legacy-only required arguments: the
    # portfolio branch rejects the undeclared keys while the legacy branch
    # rejects the portfolio discriminator, so oneOf matches zero branches.
    payload = valid_portfolio_payload()
    payload.update(
        {
            "market": "cn_a",
            "account_state": {"cash": 100000.0, "positions": []},
            "from_date": "2026-11-13",
            "to_date": "2026-11-13",
        }
    )

    assert _errors(payload) != []
    assert _matching_modes(payload) == []


def test_legacy_payload_with_portfolio_mode_is_rejected() -> None:
    payload = _legacy_payload(mode="portfolio")

    assert _errors(payload) != []
    assert _matching_modes(payload) == []
