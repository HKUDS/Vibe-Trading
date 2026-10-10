import { useRef } from "react";
import { render } from "@testing-library/react";
import { useChartLifecycle } from "../useChartLifecycle";

const chart = vi.hoisted(() => ({ init: vi.fn(), setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), dark: false }));
vi.mock("@/lib/echarts", () => ({ echarts: { init: chart.init }, CHART_GROUP: "analysis", connectCharts: vi.fn() }));
vi.mock("@/lib/theme-store", () => ({ useThemeDark: () => chart.dark }));
function Plot({ visible, value }: { visible: boolean; value: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useChartLifecycle(ref, () => ({ series: [{ data: [value] }] }), [visible, value]);
  return visible ? <div ref={ref} /> : null;
}
beforeEach(() => { vi.clearAllMocks(); chart.dark = false; chart.init.mockImplementation(() => chart); });
it("reuses a chart for data and theme edits, replaces removed series, and disposes it", () => {
  const page = render(<Plot visible value={1} />);
  page.rerender(<Plot visible value={2} />); chart.dark = true;
  page.rerender(<Plot visible value={3} />);
  expect(chart.init).toHaveBeenCalledTimes(1);
  expect(chart.setOption).toHaveBeenLastCalledWith({ series: [{ data: [3] }] }, { notMerge: true });
  page.rerender(<Plot visible={false} value={3} />);
  expect(chart.dispose).toHaveBeenCalledTimes(1);
  page.rerender(<Plot visible value={4} />); page.unmount();
  expect(chart.init).toHaveBeenCalledTimes(2); expect(chart.dispose).toHaveBeenCalledTimes(2);
});
