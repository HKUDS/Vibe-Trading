import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { CalendarRange, Database, FlaskConical } from "lucide-react";
import i18n from "@/i18n";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useThemeDark } from "@/lib/theme-store";
import type { RunData } from "@/lib/api";

const BLUE = "#3676df";
const DEEP_BLUE = "#2156ae";
const ORANGE = "#ff8a3d";
const GREEN = "#3b9b8f";
const SLATE = "#8f98a6";

function num(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function fixed(value: unknown, digits = 2): string {
  const parsed = num(value);
  return parsed == null ? "—" : parsed.toFixed(digits);
}

function pct(value: unknown, digits = 1): string {
  const parsed = num(value);
  return parsed == null ? "—" : `${(parsed * 100).toFixed(digits)}%`;
}

function timestamp(row: Record<string, string>): string {
  return row.timestamp || row.time || row.date || "";
}

type ReportIdentity = {
  title: string;
  strategy: string;
  strategyInferred: boolean;
  symbols: string[];
  startDate: string;
  endDate: string;
  source: string;
  engine: string;
};

function compactPrompt(prompt: string): string {
  const firstClause = prompt.trim().split(/[。.!！?？;；\n]/, 1)[0] || "";
  return firstClause.length > 68 ? `${firstClause.slice(0, 65).trim()}…` : firstClause;
}

function inferStrategyName(prompt: string): string {
  const zhMa = prompt.match(/(\d+)\s*(?:日|天)?\s*[\/／-]\s*(\d+)\s*(?:日|天)?[^。；,，]{0,18}均线/i)
    || prompt.match(/(\d+)\s*日均线[^。；,，]{0,18}(\d+)\s*日均线/i);
  if (zhMa) return i18n.t("runDashboard.strategyMaCrossover", { fast: zhMa[1], slow: zhMa[2] });

  const enMa = prompt.match(/(\d+)\s*[\/\-]\s*(\d+)[^.!?]{0,28}(?:moving[ -]?average|\bma\b)/i)
    || prompt.match(/(?:moving[ -]?average|\bma\b)[^.!?]{0,28}(\d+)\s*[\/\-]\s*(\d+)/i);
  if (enMa) return i18n.t("runDashboard.strategyMaCrossover", { fast: enMa[1], slow: enMa[2] });

  if (/macd/i.test(prompt)) return i18n.t("runDashboard.strategyMacd");
  if (/rsi/i.test(prompt)) return i18n.t("runDashboard.strategyRsi");
  if (/动量|momentum/i.test(prompt)) return i18n.t("runDashboard.strategyMomentum");
  if (/均值回归|mean reversion/i.test(prompt)) return i18n.t("runDashboard.strategyMeanReversion");
  if (/突破|breakout/i.test(prompt)) return i18n.t("runDashboard.strategyBreakout");
  return compactPrompt(prompt) || i18n.t("runDashboard.systematicStrategy");
}

export function getStrategyReportIdentity(run: RunData): ReportIdentity {
  const backtest = (run.run_card?.backtest || {}) as Record<string, unknown>;
  const symbols = (Array.isArray(backtest.codes) ? backtest.codes : run.chart_symbols || [])
    .map(String)
    .filter(Boolean);
  const prompt = run.prompt || "";
  const strategy = inferStrategyName(prompt);
  const symbolLabel = symbols.length === 0
    ? i18n.t("runDashboard.portfolio")
    : symbols.length <= 2
      ? symbols.join(" + ")
      : `${symbols[0]} +${symbols.length - 1}`;
  const fallbackRows = run.artifacts_equity_csv || [];
  const startDate = String(backtest.start_date || (fallbackRows[0] ? timestamp(fallbackRows[0]) : ""));
  const endDate = String(backtest.end_date || (fallbackRows.length ? timestamp(fallbackRows[fallbackRows.length - 1]) : ""));
  return {
    title: `${symbolLabel} · ${strategy}`,
    strategy,
    strategyInferred: true,
    symbols,
    startDate,
    endDate,
    source: String((run.run_card?.data_sources || [])[0] || backtest.source || ""),
    engine: String(backtest.engine || ""),
  };
}

function rollingSharpe(rows: Array<Record<string, string>>, window = 20): Array<number | null> {
  const returns = rows.map((row) => num(row.ret));
  return returns.map((_, index) => {
    if (index + 1 < window) return null;
    const sample = returns
      .slice(index + 1 - window, index + 1)
      .filter((value): value is number => value != null);
    if (sample.length < window) return null;
    const mean = sample.reduce((sum, value) => sum + value, 0) / sample.length;
    const variance = sample.reduce((sum, value) => sum + (value - mean) ** 2, 0)
      / Math.max(1, sample.length - 1);
    const std = Math.sqrt(variance);
    return std > 0 ? (mean / std) * Math.sqrt(252) : 0;
  });
}

function FigureTitle({ index, title, note }: { index: string; title: string; note: string }) {
  return (
    <div className="border-l-4 border-[#3676df] pl-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-[#3676df]">Figure {index}</p>
      <h3 className="mt-0.5 text-sm font-semibold text-foreground">{title}</h3>
      <p className="mt-1 text-xs text-muted-foreground">{note}</p>
    </div>
  );
}

export function StrategyResearchDashboard({ run }: { run: RunData }) {
  const { t } = useTranslation();
  const navRef = useRef<HTMLDivElement>(null);
  const riskRef = useRef<HTMLDivElement>(null);
  const tradesRef = useRef<HTMLDivElement>(null);
  const dark = useThemeDark();

  const equityRows = useMemo<Array<Record<string, string>>>(() => {
    if (run.artifacts_equity_csv?.length) return run.artifacts_equity_csv;
    return (run.equity_curve || []).map((row) => ({
      timestamp: row.time,
      equity: String(row.equity),
      drawdown: String(row.drawdown ?? ""),
    }));
  }, [run.artifacts_equity_csv, run.equity_curve]);
  const trades = run.artifacts_trades_csv?.length
    ? run.artifacts_trades_csv
    : run.trade_log || [];
  const identity = useMemo(() => getStrategyReportIdentity(run), [run]);

  useEffect(() => {
    const nodes = [navRef.current, riskRef.current, tradesRef.current];
    if (nodes.some((node) => !node)) return;
    const charts = nodes.map((node) => echarts.init(node!));
    const [navChart, riskChart, tradeChart] = charts;
    const theme = getChartTheme();
    const axis = {
      axisLine: { lineStyle: { color: theme.axisColor } },
      axisLabel: { color: theme.textColor, fontSize: 10 },
      splitLine: { lineStyle: { color: theme.gridColor } },
    };
    const dates = equityRows.map(timestamp);
    const equities = equityRows.map((row) => num(row.equity));
    const benchmarks = equityRows.map((row) => num(row.benchmark_equity));
    const firstEquity = equities.find((value): value is number => value != null && value !== 0) || 1;
    const firstBenchmark = benchmarks.find((value): value is number => value != null && value !== 0) || 1;

    navChart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { top: 0, right: 4, textStyle: { color: theme.textColor, fontSize: 10 } },
      grid: { left: 18, right: 22, top: 32, bottom: 18, containLabel: true },
      xAxis: { ...axis, type: "category", data: dates, boundaryGap: false },
      yAxis: { ...axis, type: "value", axisLabel: { color: theme.textColor, fontSize: 10, formatter: (v: number) => `${v.toFixed(2)}x` } },
      series: [
        { name: t("runDashboard.seriesStrategy"), type: "line", showSymbol: false, data: equities.map((v) => v == null ? null : v / firstEquity), lineStyle: { color: BLUE, width: 2.5 }, itemStyle: { color: BLUE } },
        ...(benchmarks.some((value) => value != null) ? [{ name: t("runDashboard.seriesBenchmark"), type: "line", showSymbol: false, data: benchmarks.map((v) => v == null ? null : v / firstBenchmark), lineStyle: { color: SLATE, width: 1.5, type: "dashed" }, itemStyle: { color: SLATE } }] : []),
      ],
    });

    const drawdown = equityRows.map((row) => num(row.drawdown));
    const sharpe = rollingSharpe(equityRows);
    riskChart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { top: 0, right: 4, textStyle: { color: theme.textColor, fontSize: 10 } },
      grid: { left: 18, right: 24, top: 32, bottom: 18, containLabel: true },
      xAxis: { ...axis, type: "category", data: dates, boundaryGap: false },
      yAxis: [
        { ...axis, type: "value", axisLabel: { color: theme.textColor, fontSize: 10, formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
        { ...axis, type: "value", splitLine: { show: false }, axisLabel: { color: theme.textColor, fontSize: 10 } },
      ],
      series: [
        { name: t("runDashboard.seriesDrawdown"), type: "line", showSymbol: false, data: drawdown, lineStyle: { color: ORANGE, width: 2 }, areaStyle: { color: "rgba(255,138,61,.10)" }, itemStyle: { color: ORANGE } },
        { name: t("runDashboard.seriesRollingSharpe"), type: "line", yAxisIndex: 1, showSymbol: false, connectNulls: false, data: sharpe, lineStyle: { color: GREEN, width: 1.5 }, itemStyle: { color: GREEN } },
      ],
    });

    const exits = trades.filter((trade) => (num(trade.pnl) || 0) !== 0).slice(-60);
    tradeChart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { left: 18, right: 18, top: 14, bottom: 18, containLabel: true },
      xAxis: { ...axis, type: "category", data: exits.map((trade, index) => trade.timestamp || String(index + 1)), axisLabel: { color: theme.textColor, fontSize: 9, hideOverlap: true } },
      yAxis: { ...axis, type: "value" },
      series: [{ type: "bar", barMaxWidth: 12, data: exits.map((trade) => { const value = num(trade.pnl) || 0; return { value, itemStyle: { color: value >= 0 ? GREEN : ORANGE } }; }) }],
    });

    let frame: number | null = null;
    const observer = new ResizeObserver(() => {
      if (frame != null) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => charts.forEach((chart) => chart.resize()));
    });
    nodes.forEach((node) => observer.observe(node!));
    return () => {
      observer.disconnect();
      if (frame != null) cancelAnimationFrame(frame);
      charts.forEach((chart) => chart.dispose());
    };
  }, [dark, equityRows, trades]);

  // This dashboard is built around a classic equity-curve backtest. A
  // portfolio-construction / risk-snapshot run (risk_xray, rebalance_notes)
  // has neither, so every KPI and chart here would silently render as
  // dashes/blank -- which reads as "broken", not "different run type". Point
  // to the Studio tab instead, which actually renders that run's data.
  if (equityRows.length === 0 && trades.length === 0 && (run.risk_xray || run.rebalance_notes)) {
    return (
      <div className="mx-auto max-w-[640px] rounded-xl border border-[#dfe2e7] bg-card p-8 text-center shadow-sm">
        <FlaskConical className="mx-auto h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <p className="mt-3 text-sm font-medium text-foreground">{t("runDashboard.noBacktestData")}</p>
        <p className="mt-1 text-sm text-muted-foreground">{t("runDashboard.noBacktestDataStudioHint")}</p>
      </div>
    );
  }

  const metrics: Record<string, number> = run.metrics || {};
  const kpis = [
    [t("runDashboard.kpiTotalReturn"), pct(metrics.total_return), BLUE],
    [t("runDashboard.kpiAnnualReturn"), pct(metrics.annual_return), DEEP_BLUE],
    ["Sharpe", fixed(metrics.sharpe), GREEN],
    [t("runDashboard.kpiMaxDrawdown"), pct(metrics.max_drawdown), ORANGE],
    [t("runDashboard.kpiWinRate"), pct(metrics.win_rate), GREEN],
    [t("runDashboard.kpiTrades"), fixed(metrics.trade_count, 0), SLATE],
  ] as const;

  return (
    <article className="mx-auto max-w-[1180px] overflow-hidden border border-[#dfe2e7] bg-card shadow-sm">
      <header className="relative overflow-hidden border-b border-[#dfe2e7] bg-gradient-to-br from-[#3676df]/[0.10] via-background to-[#3b9b8f]/[0.05] p-5 md:p-8">
        <div className="absolute -right-16 -top-20 h-52 w-52 rounded-full bg-[#3676df]/[0.08] blur-3xl" aria-hidden="true" />
        <div className="relative">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-[#3676df]">{t("runDashboard.eyebrow")}</p>
            <span className="rounded-full border border-[#3676df]/20 bg-background/70 px-2.5 py-1 font-mono text-[10px] text-muted-foreground">RUN {run.run_id.slice(-8).toUpperCase()}</span>
          </div>
          <div className="mt-4 flex max-w-4xl flex-wrap items-center gap-2">
            <h2 className="text-2xl font-semibold leading-tight tracking-[-0.025em] text-foreground md:text-[30px]">{identity.title}</h2>
            {identity.strategyInferred && (
              <span className="inline-flex items-center gap-1 rounded-full border border-[#ff8a3d]/30 bg-[#ff8a3d]/10 px-2 py-0.5 text-[11px] text-[#c25a14]">
                {t("runDashboard.strategyInferred")}
              </span>
            )}
          </div>
          {run.prompt && (
            <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">{compactPrompt(run.prompt)}</p>
          )}
          <div className="mt-5 flex flex-wrap gap-2 text-xs text-muted-foreground">
            {(identity.startDate || identity.endDate) && <span className="inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-background/65 px-2.5 py-1.5"><CalendarRange className="h-3.5 w-3.5 text-[#3676df]" />{identity.startDate || "—"} — {identity.endDate || "—"}</span>}
            {identity.engine && <span className="inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-background/65 px-2.5 py-1.5"><FlaskConical className="h-3.5 w-3.5 text-[#3676df]" />{identity.engine.toUpperCase()} {t("runDashboard.engine")}</span>}
            {identity.source && <span className="inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-background/65 px-2.5 py-1.5"><Database className="h-3.5 w-3.5 text-[#3676df]" />{identity.source}</span>}
          </div>
        </div>
      </header>

      <div className="grid grid-cols-2 border-b border-[#dfe2e7] md:grid-cols-3 lg:grid-cols-6">
        {kpis.map(([label, value, color]) => <div key={label} className="border-b border-r border-[#dfe2e7] p-4 lg:border-b-0"><p className="text-[11px] text-muted-foreground">{label}</p><p className="mt-1 font-mono text-xl font-semibold tabular-nums" style={{ color }}>{value}</p></div>)}
      </div>

      <div className="space-y-8 p-5 md:p-7">
        <section className="space-y-3"><FigureTitle index="01" title={t("runDashboard.figEquityTitle")} note={t("runDashboard.figEquityNote")} /><div ref={navRef} className="h-[320px] border border-[#dfe2e7] bg-background/40" /></section>
        <section className="space-y-3"><FigureTitle index="02" title={t("runDashboard.figRiskTitle")} note={t("runDashboard.figRiskNote")} /><div ref={riskRef} className="h-[300px] border border-[#dfe2e7] bg-background/40" /></section>
        <section className="space-y-3"><FigureTitle index="03" title={t("runDashboard.figPnlTitle")} note={t("runDashboard.figPnlNote")} /><div ref={tradesRef} className="h-[260px] border border-[#dfe2e7] bg-background/40" /></section>
        <section className="space-y-3"><FigureTitle index="04" title={t("runDashboard.figLedgerTitle")} note={t("runDashboard.figLedgerNote")} /><TradeTable rows={trades.slice(-100).reverse()} /></section>
        <section className="space-y-3"><FigureTitle index="05" title={t("runDashboard.figMetricsTitle")} note={t("runDashboard.figMetricsNote")} /><MetricTable metrics={metrics} /></section>
      </div>
    </article>
  );
}

function TradeTable({ rows }: { rows: Array<Record<string, string>> }) {
  const { t } = useTranslation();
  if (!rows.length) return <EmptyData text={t("runDashboard.noTrades")} />;
  return <div className="max-h-[440px] overflow-auto border border-[#dfe2e7]"><table className="w-full min-w-[760px] text-xs"><thead className="sticky top-0 bg-[#f5f7fa] text-muted-foreground dark:bg-slate-900"><tr><th className="px-3 py-2 text-left">{t("runDashboard.colTime")}</th><th className="px-3 py-2 text-left">{t("runDashboard.colSymbol")}</th><th className="px-3 py-2 text-left">{t("runDashboard.colSide")}</th><th className="px-3 py-2 text-right">{t("runDashboard.colPrice")}</th><th className="px-3 py-2 text-right">{t("runDashboard.colQty")}</th><th className="px-3 py-2 text-right">{t("runDashboard.colPnl")}</th><th className="px-3 py-2 text-left">{t("runDashboard.colReason")}</th></tr></thead><tbody>{rows.map((row, index) => { const pnl = num(row.pnl) || 0; return <tr key={`${row.timestamp}-${row.code}-${index}`} className="border-t border-[#dfe2e7]"><td className="px-3 py-2 font-mono">{row.timestamp || "—"}</td><td className="px-3 py-2 font-mono">{row.code || "—"}</td><td className="px-3 py-2 uppercase">{row.side || "—"}</td><td className="px-3 py-2 text-right font-mono">{fixed(row.price, 4)}</td><td className="px-3 py-2 text-right font-mono">{fixed(row.qty, 4)}</td><td className="px-3 py-2 text-right font-mono font-semibold" style={{ color: pnl > 0 ? GREEN : pnl < 0 ? ORANGE : SLATE }}>{fixed(pnl)}</td><td className="px-3 py-2 text-muted-foreground">{row.reason || "—"}</td></tr>; })}</tbody></table></div>;
}

function MetricTable({ metrics }: { metrics: Record<string, number> }) {
  const entries = Object.entries(metrics);
  return <div className="overflow-x-auto border border-[#dfe2e7]"><table className="w-full text-xs"><tbody>{entries.map(([key, value]) => <tr key={key} className="border-b border-[#dfe2e7] last:border-0"><td className="w-1/2 bg-[#f5f7fa] px-3 py-2 font-mono text-muted-foreground dark:bg-slate-900">{key}</td><td className="px-3 py-2 text-right font-mono tabular-nums">{fixed(value, 4)}</td></tr>)}</tbody></table></div>;
}

function EmptyData({ text }: { text: string }) {
  return <div className="border border-dashed border-[#dfe2e7] p-6 text-center text-xs text-muted-foreground">{text}</div>;
}
