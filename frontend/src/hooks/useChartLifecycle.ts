import { useEffect } from "react";
import type { RefObject } from "react";
import type { EChartsCoreOption } from "echarts/core";
import { echarts, CHART_GROUP, connectCharts } from "@/lib/echarts";
import { useThemeDark } from "@/lib/theme-store";

/**
 * Shared ECharts lifecycle: init on mount, rebuild the option whenever `deps`
 * (or the dark theme) change, keep the canvas sized with a ResizeObserver +
 * requestAnimationFrame, and dispose on teardown. Instances join CHART_GROUP
 * so axis pointers stay connected across the charts rendered together.
 *
 * `deps` are the data props the built option depends on; `buildOption` itself
 * is re-evaluated from the current closure on every effect run, so callers pass
 * the same dependency list they would have given the inline effect (minus the
 * manual dark handling this hook already provides).
 */
export function useChartLifecycle(
  ref: RefObject<HTMLDivElement | null>,
  buildOption: () => EChartsCoreOption,
  deps: readonly unknown[],
): void {
  const dark = useThemeDark();
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.group = CHART_GROUP;
    connectCharts();
    chart.setOption(buildOption());

    let resizeFrame: number | null = null;
    const ro = new ResizeObserver(() => {
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        resizeFrame = null;
        chart.resize();
      });
    });
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      chart.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, dark]);
}
