import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, FolderCode, Loader2, PlugZap, Plus, ShieldCheck, Trash2, X } from "lucide-react";
import { PortfolioCompatibilityBadge } from "@/components/portfolio/PortfolioCompatibilityBadge";
import { api, type ConnectionsResponse, type LocalConnection } from "@/lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
  onChanged: () => Promise<void>;
}

const fieldClass = "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20";
type TestResult = { ok: boolean; message: string };

/**
 * Drawer for the connections that exist only on this computer: create one from
 * a read-only profile template, store its secrets in the OS credential vault,
 * test it, or delete it. Nothing here can place an order.
 */
export function ConnectionCenter({ open, onClose, onChanged }: Props) {
  const { t } = useTranslation();
  const [data, setData] = useState<ConnectionsResponse | null>(null);
  const [profileId, setProfileId] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});

  async function load() {
    setData(await api.getConnections());
  }

  useEffect(() => {
    if (!open) return;
    setMessage(null);
    void load().catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, [open]);

  const profiles = useMemo(() => data?.profiles.filter((profile) => !profile.invalid_plugin) ?? [], [data]);
  const selectedProfile = profiles.find((profile) => profile.id === profileId);
  const compatibilityLabel = (level: "native" | "contract_tested" | "experimental") => level === "native"
    ? t("portfolio.compatibility.native")
    : level === "contract_tested"
      ? t("portfolio.compatibility.contractTested")
      : t("portfolio.compatibility.experimental");

  function chooseProfile(value: string) {
    setProfileId(value);
    const profile = profiles.find((item) => item.id === value);
    if (!profile) return;
    const ids = new Set(data?.connections.map((item) => item.id) ?? []);
    let id = `${profile.connector}-${profile.environment}`;
    let suffix = 2;
    while (ids.has(id)) id = `${profile.connector}-${profile.environment}-${suffix++}`;
    setConnectionId(id);
    setLabel(profile.label);
  }

  async function create() {
    if (!profileId || !connectionId.trim() || !label.trim()) return;
    setBusy("create");
    setMessage(null);
    try {
      await api.createConnection({ id: connectionId, profile_id: profileId, label });
      await load();
      await onChanged();
      setProfileId("");
      setConnectionId("");
      setLabel("");
      setMessage(t("portfolio.connections.created"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  async function test(connection: LocalConnection) {
    setBusy(`test:${connection.id}`);
    setTestResults((current) => {
      const next = { ...current };
      delete next[connection.id];
      return next;
    });
    try {
      const result = await api.checkConnection(connection.id);
      const ok = result.report.status === "ok" || result.report.configured === true;
      const error = typeof result.report.error === "string"
        ? result.report.error
        : t("portfolio.connections.unknownTestError");
      setTestResults((current) => ({
        ...current,
        [connection.id]: {
          ok,
          message: ok
            ? t("portfolio.connections.testOk", { label: connection.label })
            : t("portfolio.connections.testFailed", { label: connection.label, error }),
        },
      }));
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setTestResults((current) => ({
        ...current,
        [connection.id]: {
          ok: false,
          message: t("portfolio.connections.testFailed", { label: connection.label, error: detail }),
        },
      }));
    } finally {
      setBusy(null);
    }
  }

  async function remove(connection: LocalConnection) {
    setBusy(`delete:${connection.id}`);
    setMessage(null);
    try {
      await api.deleteConnection(connection.id);
      await load();
      await onChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }

  if (!open) return null;

  return <div className="fixed inset-0 z-[60] flex justify-end bg-black/40" role="presentation">
    <section className="flex h-full w-full max-w-2xl flex-col border-l bg-background shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="connection-center-title">
      <header className="flex items-start justify-between border-b p-5">
        <div><h2 id="connection-center-title" className="text-lg font-semibold">{t("portfolio.connections.title")}</h2><p className="mt-1 text-xs text-muted-foreground">{t("portfolio.connections.subtitle")}</p></div>
        <button type="button" onClick={onClose} className="rounded-md p-2 hover:bg-muted" aria-label={t("portfolio.connections.close")}><X className="h-4 w-4" /></button>
      </header>

      <div className="flex-1 space-y-6 overflow-y-auto p-5">
        {message ? <div className="rounded-md border bg-muted/30 p-3 text-xs break-words">{message}</div> : null}

        <section className="rounded-xl border bg-card p-4">
          <div className="flex items-center gap-2"><Plus className="h-4 w-4 text-primary" /><h3 className="font-medium">{t("portfolio.connections.createTitle")}</h3></div>
          <p className="mt-1 text-xs text-muted-foreground">{t("portfolio.connections.createHint")}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-muted-foreground sm:col-span-2">{t("portfolio.connections.profile")}<select value={profileId} onChange={(event) => chooseProfile(event.target.value)} className={`mt-1 ${fieldClass}`}><option value="">{t("portfolio.connections.chooseProfile")}</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label} · {compatibilityLabel(profile.portfolio_compatibility?.level ?? "experimental")}</option>)}</select></label>
            <label className="text-xs text-muted-foreground">{t("portfolio.connections.localId")}<input value={connectionId} onChange={(event) => setConnectionId(event.target.value.toLowerCase())} className={`mt-1 ${fieldClass}`} placeholder="my-broker-live" /></label>
            <label className="text-xs text-muted-foreground">{t("portfolio.connections.displayName")}<input value={label} onChange={(event) => setLabel(event.target.value)} className={`mt-1 ${fieldClass}`} placeholder={t("portfolio.connections.displayNamePlaceholder")} /></label>
          </div>
          {selectedProfile?.onboarding ? <SetupContract onboarding={selectedProfile.onboarding} /> : null}
          <button type="button" onClick={() => void create()} disabled={!profileId || busy === "create"} className="mt-3 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40">{busy === "create" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}{t("portfolio.connections.create")}</button>
        </section>

        <section>
          <div className="flex items-end justify-between"><div><h3 className="font-medium">{t("portfolio.connections.listTitle")}</h3><p className="mt-1 text-xs text-muted-foreground">{t("portfolio.connections.listCount", { count: data?.connections.length ?? 0 })}</p></div><ShieldCheck className="h-5 w-5 text-positive" /></div>
          <div className="mt-3 space-y-3">{data?.connections.map((connection) => <ConnectionCard key={connection.id} connection={connection} busy={busy} testResult={testResults[connection.id]} onTest={test} onDelete={remove} onSaved={async () => { await load(); await onChanged(); }} setBusy={setBusy} setMessage={setMessage} />)}{data && !data.connections.length ? <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">{t("portfolio.connections.empty")}</div> : null}</div>
        </section>

        <section className="rounded-xl border border-dashed p-4">
          <div className="flex items-center gap-2"><FolderCode className="h-4 w-4" /><h3 className="font-medium">{t("portfolio.connections.codexTitle")}</h3></div>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">{t("portfolio.connections.codexBody")}</p>
          <code className="mt-3 block overflow-x-auto rounded-md bg-muted p-3 text-xs">{data?.plugin_directory ?? "~/.vibe-trading/connectors"}</code>
        </section>
      </div>
    </section>
  </div>;
}

function ConnectionCard({ connection, busy, testResult, onTest, onDelete, onSaved, setBusy, setMessage }: { connection: LocalConnection; busy: string | null; testResult?: TestResult; onTest: (connection: LocalConnection) => Promise<void>; onDelete: (connection: LocalConnection) => Promise<void>; onSaved: () => Promise<void>; setBusy: (value: string | null) => void; setMessage: (value: string | null) => void }) {
  const { t } = useTranslation();
  const [values, setValues] = useState<Record<string, string>>({});
  async function saveCredentials() {
    setBusy(`credentials:${connection.id}`);
    setMessage(null);
    try {
      await api.saveConnectionCredentials(connection.id, values);
      setValues({});
      await onSaved();
      setMessage(t("portfolio.connections.savedVault"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  }
  return <article className="rounded-xl border bg-card p-4">
    <div className="flex items-start justify-between gap-3"><div><div className="font-medium">{connection.label}</div><div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground"><span>{connection.connector.toUpperCase()}</span><span>·</span><span>{connection.environment === "live" ? t("portfolio.env.live") : t("portfolio.env.paper")}</span><span>·</span><span>{connection.transport}</span></div></div><div className="flex flex-col items-end gap-2"><span className="inline-flex items-center gap-1 rounded-full bg-positive/10 px-2 py-1 text-xs text-positive"><ShieldCheck className="h-3 w-3" />{t("portfolio.connections.readOnly")}</span><PortfolioCompatibilityBadge compatibility={connection.portfolio_compatibility} /></div></div>
    {connection.onboarding ? <SetupContract onboarding={connection.onboarding} /> : null}
    {connection.credential_fields.length ? <div className="mt-4 grid gap-2 sm:grid-cols-2">{connection.credential_fields.map((field) => <label key={field.name} className="text-xs text-muted-foreground">{field.label}{field.required ? <span className="ml-1 text-danger">*</span> : <span className="ml-1">{t("portfolio.connections.optional")}</span>}{connection.credential_status[field.name] ? <span className="ml-1 text-positive">{t("portfolio.connections.credentialSaved")}</span> : null}<input type={field.secret ? "password" : "text"} value={values[field.name] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))} className={`mt-1 ${fieldClass}`} placeholder={connection.credential_status[field.name] ? "••••••••" : ""} autoComplete="off" /></label>)}</div> : <p className="mt-3 text-xs text-muted-foreground">{connection.transport === "remote_mcp" ? t("portfolio.connections.oauthNote") : t("portfolio.connections.localNote")}</p>}
    <div className="mt-4 flex flex-wrap gap-2">{connection.credential_fields.length ? <button type="button" onClick={() => void saveCredentials()} disabled={busy === `credentials:${connection.id}` || !Object.values(values).some(Boolean)} className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs disabled:opacity-40"><ShieldCheck className="h-3.5 w-3.5" />{t("portfolio.connections.saveVault")}</button> : null}<button type="button" onClick={() => void onTest(connection)} disabled={busy === `test:${connection.id}`} className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs">{busy === `test:${connection.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlugZap className="h-3.5 w-3.5" />}{t("portfolio.connections.test")}</button><button type="button" onClick={() => void onDelete(connection)} disabled={busy === `delete:${connection.id}`} className="ml-auto inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-danger hover:bg-danger/10"><Trash2 className="h-3.5 w-3.5" />{t("portfolio.connections.delete")}</button></div>
    {testResult ? <div role="status" className={`mt-3 rounded-md border px-3 py-2 text-xs ${testResult.ok ? "border-positive/30 bg-positive/5 text-positive" : "border-danger/30 bg-danger/5 text-danger"}`}>{testResult.message}</div> : null}
    {connection.credentials_configured ? <div className="mt-3 flex items-center gap-1.5 text-xs text-positive"><CheckCircle2 className="h-3.5 w-3.5" />{t("portfolio.connections.configured")}</div> : null}
  </article>;
}

function SetupContract({ onboarding }: { onboarding: NonNullable<LocalConnection["onboarding"]> }) {
  const { t } = useTranslation();
  return <div className="mt-3 rounded-md border bg-muted/20 p-3 text-xs text-muted-foreground">
    <div className="flex flex-wrap gap-x-3 gap-y-1"><span>{t("portfolio.connections.authType")}: <strong className="font-medium text-foreground">{onboarding.auth_type}</strong></span>{onboarding.dependency ? <span>{t("portfolio.connections.dependency")}: <strong className="font-medium text-foreground">{onboarding.dependency}</strong></span> : null}</div>
    {onboarding.setup_hint ? <p className="mt-2 leading-5">{onboarding.setup_hint}</p> : null}
    {onboarding.install_command ? <code className="mt-2 block overflow-x-auto rounded bg-muted px-2 py-1.5 text-foreground">{onboarding.install_command}</code> : null}
  </div>;
}
