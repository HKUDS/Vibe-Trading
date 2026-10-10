import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  buildPayoffRequest,
  roundToNiceStrike,
  STRATEGY_PRESETS,
  type OptionLeg,
  type OptionsLabParams,
} from "@/lib/options";

interface Props {
  legs: OptionLeg[];
  params: OptionsLabParams;
  activePresetId: string | null;
  onApplyPreset: (presetId: string) => void;
  onLegsChange: (legs: OptionLeg[]) => void;
  onParamsChange: (params: OptionsLabParams) => void;
}

const INPUT_CLS =
  "w-full rounded-md border border-border/60 bg-background px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-primary/40";

export function StrategyBuilder({
  legs,
  params,
  activePresetId,
  onApplyPreset,
  onLegsChange,
  onParamsChange,
}: Props) {
  const { t } = useTranslation();

  const updateLeg = (index: number, patch: Partial<OptionLeg>) => {
    onLegsChange(legs.map((leg, i) => (i === index ? { ...leg, ...patch } : leg)));
  };

  const removeLeg = (index: number) => {
    onLegsChange(legs.filter((_, i) => i !== index));
  };

  const addLeg = () => {
    onLegsChange([
      ...legs,
      {
        option_type: "call",
        strike: roundToNiceStrike(params.entry_spot) || 100,
        qty: 1,
      },
    ]);
  };

  const setParam = (patch: Partial<OptionsLabParams>) => {
    onParamsChange({ ...params, ...patch });
  };

  const inputsValid = buildPayoffRequest(legs, params) !== null;

  return (
    <section className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
      <div className="mb-3 text-sm font-semibold">{t("options.builder.title")}</div>

      {/* Presets */}
      <div className="mb-1 text-xs font-medium text-muted-foreground">{t("options.presets.label")}</div>
      <div className="mb-4 flex flex-wrap gap-1.5">
        {STRATEGY_PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            onClick={() => onApplyPreset(preset.id)}
            className={cn(
              "rounded border px-2.5 py-1 text-xs transition-colors",
              activePresetId === preset.id
                ? "border-primary bg-primary text-primary-foreground"
                : "border-muted-foreground/30 text-muted-foreground hover:border-primary hover:text-foreground",
            )}
          >
            {t(preset.nameKey as never)}
          </button>
        ))}
      </div>

      {/* Legs table */}
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">{t("options.builder.legs")}</span>
        <span className="text-[10px] text-muted-foreground/70">{t("options.builder.qtyHint")}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th className="pb-1.5 pe-2 font-medium text-start">{t("options.builder.type")}</th>
              <th className="pb-1.5 pe-2 font-medium text-start">{t("options.builder.strike")}</th>
              <th className="pb-1.5 pe-2 font-medium text-start">{t("options.builder.qty")}</th>
              <th className="pb-1.5 pe-2 font-medium text-start">{t("options.builder.premium")}</th>
              <th className="pb-1.5 font-medium" aria-hidden="true" />
            </tr>
          </thead>
          <tbody>
            {legs.map((leg, i) => (
              <tr key={i} className="border-t border-border/40">
                <td className="py-1.5 pe-2">
                  <select
                    value={leg.option_type}
                    onChange={(e) => updateLeg(i, { option_type: e.target.value as OptionLeg["option_type"] })}
                    className={cn(INPUT_CLS, "min-w-20")}
                    aria-label={`${t("options.builder.type")} ${i + 1}`}
                  >
                    <option value="call">{t("options.builder.call")}</option>
                    <option value="put">{t("options.builder.put")}</option>
                  </select>
                </td>
                <td className="py-1.5 pe-2">
                  <input
                    type="number"
                    min={0}
                    step="any"
                    value={Number.isFinite(leg.strike) ? leg.strike : ""}
                    onChange={(e) => updateLeg(i, { strike: parseFloat(e.target.value) })}
                    className={cn(INPUT_CLS, "min-w-20 tabular-nums")}
                    aria-label={`${t("options.builder.strike")} ${i + 1}`}
                  />
                </td>
                <td className="py-1.5 pe-2">
                  <input
                    type="number"
                    step={1}
                    value={Number.isFinite(leg.qty) ? leg.qty : ""}
                    onChange={(e) => updateLeg(i, { qty: parseInt(e.target.value, 10) })}
                    className={cn(INPUT_CLS, "min-w-16 tabular-nums")}
                    aria-label={`${t("options.builder.qty")} ${i + 1}`}
                  />
                </td>
                <td className="py-1.5 pe-2">
                  <input
                    type="number"
                    min={0}
                    step="any"
                    placeholder="BS"
                    value={leg.premium === undefined ? "" : leg.premium}
                    onChange={(e) =>
                      updateLeg(i, {
                        premium: e.target.value === "" ? undefined : parseFloat(e.target.value),
                      })
                    }
                    className={cn(INPUT_CLS, "min-w-20 tabular-nums")}
                    aria-label={`${t("options.builder.premium")} ${i + 1}`}
                    title={t("options.builder.premiumHint")}
                  />
                </td>
                <td className="py-1.5 text-end">
                  <button
                    type="button"
                    onClick={() => removeLeg(i)}
                    disabled={legs.length <= 1}
                    className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-danger/10 hover:text-danger disabled:opacity-30"
                    aria-label={`${t("options.builder.removeLeg")} ${i + 1}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={addLeg}
          className="flex items-center gap-1 rounded-md border border-dashed border-muted-foreground/40 px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
        >
          <Plus className="h-3 w-3" />
          {t("options.builder.addLeg")}
        </button>
        <span className="text-[10px] text-muted-foreground/70">{t("options.builder.premiumHint")}</span>
      </div>

      {/* Parameters */}
      <div className="mt-4 mb-2 text-xs font-medium text-muted-foreground">{t("options.builder.parameters")}</div>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="option-entry_spot" className="text-[11px] text-muted-foreground">{t("options.builder.entrySpot")}</label>
          <input
            type="number"
            min={0}
            step="any"
            id="option-entry_spot"
            value={Number.isFinite(params.entry_spot) ? params.entry_spot : ""}
            onChange={(e) => setParam({ entry_spot: parseFloat(e.target.value) })}
            className={cn(INPUT_CLS, "tabular-nums")}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="option-expiry_days" className="text-[11px] text-muted-foreground">{t("options.builder.expiryDays")}</label>
          <input
            type="number"
            min={0}
            step={1}
            id="option-expiry_days"
            value={Number.isFinite(params.expiry_days) ? params.expiry_days : ""}
            onChange={(e) => setParam({ expiry_days: parseFloat(e.target.value) })}
            className={cn(INPUT_CLS, "tabular-nums")}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="option-volatility_pct" className="text-[11px] text-muted-foreground">{t("options.builder.volatility")}</label>
          <input
            type="number"
            min={0}
            step="any"
            id="option-volatility_pct"
            value={Number.isFinite(params.volatility_pct) ? params.volatility_pct : ""}
            onChange={(e) => setParam({ volatility_pct: parseFloat(e.target.value) })}
            className={cn(INPUT_CLS, "tabular-nums")}
          />
        </div>
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-muted-foreground">{t("analysis.advancedParameters")}</summary>
        <div className="mt-3 grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="option-risk_free_rate_pct" className="text-[11px] text-muted-foreground">{t("options.builder.riskFreeRate")}</label>
          <input
            type="number"
            step="any"
            id="option-risk_free_rate_pct"
            value={Number.isFinite(params.risk_free_rate_pct) ? params.risk_free_rate_pct : ""}
            onChange={(e) => setParam({ risk_free_rate_pct: parseFloat(e.target.value) })}
            className={cn(INPUT_CLS, "tabular-nums")}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="option-multiplier" className="text-[11px] text-muted-foreground">{t("options.builder.multiplier")}</label>
          <input
            type="number"
            min={0}
            step="any"
            id="option-multiplier"
            value={Number.isFinite(params.multiplier) ? params.multiplier : ""}
            onChange={(e) => setParam({ multiplier: parseFloat(e.target.value) })}
            className={cn(INPUT_CLS, "tabular-nums")}
          />
          <span className="text-[10px] text-muted-foreground/70">{t("options.builder.multiplierHint")}</span>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="option-commission_rate_pct" className="text-[11px] text-muted-foreground">{t("options.builder.commissionRate")}</label>
          <input
            type="number"
            min={0}
            step="any"
            id="option-commission_rate_pct"
            value={Number.isFinite(params.commission_rate_pct) ? params.commission_rate_pct : ""}
            onChange={(e) => setParam({ commission_rate_pct: parseFloat(e.target.value) })}
            className={cn(INPUT_CLS, "tabular-nums")}
          />
        </div>
      </div>

      </details>

      {!inputsValid && (
        <p className="mt-3 rounded border border-warning/30 bg-warning/5 p-2 text-xs text-warning">
          {t("options.builder.invalidHint")}
        </p>
      )}
    </section>
  );
}
