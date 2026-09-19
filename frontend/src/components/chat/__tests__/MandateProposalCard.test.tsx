import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MandateProposalCard } from "@/components/chat/MandateProposalCard";
import { api, type MandateProposal } from "@/lib/api";
import i18n from "@/i18n";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      getLiveAccounts: vi.fn(),
      commitMandate: vi.fn(),
    },
  };
});

const mocked = api as unknown as {
  getLiveAccounts: ReturnType<typeof vi.fn>;
  commitMandate: ReturnType<typeof vi.fn>;
};

function proposal(broker: string): MandateProposal {
  return {
    type: "mandate.proposal",
    proposal_id: `mp_${"a".repeat(32)}`,
    session_id: "sess-1",
    intent_normalized: "tech, ~$5000",
    account: { broker, type: "cash", funded_by: "user" },
    ceilings_ref: "caps_1",
    profiles: [
      { ordinal: 1, label: "Steady", universe: ["AAPL"], max_order_usd: 250, daily_trade_cap: 2, leverage: "none", instruments: ["equity"] },
    ],
  } as MandateProposal;
}

function openConfirm() {
  fireEvent.click(screen.getByRole("button", { name: i18n.t("mandate.commit", { label: "Steady" }) }));
  return screen.getByRole("alertdialog");
}

describe("MandateProposalCard account binding", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.commitMandate.mockResolvedValue({ mandate_id: "m1", consent_record_id: "cr1" });
  });

  it("requires the user to pick the account and commits it", async () => {
    mocked.getLiveAccounts.mockResolvedValue({
      status: "ok",
      broker: "robinhood",
      account_selection_required: true,
      accounts: [
        { account_ref: "5QR12345", label: "Main ····2345", is_default: true, agentic_allowed: true, deactivated: false },
        { account_ref: "5QR99887", label: "IRA ····9887", is_default: false, agentic_allowed: false, deactivated: false },
      ],
    });
    render(<MandateProposalCard proposal={proposal("robinhood")} onAdjust={() => undefined} />);

    const dialog = openConfirm();
    const select = await within(dialog).findByLabelText(new RegExp(i18n.t("mandate.accountLabel")));
    const confirm = within(dialog).getByRole("button", { name: i18n.t("mandate.confirmButton") });

    expect(mocked.getLiveAccounts).toHaveBeenCalledWith("robinhood");
    expect(select).toHaveValue("");
    expect(confirm).toBeDisabled();
    expect(within(select).getByRole("option", { name: /IRA ····9887/ })).toBeDisabled();

    fireEvent.change(select, { target: { value: "5QR12345" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await waitFor(() => expect(mocked.commitMandate).toHaveBeenCalledWith(
      expect.objectContaining({ broker: "robinhood", selected_ordinal: 1, account_ref: "5QR12345", consent_ack: true }),
    ));
  });

  it("commits without an account for a broker that binds none", async () => {
    mocked.getLiveAccounts.mockResolvedValue({
      status: "ok",
      broker: "ibkr",
      account_selection_required: false,
      accounts: [],
    });
    render(<MandateProposalCard proposal={proposal("ibkr")} onAdjust={() => undefined} />);

    const dialog = openConfirm();
    const confirm = within(dialog).getByRole("button", { name: i18n.t("mandate.confirmButton") });
    await waitFor(() => expect(confirm).toBeEnabled());
    expect(within(dialog).queryByRole("combobox")).toBeNull();
    fireEvent.click(confirm);

    await waitFor(() => expect(mocked.commitMandate).toHaveBeenCalled());
    expect(mocked.commitMandate.mock.calls[0][0]).not.toHaveProperty("account_ref");
  });

  it("keeps commit disabled when the account list cannot be read", async () => {
    mocked.getLiveAccounts.mockRejectedValue(new Error("token expired"));
    render(<MandateProposalCard proposal={proposal("robinhood")} onAdjust={() => undefined} />);

    const dialog = openConfirm();

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("token expired");
    expect(within(dialog).getByRole("button", { name: i18n.t("mandate.confirmButton") })).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: i18n.t("mandate.confirmButton") }));
    expect(mocked.commitMandate).not.toHaveBeenCalled();
  });
});
