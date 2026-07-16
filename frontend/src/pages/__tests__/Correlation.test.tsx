import { act, fireEvent, render, screen } from "@testing-library/react";
import { Correlation } from "../Correlation";
import type { CorrelationResponse } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  getCorrelation: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/components/charts/CorrelationMatrix", () => ({
  CorrelationMatrix: ({ labels }: { labels: string[] }) => (
    <div data-testid="correlation-result">{labels.join(",")}</div>
  ),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("Correlation page", () => {
  beforeEach(() => {
    apiMock.getCorrelation.mockReset();
  });

  it("clears old output and ignores an in-flight result after the query changes", async () => {
    apiMock.getCorrelation.mockResolvedValueOnce({ labels: ["OLD"], matrix: [[1]] });
    const pending = deferred<CorrelationResponse>();
    apiMock.getCorrelation.mockReturnValueOnce(pending.promise);

    render(<Correlation />);
    fireEvent.click(screen.getByRole("button", { name: "Compute" }));
    expect(await screen.findByTestId("correlation-result")).toHaveTextContent("OLD");

    fireEvent.click(screen.getByRole("button", { name: "Compute" }));
    expect(screen.queryByTestId("correlation-result")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "AAPL,SPY" } });
    expect(screen.getByRole("button", { name: "Compute" })).toBeEnabled();

    await act(async () => {
      pending.resolve({ labels: ["STALE"], matrix: [[1]] });
      await pending.promise;
    });
    expect(screen.queryByTestId("correlation-result")).not.toBeInTheDocument();
  });
});
