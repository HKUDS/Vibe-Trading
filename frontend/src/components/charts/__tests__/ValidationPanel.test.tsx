import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ValidationPanel } from "../ValidationPanel";

describe("undefined validation results", () => {
  it("renders an error-only Monte Carlo result without inventing a p-value", () => {
    render(<ValidationPanel data={{ monte_carlo: { error: "Equity must remain positive" } }} />);
    expect(screen.getByText("Equity must remain positive")).toBeInTheDocument();
    expect(screen.queryByText("1.0000")).not.toBeInTheDocument();
  });
});
