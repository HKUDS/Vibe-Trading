import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowDown, ArrowUp, ExternalLink, Landmark, RefreshCw, Search } from "lucide-react";
import { KenyaBoardTreemap } from "@/components/charts/KenyaBoardTreemap";
import { api, type KenyaBoardResponse, type KenyaBoardRow } from "@/lib/api";
import { cn } from "@/lib/utils";

type SortKey = "code" | "close" | "change_pct" | "volume" | "turnover";

const fmtPrice = (v: number | null) =>
  v === null ? "—" : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtCompact = (v: number) =>
  v.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 2 });

/** Up/down colours follow the locale, as the charts do: red is up in Chinese. */
function upDownClass(value: number, lang: string): string {
  if (value === 0) return "text-muted-foreground";
  const redUp = lang.startsWith("zh");
  return (value > 0) !== redUp ? "text-success" : "text-danger";
}

function Pct({ value }: { value: number | null }) {
  const { i18n } = useTranslation();
  if (value === null) return <span className="text-muted-foreground">—</span>;
  const cls = upDownClass(value, i18n.language || "");
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return <span className={cn("tabular-nums", cls)}>{`${sign}${Math.abs(value).toFixed(2)}%`}</span>;
}

/** Position of the close inside the 52-week range, as a thin bar. */
function RangeBar({ row }: { row: KenyaBoardRow }) {
  const { hi52, lo52, close } = row;
  if (hi52 === null || lo52 === null || close === null || hi52 <= lo52) {
    return <span className="text-muted-foreground">—</span>;
  }
  const pos = Math.max(0, Math.min(100, ((close - lo52) / (hi52 - lo52)) * 100));
  return (
    <span className="inline-flex items-center gap-2" title={`${fmtPrice(lo52)} – ${fmtPrice(hi52)}`}>
      <span className="relative inline-block h-1 w-20 rounded bg-muted">
        <span className="absolute -top-1 h-3 w-0.5 bg-foreground" style={{ left: `${pos}%` }} />
      </span>
    </span>
  );
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: "up" | "down" }) {
  const { i18n } = useTranslation();
  const toneClass = tone ? upDownClass(tone === "up" ? 1 : -1, i18n.language || "") : undefined;
  return (
    <div className="flex flex-col gap-1 rounded-lg border p-3">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span
        className={cn("text-xl font-semibold tabular-nums", toneClass)}
      >
        {value}
      </span>
    </div>
  );
}

function MoverList({ title, rows, metric }: { title: string; rows: KenyaBoardRow[]; metric: "pct" | "turnover" }) {
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-lg border p-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ol className="flex flex-col gap-1.5">
        {rows.map((row) => (
          <li key={row.isin} className="flex items-center justify-between gap-3 text-sm">
            <span className="flex min-w-0 flex-1 items-baseline gap-2 overflow-hidden">
              <span className="font-mono font-semibold">{row.code ?? "—"}</span>
              <span className="truncate text-xs text-muted-foreground">{row.name}</span>
            </span>
            <span className="shrink-0">
              {metric === "pct" ? (
                <Pct value={row.change_pct} />
              ) : (
                <span className="tabular-nums text-muted-foreground">{fmtCompact(row.turnover)}</span>
              )}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function KenyaBoard() {
  const { t } = useTranslation();
  const [board, setBoard] = useState<KenyaBoardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<string>("");
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState("all");
  const [tradedOnly, setTradedOnly] = useState(true);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "turnover", dir: -1 });
  const generation = useRef(0);

  const load = useCallback(async (date?: string) => {
    const gen = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const result = await api.getKenyaBoard(date || undefined);
      if (generation.current === gen) setBoard(result);
    } catch (e) {
      if (generation.current === gen) setError(e instanceof Error ? e.message : t("kenyaBoard.error"));
    } finally {
      if (generation.current === gen) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const traded = useMemo(() => (board?.rows ?? []).filter((r) => r.traded), [board]);
  const sectors = useMemo(
    () => [...new Set((board?.rows ?? []).map((r) => r.sector).filter((s): s is string => !!s))].sort(),
    [board],
  );
  const turnover = useMemo(() => traded.reduce((sum, r) => sum + r.turnover, 0), [traded]);

  const movers = useMemo(() => {
    const withPct = traded.filter((r) => r.change_pct !== null);
    const byPct = [...withPct].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
    return {
      gainers: byPct.filter((r) => (r.change_pct ?? 0) > 0).slice(0, 5),
      losers: byPct.filter((r) => (r.change_pct ?? 0) < 0).reverse().slice(0, 5),
      active: [...traded].sort((a, b) => b.turnover - a.turnover).slice(0, 5),
    };
  }, [traded]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = (board?.rows ?? []).filter((r) => {
      if (tradedOnly && !r.traded) return false;
      if (sector !== "all" && r.sector !== sector) return false;
      if (q && !(r.code ?? "").toLowerCase().includes(q) && !r.name.toLowerCase().includes(q)) return false;
      return true;
    });
    const { key, dir } = sort;
    return filtered.sort((a, b) => {
      if (key === "code") return (a.code ?? a.name).localeCompare(b.code ?? b.name) * dir;
      const av = a[key] ?? Number.NEGATIVE_INFINITY;
      const bv = b[key] ?? Number.NEGATIVE_INFINITY;
      return (av === bv ? 0 : av < bv ? -1 : 1) * dir;
    });
  }, [board, query, sector, tradedOnly, sort]);

  const toggleSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: key === "code" ? 1 : -1 }));

  const SortHead = ({ k, label, right }: { k: SortKey; label: string; right?: boolean }) => (
    <th className={cn("px-3 py-2 font-medium", right && "text-right")}>
      <button
        type="button"
        onClick={() => toggleSort(k)}
        className={cn("inline-flex items-center gap-1 hover:text-foreground", sort.key === k && "text-foreground")}
      >
        {label}
        {sort.key === k && (sort.dir === 1 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  );

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-3">
            <Landmark className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold">{t("kenyaBoard.title")}</h1>
          </div>
          <p className="max-w-2xl text-sm text-muted-foreground">{t("kenyaBoard.subtitle")}</p>
        </div>
        <div className="flex items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            {t("kenyaBoard.session")}
            <input
              type="date"
              value={session}
              max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => {
                setSession(e.target.value);
                void load(e.target.value);
              }}
              className="rounded-md border bg-background px-2 py-1.5 text-sm text-foreground"
            />
          </label>
          <button
            type="button"
            onClick={() => {
              setSession("");
              void load();
            }}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:border-primary"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            {t("kenyaBoard.latest")}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/40 bg-danger/5 p-4 text-sm">
          <span>{error}</span>
          <button type="button" onClick={() => void load(session)} className="underline">
            {t("kenyaBoard.retry")}
          </button>
        </div>
      )}

      {loading && !board && (
        <div className="flex h-[40vh] items-center justify-center text-sm text-muted-foreground">
          {t("kenyaBoard.loading")}
        </div>
      )}

      {board && (
        <>
          {/* Session line */}
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="font-medium">{t("kenyaBoard.asOf", { date: board.as_of })}</span>
            <a
              href={board.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
            >
              {t("kenyaBoard.source")}
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>

          {/* Breadth */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label={t("kenyaBoard.listed")} value={board.breadth.listed} />
            <Stat label={t("kenyaBoard.traded")} value={board.breadth.traded} />
            <Stat label={t("kenyaBoard.advancers")} value={board.breadth.advancers} tone="up" />
            <Stat label={t("kenyaBoard.decliners")} value={board.breadth.decliners} tone="down" />
            <Stat label={t("kenyaBoard.unchanged")} value={board.breadth.unchanged} />
            <Stat label={t("kenyaBoard.turnover")} value={`KES ${fmtCompact(turnover)}`} />
          </div>

          {/* Movers */}
          <div className="grid gap-3 md:grid-cols-3">
            <MoverList title={t("kenyaBoard.topGainers")} rows={movers.gainers} metric="pct" />
            <MoverList title={t("kenyaBoard.topLosers")} rows={movers.losers} metric="pct" />
            <MoverList title={t("kenyaBoard.mostActive")} rows={movers.active} metric="turnover" />
          </div>

          {/* Treemap */}
          <div className="flex flex-col gap-2 rounded-lg border p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold">{t("kenyaBoard.treemapTitle")}</h2>
              <span className="text-xs text-muted-foreground">{t("kenyaBoard.treemapHint")}</span>
            </div>
            <KenyaBoardTreemap rows={board.rows} />
          </div>

          {/* Table controls */}
          <div className="flex flex-wrap items-center gap-3">
            <label className="relative flex-1 min-w-[12rem]">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("kenyaBoard.search")}
                aria-label={t("kenyaBoard.search")}
                className="w-full rounded-md border bg-background py-2 pl-8 pr-3 text-sm"
              />
            </label>
            <select
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              aria-label={t("kenyaBoard.colSector")}
              className="rounded-md border bg-background px-2 py-2 text-sm"
            >
              <option value="all">{t("kenyaBoard.allSectors")}</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={tradedOnly}
                onChange={(e) => setTradedOnly(e.target.checked)}
                className="h-4 w-4"
              />
              {t("kenyaBoard.tradedOnly")}
            </label>
          </div>

          {/* Table */}
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr>
                  <SortHead k="code" label={t("kenyaBoard.colCode")} />
                  <th className="px-3 py-2 font-medium">{t("kenyaBoard.colSector")}</th>
                  <SortHead k="close" label={t("kenyaBoard.colClose")} right />
                  <SortHead k="change_pct" label={t("kenyaBoard.colChange")} right />
                  <SortHead k="volume" label={t("kenyaBoard.colVolume")} right />
                  <SortHead k="turnover" label={t("kenyaBoard.colTurnover")} right />
                  <th className="px-3 py-2 font-medium">{t("kenyaBoard.colRange")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">
                      {t("kenyaBoard.noMatches")}
                    </td>
                  </tr>
                )}
                {rows.map((row) => (
                  <tr key={row.isin} className="border-t hover:bg-muted/30">
                    <td className="px-3 py-2">
                      <div className="font-mono font-semibold">{row.code ?? row.isin}</div>
                      <div className="max-w-[16rem] truncate text-xs text-muted-foreground">{row.name}</div>
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{row.sector ?? "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmtPrice(row.close)}</td>
                    <td className="px-3 py-2 text-right">
                      {row.traded ? (
                        <Pct value={row.change_pct} />
                      ) : (
                        <span className="text-xs text-muted-foreground">{t("kenyaBoard.notTraded")}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{row.traded ? fmtCompact(row.volume) : "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{row.traded ? fmtCompact(row.turnover) : "—"}</td>
                    <td className="px-3 py-2">
                      <RangeBar row={row} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-muted-foreground">
            {t("kenyaBoard.vwapNote")} {t("kenyaBoard.backtestHint")}
          </p>
        </>
      )}
    </div>
  );
}
