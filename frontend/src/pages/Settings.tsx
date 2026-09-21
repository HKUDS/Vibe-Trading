import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Database, KeyRound, Loader2, RefreshCw, RotateCcw, Save, Server, SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ChannelSettings } from "@/components/settings/ChannelSettings";
import { ModelPicker } from "@/components/settings/ModelPicker";
import { QVerisSettings } from "@/components/settings/QVerisSettings"; // QVERIS-INTEGRATION
import { SourcePrioritySettings } from "@/components/settings/SourcePrioritySettings";
import { api, isAuthRequiredError, type DataSourceSettings, type LLMProviderOption, type LLMSettings } from "@/lib/api";
import { getApiAuthKey, setApiAuthKey } from "@/lib/apiAuth";

interface LLMFormState {
  provider: string;
  model_name: string;
  base_url: string;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort: string;
}

const fieldClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60";
const labelClass = "text-sm font-medium";
const hintClass = "text-xs text-muted-foreground";

function toForm(settings: LLMSettings): LLMFormState {
  return {
    provider: settings.provider,
    model_name: settings.model_name,
    base_url: settings.base_url,
    temperature: settings.temperature,
    timeout_seconds: settings.timeout_seconds,
    max_retries: settings.max_retries,
    reasoning_effort: settings.reasoning_effort || "",
  };
}

export function Settings() {
  const { t } = useTranslation();
  const isDesktop = window.vibeDesktop?.isDesktop === true;
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [dataSettings, setDataSettings] = useState<DataSourceSettings | null>(null);
  const [form, setForm] = useState<LLMFormState | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelListHint, setModelListHint] = useState<string | null>(null);
  const [localApiKey, setLocalApiKeyState] = useState(() => getApiAuthKey());
  const [clearApiKey, setClearApiKey] = useState(false);
  const [tushareToken, setTushareToken] = useState("");
  const [clearTushareToken, setClearTushareToken] = useState(false);
  const [gildataToken, setGildataToken] = useState("");
  const [clearGildataToken, setClearGildataToken] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dataSaving, setDataSaving] = useState(false);
  const [settingsLoadError, setSettingsLoadError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;

    Promise.allSettled([
      api.getLLMSettings(),
      api.getDataSourceSettings(),
    ])
      .then(([llmResult, dataSourceResult]) => {
        if (!alive) return;

        if (llmResult.status === "fulfilled") {
          setSettings(llmResult.value);
          setForm(toForm(llmResult.value));
          setModelOptions(Array.from(new Set([
            llmResult.value.model_name,
            llmResult.value.providers.find((provider) => provider.name === llmResult.value.provider)?.default_model ?? "",
          ].filter(Boolean))));
        } else {
          const message = llmResult.reason instanceof Error
            ? llmResult.reason.message
            : t("settings.unknownError", { defaultValue: "Unknown error" });
          setSettingsLoadError(message);
          if (isAuthRequiredError(llmResult.reason)) {
            toast.error(message);
          } else {
            toast.error(t("settings.loadLlmSettingsFailed", { message }));
          }
        }

        if (dataSourceResult.status === "fulfilled") {
          setDataSettings(dataSourceResult.value);
        } else {
          const message = dataSourceResult.reason instanceof Error
            ? dataSourceResult.reason.message
            : t("settings.unknownError", { defaultValue: "Unknown error" });
          setSettingsLoadError(message);
          if (isAuthRequiredError(dataSourceResult.reason)) {
            toast.error(message);
          } else {
            toast.error(t("settings.loadDataSourceSettingsFailed", { message }));
          }
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [t]);

  const providers = settings?.providers ?? [];
  const selectedProvider = useMemo<LLMProviderOption | undefined>(
    () => providers.find((provider) => provider.name === form?.provider),
    [form?.provider, providers],
  );

  const applyProviderDefaults = (provider = selectedProvider) => {
    if (!provider || !form) return;
    setForm({
      ...form,
      model_name: provider.default_model,
      base_url: provider.default_base_url,
    });
    setModelOptions([provider.default_model]);
    setModelListHint(null);
  };

  const onProviderChange = (name: string) => {
    const provider = providers.find((item) => item.name === name);
    if (!provider || !form) return;
    setForm({
      ...form,
      provider: provider.name,
      model_name: provider.default_model,
      base_url: provider.default_base_url,
    });
    setApiKey("");
    setClearApiKey(false);
    setModelOptions([provider.default_model]);
    setModelListHint(null);
  };

  const refreshModels = async () => {
    if (!form || !selectedProvider) return;
    setModelsLoading(true);
    setModelListHint(null);
    try {
      const result = await api.listLLMModels({
        provider: form.provider,
        base_url: form.base_url,
        api_key: apiKey.trim() || undefined,
      });
      setModelOptions(Array.from(new Set([
        form.model_name,
        selectedProvider.default_model,
        ...result.models,
      ].filter(Boolean))));
      const warningMessages = {
        oauth_discovery_unsupported: t("settings.modelDiscoveryOauthUnsupported"),
        api_key_required: t("settings.modelDiscoveryApiKeyRequired"),
        model_list_unavailable: t("settings.modelDiscoveryUnavailable"),
      };
      setModelListHint(
        result.warning_code
          ? warningMessages[result.warning_code]
          : t("settings.modelsLoaded", { count: result.models.length }),
      );
    } catch (error) {
      setModelListHint(error instanceof Error ? error.message : t("settings.modelsLoadFailed"));
    } finally {
      setModelsLoading(false);
    }
  };

  const submitLocalApiKey = (event: FormEvent) => {
    event.preventDefault();
    setApiAuthKey(localApiKey);
    toast.success(t("settings.localApiKeySaved"));
    window.location.reload();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      const desktop = window.vibeDesktop;
      const updated = await api.updateLLMSettings({
        ...form,
        api_key: isDesktop ? undefined : apiKey.trim() || undefined,
        clear_api_key: isDesktop ? false : clearApiKey,
      });
      if (desktop && selectedProvider?.api_key_env && (apiKey.trim() || clearApiKey)) {
        await desktop.setCredential(
          selectedProvider.api_key_env,
          clearApiKey ? null : apiKey.trim(),
        );
      }
      setSettings(updated);
      setForm(toForm(updated));
      setApiKey("");
      setClearApiKey(false);
      toast.success(t("settings.llmSettingsSaved"));
      if (desktop && selectedProvider?.api_key_env && (apiKey.trim() || clearApiKey)) {
        toast.info(t("settings.desktopCredentialRestarting"));
        await desktop.restartBackend();
      }
    } catch (error) {
      toast.error(t("settings.saveLlmSettingsFailed", {
        message: error instanceof Error
          ? error.message
          : t("settings.unknownError", { defaultValue: "Unknown error" }),
      }));
    } finally {
      setSaving(false);
    }
  };

  const submitDataSources = async (event: FormEvent) => {
    event.preventDefault();
    setDataSaving(true);
    try {
      const desktop = window.vibeDesktop;
      const updated = await api.updateDataSourceSettings({
        tushare_token: isDesktop ? undefined : tushareToken.trim() || undefined,
        clear_tushare_token: isDesktop ? false : clearTushareToken,
        gildata_token: isDesktop ? undefined : gildataToken.trim() || undefined,
        clear_gildata_token: isDesktop ? false : clearGildataToken,
      });
      if (desktop && (tushareToken.trim() || clearTushareToken)) {
        await desktop.setCredential(
          "TUSHARE_TOKEN",
          clearTushareToken ? null : tushareToken.trim(),
        );
      }
      if (desktop && (gildataToken.trim() || clearGildataToken)) {
        await desktop.setCredential(
          "GILDATA_TOKEN",
          clearGildataToken ? null : gildataToken.trim(),
        );
      }
      setDataSettings(updated);
      setTushareToken("");
      setClearTushareToken(false);
      setGildataToken("");
      setClearGildataToken(false);
      toast.success(t("settings.dataSourceSettingsSaved"));
      if (desktop && (tushareToken.trim() || clearTushareToken)) {
        toast.info(t("settings.desktopCredentialRestarting"));
        await desktop.restartBackend();
      }
    } catch (error) {
      toast.error(t("settings.saveDataSourceSettingsFailed", {
        message: error instanceof Error
          ? error.message
          : t("settings.unknownError", { defaultValue: "Unknown error" }),
      }));
    } finally {
      setDataSaving(false);
    }
  };

  const localApiAccessSection = (
    <form onSubmit={submitLocalApiKey} className="rounded-lg border bg-card p-5 shadow-sm">
      <div className="mb-4 space-y-1">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" />
          <h2 className="text-base font-semibold">{t("settings.localApiAccess")}</h2>
        </div>
        <p className="text-sm text-muted-foreground">{t("settings.localApiAccessDesc")}</p>
      </div>
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="grid gap-2">
          <span className={labelClass}>{t("settings.serverApiKey")}</span>
          <input
            type="password"
            value={localApiKey}
            onChange={(event) => setLocalApiKeyState(event.target.value)}
            className={fieldClass}
            placeholder={t("settings.storedInBrowser")}
            autoComplete="current-password"
          />
        </label>
        <button
          type="submit"
          className="inline-flex items-center justify-center gap-2 self-end rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90"
        >
          <Save className="h-4 w-4" />
          {t("settings.save")}
        </button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{t("settings.storedInBrowser")}</p>
    </form>
  );

  if (loading || !form || !settings || !dataSettings) {
    return (
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{t("settings.title")}</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">{t("settings.subtitle")}</p>
        </div>
        {!isDesktop && localApiAccessSection}
        {/* QVERIS-INTEGRATION */}
        <QVerisSettings />
        <div className="flex min-h-32 items-center justify-center rounded-lg border bg-card p-5 text-sm text-muted-foreground">
          {settingsLoadError ? (
            <div className="text-center">
              <div className="font-medium text-foreground">{t("settings.unavailable")}</div>
              <div className="mt-1">{settingsLoadError}</div>
            </div>
          ) : (
            <>
              <Loader2 className="me-2 h-4 w-4 animate-spin" />
              {t("settings.loading")}
            </>
          )}
        </div>
      </div>
    );
  }

  const usesManagedAuth = Boolean(
    selectedProvider?.auth_type && selectedProvider.auth_type !== "api_key",
  );
  const keyStatus = settings.api_key_configured
    ? t("settings.configured")
    : settings.api_key_required
      ? t("settings.keepCurrentKey")
      : usesManagedAuth && selectedProvider?.login_command
        ? t("settings.providerUsesManagedAuth", { command: selectedProvider.login_command })
        : t("settings.noApiKeyRequired");
  const apiKeyDisabled = !selectedProvider?.api_key_required || clearApiKey;
  const tushareStatus = dataSettings.tushare_token_configured
    ? t("settings.configured")
    : t("settings.keepCurrentToken");
  const gildataStatus = dataSettings.gildata_token_configured
    ? t("settings.configured")
    : t("settings.keepCurrentToken");

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t("settings.title")}</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">{t("settings.subtitle")}</p>
      </div>

      {!isDesktop && localApiAccessSection}

      {/* QVERIS-INTEGRATION */}
      <QVerisSettings />

      <ChannelSettings />

      <div className="space-y-2">
        <h2 className="text-lg font-semibold tracking-tight">{t("settings.llmSettings")}</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">{t("settings.llmSettingsDesc")}</p>
      </div>

      {/* Column ratio matches the QVeris and data-source sections so the
          card seams align down the page. */}
      <form onSubmit={submit} className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
        <section className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="mb-5 flex items-center gap-2">
            <Server className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t("settings.connection")}</h2>
          </div>

          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.provider")}</span>
              <select
                value={form.provider}
                onChange={(event) => onProviderChange(event.target.value)}
                className={fieldClass}
              >
                {providers.map((provider) => (
                  <option key={provider.name} value={provider.name}>{provider.label}</option>
                ))}
              </select>
              <span className={hintClass}>
                {t("settings.providerChangeHint", {
                  defaultValue: "Changing providers updates the recommended model and endpoint.",
                })}
              </span>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.model")}</span>
              <div className="flex gap-2">
                <ModelPicker
                  value={form.model_name}
                  options={modelOptions}
                  onChange={(modelName) => setForm({ ...form, model_name: modelName })}
                  ariaLabel={t("settings.model")}
                  optionsAriaLabel={t("settings.modelOptions")}
                />
                <button
                  type="button"
                  onClick={() => void refreshModels()}
                  disabled={modelsLoading}
                  className="inline-flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
                  title={t("settings.loadModels")}
                >
                  {modelsLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  <span className="hidden sm:inline">{t("settings.loadModels")}</span>
                </button>
                <button
                  type="button"
                  onClick={() => applyProviderDefaults()}
                  className="inline-flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  title={t("settings.useProviderDefaults")}
                >
                  <RotateCcw className="h-4 w-4" />
                  <span className="hidden sm:inline">{t("settings.useProviderDefaults")}</span>
                </button>
              </div>
              <span className={hintClass}>
                {modelListHint || t("settings.modelPickerHint")}
              </span>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.baseUrl")}</span>
              <input
                value={form.base_url}
                onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                className={fieldClass}
                placeholder={selectedProvider?.default_base_url}
                list={selectedProvider?.base_url_options?.length ? "llm-base-url-options" : undefined}
                disabled={usesManagedAuth}
              />
              {selectedProvider?.base_url_options?.length ? (
                <datalist id="llm-base-url-options">
                  {selectedProvider.base_url_options.map((baseUrl) => (
                    <option key={baseUrl} value={baseUrl} />
                  ))}
                </datalist>
              ) : null}
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>
                {usesManagedAuth
                  ? t("settings.authentication", { defaultValue: "Authentication" })
                  : t("settings.apiKey", { defaultValue: "API key" })}
              </span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute start-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  className={`${fieldClass} ps-9`}
                  placeholder={keyStatus}
                  autoComplete="current-password"
                  disabled={apiKeyDisabled}
                />
              </div>
              <div className="flex items-start justify-between gap-3">
                <span className={hintClass}>{keyStatus}</span>
                {selectedProvider?.api_key_required ? (
                  <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={clearApiKey}
                      onChange={(event) => {
                        setClearApiKey(event.target.checked);
                        if (event.target.checked) setApiKey("");
                      }}
                      className="h-3.5 w-3.5 accent-primary"
                    />
                    {t("settings.clearApiKey")}
                  </label>
                ) : null}
              </div>
            </label>
          </div>
        </section>

        <section className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="mb-5 flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t("settings.generation")}</h2>
          </div>

          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.temperature")}</span>
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={form.temperature}
                onChange={(event) => setForm({ ...form, temperature: Number(event.target.value) })}
                className={fieldClass}
              />
              <span className={hintClass}>{t("settings.temperatureDesc")}</span>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.timeoutSeconds")}</span>
              <input
                type="number"
                min={1}
                max={3600}
                step={1}
                value={form.timeout_seconds}
                onChange={(event) => setForm({ ...form, timeout_seconds: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.maxRetries")}</span>
              <input
                type="number"
                min={0}
                max={20}
                step={1}
                value={form.max_retries}
                onChange={(event) => setForm({ ...form, max_retries: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.reasoningEffort")}</span>
              <select
                value={form.reasoning_effort}
                onChange={(event) => setForm({ ...form, reasoning_effort: event.target.value })}
                className={fieldClass}
              >
                <option value="">{t("settings.providerDefault")}</option>
                <option value="none">{t("settings.reasoningEffortNone")}</option>
                <option value="low">{t("settings.reasoningEffortLow")}</option>
                <option value="medium">{t("settings.reasoningEffortMedium")}</option>
                <option value="high">{t("settings.reasoningEffortHigh")}</option>
                <option value="max">{t("settings.reasoningEffortMax")}</option>
              </select>
              <span className={hintClass}>{t("settings.reasoningEffortDesc")}</span>
            </label>

            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{t("settings.saved")}: </span>
              <span className="break-all font-mono">{settings.env_path}</span>
            </div>

            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? t("settings.saving") : t("settings.save")}
            </button>
          </div>
        </section>
      </form>

      <form onSubmit={submitDataSources} className="rounded-lg border bg-card p-5 shadow-sm">
        <div className="mb-5 space-y-1">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t("settings.dataSourceSettings")}</h2>
          </div>
          <p className="text-sm text-muted-foreground">{t("settings.dataSourceSettingsDesc")}</p>
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.tushareToken")}</span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute start-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="password"
                  value={tushareToken}
                  onChange={(event) => setTushareToken(event.target.value)}
                  className={`${fieldClass} ps-9`}
                  placeholder={tushareStatus}
                  autoComplete="current-password"
                  disabled={clearTushareToken}
                />
              </div>
              <div className="flex items-start justify-between gap-3">
                <span className={hintClass}>
                  {t("settings.tushareTokenDesc", {
                    defaultValue: "Used for China A-share, futures, fund, and macro data. If unset, the project falls back to AKShare where available.",
                  })}
                </span>
                <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={clearTushareToken}
                    onChange={(event) => {
                      setClearTushareToken(event.target.checked);
                      if (event.target.checked) setTushareToken("");
                    }}
                    className="h-3.5 w-3.5 accent-primary"
                  />
                  {t("settings.clearTushareToken")}
                </label>
              </div>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t("settings.gildataToken")}</span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute start-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="password"
                  value={gildataToken}
                  onChange={(event) => setGildataToken(event.target.value)}
                  className={`${fieldClass} ps-9`}
                  placeholder={gildataStatus}
                  autoComplete="current-password"
                  disabled={clearGildataToken}
                />
              </div>
              <div className="flex items-start justify-between gap-3">
                <span className={hintClass}>
                  {t("settings.gildataTokenDesc", {
                    defaultValue: "Optional Gildata (Hundsun Juyuan) A-share feed. When set, it joins the tail of the A-share fallback chain.",
                  })}
                </span>
                <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={clearGildataToken}
                    onChange={(event) => {
                      setClearGildataToken(event.target.checked);
                      if (event.target.checked) setGildataToken("");
                    }}
                    className="h-3.5 w-3.5 accent-primary"
                  />
                  {t("settings.clearGildataToken")}
                </label>
              </div>
            </label>

            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{t("settings.saved")}: </span>
              <span className="break-all font-mono">{dataSettings.env_path}</span>
            </div>

            <button
              type="submit"
              disabled={dataSaving}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {dataSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {dataSaving ? t("settings.saving") : t("settings.saveDataSourceSettings")}
            </button>
          </div>

          <div className="rounded-md border bg-muted/20 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-sm font-medium">{t("settings.baostock")}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs ${dataSettings.baostock_supported ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>
                {dataSettings.baostock_supported ? t("settings.loaderAvailable") : t("settings.noProjectLoader")}
              </span>
            </div>
            <div className="space-y-2 text-sm text-muted-foreground">
              <p>{dataSettings.baostock_message}</p>
              <p>
                {dataSettings.baostock_installed
                  ? t("settings.pythonPackageInstalled")
                  : t("settings.pythonPackageNotInstalled")}
              </p>
            </div>
          </div>
        </div>
      </form>

      <SourcePrioritySettings />
    </div>
  );
}
