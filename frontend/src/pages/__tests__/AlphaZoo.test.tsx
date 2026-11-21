import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AlphaZoo } from "../AlphaZoo";
import { clearAnalysisState } from "@/hooks/useAnalysisState";
const mock = vi.hoisted(() => ({ job: vi.fn(), submit: vi.fn(), detail: vi.fn() }));
vi.mock("@/hooks/useAlphaJob", () => ({ useAlphaJob: mock.job }));
vi.mock("@/hooks/useChartLifecycle", () => ({ useChartLifecycle: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { getAlpha: mock.detail, getAlphaReadiness: vi.fn().mockResolvedValue({ universes: { hsi: { ready: true, reason: "public_data" }, sp500: { ready: true, reason: "public_data" } }, zoo_counts: { alpha101: 101 } }) } }));
beforeEach(() => {
  clearAnalysisState("alpha-bench:alpha101:alpha101_001"); vi.clearAllMocks();
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

it("selects HSI and submits its canonical benchmark universe", async () => {
  page();
  const selector = screen.getByLabelText("Universe");
  expect(screen.getByRole("option", { name: "Hang Seng Index (HK)" })).toBeEnabled();
  fireEvent.change(selector, { target: { value: "hsi" } });
  await screen.findByText("Uses public data. Availability is checked when the task runs.");
  fireEvent.click(screen.getByRole("button", { name: "Run benchmark" }));
  expect(mock.submit).toHaveBeenCalledWith(expect.objectContaining({ universe: "hsi" }));
});

it("prefills HSI from Hong Kong factor metadata", async () => {
  mock.detail.mockResolvedValue({ status: "ok", alpha: { id: "hk_factor", zoo: "alpha101", meta: { universe: ["equity_hk"] } }, source_code: "" });
  render(<MemoryRouter initialEntries={["/alpha-zoo/hk_factor"]}><Routes><Route path="/alpha-zoo/:alphaId" element={<AlphaZoo />} /><Route path="/alpha-zoo/bench" element={<AlphaZoo />} /></Routes></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "Evaluate this factor" }));
  expect(screen.getByLabelText("Universe")).toHaveValue("hsi");
  await screen.findByText("Uses public data. Availability is checked when the task runs.");
});

it("offers HSI in the comparison selector", async () => {
  render(<MemoryRouter initialEntries={["/alpha-zoo/compare?ids=alpha101_001,alpha101_002"]}><AlphaZoo /></MemoryRouter>);
  expect(screen.getByRole("option", { name: "Hang Seng Index (HK)" })).toBeEnabled();
  fireEvent.change(screen.getByLabelText("Universe"), { target: { value: "hsi" } });
  await screen.findByText("Uses public data. Availability is checked when the task runs.");
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  expect(mock.submit).toHaveBeenCalledWith(expect.objectContaining({ universe: "hsi" }));
});
