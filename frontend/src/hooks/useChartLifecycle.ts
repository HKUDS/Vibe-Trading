import { useEffect, useRef } from "react";
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
  const resource = useRef<{ node: HTMLDivElement; chart: ReturnType<typeof echarts.init>; observer: ResizeObserver; frame: number | null } | null>(null);
  const dispose = () => {
    const current = resource.current;
    if (!current) return;
    current.observer.disconnect();
    if (current.frame !== null) cancelAnimationFrame(current.frame);
    current.chart.dispose();
    resource.current = null;
  };
  useEffect(() => dispose, []);
  useEffect(() => {
    if (resource.current?.node !== ref.current) dispose();
    if (!ref.current) return;
    if (!resource.current) {
      const chart = echarts.init(ref.current);
      chart.group = CHART_GROUP;
      connectCharts();
      const current = { node: ref.current, chart, observer: null as unknown as ResizeObserver, frame: null as number | null };
      current.observer = new ResizeObserver(() => {
        if (current.frame !== null) cancelAnimationFrame(current.frame);
        current.frame = requestAnimationFrame(() => {
          current.frame = null;
          chart.resize();
        });
      });
      current.observer.observe(ref.current);
      resource.current = current;
    }
    // Replace options so removed legs/series cannot survive a parameter edit.
    resource.current.chart.setOption(buildOption(), { notMerge: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, dark]);
}
