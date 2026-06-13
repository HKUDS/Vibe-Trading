import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Loader2,
  OctagonX,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
  Wifi,
  WifiOff,
} from "lucide-react";
import { api, type LiveBrokerStatus, type LiveMandateLimits, type LiveStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const RUNTIME_POLL_INTERVAL_MS = 15_000;

export function Runtime() {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async (mode: "initial" | "refresh" = "refresh") => {
    if (mode === "initial") setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const next = await api.getLiveStatus();
      setStatus(next);
    } catch (err) {
      setStatus(null);
      setError(err instanceof Error ? err.message : "Runtime status unavailable.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadStatus("initial");
    const timer = window.setInterval(() => loadStatus("refresh"), RUNTIME_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadStatus]);

  const summary = useMemo(() => summarizeRuntime(status), [status]);

  return (
    <div className="min-h-screen p-6 lg:p-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <section className="flex flex-col gap-4 border-b pb-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs font-medium text-muted-foreground">
              <Activity className="h-3.5 w-3.5" />
              Runtime Monitor
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Live / Paper Runtime Status</h1>
              <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
                Read-only status from <span className="font-mono">/live/status</span>. This page does not authorize connectors,
                start runners, stop runners, submit orders, cancel orders, or change mandates.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => loadStatus("refresh")}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium transition hover:bg-muted disabled:opacity-50"
          >
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Refresh
          </button>
        </section>

        {loading ? (
          <div className="grid gap-3 md:grid-cols-4">
            {[1, 2, 3, 4].map((item) => (
              <div key={item} className="h-24 animate-pulse rounded-md border bg-muted/40" />
            ))}
          </div>
        ) : null}

        {!loading && error ? (
          <section className="rounded-md border border-amber-500/30 bg-amber-500/5 p-5">
            <div className="flex items-center gap-2 font-medium text-amber-700 dark:text-amber-300">
              <AlertTriangle className="h-5 w-5" />
              Runtime status unavailable
            </div>
            <p className="mt-2 text-sm text-muted-foreground">{error}</p>
            <p className="mt-2 text-xs text-muted-foreground">
              Treat connector runtime as unavailable until the backend provides a current status snapshot.
            </p>
          </section>
        ) : null}

        {!loading && !error && status ? (
          <>
            <section className="grid gap-3 md:grid-cols-4">
              <SummaryTile
                label="Global Halt"
                value={status.global_halted ? "Halted" : "Clear"}
                tone={status.global_halted ? "danger" : "success"}
                icon={status.global_halted ? OctagonX : CheckCircle2}
              />
              <SummaryTile label="Brokers" value={String(summary.brokerCount)} tone="neutral" icon={Activity} />
              <SummaryTile
                label="Authorized"
                value={String(summary.authorizedCount)}
                tone={summary.authorizedCount > 0 ? "success" : "neutral"}
                icon={summary.authorizedCount > 0 ? Wifi : WifiOff}
              />
              <SummaryTile
                label="Runners"
                value={`${summary.runningCount} running`}
                tone={summary.runningCount > 0 && !status.global_halted ? "success" : "neutral"}
                icon={summary.runningCount > 0 ? Activity : Clock3}
              />
            </section>

            {status.brokers.length === 0 ? (
              <section className="rounded-md border border-dashed p-8 text-center">
                <ShieldOff className="mx-auto h-8 w-8 text-muted-foreground" />
                <h2 className="mt-3 font-medium">No runtime profiles reported</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  The backend did not return any recognized live or paper broker profiles.
                </p>
              </section>
            ) : (
              <section className="grid gap-4">
                {status.brokers.map((broker) => (
                  <BrokerRuntimeCard key={broker.auth.broker} broker={broker} globalHalted={status.global_halted} />
                ))}
              </section>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

interface SummaryTileProps {
  label: string;
  value: string;
  tone: "success" | "danger" | "neutral";
  icon: typeof Activity;
}

function SummaryTile({ label, value, tone, icon: Icon }: SummaryTileProps) {
  return (
    <div className="rounded-md border p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium uppercase text-muted-foreground">{label}</span>
        <Icon
          className={cn(
            "h-4 w-4",
            tone === "success" && "text-success",
            tone === "danger" && "text-danger",
            tone === "neutral" && "text-muted-foreground",
          )}
        />
      </div>
      <div
        className={cn(
          "mt-3 text-2xl font-semibold",
          tone === "success" && "text-success",
          tone === "danger" && "text-danger",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function BrokerRuntimeCard({ broker, globalHalted }: { broker: LiveBrokerStatus; globalHalted: boolean }) {
  const brokerKey = broker.auth.broker;
  const runnerAlive = broker.runner?.alive ?? false;
  const halted = globalHalted || broker.halted;
  const mandate = broker.mandate ?? null;
  const risk = deriveRiskState(broker, globalHalted);
  const mandateCountdown = formatCountdown(mandate?.expires_at);

  return (
    <article className="rounded-md border p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold capitalize">{brokerKey}</h2>
            <StatusPill
              label={broker.auth.oauth_token_present ? "auth present" : "auth missing"}
              tone={broker.auth.oauth_token_present ? "success" : "neutral"}
            />
            <StatusPill label={runnerAlive ? "runner alive" : "runner stopped"} tone={runnerAlive ? "success" : "neutral"} />
            {halted ? <StatusPill label="halted" tone="danger" /> : null}
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            {broker.auth.is_live_broker ? "Recognized connector profile" : "Unknown connector profile"} · Last tick{" "}
            {formatLastTick(broker.runner?.last_tick, broker.runner?.last_tick_age_seconds)}
          </p>
        </div>
        <StatusPill label={risk.label} tone={risk.tone} />
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <RuntimePanel title="Authorization" icon={broker.auth.oauth_token_present ? Wifi : WifiOff}>
          <KeyValue label="OAuth token" value={broker.auth.oauth_token_present ? "present" : "missing"} />
          <KeyValue label="Profile type" value={broker.auth.is_live_broker ? "recognized" : "unknown"} />
        </RuntimePanel>

        <RuntimePanel title="Mandate" icon={mandate ? ShieldCheck : ShieldOff}>
          {mandate ? (
            <>
              <KeyValue label="Account" value={mandate.account_ref || "unrecorded"} />
              <KeyValue label="Expiry" value={mandate.expired ? "expired" : mandateCountdown} />
              <KeyValue label="Limits" value={summarizeLimits(mandate.limits)} />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">No active mandate reported.</p>
          )}
        </RuntimePanel>

        <RuntimePanel title="Runtime Risk State" icon={risk.icon}>
          <p className="text-sm text-muted-foreground">{risk.description}</p>
        </RuntimePanel>
      </div>
    </article>
  );
}

function RuntimePanel({ title, icon: Icon, children }: { title: string; icon: typeof Activity; children: ReactNode }) {
  return (
    <section className="rounded-md border bg-muted/20 p-3">
      <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {title}
      </div>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase text-muted-foreground">{label}</div>
      <div className="font-mono text-sm">{value || "-"}</div>
    </div>
  );
}

function StatusPill({ label, tone }: { label: string; tone: "success" | "danger" | "warning" | "neutral" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-2 py-0.5 text-xs font-medium",
        tone === "success" && "bg-success/10 text-success",
        tone === "danger" && "bg-danger/10 text-danger",
        tone === "warning" && "bg-amber-500/10 text-amber-700 dark:text-amber-300",
        tone === "neutral" && "bg-muted text-muted-foreground",
      )}
    >
      {label}
    </span>
  );
}

function summarizeRuntime(status: LiveStatus | null) {
  const brokers = status?.brokers || [];
  return {
    brokerCount: brokers.length,
    authorizedCount: brokers.filter((broker) => broker.auth.oauth_token_present).length,
    runningCount: brokers.filter((broker) => broker.runner?.alive).length,
  };
}

function deriveRiskState(broker: LiveBrokerStatus, globalHalted: boolean): {
  label: string;
  tone: "success" | "danger" | "warning" | "neutral";
  icon: typeof Activity;
  description: string;
} {
  if (globalHalted || broker.halted) {
    return {
      label: "risk halted",
      tone: "danger",
      icon: OctagonX,
      description: "The kill switch is tripped for this profile. Treat connector runtime as stopped until status clears.",
    };
  }
  if (broker.runner?.alive && broker.mandate && !broker.mandate.expired) {
    return {
      label: "runtime active",
      tone: "success",
      icon: Activity,
      description: "Runner is alive and an unexpired mandate is present. This page is still read-only status only.",
    };
  }
  if (broker.auth.oauth_token_present && broker.mandate && !broker.mandate.expired) {
    return {
      label: "ready but idle",
      tone: "warning",
      icon: Clock3,
      description: "Authorization and mandate are present, but the runner is not alive.",
    };
  }
  return {
    label: "dormant",
    tone: "neutral",
    icon: ShieldOff,
    description: "Connector runtime is not ready for autonomous operation because authorization, mandate, or runner liveness is missing.",
  };
}

function summarizeLimits(limits: LiveMandateLimits | undefined): string {
  if (!limits) return "limits unavailable";
  const parts: string[] = [];
  if (typeof limits.max_order_notional_usd === "number") parts.push(`$${limits.max_order_notional_usd.toLocaleString()}/order`);
  if (typeof limits.max_total_exposure_usd === "number") parts.push(`$${limits.max_total_exposure_usd.toLocaleString()} exposure`);
  if (typeof limits.max_trades_per_day === "number") parts.push(`${limits.max_trades_per_day}/day`);
  if (typeof limits.max_leverage === "number") parts.push(`${limits.max_leverage}x leverage`);
  if (limits.allowed_instruments?.length) parts.push(limits.allowed_instruments.join(", "));
  return parts.join(" · ") || "limits unavailable";
}

function formatCountdown(iso: string | undefined): string {
  if (!iso) return "unknown";
  const target = new Date(iso).getTime();
  if (!Number.isFinite(target)) return "unknown";
  const deltaSec = Math.round((target - Date.now()) / 1000);
  if (deltaSec <= 0) return "expired";
  const days = Math.floor(deltaSec / 86_400);
  const hours = Math.floor((deltaSec % 86_400) / 3600);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h`;
  return `${Math.max(1, Math.floor(deltaSec / 60))}m`;
}

function formatLastTick(value: string | number | null | undefined, ageSeconds: number | null | undefined): string {
  if (typeof ageSeconds === "number" && Number.isFinite(ageSeconds)) {
    if (ageSeconds < 60) return `${Math.round(ageSeconds)}s ago`;
    if (ageSeconds < 3600) return `${Math.floor(ageSeconds / 60)}m ago`;
    return `${Math.floor(ageSeconds / 3600)}h ago`;
  }
  if (value == null || value === "") return "never";
  const timestamp = typeof value === "number"
    ? (value < 1_000_000_000_000 ? value * 1000 : value)
    : new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "unknown";
  const deltaSec = Math.round((Date.now() - timestamp) / 1000);
  if (deltaSec < 60) return `${Math.max(0, deltaSec)}s ago`;
  if (deltaSec < 3600) return `${Math.floor(deltaSec / 60)}m ago`;
  return `${Math.floor(deltaSec / 3600)}h ago`;
}
