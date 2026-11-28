import { Cpu, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { LLMSettings, SessionModelSelection } from "@/lib/api";
import { effortLabelKey } from "@/lib/reasoningEffort";

interface Props {
  settings: LLMSettings | null;
  runtimeProvider?: string;
  runtimeModel?: string;
  runtimeReasoningEffort?: string;
  sessionModel?: SessionModelSelection | null;
  onSelectionChange?: (selection: { provider: string; model: string; reasoning_effort: string }) => void;
  onClearSelection?: () => void;
}

export function ModelRuntimeBar({
  settings,
  runtimeProvider,
  runtimeModel,
  runtimeReasoningEffort,
  sessionModel,
  onSelectionChange,
  onClearSelection,
}: Props) {
  const { t } = useTranslation();
  if (!settings) return null;

  const providerId = sessionModel?.provider || runtimeProvider || settings.provider;
  const provider = settings.providers.find((item) => item.name === providerId);
  const providerLabel = provider?.label || providerId || t("agent.unknownProvider");
  const model = sessionModel?.model || runtimeModel || settings.model_name || t("agent.unknownModel");
  const reasoningEffort = runtimeReasoningEffort !== undefined
    ? (sessionModel?.reasoning_effort || runtimeReasoningEffort)
    : (sessionModel?.reasoning_effort || settings.reasoning_effort);
  const effortKey = effortLabelKey(reasoningEffort);
  const effortLabel = effortKey ? t(effortKey) : t("settings.providerDefault");

  return (
    <div className="shrink-0 border-b border-border/70 bg-background/95 px-6 py-2 backdrop-blur-sm">
      <div className="mx-auto flex max-w-3xl items-center gap-2 overflow-hidden text-xs">
        <span className="relative flex h-2 w-2 shrink-0" aria-hidden="true">
          <span className="absolute inline-flex h-full w-full rounded-full bg-success/30" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
        </span>
        <span className="shrink-0 font-medium text-foreground">{providerLabel}</span>
        <span className="text-muted-foreground/60">·</span>
        <span className="truncate font-mono text-[11px] text-muted-foreground" title={model}>{model}</span>
        <span className="shrink-0 text-[10px] text-muted-foreground">
          {sessionModel?.source === "session" ? t("agent.sessionModel") : t("agent.inheritedModel")}
        </span>
        <span className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border/70 bg-muted/35 px-2 py-0.5 text-[10px] text-muted-foreground">
          <Cpu className="h-3 w-3" aria-hidden="true" />
          {t("agent.reasoningStrength")}: {effortLabel}
        </span>
        {onSelectionChange && (
          <details className="relative shrink-0">
            <summary className="flex cursor-pointer list-none items-center gap-1 rounded border border-border/70 px-2 py-1 text-[10px] text-muted-foreground hover:bg-muted">
              <Settings2 className="h-3 w-3" aria-hidden="true" />
              {t("agent.changeModel")}
            </summary>
            <div className="absolute right-0 top-8 z-20 w-64 space-y-2 rounded-lg border border-border bg-background p-3 shadow-xl">
              <label className="block text-[10px] text-muted-foreground">
                {t("agent.provider")}
                <select
                  className="mt-1 w-full rounded border bg-background px-2 py-1 text-xs text-foreground"
                  value={providerId}
                  onChange={(event) => {
                    const nextProvider = settings.providers.find((item) => item.name === event.target.value);
                    const nextModel = nextProvider?.model_options?.[0] || nextProvider?.default_model || settings.model_name;
                    onSelectionChange({ provider: event.target.value, model: nextModel, reasoning_effort: "" });
                  }}
                >
                  {settings.providers.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}
                </select>
              </label>
              <label className="block text-[10px] text-muted-foreground">
                {t("agent.model")}
                <select
                  className="mt-1 w-full rounded border bg-background px-2 py-1 text-xs text-foreground"
                  value={model}
                  onChange={(event) => onSelectionChange({ provider: providerId, model: event.target.value, reasoning_effort: reasoningEffort || "" })}
                >
                  {Array.from(new Set([...(provider?.model_options || []), provider?.default_model || model])).filter(Boolean).map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              <label className="block text-[10px] text-muted-foreground">
                {t("agent.reasoningStrength")}
                <select
                  className="mt-1 w-full rounded border bg-background px-2 py-1 text-xs text-foreground"
                  value={reasoningEffort || ""}
                  onChange={(event) => onSelectionChange({ provider: providerId, model, reasoning_effort: event.target.value })}
                >
                  <option value="">{t("settings.providerDefault")}</option>
                  {(provider?.reasoning_efforts || []).map((effort) => <option key={effort} value={effort}>{effort}</option>)}
                </select>
              </label>
              {sessionModel?.source === "session" && onClearSelection && (
                <button type="button" className="w-full rounded border px-2 py-1 text-[10px] text-muted-foreground hover:bg-muted" onClick={onClearSelection}>
                  {t("agent.useInheritedModel")}
                </button>
              )}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}
