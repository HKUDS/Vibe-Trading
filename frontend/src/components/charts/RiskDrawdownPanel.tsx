import i18n from "@/i18n";
import type { RiskDrawdownEpisodes } from "@/lib/api";

const unavailableReasons = {
  missing_return_observations: "runDetail.riskDrawdownMissing",
  empty_path: "runDetail.riskDrawdownEmptyPath",
  non_finite_wealth: "runDetail.riskDrawdownNonFinite",
  non_positive_wealth: "runDetail.riskDrawdownNonPositive",
} as const;

export function RiskDrawdownPanel({ episodes }: { episodes?: RiskDrawdownEpisodes }) {
  if (!episodes) return null;
  const title = i18n.t("runDetail.riskDrawdownTitle");
  const current = episodes.current;

  return (
    <div className="mt-4 space-y-2 border-t pt-3">
      <h4 className="text-sm font-medium">{title}</h4>
      <p className="text-xs text-muted-foreground">
        {i18n.t("runDetail.riskDrawdownModel", { tolerance: episodes.recovery_rtol })}
      </p>
      {!episodes.available ? (
        <p className="text-xs text-warning">
          {i18n.t("runDetail.riskDrawdownUnavailable", {
            reason: i18n.t(unavailableReasons[episodes.reason] ?? "runDetail.riskDrawdownUnknown"),
          })}
        </p>
      ) : episodes.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{i18n.t("runDetail.riskDrawdownEmpty")}</p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            {i18n.t("runDetail.riskDrawdownCount", { shown: episodes.items.length, total: episodes.total })}
          </p>
          <div className="overflow-x-auto">
            <table aria-label={title} className="w-full whitespace-nowrap text-sm">
              <thead>
                <tr className="border-b bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground [&_th]:font-medium">
                  <th className="py-2 ps-4 pr-4">{i18n.t("runDetail.ddRank")}</th>
                  <th className="py-2 pr-4">{i18n.t("runDetail.ddDepth")}</th>
                  <th className="py-2 pr-4">{i18n.t("runDetail.ddPeak")}</th>
                  <th className="py-2 pr-4">{i18n.t("runDetail.ddTrough")}</th>
                  <th className="py-2 pr-4">{i18n.t("runDetail.ddRecovery")}</th>
                  <th className="py-2">{i18n.t("runDetail.riskDrawdownBars")}</th>
                </tr>
              </thead>
              <tbody>
                {episodes.items.map((item, index) => (
                  <tr key={`${item.peak}-${index}`} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="py-2 ps-4 pr-4 font-mono tabular-nums text-muted-foreground">{index + 1}</td>
                    <td className="py-2 pr-4 font-mono tabular-nums text-danger">{(item.depth * 100).toFixed(2)}%</td>
                    <td className="py-2 pr-4 font-mono text-xs">{item.peak ?? "-"}</td>
                    <td className="py-2 pr-4 font-mono text-xs">{item.trough ?? "-"}</td>
                    <td className="py-2 pr-4 font-mono text-xs">{item.recovery ?? i18n.t("runDetail.ddNotRecovered")}</td>
                    <td className="py-2 font-mono tabular-nums">{item.duration_bars}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {current && (
            <div className="space-y-1 text-xs">
              <p>{i18n.t("runDetail.riskDrawdownCurrent", { depth: `${(current.depth * 100).toFixed(2)}%`, bars: current.duration_bars })}</p>
              <p className="text-muted-foreground">
                {i18n.t("runDetail.ddPeak")}: {current.peak ?? "-"}; {i18n.t("runDetail.ddTrough")}: {current.trough ?? "-"}
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
