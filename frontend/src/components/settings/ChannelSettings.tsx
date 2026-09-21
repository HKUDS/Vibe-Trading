import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronRight,
  Loader2,
  MessageSquareMore,
  Play,
  RefreshCw,
  Square,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ChannelConfigPanel } from "@/components/settings/ChannelConfigPanel";
import {
  api,
  type ChannelsConfigResponse,
  type ChannelRuntimeStatus,
} from "@/lib/api";

/**
 * IM channel card: runtime status table with Start/Stop/Refresh, and one
 * expandable configuration panel per channel (credentials, connection test,
 * non-destructive enable toggle) backed by GET /channels/config.
 */
export function ChannelSettings() {
  const { t } = useTranslation();
  const [channelStatus, setChannelStatus] = useState<ChannelRuntimeStatus | null>(null);
  const [channelsConfig, setChannelsConfig] = useState<ChannelsConfigResponse | null>(null);
  const [configFailed, setConfigFailed] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [channelRefreshing, setChannelRefreshing] = useState(false);
  const [channelAction, setChannelAction] = useState<"start" | "stop" | null>(null);

  useEffect(() => {
    let alive = true;

    Promise.allSettled([api.getChannelStatus(), api.getChannelsConfig()])
      .then(([statusResult, configResult]) => {
        if (!alive) return;
        if (statusResult.status === "fulfilled") {
          setChannelStatus(statusResult.value);
        } else {
          const message = statusResult.reason instanceof Error
            ? statusResult.reason.message
            : t("settings.unknownError", { defaultValue: "Unknown error" });
          toast.error(`${t("settings.channels.refreshFailed")}: ${message}`);
          setChannelStatus(null);
        }
        if (configResult.status === "fulfilled") {
          setChannelsConfig(configResult.value);
          setConfigFailed(false);
        } else {
          setChannelsConfig(null);
          setConfigFailed(true);
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [t]);

  const reloadConfig = useCallback(async () => {
    try {
      setChannelsConfig(await api.getChannelsConfig());
      setConfigFailed(false);
    } catch {
      setChannelsConfig(null);
      setConfigFailed(true);
    }
  }, []);

  /** Re-read runtime status + config after a panel save/toggle (hot-applied). */
  const refreshAfterChange = useCallback(async () => {
    const [statusResult, configResult] = await Promise.allSettled([
      api.getChannelStatus(),
      api.getChannelsConfig(),
    ]);
    if (statusResult.status === "fulfilled") setChannelStatus(statusResult.value);
    if (configResult.status === "fulfilled") {
      setChannelsConfig(configResult.value);
      setConfigFailed(false);
    } else {
      setConfigFailed(true);
    }
  }, []);

  const refreshChannelStatus = async () => {
    setChannelRefreshing(true);
    try {
      const [statusResult] = await Promise.allSettled([
        api.getChannelStatus(),
        reloadConfig(),
      ]);
      if (statusResult.status === "fulfilled") {
        setChannelStatus(statusResult.value);
      } else {
        throw statusResult.reason;
      }
    } catch (error) {
      toast.error(`${t("settings.channels.refreshFailed")}: ${error instanceof Error ? error.message : t("settings.unknownError", { defaultValue: "Unknown error" })}`);
    } finally {
      setChannelRefreshing(false);
    }
  };

  const setChannelsRunning = async (action: "start" | "stop") => {
    setChannelAction(action);
    try {
      const updated = action === "start" ? await api.startChannels() : await api.stopChannels();
      setChannelStatus(updated);
      toast.success(action === "start" ? t("settings.channels.started") : t("settings.channels.stoppedToast"));
    } catch (error) {
      toast.error(`${action === "start" ? t("settings.channels.startFailed") : t("settings.channels.stopFailed")}: ${error instanceof Error ? error.message : t("settings.unknownError", { defaultValue: "Unknown error" })}`);
    } finally {
      setChannelAction(null);
    }
  };

  const rows = useMemo(() => {
    const statusChannels = channelStatus?.channels ?? {};
    const configChannels = channelsConfig?.channels ?? {};
    const names = Array.from(new Set([
      ...Object.keys(statusChannels),
      ...Object.keys(configChannels),
    ])).sort((a, b) => a.localeCompare(b));
    return names.map((name) => ({
      name,
      status: statusChannels[name],
      entry: configChannels[name],
    }));
  }, [channelStatus, channelsConfig]);

  const statusChannels = Object.values(channelStatus?.channels ?? {});
  const channelEnabledCount = statusChannels.filter((item) => item.enabled).length;
  const channelLoadedCount = statusChannels.filter((item) => item.loaded).length;
  const channelUnavailableCount = statusChannels.filter((item) => item.available === false).length;
  const channelBusy = channelRefreshing || channelAction !== null;
  const writable = channelsConfig?.writable ?? false;

  const toggleExpanded = (name: string) => {
    setExpanded((current) => ({ ...current, [name]: !current[name] }));
  };

  return (
    <section className="rounded-lg border bg-card p-5 shadow-sm">
      <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <MessageSquareMore className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t("settings.channels.title")}</h2>
            {channelsConfig && !channelsConfig.writable ? (
              <span className="rounded-full bg-warning/10 px-2 py-0.5 text-xs text-warning-foreground">
                {t("settings.channels.config.notWritableChip")}
              </span>
            ) : null}
            {configFailed ? (
              <span className="rounded-full bg-warning/10 px-2 py-0.5 text-xs text-warning-foreground">
                {t("settings.channels.config.loadFailed")}
              </span>
            ) : null}
          </div>
          <p className="max-w-3xl text-sm text-muted-foreground">{t("settings.channels.description")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void refreshChannelStatus()}
            disabled={channelBusy}
            className="inline-flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
          >
            {channelRefreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {t("settings.channels.refresh")}
          </button>
          <button
            type="button"
            onClick={() => void setChannelsRunning("start")}
            disabled={channelBusy || !channelStatus}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {channelAction === "start" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {t("settings.channels.start")}
          </button>
          <button
            type="button"
            onClick={() => void setChannelsRunning("stop")}
            disabled={channelBusy || !channelStatus}
            className="inline-flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
          >
            {channelAction === "stop" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
            {t("settings.channels.stop")}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("settings.loading")}
        </div>
      ) : channelStatus ? (
        <>
          <div className="mb-4 grid gap-3 md:grid-cols-4">
            <div className="rounded-md border bg-muted/20 px-3 py-2">
              <div className="text-xs text-muted-foreground">{t("settings.channels.runtime")}</div>
              <div className="text-sm font-medium">{channelStatus.running ? t("settings.channels.running") : t("settings.channels.stopped")}</div>
            </div>
            <div className="rounded-md border bg-muted/20 px-3 py-2">
              <div className="text-xs text-muted-foreground">{t("settings.channels.enabled")}</div>
              <div className="text-sm font-medium">{channelEnabledCount}</div>
            </div>
            <div className="rounded-md border bg-muted/20 px-3 py-2">
              <div className="text-xs text-muted-foreground">{t("settings.channels.loaded")}</div>
              <div className="text-sm font-medium">{channelLoadedCount}</div>
            </div>
            <div className="rounded-md border bg-muted/20 px-3 py-2">
              <div className="text-xs text-muted-foreground">{t("settings.channels.unavailable")}</div>
              <div className="text-sm font-medium">{channelUnavailableCount}</div>
            </div>
          </div>

          <div className="overflow-hidden rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-start font-medium">{t("settings.channels.channel")}</th>
                  <th className="px-3 py-2 text-start font-medium">{t("settings.channels.state")}</th>
                  <th className="px-3 py-2 text-start font-medium">{t("settings.channels.recovery")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ name, status: item, entry }) => {
                  const displayName = item?.display_name || entry?.display_name || name;
                  const isExpanded = Boolean(expanded[name]);
                  const enabled = item?.enabled ?? Boolean(entry?.values.enabled);
                  const loaded = item?.loaded ?? entry?.loaded ?? false;
                  const running = item?.running ?? false;
                  const recovery =
                    item?.install_hint || item?.error
                    || entry?.install_hint || entry?.error
                    || t("settings.channels.noRecovery");
                  return (
                    <Fragment key={name}>
                      <tr className="border-t">
                        <td className="px-3 py-2 align-top">
                          <button
                            type="button"
                            onClick={() => toggleExpanded(name)}
                            aria-expanded={isExpanded}
                            aria-label={t("settings.channels.config.toggleConfig", { name: displayName })}
                            className="flex items-start gap-2 text-start"
                          >
                            <ChevronRight
                              className={`mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform ${isExpanded ? "rotate-90" : ""}`}
                            />
                            <span>
                              <span className="block font-medium">{displayName}</span>
                              <span className="block text-xs text-muted-foreground">{name}</span>
                            </span>
                          </button>
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex flex-wrap gap-1.5">
                            <span className={`rounded-full px-2 py-0.5 text-xs ${enabled ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"}`}>
                              {enabled ? t("settings.channels.enabled") : t("settings.channels.disabled")}
                            </span>
                            <span className={`rounded-full px-2 py-0.5 text-xs ${loaded ? "bg-success/10 text-success" : "bg-muted text-muted-foreground"}`}>
                              {loaded ? t("settings.channels.loaded") : t("settings.channels.notLoaded")}
                            </span>
                            <span className={`rounded-full px-2 py-0.5 text-xs ${running ? "bg-success/10 text-success" : "bg-muted text-muted-foreground"}`}>
                              {running ? t("settings.channels.running") : t("settings.channels.stopped")}
                            </span>
                          </div>
                        </td>
                        <td className="max-w-md px-3 py-2 align-top text-xs text-muted-foreground">
                          {recovery}
                        </td>
                      </tr>
                      {isExpanded ? (
                        <tr className="border-t bg-muted/10">
                          <td colSpan={3} className="px-3 py-4">
                            {entry ? (
                              <ChannelConfigPanel
                                name={name}
                                entry={entry}
                                writable={writable}
                                configPath={channelsConfig?.config_path}
                                onChanged={refreshAfterChange}
                              />
                            ) : (
                              <p className="text-sm text-muted-foreground">
                                {t("settings.channels.config.loadFailed")}
                              </p>
                            )}
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="rounded-md border bg-muted/20 px-4 py-6 text-center text-sm text-muted-foreground">
          {t("settings.channels.refreshFailed")}
        </div>
      )}
    </section>
  );
}
