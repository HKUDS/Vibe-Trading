import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { api } from "@/lib/api";
import type { OptionsPayoffRequest, OptionsStrategyCompareRequest, OptionsStrategyCompareResponse } from "@/lib/options";
import { StrategyScenarioComparison } from "../StrategyScenarioComparison";

vi.mock("@/lib/api", () => ({ api: { compareOptionsStrategies: vi.fn() } }));
vi.mock("@/components/charts/OptionsScenarioMatrix", () => ({
  OptionsScenarioMatrix: ({ grid }: { grid: unknown }) => <pre>{JSON.stringify(grid)}</pre>,
}));

const legs = [{ option_type: "call" as const, strike: 100, qty: 1, premium: 5 }];
const request: OptionsPayoffRequest = {
  label: "Current strategy",
  legs,
  alternatives: [
    { label: "Strategy 1", legs: [{ ...legs[0], strike: 105 }] },
    { label: "Strategy 2", legs: [{ ...legs[0], strike: 110 }] },
  ],
  entry_spot: 100,
  expiry_days: 30,
  volatility: 0.3,
  spot_min: 80,
  spot_max: 120,
  spot_points: 21,
};

function output(body: OptionsStrategyCompareRequest): OptionsStrategyCompareResponse {
  const names = body.strategies.map((strategy) => strategy.name);
  const baselineName = names[body.baseline_index ?? 0];
  const targetName = names.find((name) => name !== baselineName)!;
  return {
    status: "ok",
    comparison: { baseline_index: body.baseline_index ?? 0, baseline_name: baselineName },
    strategies: [],
    expiry_curve: {
      spot: [100, 110],
      pnl: Object.fromEntries(names.map((name, index) => [name, [index * 10, index * 10 + 1]])),
      delta_to_baseline: { [targetName]: [5, 6] },
    },
    scenario_grid: {
      iv_values: [0.3],
      spot: [100, 110],
      pnl: Object.fromEntries(names.map((name, index) => [name, [[index * 10, index * 10 + 1]]])),
      delta_to_baseline: { [targetName]: [[5, 6]] },
    },
    limitations: [],
  } as OptionsStrategyCompareResponse;
}

function openComparison() {
  fireEvent.click(screen.getByRole("button", { name: /spot/i }));
}

beforeEach(() => vi.clearAllMocks());

it("maps a reversed pair to its original order and baseline without truncating strategies", async () => {
  vi.mocked(api.compareOptionsStrategies).mockImplementation(async (body) => output(body));
  const many = {
    ...request,
    alternatives: Array.from({ length: 5 }, (_, index) => ({ label: `Strategy ${index + 1}`, legs })),
  };
  render(<StrategyScenarioComparison request={many} />);
  expect(api.compareOptionsStrategies).not.toHaveBeenCalled();
  openComparison();
  await waitFor(() => expect(api.compareOptionsStrategies).toHaveBeenCalledTimes(1));

  const baseline = screen.getByLabelText("Base");
  const target = screen.getByLabelText("Alternative");
  expect(within(baseline).getAllByRole("option")).toHaveLength(6);
  expect(within(target).getAllByRole("option")).toHaveLength(6);

  fireEvent.change(baseline, { target: { value: "2" } });
  await waitFor(() => expect(api.compareOptionsStrategies).toHaveBeenCalledTimes(2));
  const sent = vi.mocked(api.compareOptionsStrategies).mock.calls[1][0];
  expect(sent.strategies.map((strategy) => strategy.name)).toEqual(["strategy-1", "strategy-2"]);
  expect(sent.baseline_index).toBe(1);
  expect(sent.entry_spot).toBe(100);
  expect(sent.spot_min).toBe(80);
  await waitFor(() => expect(screen.getByTestId("scenario-delta")).toHaveTextContent("5,6"));
  expect(screen.getByTestId("scenario-raw")).toHaveTextContent("0,1");
});

it("aborts the previous comparison and ignores its stale grid", async () => {
  let resolveFirst!: (value: OptionsStrategyCompareResponse) => void;
  let resolveSecond!: (value: OptionsStrategyCompareResponse) => void;
  vi.mocked(api.compareOptionsStrategies)
    .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
    .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
  render(<StrategyScenarioComparison request={request} />);
  openComparison();
  await waitFor(() => expect(api.compareOptionsStrategies).toHaveBeenCalledTimes(1));
  const firstSignal = vi.mocked(api.compareOptionsStrategies).mock.calls[0][1] as AbortSignal;

  fireEvent.change(screen.getByLabelText("Base"), { target: { value: "2" } });
  await waitFor(() => expect(api.compareOptionsStrategies).toHaveBeenCalledTimes(2));
  expect(firstSignal.aborted).toBe(true);
  const secondBody = vi.mocked(api.compareOptionsStrategies).mock.calls[1][0];
  const stale = output(secondBody);
  stale.scenario_grid.delta_to_baseline["strategy-1"] = [[999, 999]];
  resolveFirst(stale);
  await waitFor(() => expect(screen.queryByText(/999/)).not.toBeInTheDocument());
  resolveSecond(output(secondBody));
  await waitFor(() => expect(screen.getByTestId("scenario-delta")).toHaveTextContent("5,6"));
});

it("compares saved strategies with labels longer than the API key limit", async () => {
  vi.mocked(api.compareOptionsStrategies).mockImplementation(async (body) => output(body));
  const longLabel = "Long saved strategy name ".repeat(4).trim();
  render(<StrategyScenarioComparison request={{
    ...request,
    alternatives: [{ label: longLabel, legs }],
  }} />);
  openComparison();
  await waitFor(() => expect(screen.getByTestId("scenario-delta")).toHaveTextContent("5,6"));
  expect(screen.getByTestId("scenario-raw")).toHaveTextContent(longLabel);
  expect(vi.mocked(api.compareOptionsStrategies).mock.calls[0][0].strategies.map((strategy) => strategy.name))
    .toEqual(["strategy-0", "strategy-1"]);
});

it("caps only the comparison grid and discloses the lower backend limit", async () => {
  vi.mocked(api.compareOptionsStrategies).mockImplementation(async (body) => output(body));
  render(<StrategyScenarioComparison request={{ ...request, spot_points: 501 }} />);
  openComparison();
  await waitFor(() => expect(api.compareOptionsStrategies).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.compareOptionsStrategies).mock.calls[0][0].spot_points).toBe(201);
  expect(screen.getByText(/at most 201 spot points/)).toBeInTheDocument();
});

it("shows a bounded error and retries the same comparison", async () => {
  vi.mocked(api.compareOptionsStrategies)
    .mockRejectedValueOnce(new Error("compare unavailable"))
    .mockImplementationOnce(async (body) => output(body));
  render(<StrategyScenarioComparison request={request} />);
  openComparison();
  await screen.findByText("compare unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));
  await waitFor(() => expect(screen.getByTestId("scenario-delta")).toHaveTextContent("5,6"));
  expect(api.compareOptionsStrategies).toHaveBeenCalledTimes(2);
});

it("exports only the accepted comparison snapshot with its reversed pair labels", async () => {
  let resolveSecond!: (value: OptionsStrategyCompareResponse) => void;
  vi.mocked(api.compareOptionsStrategies)
    .mockImplementationOnce(async (body) => output(body))
    .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
  const blobs: Blob[] = [];
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn((blob: Blob) => { blobs.push(blob); return "blob:comparison"; }),
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

  render(<StrategyScenarioComparison request={request} />);
  openComparison();
  await screen.findByTestId("comparison-export");
  fireEvent.change(screen.getByLabelText("Base"), { target: { value: "2" } });
  await waitFor(() => expect(api.compareOptionsStrategies).toHaveBeenCalledTimes(2));
  expect(screen.queryByTestId("comparison-export")).not.toBeInTheDocument();

  const secondBody = vi.mocked(api.compareOptionsStrategies).mock.calls[1][0];
  resolveSecond(output(secondBody));
  const exportArea = await screen.findByTestId("comparison-export");
  fireEvent.click(within(exportArea).getByRole("button", { name: /export json/i }));

  await waitFor(() => expect(blobs).toHaveLength(1));
  const document = JSON.parse(await blobs[0].text());
  expect(document.format).toBe("vibe-options-strategy-comparison-v1");
  expect(document.request).toEqual(secondBody);
  expect(document.result).toEqual(output(secondBody));
  expect(document.source_request).toEqual(request);
  expect(document.pair).toEqual({
    baseline_label: "Strategy 2",
    target_label: "Strategy 1",
    target_key: "strategy-1",
  });
  expect(click).toHaveBeenCalledTimes(1);
  click.mockRestore();
});

it("refreshes chart and download labels without refetching an unchanged comparison", async () => {
  vi.mocked(api.compareOptionsStrategies).mockImplementation(async (body) => output(body));
  const { rerender } = render(<StrategyScenarioComparison request={request} />);
  openComparison();
  await screen.findByTestId("comparison-export");
  const compare = vi.mocked(api.compareOptionsStrategies).mock.calls[0][0];

  const renamed = {
    ...request,
    label: "Renamed baseline",
    alternatives: request.alternatives!.map((item, index) =>
      index === 0 ? { ...item, label: "Renamed alternative" } : item,
    ),
  };
  rerender(<StrategyScenarioComparison request={renamed} />);
  expect(within(screen.getByLabelText("Alternative")).getByRole("option", {
    name: "Renamed alternative", selected: true,
  })).toBeInTheDocument();
  expect(screen.getByTestId("scenario-raw")).toHaveTextContent("Renamed alternative");
  expect(screen.getByTestId("scenario-delta")).toHaveTextContent("Renamed alternative − Renamed baseline");
  expect(api.compareOptionsStrategies).toHaveBeenCalledTimes(1);

  const blobs: Blob[] = [];
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn((blob: Blob) => { blobs.push(blob); return "blob:comparison"; }),
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  try {
    const area = screen.getByTestId("comparison-export");
    fireEvent.click(within(area).getByRole("button", { name: /export json/i }));
    fireEvent.click(within(area).getByRole("button", { name: /export csv/i }));
    expect(blobs).toHaveLength(2);
    const exported = JSON.parse(await blobs[0].text());
    expect(exported.request).toEqual(compare);
    expect(exported.result).toEqual(output(compare));
    expect(exported.source_request).toEqual(renamed);
    expect(exported.pair).toEqual({
      baseline_label: "Renamed baseline",
      target_label: "Renamed alternative",
      target_key: "strategy-1",
    });
    expect(await blobs[1].text()).toContain("Renamed baseline,0,Renamed alternative,10,5");
  } finally {
    click.mockRestore();
  }
});
