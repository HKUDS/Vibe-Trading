"""Compile strategy templates into Vibe-Trading backtest configurations."""

from __future__ import annotations

from typing import Any


class TemplateCompiler:
    """Compile template + params into backtest engine configuration."""

    def compile(self, template_key: str, params: dict[str, Any]) -> dict[str, Any]:
        """Compile a strategy template into backtest config.

        Args:
            template_key: e.g., "moving_average_cross"
            params: User-provided parameters for the template

        Returns:
            Vibe-Trading backtest engine configuration dict
        """
        compilers = {
            "moving_average_cross": self._compile_ma_cross,
            "grid_trading": self._compile_grid_trading,
            "rsi_mean_reversion": self._compile_rsi,
            "breakout_momentum": self._compile_breakout,
        }

        compiler = compilers.get(template_key)
        if compiler is None:
            raise ValueError(f"Unknown template: {template_key}")

        return compiler(params)

    def _compile_ma_cross(self, params: dict[str, Any]) -> dict[str, Any]:
        """Compile moving average crossover strategy."""
        return {
            "type": "moving_average_cross",
            "symbol": params["symbol"],
            "short_period": params["shortPeriod"],
            "long_period": params["longPeriod"],
            "position_size": params.get("positionSize", 1.0),
            "stop_loss": params.get("stopLoss"),
            "take_profit": params.get("takeProfit"),
        }

    def _compile_grid_trading(self, params: dict[str, Any]) -> dict[str, Any]:
        """Compile grid trading strategy."""
        return {
            "type": "grid_trading",
            "symbol": params["symbol"],
            "grid_count": params.get("gridCount", 10),
            "grid_range": params.get("gridRange", 0.1),
            "position_per_grid": params.get("positionPerGrid", 0.1),
        }

    def _compile_rsi(self, params: dict[str, Any]) -> dict[str, Any]:
        """Compile RSI mean reversion strategy."""
        return {
            "type": "rsi_mean_reversion",
            "symbol": params["symbol"],
            "rsi_period": params.get("rsiPeriod", 14),
            "oversold_threshold": params.get("oversoldThreshold", 30),
            "overbought_threshold": params.get("overboughtThreshold", 70),
            "position_size": params.get("positionSize", 1.0),
        }

    def _compile_breakout(self, params: dict[str, Any]) -> dict[str, Any]:
        """Compile breakout momentum strategy."""
        return {
            "type": "breakout_momentum",
            "symbol": params["symbol"],
            "lookback_period": params.get("lookbackPeriod", 20),
            "position_size": params.get("positionSize", 1.0),
            "stop_loss": params.get("stopLoss"),
        }
