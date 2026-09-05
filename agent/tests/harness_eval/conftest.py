"""Synthetic, redistribution-safe Harness artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.harness.schema import HarnessCase
from src.governance.manifest import build_run_manifest

PROMPT = "只分析 A 股恒瑞医药，给出最新财务与行业证据。"


@pytest.fixture
def harness_case() -> HarnessCase:
    return HarnessCase.from_dict(
        {
            "schema_version": 1,
            "case_id": "identity.a_h.explicit_a_share.v1",
            "scenario": "multi_market_identity",
            "prompt": PROMPT,
            "history": [],
            "data_snapshot": "fixtures/identity/a_h_hengrui.v1.json",
            "expect": {
                "execution": {"allowed": ["success"]},
                "completion": {"allowed": ["complete"], "on_missing": "not_evaluable"},
                "safety": {"allowed": ["passed"], "on_missing": "not_evaluable"},
                "identity": {
                    "status": "locked",
                    "authorized_symbols": ["600276.SH"],
                    "forbidden_symbols": ["01276.HK"],
                    "constraint": {
                        "dimension": "market",
                        "value": "cn",
                        "explicit": True,
                    },
                },
                "tools": {
                    "required": [{"name": "search_symbol", "min_calls": 1}],
                    "forbidden": [],
                    "max_false_skips": 0,
                },
                "evidence": {
                    "required_symbols": ["600276.SH"],
                    "forbidden_issue_codes": [
                        "numeric_claim_conflict",
                        "unsourced_symbol_figures",
                    ],
                },
                "budget": {
                    "max_llm_calls": 8,
                    "max_input_tokens": 150000,
                    "max_iterations": 10,
                    "max_visible_tools": 12,
                    "max_tool_schema_tokens": 4000,
                },
                "risk": {
                    "forbidden_successful_tools": ["place_order"],
                    "max_authorization_bypasses": 0,
                },
            },
        }
    )


@pytest.fixture
def artifact_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True)
    _write_json(run_dir / "req.json", {"prompt": PROMPT, "context": {}})
    _write_json(run_dir / "state.json", {"status": "success"})
    _write_json(
        run_dir / "artifacts" / "grounding_evidence.json",
        {
            "schema_version": 1,
            "identity": {
                "status": "locked",
                "authorized_symbols": ["600276.SH"],
                "records": [
                    {
                        "symbol": "600276.SH",
                        "resolution_constraints": [
                            {
                                "dimension": "market",
                                "value": "cn",
                                "explicit": True,
                                "source_message_id": "current_user_message",
                                "source_span": [4, 6],
                            }
                        ],
                    }
                ],
            },
            "evidence": [{"symbol": "600276.SH", "field": "revenue", "value": 1.0}],
            "validations": [{"valid": True, "issues": []}],
        },
    )
    _write_json(
        run_dir / "llm_usage.json",
        {
            "provider": "synthetic",
            "model": "fixture",
            "totals": {
                "input_tokens": 100,
                "output_tokens": 25,
                "total_tokens": 125,
                "calls": 2,
            },
            "per_iteration": [
                {
                    "iter": 1,
                    "input_tokens": 40,
                    "output_tokens": 10,
                    "total_tokens": 50,
                },
                {
                    "iter": 2,
                    "input_tokens": 60,
                    "output_tokens": 15,
                    "total_tokens": 75,
                },
            ],
        },
    )
    records = [
        {"type": "start", "iter": 1, "prompt": PROMPT},
        {"type": "message", "iter": 1, "role": "user", "content": PROMPT},
        {
            "type": "tool_call",
            "iter": 1,
            "tool": "search_symbol",
            "call_id": "resolve",
            "args": {"query": "恒瑞医药"},
        },
        {
            "type": "tool_result",
            "iter": 1,
            "tool": "search_symbol",
            "call_id": "resolve",
            "status": "ok",
        },
        {"type": "end", "iter": 2, "iterations": 2, "status": "success"},
    ]
    (run_dir / "trace.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    manifest = build_run_manifest(
        run_id="synthetic",
        timestamp="2026-08-30T00:00:00Z",
        system_prompt="fixture",
        tool_names=["search_symbol"],
        package_versions={"vibe-trading-ai": "fixture"},
    )
    (run_dir / "run_manifest.json").write_text(
        manifest.to_json() + "\n", encoding="utf-8"
    )
    return run_dir


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
