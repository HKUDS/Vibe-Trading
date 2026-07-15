import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { IntelligenceTerminal } from "./IntelligenceTerminal";

export function HeroSection() {
  return (
    <section id="platform" className="overflow-hidden px-4 py-20 sm:px-6 lg:px-8 lg:py-24">
      <div className="mx-auto grid max-w-7xl items-center gap-12 lg:grid-cols-[1fr_0.92fr]">
        <div className="max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-primary">Explainable Forex Intelligence</p>
          <h1 className="mt-5 text-4xl font-bold tracking-tight text-foreground sm:text-5xl lg:text-6xl">
            Identify Better Trading Opportunities Before Risking Your Capital.
          </h1>
          <p className="mt-6 text-lg leading-8 text-muted-foreground">
            TradeCoreFX combines market structure, technical confluence, risk analysis and strategy validation to help traders evaluate opportunities with greater discipline and clarity.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link to="/agent" className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
              Begin Your Analysis <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
            <a href="#intelligence" className="inline-flex items-center justify-center rounded-lg border bg-background px-5 py-3 text-sm font-semibold transition hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
              Explore the Platform
            </a>
          </div>
          <p className="mt-5 text-sm text-muted-foreground">Built for research, validation and disciplined risk management—not guaranteed returns.</p>
        </div>
        <IntelligenceTerminal />
      </div>
    </section>
  );
}
