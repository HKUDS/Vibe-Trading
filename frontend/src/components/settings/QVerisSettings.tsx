import { useEffect, useId, useState, type FormEvent } from "react";
import { ExternalLink, KeyRound, Loader2, Save, SearchCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { authHeaders } from "@/lib/apiAuth";

type QVerisMode = "free" | "paid";

interface QVerisConfig {
  enabled: boolean;
  base_url: string;
  api_key_masked: string;
  mode: QVerisMode;
  budget_credits_per_session: number;
  configured: boolean;
  signup_url: string;
  invite_code: string;
}

interface QVerisStatus {
  enabled: boolean;
  ok: boolean;
  error: string | null;
  remaining_credits: number | null;
  recent: Array<{
    ts: string;
    tool_id: string;
    cost: number;
    charge_outcome: string;
  }>;
  signup_url: string;
  invite_code: string;
}

interface QVerisForm {
  enabled: boolean;
  base_url: string;
  api_key: string;
  mode: QVerisMode;
  budget_credits_per_session: number;
}

const DEFAULT_BASE_URL = "https://qveris.ai/api/v1";
const fieldClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60";
const labelClass = "text-sm font-medium";
const hintClass = "text-xs text-muted-foreground";

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers, ...rest } = options ?? {};
  const mergedHeaders: Record<string, string> = { "Content-Type": "application/json", ...authHeaders() };
  if (headers) {
    new Headers(headers).forEach((value, key) => {
      mergedHeaders[key] = value;
    });
  }

  const response = await fetch(path, { ...rest, headers: mergedHeaders });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || body.message || message;
    } catch { /* ignore */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function formFromConfig(config: QVerisConfig): QVerisForm {
  return {
    enabled: config.enabled && config.mode === "paid",
    base_url: config.base_url || DEFAULT_BASE_URL,
    api_key: "",
    mode: config.mode,
    budget_credits_per_session: config.budget_credits_per_session,
  };
}

export function QVerisSettings() {
  const { t } = useTranslation();
  const idPrefix = useId();
  const [config, setConfig] = useState<QVerisConfig | null>(null);
  const [status, setStatus] = useState<QVerisStatus | null>(null);
  const [form, setForm] = useState<QVerisForm>({
    enabled: false,
    base_url: DEFAULT_BASE_URL,
    api_key: "",
    mode: "free",
    budget_credits_per_session: 50,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextConfig, nextStatus] = await Promise.all([
        requestJson<QVerisConfig>("/qveris/config"),
        requestJson<QVerisStatus>("/qveris/status"),
      ]);
      setConfig(nextConfig);
      setForm(formFromConfig(nextConfig));
      setStatus(nextStatus);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t("qveris.testFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);

    Promise.all([
      requestJson<QVerisConfig>("/qveris/config"),
      requestJson<QVerisStatus>("/qveris/status"),
    ])
      .then(([nextConfig, nextStatus]) => {
        if (!alive) return;
        setConfig(nextConfig);
        setForm(formFromConfig(nextConfig));
        setStatus(nextStatus);
      })
      .catch((loadError) => {
        if (!alive) return;
        setError(loadError instanceof Error ? loadError.message : t("qveris.testFailed"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [t]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload: {
        enabled: boolean;
        base_url: string;
        mode: QVerisMode;
        budget_credits_per_session: number;
        api_key?: string;
      } = {
        enabled: form.mode === "paid" && form.enabled,
        base_url: form.base_url.trim(),
        mode: form.mode,
        budget_credits_per_session: Number(form.budget_credits_per_session) || 0,
      };
      const trimmedApiKey = form.api_key.trim();
      if (trimmedApiKey) payload.api_key = trimmedApiKey;

      const nextConfig = await requestJson<QVerisConfig>("/qveris/config", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setConfig(nextConfig);
      setForm(formFromConfig(nextConfig));
      toast.success(t("qveris.saved"));
      await load();
    } catch (saveError) {
      const message = saveError instanceof Error ? saveError.message : t("qveris.testFailed");
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  const recent = status?.recent ?? [];
  const signupUrl = config?.signup_url || "";
  const inviteCode = config?.invite_code || status?.invite_code || "";
  const apiKeyPlaceholder = config?.api_key_masked || t("qveris.apiKeyPlaceholder");

  return (
    <section className="rounded-lg border bg-card p-5 shadow-sm">
      <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <SearchCheck className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t("qveris.title")}</h2>
          </div>
          <p className="max-w-3xl text-sm text-muted-foreground">{t("qveris.subtitle")}</p>
        </div>
        <a
          href={signupUrl || undefined}
          target="_blank"
          rel="noreferrer"
          aria-disabled={!signupUrl}
          className={`inline-flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm transition ${
            signupUrl
              ? "text-muted-foreground hover:bg-muted hover:text-foreground"
              : "pointer-events-none text-muted-foreground opacity-60"
          }`}
        >
          <ExternalLink className="h-4 w-4" />
          {t("qveris.signupCta")}
        </a>
      </div>

      {error ? (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <span className="font-medium">{t("qveris.testFailed")}: </span>
          <span>{error}</span>
        </div>
      ) : null}

      <form onSubmit={submit} className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
        <div className="grid gap-4">
          <label className="flex items-center justify-between gap-3 rounded-md border bg-muted/20 px-3 py-2">
            <span className={labelClass}>{t("qveris.enabled")}</span>
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) => {
                const enabled = event.target.checked;
                setForm({ ...form, enabled, mode: enabled ? "paid" : "free" });
              }}
              className="h-4 w-4 accent-primary"
              disabled={loading}
            />
          </label>

          <label className="grid gap-2" htmlFor={`${idPrefix}-base-url`}>
            <span className={labelClass}>{t("qveris.baseUrl")}</span>
            <input
              id={`${idPrefix}-base-url`}
              value={form.base_url}
              onChange={(event) => setForm({ ...form, base_url: event.target.value })}
              className={fieldClass}
              placeholder={DEFAULT_BASE_URL}
              disabled={loading}
            />
          </label>

          <label className="grid gap-2" htmlFor={`${idPrefix}-api-key`}>
            <span className={labelClass}>{t("qveris.apiKey")}</span>
            <div className="relative">
              <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <input
                id={`${idPrefix}-api-key`}
                type="password"
                value={form.api_key}
                onChange={(event) => setForm({ ...form, api_key: event.target.value })}
                className={`${fieldClass} pl-9`}
                placeholder={apiKeyPlaceholder}
                autoComplete="current-password"
                disabled={loading}
              />
            </div>
            <span className={hintClass}>{t("qveris.apiKeyPlaceholder")}</span>
          </label>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2" htmlFor={`${idPrefix}-mode`}>
              <span className={labelClass}>{t("qveris.mode")}</span>
              <select
                id={`${idPrefix}-mode`}
                value={form.mode}
                onChange={(event) => {
                  const mode = event.target.value as QVerisMode;
                  setForm({ ...form, mode, enabled: mode === "paid" });
                }}
                className={fieldClass}
                disabled={loading}
              >
                <option value="free">{t("qveris.modeFree")}</option>
                <option value="paid">{t("qveris.modePaid")}</option>
              </select>
            </label>

            <label className="grid gap-2" htmlFor={`${idPrefix}-budget`}>
              <span className={labelClass}>{t("qveris.budget")}</span>
              <input
                id={`${idPrefix}-budget`}
                type="number"
                min={0}
                step={1}
                value={form.budget_credits_per_session}
                onChange={(event) => setForm({ ...form, budget_credits_per_session: Number(event.target.value) })}
                className={fieldClass}
                disabled={loading}
              />
              <span className={hintClass}>{t("qveris.budgetHint")}</span>
            </label>
          </div>

          <button
            type="submit"
            disabled={loading || saving}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {t("qveris.save")}
          </button>
        </div>

        <div className="grid gap-4">
          <div className="rounded-md border bg-muted/20 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-sm font-medium">{t("qveris.balance")}</span>
              {loading ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
            </div>
            <div className="text-2xl font-semibold">
              {status?.remaining_credits ?? t("qveris.notConfigured")}
            </div>
            {status?.error ? <p className="mt-2 text-xs text-destructive">{status.error}</p> : null}
          </div>

          <div className="rounded-md border bg-muted/20 p-4">
            <div className="mb-3 text-sm font-medium">{t("qveris.recentUsage")}</div>
            {recent.length ? (
              <div className="space-y-2">
                {recent.map((item) => (
                  <div key={`${item.ts}-${item.tool_id}`} className="rounded-md border bg-background px-3 py-2 text-xs">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium">{item.tool_id}</span>
                      <span className="text-muted-foreground">{item.cost}</span>
                    </div>
                    <div className="mt-1 flex items-center justify-between gap-3 text-muted-foreground">
                      <span>{item.ts}</span>
                      <span>{item.charge_outcome}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">{t("qveris.noUsage")}</p>
            )}
          </div>

          <div className="rounded-md border bg-muted/20 p-4">
            <div className="mb-2 text-sm font-medium">{t("qveris.signupHint")}</div>
            <div className="text-xs text-muted-foreground">{t("qveris.inviteCode")}</div>
            <div className="mt-1 break-all font-mono text-sm">{inviteCode || t("qveris.notConfigured")}</div>
          </div>
        </div>
      </form>
    </section>
  );
}
