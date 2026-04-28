import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Database, KeyRound, Loader2, RotateCcw, Save, Server, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api, type DataSourceSettings, type LLMProviderOption, type LLMSettings } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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
  const { t } = useI18n();
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [dataSettings, setDataSettings] = useState<DataSourceSettings | null>(null);
  const [form, setForm] = useState<LLMFormState | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [tushareToken, setTushareToken] = useState("");
  const [clearTushareToken, setClearTushareToken] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dataSaving, setDataSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([api.getLLMSettings(), api.getDataSourceSettings()])
      .then(([llmData, dataSourceData]) => {
        if (!alive) return;
        setSettings(llmData);
        setForm(toForm(llmData));
        setDataSettings(dataSourceData);
      })
      .catch((error) => {
        toast.error(`${t.llmSettingsLoadFailed}: ${error.message}`);
        toast.error(`${t.dataSourceSettingsLoadFailed}: ${error.message}`);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, [t.dataSourceSettingsLoadFailed, t.llmSettingsLoadFailed]);

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
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      const updated = await api.updateLLMSettings({
        ...form,
        api_key: apiKey.trim() || undefined,
        clear_api_key: clearApiKey,
      });
      setSettings(updated);
      setForm(toForm(updated));
      setApiKey("");
      setClearApiKey(false);
      toast.success(t.llmSettingsSaved);
    } catch (error) {
      toast.error(`${t.llmSettingsSaveFailed}: ${error instanceof Error ? error.message : t.unknownError}`);
    } finally {
      setSaving(false);
    }
  };

  const submitDataSources = async (event: FormEvent) => {
    event.preventDefault();
    setDataSaving(true);
    try {
      const updated = await api.updateDataSourceSettings({
        tushare_token: tushareToken.trim() || undefined,
        clear_tushare_token: clearTushareToken,
      });
      setDataSettings(updated);
      setTushareToken("");
      setClearTushareToken(false);
      toast.success(t.dataSourceSettingsSaved);
    } catch (error) {
      toast.error(`${t.dataSourceSettingsSaveFailed}: ${error instanceof Error ? error.message : t.unknownError}`);
    } finally {
      setDataSaving(false);
    }
  };

  if (loading || !form || !settings || !dataSettings) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        {t.loading}
      </div>
    );
  }

  const keyStatus = settings.api_key_hint
    ? t.llmApiKeyConfigured.replace("{key}", settings.api_key_hint)
    : settings.api_key_required ? t.llmApiKeyPlaceholder : t.llmNoApiKeyRequired;
  const apiKeyDisabled = !selectedProvider?.api_key_required || clearApiKey;
  const tushareStatus = dataSettings.tushare_token_hint
    ? t.tushareTokenConfigured.replace("{key}", dataSettings.tushare_token_hint)
    : t.tushareTokenPlaceholder;

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t.settings}</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">{t.settingsDesc}</p>
      </div>

      <div className="space-y-2">
        <h2 className="text-lg font-semibold tracking-tight">{t.llmSettings}</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">{t.llmSettingsDesc}</p>
      </div>

      <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
        <section className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="mb-5 flex items-center gap-2">
            <Server className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t.llmConnection}</h2>
          </div>

          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{t.llmProvider}</span>
              <select
                value={form.provider}
                onChange={(event) => onProviderChange(event.target.value)}
                className={fieldClass}
              >
                {providers.map((provider) => (
                  <option key={provider.name} value={provider.name}>{provider.label}</option>
                ))}
              </select>
              <span className={hintClass}>{t.llmProviderHint}</span>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t.llmModelName}</span>
              <div className="flex gap-2">
                <input
                  value={form.model_name}
                  onChange={(event) => setForm({ ...form, model_name: event.target.value })}
                  className={fieldClass}
                  required
                />
                <button
                  type="button"
                  onClick={() => applyProviderDefaults()}
                  className="inline-flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  title={t.llmUseProviderDefaults}
                >
                  <RotateCcw className="h-4 w-4" />
                  <span className="hidden sm:inline">{t.llmUseProviderDefaults}</span>
                </button>
              </div>
              <span className={hintClass}>{t.llmModelHint}</span>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t.llmBaseUrl}</span>
              <input
                value={form.base_url}
                onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                className={fieldClass}
                placeholder={selectedProvider?.default_base_url}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t.llmApiKey}</span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  className={`${fieldClass} pl-9`}
                  placeholder={keyStatus}
                  autoComplete="current-password"
                  disabled={apiKeyDisabled}
                />
              </div>
              <div className="flex items-center justify-between gap-3">
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
                    {t.llmClearApiKey}
                  </label>
                ) : null}
              </div>
            </label>
          </div>
        </section>

        <section className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="mb-5 flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t.llmGeneration}</h2>
          </div>

          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{t.llmTemperature}</span>
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={form.temperature}
                onChange={(event) => setForm({ ...form, temperature: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{t.llmTimeoutSeconds}</span>
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
              <span className={labelClass}>{t.llmMaxRetries}</span>
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
              <span className={labelClass}>{t.llmReasoningEffort}</span>
              <select
                value={form.reasoning_effort}
                onChange={(event) => setForm({ ...form, reasoning_effort: event.target.value })}
                className={fieldClass}
              >
                <option value="">{t.llmReasoningOff}</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="max">max</option>
              </select>
            </label>

            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{t.llmEnvPath}: </span>
              <span className="break-all font-mono">{settings.env_path}</span>
            </div>

            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? t.llmSaving : t.llmSaveSettings}
            </button>
          </div>
        </section>
      </form>

      <form onSubmit={submitDataSources} className="rounded-lg border bg-card p-5 shadow-sm">
        <div className="mb-5 space-y-1">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t.dataSourceSettings}</h2>
          </div>
          <p className="text-sm text-muted-foreground">{t.dataSourceSettingsDesc}</p>
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{t.tushareToken}</span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="password"
                  value={tushareToken}
                  onChange={(event) => setTushareToken(event.target.value)}
                  className={`${fieldClass} pl-9`}
                  placeholder={tushareStatus}
                  autoComplete="current-password"
                  disabled={clearTushareToken}
                />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className={hintClass}>{t.tushareTokenHint}</span>
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
                  {t.clearTushareToken}
                </label>
              </div>
            </label>

            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{t.llmEnvPath}: </span>
              <span className="break-all font-mono">{dataSettings.env_path}</span>
            </div>

            <button
              type="submit"
              disabled={dataSaving}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {dataSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {dataSaving ? t.llmSaving : t.saveDataSourceSettings}
            </button>
          </div>

          <div className="rounded-md border bg-muted/20 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-sm font-medium">{t.baostockStatus}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs ${dataSettings.baostock_supported ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>
                {dataSettings.baostock_supported ? t.baostockSupported : t.baostockNotSupported}
              </span>
            </div>
            <div className="space-y-2 text-sm text-muted-foreground">
              <p>{dataSettings.baostock_message}</p>
              <p>
                {dataSettings.baostock_installed
                  ? t.baostockPackageInstalled
                  : t.baostockPackageMissing}
              </p>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}
