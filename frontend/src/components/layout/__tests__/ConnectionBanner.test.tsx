import { render, screen } from "@testing-library/react";
import i18n from "../../../i18n";
import { ConnectionBanner } from "../ConnectionBanner";

describe("ConnectionBanner", () => {
  beforeAll(() => {
    i18n.addResourceBundle(
      "en",
      "translation",
      { connection: { reload: "Reload" } },
      true,
      true,
    );
  });

  it("renders nothing when status is connected", () => {
    const { container } = render(<ConnectionBanner status="connected" />);
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing for the idle disconnected state", () => {
    const { container } = render(<ConnectionBanner status="disconnected" />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the calm reconnecting message regardless of attempt count", () => {
    render(<ConnectionBanner status="reconnecting" retryAttempt={3} />);
    expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
    expect(screen.getByText(/Reconnecting/)).toBeInTheDocument();
  });

  it("renders the same message when retryAttempt is not provided", () => {
    render(<ConnectionBanner status="reconnecting" />);
    expect(screen.getByText(/Reconnecting/)).toBeInTheDocument();
  });

  it("has warning styling", () => {
    const { container } = render(<ConnectionBanner status="reconnecting" retryAttempt={1} />);
    const banner = container.firstChild as HTMLElement;
    expect(banner.className).toMatch(/warning/);
    expect(banner).toHaveClass("absolute");
  });

  it("switches to the terminal state after five reconnect attempts", () => {
    render(<ConnectionBanner status="reconnecting" retryAttempt={5} />);

    expect(screen.getByText(/Connection lost/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    expect(document.querySelector(".animate-spin")).not.toBeInTheDocument();
  });
});
