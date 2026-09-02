import { CheckCircle2, Loader2, MessageSquareMore, Save, TestTube2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api, type ChannelConfigSummary } from "@/lib/api";

interface Draft {
  enabled: boolean;
  token: string;
  allowlist: string;
}

const fieldClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60";
const hintClass = "text-xs text-muted-foreground";

export function ChannelConfigSection() {
  const { t } = useTranslation();
  const [channels, setChannels] = useState<ChannelConfigSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [openChannel, setOpenChannel] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({ enabled: false, token: "", allowlist: "" });
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testOk, setTestOk] = useState<string | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  const refresh = async () => {
    const result = await api.getChannelsConfig();
    setChannels(result.channels);
  };

  useEffect(() => {
    setLoading(true);
    refresh()
      .then(() => setLoadError(null))
      .catch((error: unknown) => {
        setLoadError(error instanceof Error ? error.message : t("settings.channels.loadFailed"));
      })
      .finally(() => setLoading(false));
  }, [t]);

  const open = (channel: ChannelConfigSummary) => {
    setOpenChannel((current) => (current === channel.channel ? null : channel.channel));
    setDraft({ enabled: channel.enabled, token: "", allowlist: channel.allowlist.join(", ") });
    setTestOk(null);
    setTestError(null);
  };

  const testChannel = async (channel: ChannelConfigSummary) => {
    setTesting(true);
    setTestOk(null);
    setTestError(null);
    try {
      const result = await api.testChannelsConfig({
        channel: channel.channel,
        token: draft.token.trim() || undefined,
      });
      const bot = result.checks.bot_username ? ` @${result.checks.bot_username}` : "";
      setTestOk(`${t("settings.channels.testOk")}${bot}`);
    } catch (error: unknown) {
      setTestError(error instanceof Error ? error.message : t("settings.channels.testFailed"));
    } finally {
      setTesting(false);
    }
  };

  const saveChannel = async (channel: ChannelConfigSummary) => {
    setSaving(true);
    try {
      await api.updateChannelsConfig({
        channel: channel.channel,
        enabled: draft.enabled,
        token: draft.token.trim() || undefined,
        allowlist: draft.allowlist.trim() || undefined,
      });
      setOpenChannel(null);
      await refresh();
      toast.success(t("settings.channels.saved"));
    } catch (error: unknown) {
      toast.error(error instanceof Error ? error.message : t("settings.channels.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-lg border bg-card p-5 shadow-sm">
      <div className="mb-5 space-y-1">
        <div className="flex items-center gap-2">
          <MessageSquareMore className="h-4 w-4 text-primary" aria-hidden="true" />
          <h2 className="text-base font-semibold">{t("settings.channels.configTitle")}</h2>
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground">{t("settings.channels.configHint")}</p>
      </div>

      {loadError ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
          {loadError}
        </div>
      ) : loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {t("settings.loading")}
        </div>
      ) : (
        <div className="space-y-2">
          {channels.map((channel) => (
            <div key={channel.channel} className="rounded-md border">
              <div className="flex flex-col gap-3 p-3 md:flex-row md:items-center md:justify-between">
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{channel.display_name}</span>
                    {channel.enabled ? (
                      <span className="rounded-full bg-success/10 px-2 py-0.5 text-xs text-success">{t("settings.channels.enabled")}</span>
                    ) : (
                      <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{t("settings.channels.disabled")}</span>
                    )}
                    {channel.token_configured ? (
                      <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{t("settings.configured")}</span>
                    ) : null}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {channel.available ? channel.channel : `${channel.error} · ${channel.install_hint}`}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => open(channel)}
                  className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground"
                >
                  {openChannel === channel.channel ? t("portfolio.editor.close") : t("settings.channels.configTitle")}
                </button>
              </div>

              {openChannel === channel.channel ? (
                <div className="space-y-4 border-t p-3">
                  <label className="flex items-center gap-2 text-sm font-medium">
                    <input
                      type="checkbox"
                      checked={draft.enabled}
                      onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
                      className="h-4 w-4 accent-primary"
                    />
                    {t("settings.channels.enabledLabel")}
                  </label>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="grid gap-2">
                      <label htmlFor={`channel-token-${channel.channel}`} className="text-sm font-medium">
                        {t("settings.channels.token")}
                      </label>
                      <input
                        id={`channel-token-${channel.channel}`}
                        type="password"
                        value={draft.token}
                        onChange={(event) => setDraft((current) => ({ ...current, token: event.target.value }))}
                        className={`${fieldClass} font-mono`}
                        placeholder={channel.token_configured ? t("settings.keepCurrentToken") : ""}
                        autoComplete="new-password"
                      />
                      <span className={hintClass}>{t("settings.channels.tokenHint")}</span>
                    </div>
                    <div className="grid gap-2">
                      <label htmlFor={`channel-allowlist-${channel.channel}`} className="text-sm font-medium">
                        {t("settings.channels.allowlistLabel")}
                      </label>
                      <input
                        id={`channel-allowlist-${channel.channel}`}
                        value={draft.allowlist}
                        onChange={(event) => setDraft((current) => ({ ...current, allowlist: event.target.value }))}
                        className={fieldClass}
                        autoComplete="off"
                      />
                      <span className={hintClass}>{t("settings.channels.allowlistHint")}</span>
                    </div>
                  </div>

                  {testOk ? (
                    <div className="rounded-md border border-success/30 bg-success/10 px-3 py-2 text-sm text-success" role="status">
                      <CheckCircle2 className="me-1 inline h-4 w-4" aria-hidden="true" /> {testOk}
                    </div>
                  ) : null}
                  {testError ? (
                    <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
                      {t("settings.channels.testFailed")}: {testError}
                    </div>
                  ) : null}

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void testChannel(channel)}
                      disabled={testing || saving}
                      className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border px-4 py-2 text-sm font-medium transition hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {testing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <TestTube2 className="h-4 w-4" aria-hidden="true" />}
                      {t("settings.channels.test")}
                    </button>
                    <button
                      type="button"
                      onClick={() => void saveChannel(channel)}
                      disabled={saving || testing}
                      className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Save className="h-4 w-4" aria-hidden="true" />}
                      {t("settings.channels.save")}
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
