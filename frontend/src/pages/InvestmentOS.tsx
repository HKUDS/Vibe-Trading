import { useCallback, useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, ArrowRight, Copy, Cpu, Eye, FileText, Globe2, Loader2, ShieldCheck, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type InvestmentOSCandidate, type InvestmentOSDeepQuantSummary, type InvestmentOSMemo, type StockCoreMemoResponse } from "@/lib/api";

const fallbackCandidates: InvestmentOSCandidate[] = [
  {
    symbol: "VT",
    name: "Vanguard Total World Stock ETF",
    role: "default_global_core",
    status: "research_proxy",
    currency: "USD",
    vehicle_type: "ETF",
    notes: "Broad global equity beta proxy used by current backtests.",
  },
  {
    symbol: "VTI",
    name: "Vanguard Total Stock Market ETF",
    role: "us_core_alt",
    status: "watchlist",
    currency: "USD",
    vehicle_type: "ETF",
    notes: "US total-market alternative for sensitivity review.",
  },
  {
    symbol: "VOO",
    name: "Vanguard S&P 500 ETF",
    role: "us_core_alt",
    status: "sensitivity_proxy",
    currency: "USD",
    vehicle_type: "ETF",
    notes: "US large-cap comparison proxy already supported by proxy comparison.",
  },
  {
    symbol: "THB_GLOBAL_FEEDER_TBD",
    name: "Thai global equity feeder fund TBD",
    role: "thb_access",
    status: "research_required",
    currency: "THB",
    vehicle_type: "Thai feeder fund",
    notes: "Placeholder for broker/tax/access research before approval.",
  },
];

const policyGates = [
  "Human decision required before any candidate becomes policy-approved.",
  "Research reports must reference investment policy, risk policy, source date, and caveat.",
  "This screen organizes evidence only; it does not approve, recommend, or execute trades.",
] as const;

function statusClass(status: string) {
  if (status === "research_required") return "border-warning/30 bg-warning/10 text-warning";
  if (status === "research_proxy") return "border-info/30 bg-info/10 text-info";
  return "border-primary/30 bg-primary/10 text-primary";
}

function memoStatusClass(status: string) {
  if (status === "superseded") return "border-warning/30 bg-warning/10 text-warning";
  if (status === "archived") return "border-muted bg-muted text-muted-foreground";
  return "border-primary/30 bg-primary/10 text-primary";
}

function deepQuantStatusClass(status: string) {
  if (status === "ok") return "border-primary/30 bg-primary/10 text-primary";
  if (status === "missing" || status === "not_configured") return "border-warning/30 bg-warning/10 text-warning";
  return "border-danger/30 bg-danger/10 text-danger";
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function InvestmentOS() {
  const [candidates, setCandidates] = useState<InvestmentOSCandidate[]>(fallbackCandidates);
  const [source, setSource] = useState<"file" | "fallback">("fallback");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>(["VT"]);
  const [memoQuestion, setMemoQuestion] = useState("Which stock-core implementation should be researched for policy approval?");
  const [memoCreating, setMemoCreating] = useState(false);
  const [memoError, setMemoError] = useState<string | null>(null);
  const [memoResult, setMemoResult] = useState<StockCoreMemoResponse | null>(null);
  const [memos, setMemos] = useState<InvestmentOSMemo[]>([]);
  const [memosLoading, setMemosLoading] = useState(true);
  const [memosError, setMemosError] = useState<string | null>(null);
  const [selectedMemo, setSelectedMemo] = useState<InvestmentOSMemo | null>(null);
  const [selectedMemoContent, setSelectedMemoContent] = useState<string>("");
  const [selectedMemoLoading, setSelectedMemoLoading] = useState(false);
  const [statusUpdatingId, setStatusUpdatingId] = useState<string | null>(null);
  const [discardingId, setDiscardingId] = useState<string | null>(null);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [copiedPath, setCopiedPath] = useState<string | null>(null);
  const [showDiscarded, setShowDiscarded] = useState(false);
  const [deepQuantSummary, setDeepQuantSummary] = useState<InvestmentOSDeepQuantSummary | null>(null);
  const [deepQuantLoading, setDeepQuantLoading] = useState(true);
  const [deepQuantError, setDeepQuantError] = useState<string | null>(null);

  const loadMemos = useCallback(async () => {
    setMemosLoading(true);
    try {
      const response = await api.listInvestmentOSMemos(showDiscarded);
      setMemos(response.memos);
      setMemosError(null);
    } catch (error) {
      setMemosError(error instanceof Error ? error.message : "Failed to load research memos");
    } finally {
      setMemosLoading(false);
    }
  }, [showDiscarded]);

  useEffect(() => {
    let alive = true;
    api.listInvestmentOSCandidates()
      .then((response) => {
        if (!alive) return;
        setCandidates(response.stock_core_candidates);
        setSource(response.source);
        setLoadError(null);
      })
      .catch((error) => {
        if (!alive) return;
        setLoadError(error instanceof Error ? error.message : "Failed to load candidates");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    void loadMemos();
  }, [loadMemos]);

  useEffect(() => {
    let alive = true;
    api.getInvestmentOSDeepQuantSummary()
      .then((response) => {
        if (!alive) return;
        setDeepQuantSummary(response);
        setDeepQuantError(null);
      })
      .catch((error) => {
        if (!alive) return;
        setDeepQuantError(error instanceof Error ? error.message : "Failed to load DeepQuant summary");
      })
      .finally(() => {
        if (alive) setDeepQuantLoading(false);
      });
    return () => { alive = false; };
  }, []);

  const toggleSymbol = (symbol: string) => {
    setSelectedSymbols((current) => (
      current.includes(symbol)
        ? current.filter((item) => item !== symbol)
        : [...current, symbol]
    ));
  };

  const createMemo = async (event: FormEvent) => {
    event.preventDefault();
    setMemoCreating(true);
    setMemoError(null);
    try {
      const result = await api.createStockCoreMemo({
        symbols: selectedSymbols,
        question: memoQuestion.trim() || "Which stock-core implementation should be researched for policy approval?",
      });
      setMemoResult(result);
      await loadMemos();
    } catch (error) {
      setMemoError(error instanceof Error ? error.message : "Failed to create memo draft");
    } finally {
      setMemoCreating(false);
    }
  };

  const openMemo = async (memo: InvestmentOSMemo) => {
    setSelectedMemo(memo);
    setSelectedMemoLoading(true);
    try {
      const response = await api.getInvestmentOSMemo(memo.id);
      setSelectedMemo(response.memo);
      setSelectedMemoContent(response.content);
      setMemos((current) => current.map((item) => (item.id === response.memo.id ? response.memo : item)));
      setMemosError(null);
    } catch (error) {
      setMemosError(error instanceof Error ? error.message : "Failed to open memo review");
    } finally {
      setSelectedMemoLoading(false);
    }
  };

  const markSuperseded = async (memo: InvestmentOSMemo) => {
    setStatusUpdatingId(memo.id);
    try {
      const updated = await api.updateInvestmentOSMemoStatus(memo.id, "superseded");
      setMemos((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setSelectedMemo((current) => (current?.id === updated.id ? updated : current));
      setMemosError(null);
    } catch (error) {
      setMemosError(error instanceof Error ? error.message : "Failed to mark memo superseded");
    } finally {
      setStatusUpdatingId(null);
    }
  };

  const discardMemo = async (memo: InvestmentOSMemo) => {
    const confirmed = window.confirm(
      `Discard draft?\n\nThis removes ${memo.relative_path} from the active memo list. The Markdown file will be moved to research/.discarded/. No investment decision or policy record will be changed.`
    );
    if (!confirmed) return;

    setDiscardingId(memo.id);
    try {
      await api.discardInvestmentOSMemo(memo.id);
      setMemos((current) => current.filter((item) => item.id !== memo.id));
      if (selectedMemo?.id === memo.id) {
        setSelectedMemo(null);
        setSelectedMemoContent("");
      }
      setMemosError(null);
      await loadMemos();
    } catch (error) {
      setMemosError(error instanceof Error ? error.message : "Failed to discard memo draft");
    } finally {
      setDiscardingId(null);
    }
  };

  const restoreMemo = async (memo: InvestmentOSMemo) => {
    setRestoringId(memo.id);
    try {
      const restored = await api.restoreInvestmentOSMemo(memo.id);
      setMemos((current) => current.map((item) => (item.id === memo.id ? restored : item)));
      setSelectedMemo((current) => (current?.id === memo.id ? restored : current));
      setMemosError(null);
      await loadMemos();
    } catch (error) {
      setMemosError(error instanceof Error ? error.message : "Failed to restore memo draft");
    } finally {
      setRestoringId(null);
    }
  };

  const copyPath = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      setCopiedPath(path);
      window.setTimeout(() => setCopiedPath((current) => (current === path ? null : current)), 1800);
    } catch {
      setCopiedPath(null);
    }
  };

  return (
    <div className="min-h-full bg-background">
      <section className="border-b bg-card/60 px-6 py-8 lg:px-10">
        <div className="mx-auto grid max-w-7xl gap-6 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
          <div className="space-y-5">
            <div className="inline-flex items-center gap-2 rounded-full border bg-background px-3 py-1 text-xs font-medium text-muted-foreground">
              <ShieldCheck className="h-3.5 w-3.5 text-primary" />
              Policy-gated research layer
            </div>
            <div className="space-y-3">
              <h1 className="max-w-4xl text-4xl font-semibold tracking-tight md:text-5xl">
                Investment OS control room inside Vibe-Trading
              </h1>
              <p className="max-w-3xl text-base leading-7 text-muted-foreground">
                Use Vibe-Trading as the front door for portfolio research, backtest review,
                and stock-core candidate selection. The current registry is public and sanitized;
                private holdings and broker data stay outside the UI until explicitly wired.
              </p>
            </div>
          </div>

          <div className="rounded-xl border bg-background p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Current mode</p>
                <h2 className="text-lg font-semibold">Research only</h2>
              </div>
              <AlertTriangle className="h-5 w-5 text-warning" />
            </div>
            <div className="space-y-3 text-sm text-muted-foreground">
              <p>Stock-core proxy: <span className="font-medium text-foreground">VT</span></p>
              <p>Approval status: <span className="font-medium text-foreground">Draft menu</span></p>
              <p>Next gate: <span className="font-medium text-foreground">Decision memo</span></p>
            </div>
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-8 lg:px-10">
        <section className="grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border bg-card p-5 shadow-sm">
            <FileText className="mb-4 h-5 w-5 text-primary" />
            <h2 className="font-semibold">Evidence before narrative</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Every material number needs a source, as-of date, and caveat before it can
              support a decision memo.
            </p>
          </div>
          <div className="rounded-xl border bg-card p-5 shadow-sm">
            <Globe2 className="mb-4 h-5 w-5 text-primary" />
            <h2 className="font-semibold">FX-aware by default</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              USD proxies are useful, but THB base-currency exposure remains an explicit
              policy review item.
            </p>
          </div>
          <div className="rounded-xl border bg-card p-5 shadow-sm">
            <ShieldCheck className="mb-4 h-5 w-5 text-primary" />
            <h2 className="font-semibold">No trade execution</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Vibe-Trading can host research workflows, but human-only approval remains
              the boundary for portfolio action.
            </p>
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border bg-card shadow-sm">
          <div className="flex flex-col gap-3 border-b p-5 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">DeepQuant On-Pilot</p>
              <h2 className="text-xl font-semibold">Read-only execution-engine inventory</h2>
            </div>
            <div className="inline-flex items-center gap-2 rounded-full border bg-background px-3 py-1.5 text-xs text-muted-foreground">
              {deepQuantLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Cpu className="h-3.5 w-3.5" />}
              Snapshot source: {deepQuantSummary?.source === "file" ? "Investment OS report" : "not mounted"}
            </div>
          </div>

          {deepQuantError ? (
            <div className="mx-5 mt-5 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
              DeepQuant summary API unavailable. {deepQuantError}
            </div>
          ) : null}

          <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_360px]">
            <div className="space-y-5">
              {deepQuantLoading && !deepQuantSummary ? (
                <div className="flex items-center gap-2 rounded-lg border bg-background p-4 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading DeepQuant static inventory...
                </div>
              ) : null}

              {deepQuantSummary ? (
                <>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="rounded-lg border bg-background p-4">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Status</p>
                      <span className={`mt-2 inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${deepQuantStatusClass(deepQuantSummary.status)}`}>
                        {deepQuantSummary.status}
                      </span>
                    </div>
                    <div className="rounded-lg border bg-background p-4">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Models</p>
                      <p className="mt-2 text-2xl font-semibold">{deepQuantSummary.model_count}</p>
                    </div>
                    <div className="rounded-lg border bg-background p-4">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Portfolios</p>
                      <p className="mt-2 text-2xl font-semibold">{deepQuantSummary.portfolio_count}</p>
                    </div>
                    <div className="rounded-lg border bg-background p-4">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Evidence gaps</p>
                      <p className="mt-2 text-2xl font-semibold">{deepQuantSummary.evidence_gap_count}</p>
                    </div>
                  </div>

                  <div className="rounded-lg border bg-background p-4">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Symbols</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {deepQuantSummary.symbols.length > 0 ? deepQuantSummary.symbols.map((symbol) => (
                        <span key={symbol} className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 font-mono text-xs font-medium text-primary">
                          {symbol}
                        </span>
                      )) : (
                        <span className="text-sm text-muted-foreground">No symbols found in the mounted snapshot.</span>
                      )}
                    </div>
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="rounded-lg border bg-background p-4">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Model families</p>
                      <div className="mt-3 space-y-2 text-sm">
                        {Object.entries(deepQuantSummary.model_family_counts).length > 0 ? Object.entries(deepQuantSummary.model_family_counts).map(([family, count]) => (
                          <div key={family} className="flex items-center justify-between gap-3">
                            <span className="font-mono text-muted-foreground">{family}</span>
                            <span className="font-semibold">{count}</span>
                          </div>
                        )) : <p className="text-muted-foreground">No model families reported.</p>}
                      </div>
                    </div>
                    <div className="rounded-lg border bg-background p-4">
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Actionability</p>
                      <div className="mt-3 space-y-2 text-sm">
                        {Object.entries(deepQuantSummary.actionability_counts).length > 0 ? Object.entries(deepQuantSummary.actionability_counts).map(([status, count]) => (
                          <div key={status} className="flex items-center justify-between gap-3">
                            <span className="font-mono text-warning">{status}</span>
                            <span className="font-semibold">{count}</span>
                          </div>
                        )) : <p className="text-muted-foreground">No actionability counts reported.</p>}
                      </div>
                    </div>
                  </div>
                </>
              ) : null}
            </div>

            <aside className="space-y-4 rounded-lg border bg-background p-4">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Control boundary</p>
                <h3 className="mt-1 font-semibold">Inventory only</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  This panel reads a generated JSON snapshot from Investment OS. It does not parse DeepQuant live,
                  mutate config, promote models, start bots, or place orders.
                </p>
              </div>

              {deepQuantSummary?.generated_at ? (
                <div className="rounded-md border bg-card p-3 text-sm">
                  <span className="text-muted-foreground">Generated: </span>
                  <span className="font-medium">{formatDateTime(deepQuantSummary.generated_at)}</span>
                </div>
              ) : null}

              {deepQuantSummary?.adapter_version || deepQuantSummary?.schema_version ? (
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-md border bg-card p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Adapter</p>
                    <p className="mt-1 font-mono">{deepQuantSummary.adapter_version ?? "unknown"}</p>
                  </div>
                  <div className="rounded-md border bg-card p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">Schema</p>
                    <p className="mt-1 font-mono">{deepQuantSummary.schema_version ?? "unknown"}</p>
                  </div>
                </div>
              ) : null}

              {deepQuantSummary?.warnings.length ? (
                <div className="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
                  <p className="font-medium">Warnings</p>
                  <ul className="mt-2 list-disc space-y-1 pl-4">
                    {deepQuantSummary.warnings.map((warning) => <li key={warning}>{warning}</li>)}
                  </ul>
                </div>
              ) : null}

              {deepQuantSummary?.evidence_gaps.length ? (
                <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
                  <p className="font-medium text-foreground">Open gaps</p>
                  <ul className="mt-2 list-disc space-y-1 pl-4">
                    {deepQuantSummary.evidence_gaps.map((gap) => <li key={gap}>{gap}</li>)}
                  </ul>
                </div>
              ) : null}
            </aside>
          </div>
        </section>

        <section className="rounded-xl border bg-card p-5 shadow-sm">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
            <form onSubmit={createMemo} className="space-y-5">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">First vertical slice</p>
                <h2 className="mt-1 text-xl font-semibold">Draft a stock-core decision memo</h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                  This creates a research-only Markdown memo in `investment-os/research/`.
                  It reads the candidate registry plus policy/risk docs, then leaves evidence
                  gaps explicit for human follow-up.
                </p>
              </div>

              <label className="block space-y-2">
                <span className="text-sm font-medium">Decision question</span>
                <textarea
                  value={memoQuestion}
                  onChange={(event) => setMemoQuestion(event.target.value)}
                  rows={3}
                  className="w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </label>

              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">Candidates</span>
                  <span className="text-xs text-muted-foreground">Empty selection drafts the full menu</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {candidates.map((candidate) => {
                    const selected = selectedSymbols.includes(candidate.symbol);
                    return (
                      <button
                        key={candidate.symbol}
                        type="button"
                        onClick={() => toggleSymbol(candidate.symbol)}
                        className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                          selected
                            ? "border-primary bg-primary text-primary-foreground"
                            : "bg-background text-muted-foreground hover:border-primary/50 hover:text-foreground"
                        }`}
                      >
                        {candidate.symbol}
                      </button>
                    );
                  })}
                </div>
              </div>

              <button
                type="submit"
                disabled={memoCreating}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {memoCreating ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                Create memo draft
              </button>
            </form>

            <aside className="rounded-lg border bg-background p-4">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Memo status</p>
              {memoResult ? (
                <div className="mt-3 space-y-3 text-sm">
                  <div>
                    <span className="text-muted-foreground">Status: </span>
                    <span className="font-medium text-foreground">{memoResult.status}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Actionability: </span>
                    <span className="font-medium text-warning">{memoResult.actionability_status}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Candidates: </span>
                    <span className="font-medium text-foreground">{memoResult.candidate_symbols.join(", ")}</span>
                  </div>
                  <div className="rounded-md border bg-card p-3 font-mono text-xs break-all text-muted-foreground">
                    {memoResult.relative_path}
                  </div>
                  <p className="leading-6 text-muted-foreground">{memoResult.message}</p>
                </div>
              ) : (
                <p className="mt-3 text-sm leading-6 text-muted-foreground">
                  No memo drafted in this browser session yet. Drafts remain research-only
                  until evidence, risk, and human decision gates are complete.
                </p>
              )}
              {memoError ? (
                <div className="mt-4 rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
                  {memoError}
                </div>
              ) : null}
            </aside>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(420px,0.9fr)]">
          <div className="rounded-xl border bg-card shadow-sm">
            <div className="flex flex-col gap-3 border-b p-5 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Research memo workspace</p>
                <h2 className="text-xl font-semibold">Recent research memos</h2>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setShowDiscarded((current) => !current)}
                  className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition ${
                    showDiscarded ? "border-warning/40 bg-warning/10 text-warning" : "bg-background text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {showDiscarded ? "Hide discarded" : "Show discarded"}
                </button>
                <button
                  type="button"
                  onClick={() => void loadMemos()}
                  disabled={memosLoading}
                  className="inline-flex items-center gap-2 rounded-lg border bg-background px-3 py-2 text-xs font-medium text-muted-foreground transition hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {memosLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRight className="h-3.5 w-3.5" />}
                  Refresh
                </button>
              </div>
            </div>

            {memosError ? (
              <div className="mx-5 mt-5 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
                {memosError}
              </div>
            ) : null}

            <div className="space-y-3 p-5">
              {memosLoading && memos.length === 0 ? (
                <div className="flex items-center gap-2 rounded-lg border bg-background p-4 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading research memos...
                </div>
              ) : null}

              {!memosLoading && memos.length === 0 ? (
                <div className="rounded-lg border bg-background p-5 text-sm leading-6 text-muted-foreground">
                  No research memos found yet. Create a draft above to start the review loop.
                </div>
              ) : null}

              {memos.map((memo) => (
                <article
                  key={memo.id}
                  className={`rounded-lg border bg-background p-4 transition ${selectedMemo?.id === memo.id ? "border-primary/50 ring-2 ring-primary/10" : ""}`}
                >
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate font-semibold">{memo.title}</h3>
                        <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${memoStatusClass(memo.status)}`}>
                          {memo.status}
                        </span>
                        <span className="rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
                          {memo.actionability_status}
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                        <span>Created {formatDateTime(memo.created_at)}</span>
                        <span>{memo.candidate_symbols.join(", ") || "No symbols parsed"}</span>
                        <span>{memo.evidence_gap_count} evidence gaps</span>
                      </div>
                      <div className="font-mono text-xs text-muted-foreground break-all">{memo.relative_path}</div>
                    </div>

                    <div className="flex shrink-0 flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void openMemo(memo)}
                        className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:opacity-90"
                      >
                        <Eye className="h-3.5 w-3.5" />
                        Open review
                      </button>
                      {memo.status === "discarded" ? (
                        <button
                          type="button"
                          onClick={() => void restoreMemo(memo)}
                          disabled={restoringId === memo.id}
                          className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {restoringId === memo.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                          Restore draft
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => void markSuperseded(memo)}
                          disabled={memo.status === "superseded" || statusUpdatingId === memo.id}
                          className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {statusUpdatingId === memo.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                          Mark superseded
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void copyPath(memo.relative_path)}
                        className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition hover:text-foreground"
                      >
                        <Copy className="h-3.5 w-3.5" />
                        {copiedPath === memo.relative_path ? "Copied" : "Copy path"}
                      </button>
                      {memo.status !== "discarded" ? (
                        <button
                          type="button"
                          onClick={() => void discardMemo(memo)}
                          disabled={discardingId === memo.id}
                          className="inline-flex items-center gap-1.5 rounded-md border border-danger/30 bg-background px-3 py-1.5 text-xs font-medium text-danger transition hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {discardingId === memo.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                          Discard draft
                        </button>
                      ) : null}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>

          <aside className="rounded-xl border bg-card shadow-sm">
            <div className="border-b p-5">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Memo review</p>
              <h2 className="text-xl font-semibold">Open inside the cockpit</h2>
            </div>

            {selectedMemo ? (
              <div className="space-y-4 p-5">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${memoStatusClass(selectedMemo.status)}`}>
                      {selectedMemo.status}
                    </span>
                    <span className="rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
                      {selectedMemo.actionability_status}
                    </span>
                  </div>
                  <h3 className="text-lg font-semibold">{selectedMemo.title}</h3>
                  <div className="font-mono text-xs text-muted-foreground break-all">{selectedMemo.relative_path}</div>
                </div>

                <div className="flex flex-wrap gap-2">
                  {selectedMemo.status === "discarded" ? (
                    <button
                      type="button"
                      onClick={() => void restoreMemo(selectedMemo)}
                      disabled={restoringId === selectedMemo.id}
                      className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {restoringId === selectedMemo.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      Restore draft
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void markSuperseded(selectedMemo)}
                      disabled={selectedMemo.status === "superseded" || statusUpdatingId === selectedMemo.id}
                      className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {statusUpdatingId === selectedMemo.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      Mark superseded
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void copyPath(selectedMemo.relative_path)}
                    className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition hover:text-foreground"
                  >
                    <Copy className="h-3.5 w-3.5" />
                    {copiedPath === selectedMemo.relative_path ? "Copied" : "Copy path"}
                  </button>
                  {selectedMemo.status !== "discarded" ? (
                    <button
                      type="button"
                      onClick={() => void discardMemo(selectedMemo)}
                      disabled={discardingId === selectedMemo.id}
                      className="inline-flex items-center gap-1.5 rounded-md border border-danger/30 bg-background px-3 py-1.5 text-xs font-medium text-danger transition hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {discardingId === selectedMemo.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                      Discard draft
                    </button>
                  ) : null}
                </div>

                <div className="max-h-[640px] overflow-auto rounded-lg border bg-background p-4 text-sm leading-6">
                  {selectedMemoLoading ? (
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Loading memo review...
                    </div>
                  ) : (
                    <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:font-semibold prose-table:text-xs prose-th:border prose-th:px-2 prose-th:py-1 prose-td:border prose-td:px-2 prose-td:py-1">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedMemoContent}</ReactMarkdown>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-5 text-sm leading-6 text-muted-foreground">
                Select <span className="font-medium text-foreground">Open review</span> from a recent memo.
                The cockpit renders Markdown here so the raw file path stays traceability metadata, not the workflow.
              </div>
            )}
          </aside>
        </section>

        <section className="rounded-xl border bg-card shadow-sm">
          <div className="flex flex-col gap-3 border-b p-5 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Stock-core registry</p>
              <h2 className="text-xl font-semibold">Candidate menu</h2>
            </div>
            <div className="inline-flex items-center gap-2 rounded-full border bg-background px-3 py-1.5 text-xs text-muted-foreground">
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRight className="h-3.5 w-3.5" />}
              Source: {source === "file" ? "investment-os candidate registry" : "fallback registry"}
            </div>
          </div>

          {loadError ? (
            <div className="mx-5 mt-5 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
              Candidate API unavailable; showing fallback registry. {loadError}
            </div>
          ) : null}

          <div className="grid gap-4 p-5 lg:grid-cols-2">
            {candidates.map((candidate) => (
              <article key={candidate.symbol} className="rounded-lg border bg-background p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-mono text-2xl font-bold tracking-tight">{candidate.symbol}</div>
                    <h3 className="mt-1 font-semibold">{candidate.name}</h3>
                  </div>
                  <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${statusClass(candidate.status)}`}>
                    {candidate.status}
                  </span>
                </div>
                <p className="mt-4 min-h-12 text-sm leading-6 text-muted-foreground">{candidate.notes}</p>
                <dl className="mt-5 grid grid-cols-3 gap-3 text-sm">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">Role</dt>
                    <dd className="mt-1 font-medium">{candidate.role}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">Currency</dt>
                    <dd className="mt-1 font-medium">{candidate.currency}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">Vehicle</dt>
                    <dd className="mt-1 font-medium">{candidate.vehicle_type}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
            <div className="border-b p-5">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Candidate details</p>
              <h2 className="text-xl font-semibold">Comparison table</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-5 py-3 font-medium">Symbol</th>
                    <th className="px-5 py-3 font-medium">Role</th>
                    <th className="px-5 py-3 font-medium">Status</th>
                    <th className="px-5 py-3 font-medium">Currency</th>
                    <th className="px-5 py-3 font-medium">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((candidate) => (
                    <tr key={candidate.symbol} className="border-t">
                      <td className="px-5 py-4 font-mono font-semibold">{candidate.symbol}</td>
                      <td className="px-5 py-4">{candidate.role}</td>
                      <td className="px-5 py-4">
                        <span className={`rounded-full border px-2 py-1 text-xs font-medium ${statusClass(candidate.status)}`}>
                          {candidate.status}
                        </span>
                      </td>
                      <td className="px-5 py-4">{candidate.currency}</td>
                      <td className="px-5 py-4 text-muted-foreground">{candidate.notes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <aside className="rounded-xl border bg-card p-5 shadow-sm">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Policy gates</p>
            <h2 className="mt-1 text-xl font-semibold">Before promotion</h2>
            <div className="mt-5 space-y-4">
              {policyGates.map((gate, index) => (
                <div key={gate} className="flex gap-3">
                  <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                    {index + 1}
                  </div>
                  <p className="text-sm leading-6 text-muted-foreground">{gate}</p>
                </div>
              ))}
            </div>
            <div className="mt-6 rounded-lg border bg-background p-4 text-sm text-muted-foreground">
              Promotion path: candidate registry -&gt; research memo -&gt; decision log -&gt; policy update -&gt; report actionability.
            </div>
          </aside>
        </section>
      </main>
    </div>
  );
}
