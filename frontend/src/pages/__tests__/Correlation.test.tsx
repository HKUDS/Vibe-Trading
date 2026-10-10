import { act, fireEvent, render, screen } from "@testing-library/react";
import { Correlation } from "../Correlation";
import { clearAnalysisState } from "@/hooks/useAnalysisState";
import type { CorrelationAnalysisResponse } from "@/lib/api";

const apiMock = vi.hoisted(() => ({ getCorrelationAnalysis: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/components/charts/CorrelationMatrix", () => ({
  CorrelationMatrix: ({ labels }: { labels: string[] }) => <div data-testid="correlation-result">{labels.join(",")}</div>,
}));
vi.mock("@/components/charts/RegimeTimeline", () => ({ RegimeTimeline: () => <div>timeline</div> }));

function response(label: string): CorrelationAnalysisResponse {
  return { correlation: { labels: [label], matrix: [[1]] }, regime: null, errors: {},
    coverage: { requested: [label], missing: [], observations: 30, first_date: "2026-01-01", last_date: "2026-02-12", diagnostics: {} } };
}
beforeEach(() => { clearAnalysisState("correlation"); apiMock.getCorrelationAnalysis.mockReset(); });

it("marks old results and rejects a late response after editing the query", async () => {
  apiMock.getCorrelationAnalysis.mockResolvedValueOnce(response("OLD"));
  let resolve!: (r: CorrelationAnalysisResponse) => void;
  apiMock.getCorrelationAnalysis.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
  render(<Correlation />);
  fireEvent.click(screen.getByRole("button", { name: "Compute" }));
  expect(await screen.findByTestId("correlation-result")).toHaveTextContent("OLD");
  fireEvent.click(screen.getByRole("button", { name: "Compute" }));
  const signal = apiMock.getCorrelationAnalysis.mock.calls[1][4] as AbortSignal;
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "AAPL,SPY" } });
  expect(signal.aborted).toBe(true);
  expect(screen.getByText("Showing the previous parameters’ result", { exact: false })).toBeInTheDocument();
  await act(async () => resolve(response("STALE")));
  expect(screen.getByTestId("correlation-result")).toHaveTextContent("OLD");
});
it("retains a matrix when the regime cannot be calculated and restores it on return", async () => {
  apiMock.getCorrelationAnalysis.mockResolvedValue({ ...response("VALID"), errors: { regime: "Not enough overlapping observations" } });
  const page = render(<Correlation />);
  fireEvent.click(screen.getByRole("button", { name: "Compute" }));
  expect(await screen.findByTestId("correlation-result")).toHaveTextContent("VALID");
  expect(screen.getByRole("alert")).toHaveTextContent("Not enough overlapping observations");
  page.unmount(); render(<Correlation />);
  expect(screen.getByTestId("correlation-result")).toHaveTextContent("VALID");
  expect(apiMock.getCorrelationAnalysis).toHaveBeenCalledTimes(1);
});
it("rejects duplicate assets and accepts Chinese delimiters", () => {
  apiMock.getCorrelationAnalysis.mockResolvedValue(response("OK"));
  render(<Correlation />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "aapl，AAPL.US" } });
  expect(screen.getByRole("button", { name: "Compute" })).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "AAPL；SPY MSFT" } });
  fireEvent.click(screen.getByRole("button", { name: "Compute" }));
  expect(apiMock.getCorrelationAnalysis).toHaveBeenCalledWith("AAPL,SPY,MSFT", 90, "pearson", false, expect.any(AbortSignal));
});
