import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { DisclosureNote } from "./DisclosureNote";
import { SectionHeading } from "./SectionHeading";

const opportunities = [
  { pair: "EUR/USD", bias: "Bullish", score: "82/100", trend: "Aligned", momentum: "Positive", volatility: "Moderate", risk: "Acceptable", classification: "Await Confirmation" },
  { pair: "GBP/JPY", bias: "Neutral", score: "58/100", trend: "Mixed", momentum: "Weak", volatility: "Elevated", risk: "Caution", classification: "Analyse Further" },
  { pair: "XAU/USD", bias: "Bearish", score: "74/100", trend: "Bearish", momentum: "Confirmed", volatility: "High", risk: "Reduced Position Size", classification: "Watch" },
];

export function OpportunityPreview() {
  const [open, setOpen] = useState("EUR/USD");
  return (
    <section id="opportunity-preview" className="px-4 py-16 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <SectionHeading title="See How TradeCoreFX Evaluates an Opportunity" />
        <div className="mx-auto mt-6 max-w-3xl"><DisclosureNote>The examples below are illustrative until connected to a verified live-market data provider.</DisclosureNote></div>
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {opportunities.map((item) => {
            const expanded = open === item.pair;
            return (
              <article key={item.pair} className="rounded-2xl border bg-card p-5 shadow-sm">
                <button type="button" aria-expanded={expanded} aria-controls={`${item.pair}-details`} onClick={() => setOpen(expanded ? "" : item.pair)} className="flex w-full items-center justify-between gap-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
                  <span><span className="block text-lg font-semibold">{item.pair}</span><span className="text-xs uppercase tracking-wide text-muted-foreground">Illustrative Market Analysis</span></span>
                  <ChevronDown className={cn("h-5 w-5 transition-transform", expanded && "rotate-180")} aria-hidden="true" />
                </button>
                <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
                  {[['Bias', item.bias], ['Score', item.score], ['Trend', item.trend], ['Momentum', item.momentum], ['Volatility', item.volatility], ['Risk Condition', item.risk], ['Classification', item.classification]].map(([k, v]) => <div key={k} className="rounded-xl border bg-background/60 p-3"><dt className="text-xs text-muted-foreground">{k}</dt><dd className="mt-1 font-medium">{v}</dd></div>)}
                </dl>
                {expanded && <div id={`${item.pair}-details`} className="mt-5 space-y-3 text-sm leading-6 text-muted-foreground">
                  <p><strong className="text-foreground">Supporting evidence:</strong> Trend context, session behaviour and structure alignment are reviewed together.</p>
                  <p><strong className="text-foreground">Conflicting evidence:</strong> Nearby liquidity and volatility conditions may reduce clarity.</p>
                  <p><strong className="text-foreground">Confirmation conditions:</strong> Wait for price behaviour to confirm the stated bias.</p>
                  <p><strong className="text-foreground">Invalidation conditions:</strong> Reassess if structure breaks or risk conditions deteriorate.</p>
                  <p><strong className="text-foreground">Risk notes:</strong> Position size should reflect stop distance, volatility and account risk limits.</p>
                </div>}
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
