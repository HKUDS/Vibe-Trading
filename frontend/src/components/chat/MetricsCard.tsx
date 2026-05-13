import { memo } from "react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { getMetricLabel, DISPLAY_ORDER, formatMetricVal, metricSentiment } from "@/lib/formatters";

const SENTIMENT_EN = {
  positive: "text-success",
  neutral: "text-foreground",
  negative: "text-danger",
} as const;

const SENTIMENT_ZH = {
  positive: "text-danger",
  neutral: "text-foreground",
  negative: "text-success",
} as const;

interface Props {
  metrics: Record<string, number>;
  compact?: boolean;
}

export const MetricsCard = memo(function MetricsCard({ metrics, compact = false }: Props) {
  const { t, locale } = useI18n();
  const entries = DISPLAY_ORDER
    .filter((k) => metrics[k] != null)
    .map((k) => ({ k, v: metrics[k] }));

  if (entries.length === 0) return null;

  const shown = compact ? entries.slice(0, 6) : entries;
  const SENTIMENT = locale === "zh" ? SENTIMENT_ZH : SENTIMENT_EN;

  return (
    <div className={cn(
      "grid gap-1.5 rounded-xl border border-border/60 bg-muted/20 p-3",
      compact ? "grid-cols-3" : "grid-cols-[repeat(auto-fit,minmax(120px,1fr))]"
    )}>
      {shown.map(({ k, v }) => (
        <div key={k} className="text-center py-1">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
            {getMetricLabel(k, t as unknown as Record<string, string>)}
          </p>
          <p className={cn(
            "text-sm font-bold font-mono tabular-nums mt-0.5",
            SENTIMENT[metricSentiment(k, v)]
          )}>
            {formatMetricVal(k, v)}
          </p>
        </div>
      ))}
    </div>
  );
});
