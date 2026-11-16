import { useTranslation } from "react-i18next";
import type { OptionLeg, PayoffAlternative, PayoffComparison } from "@/lib/options";

/** Keep named leg sets; all calculations and comparisons come from the server. */
export function PayoffComparisons({ label, alternatives, legs, comparisons, onChange }: {
  label: string;
  alternatives: PayoffAlternative[];
  legs: OptionLeg[];
  comparisons?: PayoffComparison[];
  onChange: (label: string, alternatives: PayoffAlternative[]) => void;
}) {
  const { t } = useTranslation();
  const save = () => {
    let index = 1;
    let name = t("options.comparison.saved", { index });
    while (name === label || alternatives.some((item) => item.label === name)) {
      name = t("options.comparison.saved", { index: ++index });
    }
    onChange(label, [...alternatives, { label: name, legs: legs.map((leg) => ({ ...leg })) }]);
  };
  const percent = (value: number | undefined) => value == null ? "—" : `${(value * 100).toFixed(2)}%`;
  return (
    <section className="rounded-xl border border-border/60 bg-card p-4 shadow-sm">
      <h2 className="text-sm font-semibold">{t("options.comparison.title")}</h2>
      <p className="my-2 text-xs text-muted-foreground">{t("options.comparison.basis")}</p>
      <label className="flex items-center gap-2 text-sm">
        {t("options.comparison.current")}
        <input className="rounded border bg-background px-2 py-1" value={label}
          onChange={(event) => onChange(event.target.value, alternatives)} />
      </label>
      <button className="my-2 rounded border px-3 py-1 text-sm disabled:opacity-50" disabled={alternatives.length >= 5 || !legs.length} onClick={save}>
        {t("options.comparison.save")}
      </button>
      <ul className="space-y-1">
        {alternatives.map((item, index) => <li key={index} className="flex items-center gap-2">
          <input className="rounded border bg-background px-2 py-1 text-sm"
            aria-label={t("options.comparison.saved", { index: index + 1 })} value={item.label}
            onChange={(event) => onChange(label, alternatives.map((entry, i) => i === index ? { ...entry, label: event.target.value } : entry))} />
          <button className="text-sm text-muted-foreground" onClick={() => onChange(label, alternatives.filter((_, i) => i !== index))}>{t("options.comparison.remove")}</button>
        </li>)}
      </ul>
      {!!comparisons?.length && <div className="mt-3 overflow-x-auto"><table className="w-full text-sm tabular-nums">
        <thead><tr>{(["metric", "alternative", "baseline", "difference"] as const).map((key) => <th key={key} className="p-2 text-start">{t(`options.comparison.${key}`)}</th>)}</tr></thead>
        <tbody>{comparisons.map((comparison) => comparison.status !== "ok"
          ? <tr key={comparison.left_label}><td colSpan={4} className="p-2">{comparison.left_label}: {comparison.reason}</td></tr>
          : Object.entries(comparison.metrics ?? {}).map(([metric, values]) => <tr key={`${comparison.left_label}-${metric}`} className="border-t border-border/40">
            <td className="p-2">{t(`options.comparison.${metric}`, { defaultValue: metric })}</td>
            <td className="p-2">{comparison.left_label}: {percent(values.left_decimal)}</td>
            <td className="p-2">{comparison.right_label}: {percent(values.right_decimal)}</td>
            <td className="p-2">{values.relation ? `${t(`options.comparison.${values.relation}`)} · ${values.difference_percentage_points?.toFixed(2)}` : "—"}</td>
          </tr>))}</tbody>
      </table></div>}
    </section>
  );
}
