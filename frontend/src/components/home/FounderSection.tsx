import { useState } from "react";
import { ArrowRight } from "lucide-react";

const founderImage = "/images/founder/pascal-ngandu.webp";

export function FounderSection() {
  const [imageAvailable, setImageAvailable] = useState(true);

  return (
    <section id="company" className="px-4 py-16 sm:px-6 lg:px-8">
      <div className="mx-auto grid max-w-7xl gap-8 rounded-3xl border bg-card p-6 shadow-sm md:grid-cols-[0.85fr_1.15fr] lg:p-8">
        <div className="overflow-hidden rounded-2xl border bg-background/60">
          {/* Development note: expected asset is frontend/public/images/founder/pascal-ngandu.webp. If absent, the browser shows the polished fallback below. */}
          {imageAvailable ? (
            <img src={founderImage} alt="Pascal Ng’andu, Founder of TradeCoreFX" className="h-full min-h-[320px] w-full object-cover" onError={() => setImageAvailable(false)} />
          ) : (
            <div className="grid min-h-[320px] place-items-center p-8 text-center">
            <div><p className="text-lg font-semibold">Pascal Ng’andu</p><p className="mt-2 text-sm text-muted-foreground">Founder, TradeCoreFX</p></div>
            </div>
          )}
        </div>
        <div className="flex flex-col justify-center">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">Founder</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">Built From a Trader’s Need for Better Clarity</h2>
          <p className="mt-5 text-lg font-semibold">Pascal Ng’andu</p>
          <p className="text-sm text-muted-foreground">Founder, TradeCoreFX</p>
          <p className="mt-5 leading-7 text-muted-foreground">TradeCoreFX began with a practical question: how can traders reduce weak decisions before risking real capital? The platform was created to combine market analysis, opportunity filtering, risk calculation and performance review in one explainable system.</p>
          <div className="mt-6 grid gap-4 sm:grid-cols-2"><div className="rounded-xl border bg-background/60 p-4"><h3 className="font-semibold">Vision</h3><p className="mt-2 text-sm leading-6 text-muted-foreground">To make professional-grade forex intelligence more understandable, structured and accessible.</p></div><div className="rounded-xl border bg-background/60 p-4"><h3 className="font-semibold">Mission</h3><p className="mt-2 text-sm leading-6 text-muted-foreground">To help traders analyse more carefully, manage risk more responsibly and continuously improve through evidence, testing and disciplined review.</p></div></div>
          <a href="#company" className="mt-6 inline-flex w-fit items-center gap-2 rounded-lg border px-5 py-3 text-sm font-semibold transition hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">Read the Founder’s Story <ArrowRight className="h-4 w-4" aria-hidden="true" /></a>
        </div>
      </div>
    </section>
  );
}
