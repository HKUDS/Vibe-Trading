import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ResearchArtifacts } from "../ResearchArtifacts";

const apiMock = vi.hoisted(() => ({
  searchResearchArtifacts: vi.fn(),
  getResearchArtifact: vi.fn(),
  exportResearchArtifact: vi.fn(),
  exportResearchArtifactComparison: vi.fn(),
  saveResearchArtifact: vi.fn(),
  compareResearchArtifactRevisions: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));

const first = {
  revision_id: "ra_1_r1",
  artifact_id: "ra_1",
  revision_number: 1,
  previous_revision_id: null,
  subject: "NVDA fundamental review",
  universe: "NVDA",
  content: "Original conclusion.",
  content_hash: "old",
  provenance_hash: "old",
  identity_hash: "old",
  data_as_of: "2026-10-20",
  created_at: "2026-10-20T10:00:00Z",
  evidence: [{ source_uri: "https://example.com/old", content_hash: "abc" }],
  evidence_missing: false,
  verification_status: "verified",
  completeness: "complete",
  hypothesis_id: "hyp_1",
  goal_id: "goal_1",
  session_id: "session_1",
  run_id: "run_1",
};
const second = {
  ...first,
  revision_id: "ra_1_r2",
  revision_number: 2,
  previous_revision_id: "ra_1_r1",
  content: "Updated conclusion.",
  content_hash: "new",
  provenance_hash: "new",
  identity_hash: "new",
  data_as_of: "2026-10-27",
  created_at: "2026-10-27T10:00:00Z",
};
const third = {
  ...second,
  revision_id: "ra_1_r3",
  revision_number: 3,
  previous_revision_id: "ra_1_r2",
};

function comparisonResult(from: string, to: string, marker: string) {
  return {
    comparison: {
      artifact_id: "ra_1",
      from: { revision_id: from, revision_number: Number(from.at(-1)) },
      to: { revision_id: to, revision_number: Number(to.at(-1)) },
      content: { changed: true, diff: [marker], truncated: false },
      evidence: { changed: false },
      metadata: {},
    },
  };
}

function pendingComparison() {
  let resolve!: (value: ReturnType<typeof comparisonResult>) => void;
  const promise = new Promise<ReturnType<typeof comparisonResult>>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("ResearchArtifacts page", () => {
  beforeEach(() => {
    Object.values(apiMock).forEach((mock) => mock.mockReset());
  });

  it("keeps comparison and export bound to the last selected series after out-of-order detail replies", async () => {
    const other = { ...second, artifact_id: "ra_2", revision_id: "ra_2_r2", subject: "MSFT review" };
    const olderOther = { ...first, artifact_id: "ra_2", revision_id: "ra_2_r1", subject: "MSFT review" };
    let resolveFirst!: (value: unknown) => void;
    const pending = new Promise((resolve) => { resolveFirst = resolve; });
    apiMock.searchResearchArtifacts.mockResolvedValue({ count: 2, artifacts: [second, other] });
    apiMock.getResearchArtifact.mockImplementation((id) => id === "ra_1" ? pending : Promise.resolve({ artifact: other, revisions: [other, olderOther] }));
    apiMock.compareResearchArtifactRevisions.mockResolvedValue(comparisonResult("ra_2_r1", "ra_2_r2", "MSFT diff"));
    apiMock.exportResearchArtifact.mockRejectedValue(new Error("download unavailable"));
    render(<ResearchArtifacts />, { wrapper: MemoryRouter });
    fireEvent.click(await screen.findByText("NVDA fundamental review"));
    fireEvent.click(screen.getByText("MSFT review"));
    await waitFor(() => expect(screen.getByLabelText("From revision")).toHaveValue("ra_2_r1"));
    await act(async () => resolveFirst({ artifact: second, revisions: [second, first] }));
    expect(screen.getByLabelText("From revision")).toHaveValue("ra_2_r1");
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    await screen.findByText("MSFT diff");
    expect(apiMock.compareResearchArtifactRevisions).toHaveBeenCalledWith("ra_2", "ra_2_r1", "ra_2_r2");
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));
    await waitFor(() => expect(apiMock.exportResearchArtifact).toHaveBeenCalledWith("ra_2", "json"));
  });

  it("shows an actionable empty state", async () => {
    apiMock.searchResearchArtifacts.mockResolvedValue({ count: 0, artifacts: [] });
    render(<ResearchArtifacts />, { wrapper: MemoryRouter });

    expect(await screen.findByText("No research artifacts yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New research" })).toBeInTheDocument();
  });

  it("downloads the server-rendered series export with its exact bytes", async () => {
    apiMock.searchResearchArtifacts.mockResolvedValue({ count: 1, artifacts: [second] });
    apiMock.getResearchArtifact.mockResolvedValue({ artifact: second, revisions: [second, first] });
    apiMock.exportResearchArtifact.mockResolvedValue({
      filename: "ra_1.json",
      media_type: "application/json",
      content: '{"schema_version":1}\n',
      sha256: "abc",
    });
    const createObjectURL = vi.fn(() => "blob:research-export");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<ResearchArtifacts />, { wrapper: MemoryRouter });

    fireEvent.click(await screen.findByText("NVDA fundamental review"));
    expect(await screen.findByText("Revision history")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Export JSON" }));

    await waitFor(() => expect(apiMock.exportResearchArtifact).toHaveBeenCalledWith("ra_1", "json"));
    expect(createObjectURL).toHaveBeenCalledWith(expect.objectContaining({ type: "application/json" }));
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    expect(await blob.text()).toBe('{"schema_version":1}\n');
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:research-export");
    click.mockRestore();
  });

  it("downloads the selected comparison with its exact server-rendered bytes", async () => {
    apiMock.searchResearchArtifacts.mockResolvedValue({ count: 1, artifacts: [second] });
    apiMock.getResearchArtifact.mockResolvedValue({ artifact: second, revisions: [second, first] });
    apiMock.compareResearchArtifactRevisions.mockResolvedValue(comparisonResult("ra_1_r1", "ra_1_r2", "-Original conclusion."));
    apiMock.exportResearchArtifactComparison.mockResolvedValue({
      filename: "ra_1-r1-r2.md",
      media_type: "text/markdown; charset=utf-8",
      content: "# Research revision comparison\n\n-Original conclusion.\n",
      sha256: "def",
    });
    const createObjectURL = vi.fn(() => "blob:comparison-export");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<ResearchArtifacts />, { wrapper: MemoryRouter });

    fireEvent.click(await screen.findByText("NVDA fundamental review"));
    fireEvent.click(await screen.findByRole("button", { name: "Compare" }));
    expect(await screen.findByText("-Original conclusion.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Export comparison Markdown" }));

    await waitFor(() => expect(apiMock.exportResearchArtifactComparison).toHaveBeenCalledWith("ra_1", "ra_1_r1", "ra_1_r2", "markdown"));
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    expect(await blob.text()).toBe("# Research revision comparison\n\n-Original conclusion.\n");
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:comparison-export");
    click.mockRestore();
  });

  it("opens revision history and preserves existing evidence when revising", async () => {
    apiMock.searchResearchArtifacts.mockResolvedValue({ count: 1, artifacts: [second] });
    apiMock.getResearchArtifact.mockResolvedValue({ artifact: second, revisions: [second, first] });
    apiMock.saveResearchArtifact.mockResolvedValue({ revision: third, created: true });
    render(<ResearchArtifacts />, { wrapper: MemoryRouter });

    fireEvent.click(await screen.findByText("NVDA fundamental review"));
    expect(await screen.findByText("Revision history")).toBeInTheDocument();
    expect(screen.getByText("Original conclusion.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Revise from this revision" }));
    fireEvent.change(screen.getByLabelText("Research content"), { target: { value: "Third conclusion." } });
    fireEvent.change(screen.getByLabelText("Additional evidence URIs (one per line)"), {
      target: { value: "https://example.com/new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save research" }));

    await waitFor(() => expect(apiMock.saveResearchArtifact).toHaveBeenCalledTimes(1));
    expect(apiMock.saveResearchArtifact).toHaveBeenCalledWith(expect.objectContaining({
      artifact_id: "ra_1",
      content: "Third conclusion.",
      verification_status: "unverified",
      evidence: [
        { source_uri: "https://example.com/old", content_hash: "abc" },
        { source_uri: "https://example.com/new" },
      ],
    }));
    expect(await screen.findByText("Created revision ra_1_r3.")).toBeInTheDocument();
  });

  it("compares arbitrary revisions without changing the revision editor", async () => {
    const latest = { ...third, content: "Third conclusion." };
    apiMock.searchResearchArtifacts.mockResolvedValue({ count: 1, artifacts: [latest] });
    apiMock.getResearchArtifact.mockResolvedValue({ artifact: latest, revisions: [latest, second, first] });
    apiMock.compareResearchArtifactRevisions.mockResolvedValue({
      comparison: {
        artifact_id: "ra_1",
        from: { revision_id: first.revision_id, revision_number: 1 },
        to: { revision_id: latest.revision_id, revision_number: 3 },
        content: {
          changed: true,
          from_hash: "old",
          to_hash: "new",
          from_line_count: 1,
          to_line_count: 1,
          diff: ["--- ra_1_r1", "+++ ra_1_r3", "@@ -1 +1 @@", "-Original conclusion.", "+Third conclusion."],
          truncated: false,
        },
        evidence: {
          added: [{ source_uri: "https://example.com/new" }],
          removed: [{ source_uri: "https://example.com/old" }],
          unchanged_count: 0,
          order_changed: false,
          changed: true,
        },
        metadata: { data_as_of: { from: "2026-10-20", to: "2026-11-03" } },
      },
    });
    render(<ResearchArtifacts />, { wrapper: MemoryRouter });

    fireEvent.click(await screen.findByText("NVDA fundamental review"));
    const from = await screen.findByLabelText("From revision");
    const to = screen.getByLabelText("To revision");
    expect(from).toHaveValue("ra_1_r2");
    expect(to).toHaveValue("ra_1_r3");
    fireEvent.change(from, { target: { value: "ra_1_r1" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));

    await waitFor(() => expect(apiMock.compareResearchArtifactRevisions).toHaveBeenCalledWith("ra_1", "ra_1_r1", "ra_1_r3"));
    expect(screen.getByText(/-Original conclusion\./)).toBeInTheDocument();
    expect(screen.getByText(/\+Third conclusion\./)).toBeInTheDocument();
    expect(screen.getByText(/"data_as_of"/)).toBeInTheDocument();
    expect(screen.getByText("Read-only comparison. No revision is revalidated.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Revise from this revision" }));
    expect(screen.getByLabelText("Research content")).toHaveValue("Third conclusion.");
  });

  it.each([
    { selector: "from", from: "ra_1_r1", to: "ra_1_r3" },
    { selector: "to", from: "ra_1_r2", to: "ra_1_r1" },
  ])("ignores a stale response after changing the $selector revision", async ({ selector, from: nextFrom, to: nextTo }) => {
    const latest = { ...third, content: "Third conclusion." };
    const staleRequest = pendingComparison();
    apiMock.searchResearchArtifacts.mockResolvedValue({ count: 1, artifacts: [latest] });
    apiMock.getResearchArtifact.mockResolvedValue({ artifact: latest, revisions: [latest, second, first] });
    apiMock.compareResearchArtifactRevisions.mockReturnValueOnce(staleRequest.promise);
    render(<ResearchArtifacts />, { wrapper: MemoryRouter });

    fireEvent.click(await screen.findByText("NVDA fundamental review"));
    const from = await screen.findByLabelText("From revision");
    const to = screen.getByLabelText("To revision");
    const compare = screen.getByRole("button", { name: "Compare" });
    fireEvent.click(compare);
    await waitFor(() => expect(apiMock.compareResearchArtifactRevisions).toHaveBeenCalledWith("ra_1", "ra_1_r2", "ra_1_r3"));

    fireEvent.change(selector === "from" ? from : to, {
      target: { value: selector === "from" ? nextFrom : nextTo },
    });
    staleRequest.resolve(comparisonResult("ra_1_r2", "ra_1_r3", "stale comparison"));
    await waitFor(() => expect(compare).toBeEnabled());
    expect(screen.queryByText("stale comparison")).not.toBeInTheDocument();

    apiMock.compareResearchArtifactRevisions.mockResolvedValueOnce(comparisonResult(nextFrom, nextTo, "current comparison"));
    fireEvent.click(compare);
    expect(await screen.findByText("current comparison")).toBeInTheDocument();
    expect(apiMock.compareResearchArtifactRevisions).toHaveBeenLastCalledWith("ra_1", nextFrom, nextTo);
  });
});
