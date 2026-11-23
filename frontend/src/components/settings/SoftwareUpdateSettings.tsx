import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type SoftwareUpdate } from "@/lib/api";

export function SoftwareUpdateSettings() {
  const { t } = useTranslation();
  const [update, setUpdate] = useState<SoftwareUpdate | null>(null);
  const [busy, setBusy] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState("");
  const desktop = window.vibeDesktop?.isDesktop ? window.vibeDesktop : undefined;
  const canInstall = update?.method === "desktop" && update.available
    && update.recovery !== "manual-intervention-required";

  async function check() {
    setBusy(true);
    setError("");
    setUpdate(null);
    try {
      setUpdate(await (desktop ? desktop.checkForUpdates() : api.checkForUpdates()));
    } catch {
      setError(t("updates.checkFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function install() {
    setBusy(true);
    setInstalling(true);
    setError("");
    try {
      await desktop!.installUpdate();
      // Keep the button locked until this process exits or the user checks again.
    } catch {
      setError(t("updates.installFailed"));
      setInstalling(false);
      setUpdate(null);
      setBusy(false);
    }
  }

  const method = update?.method;
  const guidance = method === "wheel" ? "pip"
    : method === "container" ? "container"
    : method === "desktop" ? "desktop"
    : method === "desktop-manual" || method === "desktop-unconfigured" ? "manual"
    : "source";
  return (
    <section className="space-y-3 rounded-lg border bg-card p-5" aria-label={t("updates.title")}>
      <h2 className="text-lg font-semibold">{t("updates.title")}</h2>
      <p className="text-sm text-muted-foreground">{t("updates.preserve")}</p>
      <button type="button" disabled={busy} onClick={() => void check()} className="rounded-md border px-3 py-2 text-sm disabled:opacity-50">
        {t(busy ? "updates.working" : "updates.check")}
      </button>
      <div aria-live="polite" className="space-y-2 text-sm">
        {update && <>
          <p>{t("updates.current", { version: update.current_version })}</p>
          {update.latest_version && <p>{t(update.available ? "updates.available" : "updates.currentLatest", { version: update.latest_version })}</p>}
          <p className="text-muted-foreground">{t(`updates.${guidance}`)}</p>
          {method === "wheel" && <code className="block">vibe-trading update</code>}
          {update.recovery && update.recovery !== "none" && (
            <p>{t(update.recovery === "completed" ? "updates.completed" : "updates.interrupted")}</p>
          )}
          {canInstall && <button type="button" disabled={busy} onClick={() => void install()} className="rounded-md bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50">
            {t("updates.install")}
          </button>}
        </>}
        {installing && <p>{t("updates.installing")}</p>}
        {error && <p role="alert" className="text-destructive">{error}</p>}
      </div>
    </section>
  );
}
