import { act, fireEvent, render, screen } from "@testing-library/react";
import { api } from "@/lib/api";
import type { OptionsLabParams, OptionsPayoffResponse } from "@/lib/options";
import { clearAnalysisState } from "@/hooks/useAnalysisState";
import { OptionsLab } from "../OptionsLab";
vi.mock("@/lib/api", () => ({ api: { analyzeOptionsPayoff: vi.fn() } }));
vi.mock("@/components/options/StrategyBuilder", () => ({ StrategyBuilder: ({ params, onParamsChange }: { params: OptionsLabParams; onParamsChange: (p: OptionsLabParams) => void }) => <button onClick={() => onParamsChange({ ...params, entry_spot: params.entry_spot + 10 })}>Edit spot</button> }));
vi.mock("@/components/options/OptionsChainTable", () => ({ OptionsChainTable: () => <div>chain loaded</div> }));
vi.mock("@/components/options/GreeksCards", () => ({ GreeksCards: () => null }));
vi.mock("@/components/charts/OptionsScenarioMatrix", () => ({ OptionsScenarioMatrix: () => null }));
vi.mock("@/components/charts/OptionsPayoffChart", () => ({ OptionsPayoffChart: ({ entrySpot, curve }: { entrySpot: number; curve: { pnl: number[] } }) => <div data-testid="payoff">{entrySpot}:{curve.pnl.join(",")}</div> }));
const output: OptionsPayoffResponse = { status: "ok", inputs: {}, summary: { net_premium: 10, entry_commission: 0, entry_cost: 10, entry_side: "debit", breakevens: [110], breakeven_intervals: [], max_profit: null, max_loss: -10, profit_unbounded: true, loss_unbounded: false }, greeks: { delta: 0, gamma: 0, theta: 0, vega: 0, rho: 0 }, expiry_curve: { spot: [100], pnl: [7] }, scenario_grid: { iv_values: [], spot: [], pnl: [] }, limitations: [] };
beforeEach(() => { clearAnalysisState("options"); vi.clearAllMocks(); vi.useFakeTimers(); });
afterEach(() => vi.useRealTimers());
async function tick() { await act(async () => { await vi.advanceTimersByTimeAsync(260); }); }
it("aborts the previous request immediately on edit, even before the debounce starts", async () => {
  let resolve!: (r: OptionsPayoffResponse) => void;
  vi.mocked(api.analyzeOptionsPayoff).mockReturnValueOnce(new Promise((r) => { resolve = r; }));
  vi.mocked(api.analyzeOptionsPayoff).mockResolvedValueOnce(output);
  render(<OptionsLab />); await tick();
  const signal = vi.mocked(api.analyzeOptionsPayoff).mock.calls[0][1] as AbortSignal;
  fireEvent.click(screen.getByText("Edit spot")); expect(signal.aborted).toBe(true);
  await act(async () => resolve({ ...output, expiry_curve: { spot: [100], pnl: [999] } }));
  expect(screen.getByTestId("payoff")).not.toHaveTextContent("999");
  await tick(); expect(screen.getByTestId("payoff")).toHaveTextContent("110:7");
});
it("keeps old chart parameters consistent and restores completed results without refetching", async () => {
  vi.mocked(api.analyzeOptionsPayoff).mockResolvedValue(output);
  const page = render(<OptionsLab />); await tick();
  fireEvent.click(screen.getByText("Edit spot"));
  expect(screen.getByTestId("payoff")).toHaveTextContent("100:7");
  expect(screen.getByText("Showing the previous parameters’ result")).toBeInTheDocument();
  await tick(); page.unmount(); render(<OptionsLab />); await tick();
  expect(screen.getByTestId("payoff")).toHaveTextContent("110:7");
  expect(api.analyzeOptionsPayoff).toHaveBeenCalledTimes(2);
  expect(screen.queryByText("chain loaded")).not.toBeInTheDocument();
});

it("sends saved legs with the current strategy and displays server comparisons", async () => {
  vi.mocked(api.analyzeOptionsPayoff).mockResolvedValue({ ...output, comparisons: [{
    left_label: "Strategy 1", right_label: "Current strategy", status: "ok",
    metrics: { max_profit_return: { left_decimal: .21, right_decimal: .18, relation: "higher", difference_percentage_points: 3 } },
  }] });
  render(<OptionsLab />); await tick();
  fireEvent.click(screen.getByText("Save legs for comparison")); await tick();
  const sent = vi.mocked(api.analyzeOptionsPayoff).mock.lastCall![0];
  expect(sent.alternatives).toEqual([{ label: "Strategy 1", legs: sent.legs }]);
  expect(screen.getByText("Higher · 3.00")).toBeInTheDocument();
  fireEvent.click(screen.getByText("Edit spot")); await tick();
  const updated = vi.mocked(api.analyzeOptionsPayoff).mock.lastCall![0];
  expect(updated.entry_spot).toBe(110);
  expect(updated.alternatives).toEqual(sent.alternatives);
});
