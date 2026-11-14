import { render, screen, within } from "@testing-library/react";
import type { PayoffComparison } from "@/lib/options";
import { PayoffComparisons } from "../PayoffComparisons";

const comparisons: PayoffComparison[] = [
  {
    left_label: "Collar",
    right_label: "Base",
    status: "ok",
    metrics: {
      max_profit_return: {
        left_decimal: 0.12,
        right_decimal: 0.2,
        relation: "lower",
        difference_percentage_points: -8,
      },
      max_loss_return: {
        left_decimal: -0.05,
        right_decimal: -0.15,
        relation: "higher",
        difference_percentage_points: 10,
      },
      entry_cost_return: { status: "unavailable", reason: "Unbounded payoff has no finite return" },
    },
  },
  {
    left_label: "Broken",
    right_label: "Base",
    status: "unavailable",
    reason: "No entry stock notional for rate comparison",
  },
];

function renderTable() {
  render(
    <PayoffComparisons
      label="Base"
      alternatives={[{ label: "Collar", legs: [] }]}
      legs={[]}
      comparisons={comparisons}
      onChange={() => {}}
    />,
  );
  return screen.getByRole("table");
}

it("labels every comparison metric and relation with its translated string", () => {
  const table = renderTable();

  for (const header of ["Metric", "Alternative", "Base", "Difference (percentage points)"]) {
    expect(within(table).getByRole("columnheader", { name: header })).toBeInTheDocument();
  }
  expect(within(table).getByText("Maximum return")).toBeInTheDocument();
  expect(within(table).getByText("Minimum return")).toBeInTheDocument();
  expect(within(table).getByText("Entry cost / stock notional")).toBeInTheDocument();
  expect(within(table).getByText("Lower · -8.00")).toBeInTheDocument();
  expect(within(table).getByText("Higher · 10.00")).toBeInTheDocument();
  expect(within(table).queryByText(/options\.comparison\./)).not.toBeInTheDocument();
});

it("shows an unavailable metric as having no rates and keeps the unavailable comparison reason", () => {
  const table = renderTable();

  const rows = within(table).getAllByRole("row");
  const costRow = rows.find((row) => within(row).queryByText("Entry cost / stock notional"));
  expect(costRow).toBeDefined();
  const cells = within(costRow!).getAllByRole("cell");
  expect(cells.map((cell) => cell.textContent)).toEqual([
    "Entry cost / stock notional",
    "Collar: —",
    "Base: —",
    "—",
  ]);
  expect(
    within(table).getByText("Broken: No entry stock notional for rate comparison"),
  ).toBeInTheDocument();
});
