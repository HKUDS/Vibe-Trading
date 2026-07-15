import { SectionHeading } from "./SectionHeading";

const stages = [
  ["Market Data", ["Price action", "Volatility", "Market sessions", "Economic context", "Historical behaviour"]],
  ["Analysis Layers", ["Market structure", "Trend alignment", "Momentum", "Liquidity", "Support and resistance", "Multi-timeframe confluence"]],
  ["Risk Review", ["Stop-loss distance", "Position size", "Risk percentage", "Drawdown exposure", "Event-risk conditions"]],
  ["Opportunity Report", ["Bias", "Supporting evidence", "Conflicting evidence", "Confirmation conditions", "Invalidation conditions", "Risk considerations", "Classification"]],
];
const classifications = ["Analyse Further", "Watch", "Await Confirmation", "Risk Conditions Unfavourable", "Avoid"];

export function IntelligencePipeline() {
  return (
    <section id="intelligence" className="px-4 py-16 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <SectionHeading title="From Raw Market Data to an Explainable Opportunity Report" />
        <div className="mt-10 grid gap-5 lg:grid-cols-[1fr_280px_1fr]">
          <div className="grid gap-5 md:grid-cols-2 lg:col-span-1">
            {stages.slice(0, 2).map(([title, items]) => <Stage key={title as string} title={title as string} items={items as string[]} />)}
          </div>
          <div className="rounded-3xl border bg-card p-6 text-center shadow-sm">
            <div className="mx-auto grid h-40 w-40 place-items-center rounded-full border-[12px] border-primary/20" role="img" aria-label="Evidence-Based Opportunity Score 82 out of 100, not a probability of profit">
              <div>
                <p className="text-4xl font-bold">82</p>
                <p className="text-xs text-muted-foreground">/100</p>
              </div>
            </div>
            <h3 className="mt-5 font-semibold">Evidence-Based Opportunity Score</h3>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">This score summarises evidence quality and conflict. It is not a probability of profit.</p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {classifications.map((item) => <span key={item} className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground">{item}</span>)}
            </div>
          </div>
          <div className="grid gap-5 md:grid-cols-2 lg:col-span-1">
            {stages.slice(2).map(([title, items]) => <Stage key={title as string} title={title as string} items={items as string[]} />)}
          </div>
        </div>
      </div>
    </section>
  );
}

function Stage({ title, items }: { title: string; items: string[] }) {
  return (
    <article className="rounded-2xl border bg-card p-5">
      <h3 className="font-semibold">{title}</h3>
      <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
        {items.map((item) => <li key={item} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />{item}</li>)}
      </ul>
    </article>
  );
}
