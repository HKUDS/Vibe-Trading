"""Tests for runner-side financial statement gating."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from backtest.financials.ashare import get_ashare_financial_runtime
from backtest.financials.ashare.field_registry import get_financial_field_registry
from backtest.financials.contracts import FinancialCrossSectionCapability, MarketFinancialRuntime
from backtest.runner import (
    BacktestConfigSchema,
    FinancialsConfigSchema,
    UniverseConfigSchema,
    _build_financial_fetch_plan,
    _resolve_a_share_universe_codes,
    _build_financial_query_plan_from_config,
    _derive_cross_sectional_financial_periods,
    _extract_tushare_points_from_user_frame,
    _resolve_tushare_points,
    _validate_financials_request,
    main,
)


def _write_run_dir(tmp_path: Path, config: dict) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (run_dir / "code" / "signal_engine.py").write_text(
        "class SignalEngine:\n"
        "    def generate(self, data_map):\n"
        "        return {}\n",
        encoding="utf-8",
    )
    return run_dir


class TestFinancialConfigSchema:
    def test_accepts_valid_financials_block(self) -> None:
        cfg = BacktestConfigSchema(
            codes=["600519.SH"],
            start_date="2025-01-01",
            end_date="2025-06-01",
            source="tushare",
            financials=FinancialsConfigSchema(
                required=True,
                tables=["income"],
                fields=["revenue"],
            ),
        )

        assert cfg.financials is not None
        assert cfg.financials.tables == ["income"]
        assert cfg.financials.fields == ["revenue"]

    def test_rejects_unknown_financial_table(self) -> None:
        with pytest.raises(Exception, match="unsupported financial tables"):
            BacktestConfigSchema(
                codes=["600519.SH"],
                start_date="2025-01-01",
                end_date="2025-06-01",
                financials=FinancialsConfigSchema(required=True, tables=["made_up_table"]),
            )

    def test_rejects_unknown_financial_field(self) -> None:
        with pytest.raises(Exception, match="unknown financial fields"):
            BacktestConfigSchema(
                codes=["600519.SH"],
                start_date="2025-01-01",
                end_date="2025-06-01",
                financials=FinancialsConfigSchema(required=True, fields=["made_up_field"]),
            )

    def test_accepts_a_share_universe_without_codes(self) -> None:
        cfg = BacktestConfigSchema(
            start_date="2025-01-01",
            end_date="2025-06-01",
            universe=UniverseConfigSchema(market="a_share"),
        )

        assert cfg.codes == []
        assert cfg.universe is not None
        assert cfg.universe.market == "a_share"


class TestFinancialRunnerGate:
    def test_resolve_a_share_universe_codes(self, monkeypatch) -> None:
        monkeypatch.setenv("TUSHARE_TOKEN", "ts-token")
        fake_api = MagicMock()
        fake_api.stock_basic.return_value = pd.DataFrame(
            {"ts_code": ["600519.SH", "000001.SZ", "AAPL.US", None]}
        )
        monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(pro_api=lambda token: fake_api))

        codes = _resolve_a_share_universe_codes()

        assert codes == ["000001.SZ", "600519.SH"]

    def test_normalizes_auto_source_to_tushare(self, monkeypatch) -> None:
        monkeypatch.setenv("TUSHARE_TOKEN", "ts-token")
        source = _validate_financials_request(
            {
                "financials": {
                    "required": True,
                    "fields": ["grossprofit_margin"],
                }
            },
            "auto",
            ["600519.SH"],
        )

        assert source == "tushare"

    def test_rejects_non_a_share_request(self, monkeypatch) -> None:
        monkeypatch.setenv("TUSHARE_TOKEN", "ts-token")
        with pytest.raises(ValueError, match="only A-share strategies"):
            _validate_financials_request(
                {"financials": {"required": True, "fields": ["grossprofit_margin"]}},
                "tushare",
                ["AAPL.US"],
            )

    def test_rejects_missing_tushare_token(self, monkeypatch) -> None:
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        with pytest.raises(ValueError, match="TUSHARE_TOKEN"):
            _validate_financials_request(
                {"financials": {"required": True, "fields": ["grossprofit_margin"]}},
                "tushare",
                ["600519.SH"],
            )

    def test_rejects_non_tushare_source(self, monkeypatch) -> None:
        monkeypatch.setenv("TUSHARE_TOKEN", "ts-token")
        with pytest.raises(ValueError, match="strict Tushare mode"):
            _validate_financials_request(
                {"financials": {"required": True, "fields": ["grossprofit_margin"]}},
                "akshare",
                ["600519.SH"],
            )

    def test_rejects_non_daily_interval(self, monkeypatch) -> None:
        monkeypatch.setenv("TUSHARE_TOKEN", "ts-token")
        with pytest.raises(ValueError, match="interval='1D'"):
            _validate_financials_request(
                {
                    "interval": "1m",
                    "financials": {"required": True, "fields": ["grossprofit_margin"]},
                },
                "tushare",
                ["600519.SH"],
            )

    def test_build_query_plan_requires_explicit_fields(self) -> None:
        with pytest.raises(ValueError, match="explicit financials.fields"):
            _build_financial_query_plan_from_config(
                {"financials": {"required": True, "tables": ["income"]}}
            )

    def test_derives_cross_sectional_periods_with_quarter_lookback(self) -> None:
        periods = _derive_cross_sectional_financial_periods(
            "2025-05-01",
            "2025-05-07",
        )

        assert periods == ("20240630", "20240930", "20241231", "20250331")

    def test_resolve_tushare_points_queries_account_automatically(self, monkeypatch) -> None:
        monkeypatch.setenv("TUSHARE_TOKEN", "ts-token-points")
        fake_api = MagicMock()
        fake_api.user.return_value = pd.DataFrame(
            {
                "user_id": [1, 1],
                "到期时间": ["2027-04-14", "2027-04-13"],
                "到期积分": [2880.0, 2000.0],
            }
        )
        monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(pro_api=lambda token: fake_api))

        assert _resolve_tushare_points({}) == 4880
        fake_api.user.assert_called_once_with(token="ts-token-points")

    def test_extract_tushare_points_accepts_zero_total(self) -> None:
        user_frame = pd.DataFrame({"到期积分": [0.0]})

        assert _extract_tushare_points_from_user_frame(user_frame) == 0

    def test_build_fetch_plan_raises_when_account_points_query_fails(self, monkeypatch) -> None:
        monkeypatch.setenv("TUSHARE_TOKEN", "ts-token-fail")
        fake_api = MagicMock()
        fake_api.user.side_effect = RuntimeError("user endpoint unavailable")
        monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(pro_api=lambda token: fake_api))

        config = {
            "start_date": "2025-05-01",
            "end_date": "2025-05-07",
            "financials": {
                "required": True,
                "fields": ["grossprofit_margin"],
            },
            "universe": {
                "market": "a_share",
            },
            "_resolved_codes_from_universe": True,
        }
        query_plan = _build_financial_query_plan_from_config(config)

        with pytest.raises(ValueError, match=r"user\(token=\.\.\.\)") as exc_info:
            _build_financial_fetch_plan(config, query_plan)

        message = str(exc_info.value)
        assert "RuntimeError: user endpoint unavailable" in message

    def test_build_fetch_plan_rejects_unsupported_cross_section_tables(self, monkeypatch) -> None:
        config = {
            "start_date": "2025-05-01",
            "end_date": "2025-05-07",
            "financials": {
                "required": True,
                "fields": ["grossprofit_margin"],
            },
            "universe": {
                "market": "a_share",
            },
            "_resolved_codes_from_universe": True,
        }
        query_plan = _build_financial_query_plan_from_config(config)
        real_runtime = get_ashare_financial_runtime()

        class _UnsupportedCrossSectionRegistry:
            @property
            def tables(self):
                return {}

            @property
            def field_to_tables(self):
                return {}

            def get_table(self, table_name: str):
                raise AssertionError("get_table should not be called in this test")

            def has_field(self, field_name: str) -> bool:
                return False

            def get_field_tables(self, field_name: str):
                return ()

            def assess_cross_sectional_query(self, query_plan):
                return FinancialCrossSectionCapability(
                    supported_tables=(),
                    unsupported_tables=("fina_indicator",),
                    required_points_by_table={},
                    required_points=0,
                )

            def build_query_plan(self, fields, *, preferred_tables=None, include_key_columns=True, strict=True):
                raise AssertionError("build_query_plan should not be called in this test")

        runtime = MarketFinancialRuntime(
            market="a_share",
            registry=_UnsupportedCrossSectionRegistry(),
            infer_fields_from_prompt=real_runtime.infer_fields_from_prompt,
            infer_fields_from_source=real_runtime.infer_fields_from_source,
            infer_fields_from_file=real_runtime.infer_fields_from_file,
            infer_fields=real_runtime.infer_fields,
            loader_factory=real_runtime.loader_factory,
            assemble_pit_frame=real_runtime.assemble_pit_frame,
            enrich_data_map=real_runtime.enrich_data_map,
        )
        monkeypatch.setattr("backtest.runner._get_ashare_financial_runtime", lambda: runtime)

        with pytest.raises(ValueError, match="unsupported tables=fina_indicator") as exc_info:
            _build_financial_fetch_plan(config, query_plan)

        message = str(exc_info.value)
        assert "requested tables=fina_indicator" in message
        assert "supported tables=<none>" in message

    def test_build_fetch_plan_downgrades_to_per_code_when_only_ordinary_points_available(self, monkeypatch, caplog) -> None:
        monkeypatch.setenv("TUSHARE_TOKEN", "ts-token-insufficient")
        fake_api = MagicMock()
        fake_api.user.return_value = pd.DataFrame(
            {
                "user_id": [1],
                "到期时间": ["2027-04-14"],
                "到期积分": [2880.0],
            }
        )
        monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(pro_api=lambda token: fake_api))

        config = {
            "start_date": "2025-05-01",
            "end_date": "2025-05-07",
            "financials": {
                "required": True,
                "fields": ["grossprofit_margin"],
            },
            "universe": {
                "market": "a_share",
            },
            "_resolved_codes_from_universe": True,
        }
        query_plan = _build_financial_query_plan_from_config(config)

        plan = _build_financial_fetch_plan(config, query_plan)

        assert plan.mode == "per_code"
        assert "falling back to slower per-code Tushare fetch" in caplog.text
        assert "current account points=2880" in caplog.text

    def test_build_fetch_plan_rejects_points_below_ordinary_minimum(self, monkeypatch) -> None:
        monkeypatch.setenv("TUSHARE_TOKEN", "ts-token-too-low")
        fake_api = MagicMock()
        fake_api.user.return_value = pd.DataFrame(
            {
                "user_id": [1],
                "到期时间": ["2027-04-14"],
                "到期积分": [0.0],
            }
        )
        monkeypatch.setitem(sys.modules, "tushare", SimpleNamespace(pro_api=lambda token: fake_api))

        config = {
            "start_date": "2025-05-01",
            "end_date": "2025-05-07",
            "financials": {
                "required": True,
                "fields": ["grossprofit_margin"],
            },
            "universe": {
                "market": "a_share",
            },
            "_resolved_codes_from_universe": True,
        }
        query_plan = _build_financial_query_plan_from_config(config)

        with pytest.raises(ValueError, match="at least 2000 Tushare points") as exc_info:
            _build_financial_fetch_plan(config, query_plan)

        message = str(exc_info.value)
        assert "requested tables=fina_indicator" in message
        assert "current account points=0" in message
        assert "ordinary required points=2000" in message

    def test_main_enriches_data_map_before_engine_run(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("TUSHARE_TOKEN", "ts-token-main")
        run_dir = _write_run_dir(
            tmp_path,
            {
                "start_date": "2025-05-01",
                "end_date": "2025-05-07",
                "source": "tushare",
                "universe": {
                    "market": "a_share",
                },
                "financials": {
                    "required": True,
                    "fields": ["grossprofit_margin"],
                },
            },
        )

        trade_index = pd.DatetimeIndex(["2025-05-02", "2025-05-05", "2025-05-06"], name="trade_date")
        price_frame = pd.DataFrame(
            {"open": [1.0, 1.0, 1.0], "high": [1.0, 1.0, 1.0], "low": [1.0, 1.0, 1.0], "close": [1.0, 1.0, 1.0], "volume": [1.0, 1.0, 1.0]},
            index=trade_index,
        )

        class _FakePriceLoader:
            name = "tushare"
            markets = {"a_share"}
            requires_auth = True

            def is_available(self) -> bool:
                return True

            def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
                return {"600519.SH": price_frame.copy()}

        fake_raw_loader = MagicMock()

        def _fetch_for_period(query_plan, *, period, table_params=None):
            if period == "20250331":
                return {
                    "fina_indicator": pd.DataFrame(
                        {
                            "ts_code": ["600519.SH"],
                            "ann_date": ["20250502"],
                            "end_date": ["20250331"],
                            "grossprofit_margin": [91.5],
                        }
                    )
                }
            return {
                table_name: pd.DataFrame(columns=list(fields))
                for table_name, fields in query_plan.query_fields.items()
            }

        fake_raw_loader.fetch_for_period.side_effect = _fetch_for_period

        class _FakeSignalEngine:
            def generate(self, data_map):
                return {code: df["close"] * 0 for code, df in data_map.items()}

        fake_engine = SimpleNamespace(observed=None)

        def _fake_run_backtest(config, loader, signal_engine, run_dir, bars_per_year=252):
            fake_engine.observed = loader.fetch(
                config["codes"],
                config["start_date"],
                config["end_date"],
                interval=config.get("interval", "1D"),
                fields=config.get("extra_fields"),
            )
            return {}

        monkeypatch.setattr(
            "backtest.runner._get_loader",
            lambda source: _FakePriceLoader,
        )
        fake_universe_api = MagicMock()
        fake_universe_api.stock_basic.return_value = pd.DataFrame({"ts_code": ["600519.SH"]})
        fake_universe_api.user.return_value = pd.DataFrame(
            {
                "user_id": [1, 1],
                "到期时间": ["2027-04-14", "2027-04-13"],
                "到期积分": [2880.0, 3000.0],
            }
        )
        monkeypatch.setitem(
            sys.modules,
            "tushare",
            SimpleNamespace(pro_api=lambda token: fake_universe_api),
        )
        real_runtime = get_ashare_financial_runtime()
        runtime = MarketFinancialRuntime(
            market="a_share",
            registry=get_financial_field_registry(),
            infer_fields_from_prompt=real_runtime.infer_fields_from_prompt,
            infer_fields_from_source=real_runtime.infer_fields_from_source,
            infer_fields_from_file=real_runtime.infer_fields_from_file,
            infer_fields=real_runtime.infer_fields,
            loader_factory=lambda: fake_raw_loader,
            assemble_pit_frame=real_runtime.assemble_pit_frame,
            enrich_data_map=real_runtime.enrich_data_map,
        )
        monkeypatch.setattr("backtest.runner._get_ashare_financial_runtime", lambda: runtime)
        monkeypatch.setattr(
            "backtest.runner._load_module_from_file",
            lambda path, module_name: SimpleNamespace(SignalEngine=_FakeSignalEngine),
        )
        monkeypatch.setattr(
            "backtest.runner._create_market_engine",
            lambda source, config, codes: SimpleNamespace(run_backtest=_fake_run_backtest),
        )

        main(run_dir)

        observed = fake_engine.observed["600519.SH"]
        fake_raw_loader.fetch_for_codes.assert_not_called()
        assert [
            call.kwargs["period"] for call in fake_raw_loader.fetch_for_period.call_args_list
        ] == ["20240630", "20240930", "20241231", "20250331"]
        assert pd.isna(observed.loc[pd.Timestamp("2025-05-02"), "grossprofit_margin"])
        assert observed.loc[pd.Timestamp("2025-05-05"), "grossprofit_margin"] == 91.5