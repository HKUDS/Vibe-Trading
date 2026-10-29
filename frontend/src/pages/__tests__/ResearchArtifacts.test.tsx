import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ResearchArtifacts } from "../ResearchArtifacts";

const apiMock = vi.hoisted(() => ({
  searchResearchArtifacts: vi.fn(),
  getResearchArtifact: vi.fn(),
  saveResearchArtifact: vi.fn(),
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

describe("ResearchArtifacts page", () => {
  beforeEach(() => {
    Object.values(apiMock).forEach((mock) => mock.mockReset());
  });

  it("shows an actionable empty state", async () => {
    apiMock.searchResearchArtifacts.mockResolvedValue({ count: 0, artifacts: [] });
    render(<ResearchArtifacts />, { wrapper: MemoryRouter });

    expect(await screen.findByText("No research artifacts yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New research" })).toBeInTheDocument();
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
});
