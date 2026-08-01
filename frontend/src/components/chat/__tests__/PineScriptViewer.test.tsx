import { fireEvent, render, screen } from "@testing-library/react";
import { PineScriptViewer } from "../PineScriptViewer";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("PineScriptViewer", () => {
  it("renders an accessible portal dialog and restores focus after Escape closes it", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    const onClose = vi.fn();

    const { container, unmount } = render(
      <PineScriptViewer code="strategy('test')" onClose={onClose} />,
    );

    const dialog = screen.getByRole("dialog", { name: "pineViewer.pineScript" });
    expect(container).not.toContainElement(dialog);
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("button", { name: "layout.cancel" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    unmount();
    expect(trigger).toHaveFocus();
    trigger.remove();
  });
});
