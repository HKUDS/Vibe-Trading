import { Link } from "react-router-dom";
import { SectionHeading } from "./SectionHeading";

const tiers = [
  ["Starter", "Start Free"],
  ["Professional", "Choose Professional"],
  ["Elite", "Choose Elite"],
  ["Institutional", "Contact Institutional Sales"],
];

export function PricingSection() {
  return (
    <section id="pricing" className="px-4 py-16 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <SectionHeading title="Choose the Intelligence Level That Fits Your Trading Journey" />
        <div className="mt-10 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
          {tiers.map(([name, cta]) => <article key={name} className="relative rounded-2xl border bg-card p-5 shadow-sm">{name === 'Professional' && <span className="absolute right-4 top-4 rounded-full bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground">Most Popular</span>}<h3 className="text-xl font-semibold">{name}</h3><p className="mt-5 text-2xl font-bold">Pricing Coming Soon</p><p className="mt-3 text-sm leading-6 text-muted-foreground">Feature details will be compared before public pricing is finalised.</p><Link to="/agent" className="mt-6 inline-flex w-full justify-center rounded-lg border px-4 py-2 text-sm font-semibold transition hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">{cta}</Link></article>)}
        </div>
        <div className="mt-8 text-center"><button type="button" className="text-sm font-semibold text-primary underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">Compare All Features</button></div>
      </div>
    </section>
  );
}
