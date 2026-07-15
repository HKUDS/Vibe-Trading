import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { SectionHeading } from "./SectionHeading";

const backtesting = ["Rule-based strategy builder", "Historical test period", "Pair selection", "Timeframe", "Entry rules", "Exit rules", "Stop loss", "Take profit", "Session filters"];
const metrics = ["Total trades", "Win rate", "Profit factor", "Maximum drawdown", "Average risk-to-reward", "Longest losing streak", "Performance by month"];
const journal = ["MT4/MT5 history import", "Manual trade entry", "Screenshot attachment", "Setup classification", "Emotion tracking", "Rule-violation tracking", "Performance by pair", "Performance by session", "Performance by weekday", "Mistake patterns"];

export function PerformanceLabPreview() {
  return (
    <section id="performance" className="px-4 py-16 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <SectionHeading title="Test the Strategy. Review the Trader. Improve the Process." />
        <div className="mt-10 grid gap-6 lg:grid-cols-2">
          <Panel title="Strategy Backtesting" label="Demonstration Interface" items={backtesting} extra={metrics} />
          <Panel title="Trading Journal Intelligence" label="Illustrative Journal Summary" items={journal} extra={["Most Consistent Pair: EUR/USD", "Strongest Session: London", "Frequent Mistake: Early Exit", "Risk Rule Compliance: 76%", "Journal Quality: Improving"]} />
        </div>
        <div className="mt-8 text-center"><Link to="/reports" className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">Explore Performance Lab <ArrowRight className="h-4 w-4" aria-hidden="true" /></Link></div>
      </div>
    </section>
  );
}

function Panel({ title, label, items, extra }: { title: string; label: string; items: string[]; extra: string[] }) {
  return <article className="rounded-2xl border bg-card p-6"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-xl font-semibold">{title}</h3><span className="rounded-full border bg-muted/60 px-3 py-1 text-xs text-muted-foreground">{label}</span></div><div className="mt-5 grid gap-6 sm:grid-cols-2"><ul className="space-y-2 text-sm text-muted-foreground">{items.map((item) => <li key={item} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 rounded-full bg-primary" />{item}</li>)}</ul><div className="rounded-xl border bg-background/60 p-4"><ul className="space-y-2 text-sm text-muted-foreground">{extra.map((item) => <li key={item}>{item}</li>)}</ul></div></div></article>;
}
