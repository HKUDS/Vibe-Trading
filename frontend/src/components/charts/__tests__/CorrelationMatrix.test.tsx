import { render } from "@testing-library/react";
import { CorrelationMatrix } from "../CorrelationMatrix";

const captured = vi.hoisted(() => ({ option: null as any }));
vi.mock("@/hooks/useChartLifecycle", () => ({
  useChartLifecycle: (_ref: unknown, build: () => unknown) => { captured.option = build(); },
}));

it("keeps unknown cells distinct from measured zero in labels and escaped tooltips", () => {
  render(<CorrelationMatrix labels={["<A>", "B", "C"]} matrix={[
    [1, null, 0], [null, 1, 0.5], [0, 0.5, 1],
  ]} />);
  const option = captured.option;
  const series = option.series[0];
  const unknown = series.data.find((d: any) => d.value[0] === 1 && d.value[1] === 0);
  const zero = series.data.find((d: any) => d.value[0] === 2 && d.value[1] === 0);
  expect(series.label.formatter(unknown)).toBe("—");
  expect(series.label.formatter(zero)).toBe("0.00");
  expect(unknown.itemStyle.opacity).toBeLessThan(1);
  expect(option.tooltip.formatter({ data: unknown })).toContain("undefined");
  expect(option.tooltip.formatter({ data: unknown })).toContain("&lt;A&gt;");
  expect(option.tooltip.formatter({ data: zero })).toContain("0.0000");
});
