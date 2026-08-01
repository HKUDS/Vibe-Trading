import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmDialog } from "../ConfirmDialog";

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <ConfirmDialog
        open={open}
        title="Delete session?"
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={() => setOpen(false)}
        onCancel={() => setOpen(false)}
      />
    </>
  );
}

describe("ConfirmDialog keyboard focus", () => {
  it("traps Tab inside the dialog and restores focus after Escape", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);

    const trigger = screen.getByRole("button", { name: "Open dialog" });
    await user.click(trigger);

    const confirm = screen.getByRole("button", { name: "Delete" });
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(confirm).toHaveFocus();

    await user.tab();
    expect(cancel).toHaveFocus();

    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
