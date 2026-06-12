import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Usage } from "../Usage";
import type { RunData, RunListItem } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  listRuns: vi.fn(),
  getRun: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: apiMock,
}));

function renderUsage() {
  return render(
    <MemoryRouter>
      <Usage />
    </MemoryRouter>,
  );
}

function makeRun(overrides: Partial<RunListItem> = {}): RunListItem {
  return {
    run_id: "run-1",
    status: "success",
    created_at: "2026-06-12T08:00:00Z",
    prompt: "Backtest a momentum strategy",
    ...overrides,
  };
}

function makeDetail(overrides: Partial<RunData> = {}): RunData {
  return {
    run_id: "run-1",
    status: "success",
    llm_usage: {
      provider: "anthropic",
      model: "claude-sonnet",
      input_tokens: 1000,
      output_tokens: 200,
      total_tokens: 1200,
      calls: 2,
      iterations: [{ iter: 1, input_tokens: 1000, output_tokens: 200, total_tokens: 1200 }],
    },
    ...overrides,
  };
}

describe("Usage dashboard", () => {
  beforeEach(() => {
    apiMock.listRuns.mockReset();
    apiMock.getRun.mockReset();
  });

  it("aggregates persisted usage across recent runs", async () => {
    apiMock.listRuns.mockResolvedValue([
      makeRun(),
      makeRun({ run_id: "run-2", prompt: "Use a different model" }),
      makeRun({ run_id: "no-usage" }),
    ]);
    apiMock.getRun.mockImplementation((runId: string) => {
      if (runId === "run-2") {
        return Promise.resolve(makeDetail({
          run_id: "run-2",
          llm_usage: {
            provider: "openai",
            model: "gpt-4.1",
            input_tokens: 250,
            output_tokens: 50,
            total_tokens: 300,
            calls: 1,
            iterations: [{ iter: 1, input_tokens: 250, output_tokens: 50, total_tokens: 300 }],
          },
        }));
      }
      if (runId === "no-usage") return Promise.resolve({ run_id: runId, status: "success" });
      return Promise.resolve(makeDetail());
    });

    renderUsage();

    expect(await screen.findByText("Agent Usage Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Runs with usage").closest(".rounded-md")).toHaveTextContent("2");
    expect(screen.getByText("LLM calls").closest(".rounded-md")).toHaveTextContent("3");
    expect(screen.getByText("Input tokens").closest(".rounded-md")).toHaveTextContent("1,250");
    expect(screen.getByText("Output tokens").closest(".rounded-md")).toHaveTextContent("250");
    expect(screen.getByText("anthropic")).toBeInTheDocument();
    expect(screen.getByText("claude-sonnet")).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(screen.getByText("gpt-4.1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /run-1/ })).toHaveAttribute("href", "/runs/run-1");
    expect(document.body.textContent || "").not.toContain("$");
  });

  it("shows an empty state when recent runs have no usage artifact", async () => {
    apiMock.listRuns.mockResolvedValue([makeRun()]);
    apiMock.getRun.mockResolvedValue({ run_id: "run-1", status: "success" });

    renderUsage();

    expect(await screen.findByText("No persisted usage found")).toBeInTheDocument();
  });

  it("refreshes by reading recent run usage again", async () => {
    apiMock.listRuns.mockResolvedValue([makeRun()]);
    apiMock.getRun.mockResolvedValue(makeDetail());

    renderUsage();
    await screen.findByText("run-1");

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => expect(apiMock.listRuns).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(apiMock.getRun).toHaveBeenCalledTimes(2));
  });
});
