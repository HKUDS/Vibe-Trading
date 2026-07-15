import { Brain, Calculator, GitCompare, ShieldCheck } from "lucide-react";
import { SectionHeading } from "./SectionHeading";

const cards = [
  { icon: GitCompare, title: "Conflicting Market Signals", text: "Multiple analysis layers are reviewed before an opportunity receives a confidence score." },
  { icon: Brain, title: "Emotional Decision-Making", text: "Structured validation encourages traders to follow evidence and predefined risk rules." },
  { icon: Calculator, title: "Poor Risk Calculation", text: "Position-sizing and drawdown tools help traders understand exposure before entering." },
  { icon: ShieldCheck, title: "Unverified Strategies", text: "Backtesting and journaling help traders evaluate historical behaviour and personal execution." },
];

export function WhyTradeCoreFX() {
  return (
    <section id="why" className="px-4 py-16 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <SectionHeading
          title="Trading Decisions Need More Than Indicators"
          intro="Traders often receive too much information but too little clarity. TradeCoreFX organises market evidence into an explainable decision-support process."
        />
        <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {cards.map(({ icon: Icon, title, text }) => (
            <article key={title} className="rounded-2xl border bg-card p-5 shadow-sm">
              <Icon className="h-6 w-6 text-primary" aria-hidden="true" />
              <h3 className="mt-4 font-semibold">{title}</h3>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">{text}</p>
            </article>
          ))}
        </div>
        <p className="mx-auto mt-8 max-w-3xl text-center text-sm leading-6 text-muted-foreground">
          TradeCoreFX does not replace trader judgment. It improves the structure, transparency and accountability of that judgment.
        </p>
      </div>
    </section>
  );
}
