export function RiskDisclosure() {
  return (
    <section className="rounded-2xl border bg-muted/40 p-5" aria-labelledby="risk-disclosure-title">
      <h2 id="risk-disclosure-title" className="text-xl font-semibold">Educational Disclosures</h2>
      <div className="mt-3 space-y-2 text-sm text-muted-foreground">
        <p>TradeCoreFX provides risk-calculation and educational tools. Outputs are estimates based on user-entered assumptions and should not be treated as financial advice or a recommendation to trade.</p>
        <p>Historical or simulated outcomes do not guarantee future performance.</p>
      </div>
    </section>
  );
}
