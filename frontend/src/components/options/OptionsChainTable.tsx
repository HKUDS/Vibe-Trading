import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useAnalysisState } from "@/hooks/useAnalysisState";
import {
  bidAskSpreadPct,
  expirationLabel,
  type OptionsChainData,
  type OptionsContractRow,
} from "@/lib/options";

const DEFAULT_TICKER = "AAPL";

function fmt(v: number | null, maxDigits = 2): string {
  if (v === null || !Number.isFinite(v)) return "–";
  return v.toLocaleString(undefined, { maximumFractionDigits: maxDigits });
}

function fmtInt(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "–";
  return Math.round(v).toLocaleString();
}

function fmtIv(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "–";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtSpread(bid: number | null, ask: number | null): string {
  const pct = bidAskSpreadPct(bid, ask);
  return pct === null ? "–" : `${pct.toFixed(2)}%`;
}

interface WingTableProps {
  title: string;
  rows: OptionsContractRow[];
  atmStrike: number | null;
  showAll?: boolean;
}

function WingTable({ title, rows, atmStrike, showAll }: WingTableProps) {
  const { t } = useTranslation();
  const sorted = useMemo(() => {
    const nearby = !showAll && atmStrike !== null
      ? [...rows].sort((a, b) => Math.abs(a.strike - atmStrike) - Math.abs(b.strike - atmStrike)).slice(0, 15)
      : rows;
    return [...nearby].sort((a, b) => a.strike - b.strike);
  }, [rows, atmStrike, showAll]);

  const headers = [
    t("options.chain.strike"),
    t("options.chain.last"),
    t("options.chain.bid"),
    t("options.chain.ask"),
    t("options.chain.spread"),
    t("options.chain.volume"),
    t("options.chain.openInterest"),
    t("options.chain.iv"),
    t("options.chain.itm"),
  ];

  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold text-muted-foreground">{title}</div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground">
              {headers.map((h, i) => (
                <th
                  key={h}
                  className={cn(
                    "border-b border-border/60 pb-1.5 pe-3 font-medium whitespace-nowrap",
                    i === 0 ? "text-start" : "text-end",
                  )}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const isAtm = atmStrike !== null && row.strike === atmStrike;
              return (
                <tr
                  key={row.contract_symbol}
                  className={cn(
                    "border-b border-border/30 transition-colors",
                    isAtm ? "bg-primary/10" : "hover:bg-muted/40",
                  )}
                >
                  <td className="py-1.5 pe-3 text-start font-medium tabular-nums whitespace-nowrap">
                    {fmt(row.strike)}
                    {isAtm && (
                      <span className="ms-1.5 rounded bg-primary/15 px-1 py-0.5 text-[10px] font-medium text-primary">
                        {t("options.chain.atm")}
                      </span>
                    )}
                  </td>
                  <td className="py-1.5 pe-3 text-end tabular-nums">{fmt(row.last_price)}</td>
                  <td className="py-1.5 pe-3 text-end tabular-nums">{fmt(row.bid)}</td>
                  <td className="py-1.5 pe-3 text-end tabular-nums">{fmt(row.ask)}</td>
                  <td className="py-1.5 pe-3 text-end tabular-nums text-muted-foreground">
                    {fmtSpread(row.bid, row.ask)}
                  </td>
                  <td className="py-1.5 pe-3 text-end tabular-nums">{fmtInt(row.volume)}</td>
                  <td className="py-1.5 pe-3 text-end tabular-nums">{fmtInt(row.open_interest)}</td>
                  <td className="py-1.5 pe-3 text-end tabular-nums">{fmtIv(row.implied_volatility)}</td>
                  <td className="py-1.5 text-end">
                    {row.in_the_money && (
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                        {t("options.chain.itm")}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SkeletonRows() {
  return (
    <div className="space-y-1.5 py-2">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <div key={i} className="h-6 rounded bg-muted/50 animate-pulse" />
      ))}
    </div>
  );
}

export function OptionsChainTable() {
  const { t } = useTranslation();
  const [draft, setDraft] = useAnalysisState("options-chain", { tickerInput: DEFAULT_TICKER, data: null as OptionsChainData | null, fetchedAt: "", showAll: false });
  const { tickerInput, data, fetchedAt, showAll } = draft;
  const setTickerInput = (tickerInput: string) => setDraft((d) => ({ ...d, tickerInput }));
  const setData = (data: OptionsChainData | null) => setDraft((d) => ({ ...d, data, fetchedAt: data ? new Date().toISOString() : "" }));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);

  const load = useCallback(async (ticker: string, expiration?: number) => {
    const gen = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const res = await api.getOptionsChain(ticker, expiration);
      if (generation.current !== gen) return;
      if (!res.ok || !res.data) {
        setError(res.error || t("options.chain.errorTitle"));
        setData(null);
        return;
      }
      setData(res.data);
    } catch (e) {
      if (generation.current !== gen) return;
      setError(e instanceof Error ? e.message : t("options.chain.errorTitle"));
      setData(null);
    } finally {
      if (generation.current === gen) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (!data) void load(tickerInput.trim().toUpperCase() || DEFAULT_TICKER);
    return () => { generation.current += 1; };
    // A restored chain is explicitly refreshed by its load button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const ticker = tickerInput.trim().toUpperCase();
    if (!ticker) return;
    void load(ticker);
  };

  const atmStrike = data?.atm_strike != null && Number.isFinite(data.atm_strike)
    && data.atm_strike > 0 ? data.atm_strike : null;

  return (
    <section className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm font-semibold">{t("options.chain.title")}</div>
        <form onSubmit={onSubmit} className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={tickerInput}
            onChange={(e) => setTickerInput(e.target.value)}
            placeholder={DEFAULT_TICKER}
            aria-label={t("options.chain.ticker")}
            className="w-24 rounded-md border border-border/60 bg-background px-2 py-1.5 text-sm uppercase outline-none focus:ring-2 focus:ring-primary/40"
          />
          <select
            value={data?.expiration ?? ""}
            onChange={(e) => {
              const exp = e.target.value === "" ? undefined : Number(e.target.value);
              if (data) void load(data.ticker, exp);
            }}
            disabled={!data || loading}
            aria-label={t("options.chain.expiration")}
            className="rounded-md border border-border/60 bg-background px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-50"
          >
            {(data?.expirations ?? []).map((exp) => (
              <option key={exp} value={exp}>
                {expirationLabel(exp)}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={loading}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {t("options.chain.load")}
          </button>
        </form>
      </div>

      {data && <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>{t("analysis.chainQuote", { ticker: data.ticker, price: fmt(data.underlying_price ?? null) })}</span>
        <span>{t("analysis.lastFetched", { time: fetchedAt ? new Date(fetchedAt).toLocaleString() : "–" })}</span>
        {atmStrike !== null && <button type="button" className="text-primary underline" onClick={() => setDraft((d) => ({ ...d, showAll: !d.showAll }))}>{t(showAll ? "analysis.nearAtm" : "analysis.allStrikes")}</button>}
      </div>}

      {error && (
        <div className="mb-3 flex items-center justify-between gap-3 rounded border border-danger/30 bg-danger/5 p-3 text-sm text-danger">
          <span>
            <b>{t("options.chain.errorTitle")}.</b> {error}
          </span>
          <button
            type="button"
            onClick={() => void load(data?.ticker ?? tickerInput.trim().toUpperCase() ?? DEFAULT_TICKER, data?.expiration)}
            className="shrink-0 rounded border border-danger/40 px-2.5 py-1 text-xs font-medium transition-colors hover:bg-danger/10"
          >
            {t("options.chain.retry")}
          </button>
        </div>
      )}

      {loading ? (
        <div aria-label={t("options.chain.loading")}>
          <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("options.chain.loading")}
          </div>
          <SkeletonRows />
        </div>
      ) : data ? (
        data.calls.length === 0 && data.puts.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("options.chain.noData")}</p>
        ) : (
          <div className="flex flex-col gap-5">
            {data.calls.length > 0 && (
              <WingTable title={t("options.chain.calls")} rows={data.calls} atmStrike={atmStrike} showAll={showAll} />
            )}
            {data.puts.length > 0 && (
              <WingTable title={t("options.chain.puts")} rows={data.puts} atmStrike={atmStrike} showAll={showAll} />
            )}
          </div>
        )
      ) : !error ? (
        <p className="text-sm text-muted-foreground">{t("options.chain.noData")}</p>
      ) : null}
    </section>
  );
}
