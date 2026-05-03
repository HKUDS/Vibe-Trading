"""Tests for financial field inference."""

from __future__ import annotations

import pytest

from backtest.financials.ashare.field_inference import (
    infer_financial_fields,
    infer_financial_fields_from_prompt,
    infer_financial_fields_from_source,
)


class TestPromptInference:
    def test_matches_pure_chinese_financial_concepts(self) -> None:
        prompt = "做一个 A 股策略，使用资产总计、有形资产和净债务做排序。"

        assert infer_financial_fields_from_prompt(prompt) == (
            "total_assets",
            "tangible_asset",
            "netdebt",
        )

    def test_matches_chinese_field_descriptions(self) -> None:
        prompt = "我需要营业收入、总资产和经营活动产生的现金流量净额。"

        assert infer_financial_fields_from_prompt(prompt) == (
            "revenue",
            "total_assets",
            "n_cashflow_act",
        )


class TestSourceInference:
    def test_extracts_fields_from_common_string_literal_patterns(self) -> None:
        source = '''
class SignalEngine:
    def generate(self, data_map):
        result = {}
        required = ["grossprofit_margin", "ocfps"]
        selected = "n_cashflow_act"
        for code, df in data_map.items():
            score = df["grossprofit_margin"].fillna(0)
            score = score + df.get(selected, 0)
            result[code] = score.rank(pct=True)
        return result
'''

        assert infer_financial_fields_from_source(source) == (
            "grossprofit_margin",
            "ocfps",
            "n_cashflow_act",
        )

    def test_syntax_error_is_not_silenced(self) -> None:
        with pytest.raises(SyntaxError):
            infer_financial_fields_from_source("class SignalEngine(:\n    pass\n")


class TestCombinedInference:
    def test_combines_prompt_and_source_and_preserves_ambiguity(self) -> None:
        prompt = "策略需要营业收入和总资产。"
        source = '''
class SignalEngine:
    def generate(self, data_map):
        return {code: df["grossprofit_margin"] for code, df in data_map.items()}
'''

        result = infer_financial_fields(prompt=prompt, source=source)

        assert result.prompt_fields == ("revenue", "total_assets")
        assert result.source_fields == ("grossprofit_margin",)
        assert result.combined_fields == ("revenue", "total_assets", "grossprofit_margin")
        assert result.query_plan.requested_fields == {"fina_indicator": ("grossprofit_margin",)}
        assert result.query_plan.ambiguous_fields == {
            "revenue": ("income", "express"),
            "total_assets": ("balancesheet", "express"),
        }

    def test_preferred_tables_resolve_query_plan(self) -> None:
        result = infer_financial_fields(
            prompt="策略需要营业收入和总资产。",
            preferred_tables={
                "revenue": "income",
                "total_assets": "balancesheet",
            },
        )

        assert result.query_plan.requested_fields == {
            "income": ("revenue",),
            "balancesheet": ("total_assets",),
        }