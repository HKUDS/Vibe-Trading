import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AlphaZoo } from "../AlphaZoo";
import { clearAnalysisState } from "@/hooks/useAnalysisState";
const mock = vi.hoisted(() => ({ job: vi.fn(), submit: vi.fn(), list: vi.fn(), detail: vi.fn() }));
vi.mock("@/hooks/useAlphaJob", () => ({ useAlphaJob: mock.job }));
vi.mock("@/hooks/useChartLifecycle", () => ({ useChartLifecycle: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { getAlphaReadiness: vi.fn().mockResolvedValue({ universes: { csi300: { ready: false, reason: "tushare_token_missing" }, sp500: { ready: true, reason: "public_data" }, nifty100: { ready: true, reason: "public_data" }, "btc-usdt": { ready: false, reason: "single_asset" } }, zoo_counts: { alpha101: 101 } }), listAlphas: mock.list, getAlpha: mock.detail } }));
beforeEach(() => {
  for (const key of ["alpha-bench:alpha101:alpha101_001", "alpha-bench:alpha101:", "alpha-browse", "alpha-compare:alpha101_001, alpha101_002"]) clearAnalysisState(key);
  vi.clearAllMocks();
  mock.list.mockResolvedValue({ status: "ok", alphas: [], total: 0, returned: 0, truncated: false });
  mock.job.mockReturnValue({ status: "idle", jobId: null, progress: null, result: null, formError: null, busy: false, submit: mock.submit, reconnect: vi.fn(), setFormError: vi.fn() });
});
const page = () => render(<MemoryRouter initialEntries={["/alpha-zoo/bench?zoo=alpha101&alpha_id=alpha101_001&universe=sp500"]}><AlphaZoo /></MemoryRouter>);
it("describes and submits only the selected factor", async () => {
  page();
  expect(screen.getByRole("heading", { name: "Evaluate this factor" })).toBeInTheDocument();
  expect(screen.getByText("Selected factor: alpha101_001. Only this factor will be evaluated.")).toBeInTheDocument();
  await screen.findByText("Uses public data. Availability is checked when the task runs.");
  fireEvent.click(screen.getByRole("button", { name: "Run benchmark" }));
  expect(mock.submit).toHaveBeenCalledWith({ zoo: "alpha101", alpha_id: "alpha101_001", universe: "sp500", period: "2020-2025", top: 5 });
});
it("explains how to recover when all selected factors were skipped", async () => {
  mock.job.mockReturnValue({ ...mock.job(), status: "done", result: { alive: 0, reversed: 0, dead: 0, skipped: 1, n_alphas_tested: 0, top5_by_ir: [], dead_examples: [], by_theme: {} } });
  page();
  expect(screen.getByRole("alert")).toHaveTextContent("No factors could be evaluated. Try a longer history");
  await screen.findByText("Uses public data. Availability is checked when the task runs.");
});

const renderAt = (path: string) => render(
  <MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path="/alpha-zoo" element={<AlphaZoo />} />
      <Route path="/alpha-zoo/bench" element={<AlphaZoo />} />
      <Route path="/alpha-zoo/compare" element={<AlphaZoo />} />
      <Route path="/alpha-zoo/:alphaId" element={<AlphaZoo />} />
    </Routes>
  </MemoryRouter>,
);

it("offers NIFTY 100 alongside existing benchmarks and submits the selected universe", async () => {
  renderAt("/alpha-zoo/bench");
  const universe = screen.getByLabelText("Universe");
  expect(universe).toHaveValue("csi300");
  expect([...universe.querySelectorAll("option")].map((option) => option.value)).toEqual(["csi300", "sp500", "nifty100", "btc-usdt"]);
  expect(screen.getByRole("option", { name: "BTC-USDT (Crypto)" })).toBeDisabled();
  fireEvent.change(universe, { target: { value: "nifty100" } });
  await screen.findByText("Uses public data. Availability is checked when the task runs.");
  expect(screen.getByRole("option", { name: "NIFTY 100 (India)" })).toHaveValue("nifty100");
  fireEvent.click(screen.getByRole("button", { name: "Run benchmark" }));
  expect(mock.submit).toHaveBeenCalledWith({ zoo: "alpha101", universe: "nifty100", period: "2020-2025", top: 5 });
});

it("prefills NIFTY 100 links and retains the selected factor in the request", async () => {
  renderAt("/alpha-zoo/bench?zoo=alpha101&alpha_id=alpha101_001&universe=nifty100");
  expect(screen.getByLabelText("Universe")).toHaveValue("nifty100");
  await screen.findByText("Uses public data. Availability is checked when the task runs.");
  fireEvent.click(screen.getByRole("button", { name: "Run benchmark" }));
  expect(mock.submit).toHaveBeenCalledWith({ zoo: "alpha101", alpha_id: "alpha101_001", universe: "nifty100", period: "2020-2025", top: 5 });
});

it("submits NIFTY 100 comparisons without changing existing comparison defaults", async () => {
  renderAt("/alpha-zoo/compare?ids=alpha101_001,alpha101_002");
  expect(screen.getByLabelText("Universe")).toHaveValue("csi300");
  fireEvent.change(screen.getByLabelText("Universe"), { target: { value: "nifty100" } });
  await screen.findByText("Uses public data. Availability is checked when the task runs.");
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  expect(mock.submit).toHaveBeenCalledWith({ alpha_ids: ["alpha101_001", "alpha101_002"], universe: "nifty100", period: "2020-2025", sort: "ir" });
});

it.each([
  [["equity_in"], "nifty100"],
  [["equity_us"], "sp500"],
  [["equity_cn"], "csi300"],
  [["equity_us", "equity_in"], "sp500"],
  [["equity_cn", "equity_in"], "csi300"],
])("uses the appropriate browse shortcut for %j", async (universes, expected) => {
  mock.list.mockResolvedValue({ status: "ok", alphas: [{ id: "alpha101_001", zoo: "alpha101", theme: ["reversal"], universe: universes }], total: 1, returned: 1, truncated: false });
  renderAt("/alpha-zoo");
  fireEvent.click(await screen.findByRole("checkbox", { name: "Select alpha101_001 for compare" }));
  const link = screen.getByRole("link", { name: /Evaluate selected/ });
  expect(link).toHaveAttribute("href", `/alpha-zoo/bench?alpha_id=alpha101_001&zoo=alpha101&universe=${expected}`);
});

it.each([
  [["equity_in"], "nifty100"],
  [["equity_us"], "sp500"],
  [["equity_cn"], "csi300"],
])("maps detail metadata %j to its benchmark panel", async (universes, expected) => {
  mock.detail.mockResolvedValue({ status: "ok", alpha: { id: "alpha101_001", zoo: "alpha101", meta: { universe: universes } }, source_code: "# synthetic detail fixture" });
  renderAt("/alpha-zoo/alpha101_001");
  fireEvent.click(await screen.findByRole("button", { name: "Evaluate this factor" }));
  expect(await screen.findByLabelText("Universe")).toHaveValue(expected);
  expect(screen.getByText("Selected factor: alpha101_001. Only this factor will be evaluated.")).toBeInTheDocument();
});

it("uses the translated NIFTY 100 label in completed benchmark results", async () => {
  mock.job.mockReturnValue({ ...mock.job(), status: "done", request: { universe: "nifty100", period: "2024-2025" }, result: { alive: 1, reversed: 0, dead: 0, n_alphas_tested: 1, top5_by_ir: [], dead_examples: [], by_theme: {} } });
  renderAt("/alpha-zoo/bench?universe=nifty100");
  expect(screen.getByText(/NIFTY 100 \(India\).*2024-2025/)).toBeInTheDocument();
  await screen.findByText("Uses public data. Availability is checked when the task runs.");
});
