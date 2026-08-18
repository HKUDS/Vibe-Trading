import { fireEvent, render, screen } from "@testing-library/react";
import { FactorResearchPanel } from "../FactorResearchPanel";
import type { FactorReportPayload, FactorResult } from "@/lib/api";

// No canvas in jsdom: stub the echarts instance contract so chart init is a
// no-op and only the DOM around the charts is asserted here.
vi.mock("@/lib/echarts", () => ({
  CHART_GROUP: "quant-charts",
  connectCharts: vi.fn(),
  echarts: {
    init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), group: "" })),
  },
}));

vi.mock("../CorrelationMatrix", () => ({
  CorrelationMatrix: ({ labels, matrix }: { labels: string[]; matrix: number[][] }) => (
    <div
      data-testid="factor-correlation-matrix"
      data-labels={labels.join(",")}
      data-size={String(matrix.length)}
    />
  ),
}));

function makeFactor(overrides: Partial<FactorResult> = {}): FactorResult {
  return {
    name: "momentum_20d",
    path: "artifacts/factor_momentum_20d",
    ic_series: [
      { date: "2024-01-02", ic: 0.031 },
      { date: "2024-01-03", ic: -0.018 },
      { date: "2024-01-04", ic: 0.042 },
    ],
    ic_stats: { ic_mean: 0.0521, ic_std: 0.0287, ir: 0.8734, ic_positive_ratio: 0.625, ic_count: 128 },
    group_equity: [
      { date: "2024-01-02", Group_1: 1.0, Group_2: 1.004, Group_3: 1.011 },
      { date: "2024-01-03", Group_1: 1.002, Group_2: 1.009, Group_3: 1.02 },
    ],
    n_groups: 3,
    long_short_spread: 0.021,
    group_final_equity: { Group_1: 1.002, Group_2: 1.009, Group_3: 1.02 },
    ...overrides,
  };
}

function makeReport(overrides: Partial<FactorReportPayload> = {}): FactorReportPayload {
  return {
    exists: true,
    factors: [makeFactor()],
    ic_correlation: null,
    ...overrides,
  };
}

describe("FactorResearchPanel", () => {
  it("shows the IC statistics cards for the selected factor", () => {
    render(<FactorResearchPanel report={makeReport()} />);

    expect(screen.getByText("IC Statistics")).toBeInTheDocument();
    expect(screen.getByText("0.0521")).toBeInTheDocument(); // ic_mean, 4 decimals
    expect(screen.getByText("0.8734")).toBeInTheDocument(); // ir
    expect(screen.getByText("62.50%")).toBeInTheDocument(); // ic_positive_ratio
    expect(screen.getByText("128")).toBeInTheDocument(); // ic_count
    expect(screen.getByText("+2.10%")).toBeInTheDocument(); // long_short_spread as signed percent
  });

  it("renders the factor selector only with multiple factors and switches the selection", () => {
    const { rerender } = render(<FactorResearchPanel report={makeReport()} />);
    expect(screen.queryByText("Select factor")).not.toBeInTheDocument();

    const second = makeFactor({
      name: "value_pe",
      ic_stats: { ic_mean: -0.0113, ic_std: 0.0301, ir: -0.3754, ic_positive_ratio: 0.44, ic_count: 96 },
      long_short_spread: -0.012,
    });
    rerender(<FactorResearchPanel report={makeReport({ factors: [makeFactor(), second] })} />);

    expect(screen.getByText("Select factor")).toBeInTheDocument();
    expect(screen.getByTestId("factor-selected")).toHaveTextContent("momentum_20d");

    fireEvent.click(screen.getByRole("button", { name: "value_pe" }));

    expect(screen.getByTestId("factor-selected")).toHaveTextContent("value_pe");
    expect(screen.getByText("-0.0113")).toBeInTheDocument();
    expect(screen.getByText("-1.20%")).toBeInTheDocument(); // negative spread keeps its sign
    expect(screen.queryByText("0.0521")).not.toBeInTheDocument();
  });

  it("renders the IC correlation heatmap only when the report provides it", () => {
    const twoFactors = [makeFactor(), makeFactor({ name: "value_pe" })];
    const overlapNote =
      "IC correlation is unavailable because the factor IC series do not overlap enough on common dates.";

    const { rerender } = render(<FactorResearchPanel report={makeReport()} />);
    expect(screen.queryByTestId("factor-correlation-matrix")).not.toBeInTheDocument();
    expect(screen.queryByText(overlapNote)).not.toBeInTheDocument();

    rerender(<FactorResearchPanel report={makeReport({ factors: twoFactors })} />);
    expect(screen.queryByTestId("factor-correlation-matrix")).not.toBeInTheDocument();
    expect(screen.getByText(overlapNote)).toBeInTheDocument();

    rerender(
      <FactorResearchPanel
        report={makeReport({
          factors: twoFactors,
          ic_correlation: {
            labels: ["momentum_20d", "value_pe"],
            matrix: [
              [1, 0.42],
              [0.42, 1],
            ],
          },
        })}
      />,
    );
    expect(screen.queryByText(overlapNote)).not.toBeInTheDocument();
    expect(screen.getByTestId("factor-correlation-matrix")).toHaveAttribute(
      "data-labels",
      "momentum_20d,value_pe",
    );
  });

  it("shows the empty state when the report has no factors", () => {
    render(<FactorResearchPanel report={{ exists: false, factors: [], ic_correlation: null }} />);
    expect(screen.getByText("No factor analysis results are available for this run.")).toBeInTheDocument();
  });
});

describe("FactorResearchPanel circular-import safety", () => {
  it("loads standalone via dynamic import without importing RunDetail first", async () => {
    // RunCardPanel/RunCardStat now live in components/run/RunCard, so this module
    // no longer imports pages/RunDetail (which imports this module back).
    const mod = await import("@/components/charts/FactorResearchPanel");
    expect(mod.FactorResearchPanel).toBeTypeOf("function");
  });
});
