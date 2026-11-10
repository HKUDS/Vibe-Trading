import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { buildPayoffRequest, DEFAULT_PARAMS, type OptionLeg } from "@/lib/options";
import { StrategyBuilder } from "../StrategyBuilder";

function Builder() {
  const [legs, setLegs] = useState<OptionLeg[]>([{ option_type: "call", strike: 100, qty: 1 }]);
  return <>
    <StrategyBuilder legs={legs} params={DEFAULT_PARAMS} activePresetId={null}
      onApplyPreset={() => {}} onLegsChange={setLegs} onParamsChange={() => {}} />
    <output data-testid="request">{JSON.stringify(buildPayoffRequest(legs, DEFAULT_PARAMS))}</output>
  </>;
}

it.each(["1.9", "-1.9"])("keeps fractional quantity %s invalid instead of truncating it", (value) => {
  render(<Builder />);
  const input = screen.getByLabelText("Qty 1");
  fireEvent.change(input, { target: { value } });
  expect(input).toHaveValue(Number(value));
  expect(screen.getByTestId("request")).toHaveTextContent("null");
});

it("uses the full numeric quantity for scientific notation and rejects an empty input", () => {
  render(<Builder />);
  const input = screen.getByLabelText("Qty 1");
  fireEvent.change(input, { target: { value: "1e2" } });
  expect(JSON.parse(screen.getByTestId("request").textContent!).legs[0].qty).toBe(100);
  fireEvent.change(input, { target: { value: "" } });
  expect(screen.getByTestId("request")).toHaveTextContent("null");
  fireEvent.change(input, { target: { value: "-2" } });
  expect(JSON.parse(screen.getByTestId("request").textContent!).legs[0].qty).toBe(-2);
});
