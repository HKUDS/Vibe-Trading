import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AlphaZoo } from "../AlphaZoo";
import { clearAnalysisState } from "@/hooks/useAnalysisState";
const mock = vi.hoisted(() => ({ job: vi.fn(), submit: vi.fn() }));
vi.mock("@/hooks/useAlphaJob", () => ({ useAlphaJob: mock.job }));
vi.mock("@/hooks/useChartLifecycle", () => ({ useChartLifecycle: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { getAlphaReadiness: vi.fn().mockResolvedValue({ universes: { sp500: { ready: true, reason: "public_data" } }, zoo_counts: { alpha101: 101 } }) } }));
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
