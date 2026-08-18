import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { api } from "@/lib/api";
import type { AttributionResponse, RunData } from "@/lib/api";
import { AttributionTab } from "../AttributionTab";

vi.mock("@/lib/echarts", () => ({
  echarts: { init: vi.fn() },
  CHART_GROUP: "quant-charts",
  connectCharts: vi.fn(),
}));

import { echarts } from "@/lib/echarts";

function makeRun(): RunData {
  return {
    status: "success",
    run_id: "run-attr",
    metrics: {
      final_value: 1_100_000,
      total_return: 0.1,
      annual_return: 0.08,
      max_drawdown: -0.05,
      sharpe: 1.2,
      win_rate: 0.55,
      trade_count: 42,
      information_ratio: 0.8,
      tracking_error: 0.02,
    },
  };
}

const fullPayload: AttributionResponse = {
  exists: true,
  benchmark: { ticker: "SPY", mode: "explicit" },
  factor: {
    beta: 1.2,
    alpha_per_period: 0.0002,
    alpha_annualized: 0.05,
    alpha_t_stat: 2.1,
    r_squared: 0.85,
    n_obs: 120,
    rolling_window: 60,
    rolling: [
      { date: "2024-01-01", beta: 1.1, alpha_annualized: 0.04 },
      { date: "2024-01-02", beta: 1.2, alpha_annualized: 0.05 },
    ],
    cumulative: [
      { date: "2024-01-01", portfolio: 0.01, benchmark: 0.008, active: 0.002 },
      { date: "2024-01-02", portfolio: 0.02, benchmark: 0.015, active: 0.005 },
    ],
  },
  brinson: {
    mode: "asset_class",
    portfolio_return: 0.08,
    benchmark_return: 0.06,
    active_return: 0.02,
    allocation: 0.01,
    selection: 0.008,
    interaction: 0.002,
    sectors: [
      {
        sector: "Technology",
        portfolio_weight: 0.5,
        benchmark_weight: 0.4,
        portfolio_return: 0.1,
        benchmark_return: 0.08,
        allocation: 0.005,
        selection: 0.004,
        interaction: 0.001,
        total: 0.01,
      },
    ],
  },
  notes: [],
};

describe("AttributionTab", () => {
  beforeEach(() => {
    vi.mocked(echarts.init).mockImplementation((() => ({
      setOption: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
      group: "",
    })) as unknown as typeof echarts.init);
  });

  it("shows a loading state while the attribution payload is fetched", () => {
    vi.spyOn(api, "getRunAttribution").mockReturnValue(new Promise<AttributionResponse>(() => {}));

    render(<AttributionTab runId="run-attr" run={makeRun()} />);

    expect(screen.getByText("Loading attribution…")).toBeInTheDocument();
  });

  it("shows an error state when the request fails", async () => {
    vi.spyOn(api, "getRunAttribution").mockRejectedValue(new Error("boom"));

    render(<AttributionTab runId="run-attr" run={makeRun()} />);

    expect(await screen.findByText("Failed to load attribution.")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("shows the empty note when the response has no attribution", async () => {
    vi.spyOn(api, "getRunAttribution").mockResolvedValue({
      exists: false,
      benchmark: null,
      factor: null,
      brinson: null,
      notes: ["equity.csv missing"],
    });

    render(<AttributionTab runId="run-attr" run={makeRun()} />);

    expect(
      await screen.findByText("No attribution data is available for this run."),
    ).toBeInTheDocument();
  });

  it("renders the Brinson table and factor stat cards for a full payload", async () => {
    vi.spyOn(api, "getRunAttribution").mockResolvedValue(fullPayload);

    render(<AttributionTab runId="run-attr" run={makeRun()} />);

    expect(await screen.findByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("Brinson Attribution")).toBeInTheDocument();
    expect(screen.getByText("1.20")).toBeInTheDocument(); // beta
    expect(screen.getByText("+5.00%")).toBeInTheDocument(); // annualized alpha
  });

  it("shows the benchmark caption for an explicit benchmark", async () => {
    vi.spyOn(api, "getRunAttribution").mockResolvedValue(fullPayload);

    render(<AttributionTab runId="run-attr" run={makeRun()} />);

    expect(await screen.findByText(/Benchmark: SPY/)).toBeInTheDocument();
  });

  it("shows the factor empty note when only Brinson attribution exists", async () => {
    vi.spyOn(api, "getRunAttribution").mockResolvedValue({
      ...fullPayload,
      factor: null,
    });

    render(<AttributionTab runId="run-attr" run={makeRun()} />);

    expect(
      await screen.findByText("Factor attribution is not available for this run."),
    ).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
  });
});
