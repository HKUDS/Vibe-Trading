import { render, screen } from "@testing-library/react";
import { ConnectionBanner } from "../ConnectionBanner";
import { copy } from "@/i18n/display";

describe("ConnectionBanner", () => {
  it("renders nothing when status is connected", () => {
    const { container } = render(<ConnectionBanner status="connected" />);
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when status is disconnected", () => {
    const { container } = render(<ConnectionBanner status="disconnected" />);
    expect(container.innerHTML).toBe("");
  });

  it("shows reconnecting message with attempt number", () => {
    render(<ConnectionBanner status="reconnecting" retryAttempt={3} />);
    expect(screen.getByText(copy.status.reconnecting(3))).toBeInTheDocument();
  });

  it("defaults to attempt 1 when retryAttempt is not provided", () => {
    render(<ConnectionBanner status="reconnecting" />);
    expect(screen.getByText(copy.status.reconnecting(1))).toBeInTheDocument();
  });

  it("has warning styling", () => {
    const { container } = render(<ConnectionBanner status="reconnecting" retryAttempt={1} />);
    const banner = container.firstChild as HTMLElement;
    expect(banner.className).toMatch(/warning/);
  });
});
