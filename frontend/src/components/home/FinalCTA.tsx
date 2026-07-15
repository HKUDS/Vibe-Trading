import { Link } from "react-router-dom";
import { DisclosureNote } from "./DisclosureNote";

export function FinalCTA() {
  return (
    <section id="final-cta" className="px-4 py-16 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl rounded-3xl border bg-card p-8 text-center shadow-sm lg:p-12">
        <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">Turn Market Information Into a More Disciplined Decision.</h2>
        <p className="mx-auto mt-4 max-w-2xl text-lg leading-8 text-muted-foreground">Use structured analysis, risk tools and performance intelligence to evaluate your next opportunity with greater clarity.</p>
        <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row"><Link to="/agent" className="rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">Begin Your Analysis</Link><a href="#why" className="rounded-lg border px-5 py-3 text-sm font-semibold transition hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">View Platform Features</a></div>
        <div className="mt-8 text-left"><DisclosureNote>TradeCoreFX provides market-analysis, research, risk-management and educational tools. Information displayed by the platform is not financial advice, does not guarantee future performance and should not be treated as a recommendation to buy or sell any financial instrument.</DisclosureNote></div>
      </div>
    </section>
  );
}
