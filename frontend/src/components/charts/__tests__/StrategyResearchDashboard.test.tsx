import { render, screen } from "@testing-library/react";
import type { RunData } from "@/lib/api";
import { StrategyResearchDashboard } from "../StrategyResearchDashboard";
import { echarts } from "@/lib/echarts";

// Regression test for: a portfolio-construction / risk-snapshot run (only
// risk_xray / rebalance_notes, no equity curve or trades) rendered the full
// backtest dashboard shell with every KPI and chart silently blank/dashed --
// indistinguishable from a broken page. It should instead point to the
// Studio tab, which is where that run's actual numbers render.

vi.mock("@/lib/echarts", () => ({
  echarts: { init: vi.fn() },
}));

function makeRun(overrides: Partial<RunData> = {}): RunData {
  return {
    status: "success",
    run_id: "run-riskxray",
    ...overrides,
  };
}

describe("StrategyResearchDashboard empty state", () => {
  beforeEach(() => {
    vi.mocked(echarts.init).mockImplementation((() => ({
      setOption: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
      group: "",
    })) as unknown as typeof echarts.init);
  });

  it("points to Studio instead of a blank KPI shell for a risk_xray-only run", () => {
    render(<StrategyResearchDashboard run={makeRun({ risk_xray: { concentration: { hhi: 0.018 } } })} />);

    expect(screen.getByText("This run has no backtest data to chart")).toBeInTheDocument();
    expect(screen.getByText(/Studio tab/)).toBeInTheDocument();
    expect(screen.queryByText("Sharpe")).not.toBeInTheDocument();
  });

  it("also applies for a rebalance_notes-only run", () => {
    render(<StrategyResearchDashboard run={makeRun({
      rebalance_notes: { summary: { target_change_count: 3, turnover_total: 0.3, turnover_mean: 0.1, turnover_max: 0.15 } },
    })} />);

    expect(screen.getByText("This run has no backtest data to chart")).toBeInTheDocument();
  });

  it("renders the normal dashboard when equity/trade data is present, even alongside risk_xray", () => {
    render(<StrategyResearchDashboard run={makeRun({
      risk_xray: { concentration: { hhi: 0.018 } },
      equity_curve: [
        { time: "2026-01-01", equity: 100, drawdown: 0 },
        { time: "2026-01-02", equity: 101, drawdown: 0 },
      ],
      metrics: {
        final_value: 1_010_000,
        total_return: 0.01,
        annual_return: 0.01,
        max_drawdown: -0.01,
        sharpe: 1.2,
        win_rate: 0.5,
        trade_count: 2,
      },
    })} />);

    expect(screen.queryByText("This run has no backtest data to chart")).not.toBeInTheDocument();
    expect(screen.getByText("Sharpe")).toBeInTheDocument();
  });

  it("falls back to trade_log when the artifact trade array is empty", () => {
    render(<StrategyResearchDashboard run={makeRun({
      risk_xray: { concentration: { hhi: 0.018 } },
      artifacts_trades_csv: [],
      trade_log: [{
        timestamp: "2026-01-02",
        code: "AAPL",
        side: "sell",
        price: "101",
        qty: "1",
        pnl: "1",
        reason: "exit signal",
      }],
    })} />);

    expect(screen.queryByText("This run has no backtest data to chart")).not.toBeInTheDocument();
    expect(screen.getByText("exit signal")).toBeInTheDocument();
  });
});
