const candles = [32, 48, 38, 62, 54, 72, 58, 80, 66, 88, 76, 94];
const metrics = [
  ["Bias", "Bullish"],
  ["Opportunity score", "82/100"],
  ["Trend alignment", "Aligned"],
  ["Momentum", "Positive"],
  ["Volatility", "Moderate"],
  ["Risk condition", "Acceptable"],
  ["Classification", "Await Confirmation"],
  ["Supporting evidence", "7"],
  ["Conflicting evidence", "2"],
];

export function IntelligenceTerminal() {
  return (
    <div className="relative overflow-hidden rounded-3xl border bg-card p-5 shadow-2xl shadow-primary/5" aria-label="Illustrative Market Analysis terminal">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/70 to-transparent" />
      <div className="pointer-events-none absolute inset-0 tradecorefx-scan opacity-60" />
      <div className="relative flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-muted-foreground">EUR/USD</p>
          <p className="mt-1 font-semibold">Illustrative Market Analysis</p>
        </div>
        <span className="rounded-full border bg-muted/60 px-3 py-1 text-xs font-medium text-muted-foreground">London Session</span>
      </div>

      <div className="relative mt-6 h-44 overflow-hidden rounded-2xl border bg-background/70 p-4" role="img" aria-label="Animated illustrative candlestick display, not live market data">
        <svg className="h-full w-full" viewBox="0 0 360 150" preserveAspectRatio="none" aria-hidden="true">
          <path d="M0 118 C60 92 86 112 126 78 S208 88 248 52 S318 64 360 28" fill="none" stroke="hsl(var(--primary) / .35)" strokeWidth="2" />
          {candles.map((height, index) => {
            const x = 18 + index * 29;
            const y = 118 - height;
            const up = index % 3 !== 1;
            return (
              <g key={x} className="tradecorefx-candle" style={{ animationDelay: `${index * 120}ms` }}>
                <line x1={x + 5} x2={x + 5} y1={Math.max(8, y - 12)} y2={Math.min(140, y + height + 8)} stroke={up ? "hsl(var(--success))" : "hsl(var(--danger))"} strokeWidth="2" />
                <rect x={x} y={y} width="10" height={Math.max(16, height / 2)} rx="2" fill={up ? "hsl(var(--success) / .9)" : "hsl(var(--danger) / .85)"} />
              </g>
            );
          })}
        </svg>
      </div>

      <div className="relative mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-xl border bg-background/70 p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
            <p className="mt-1 text-sm font-semibold text-foreground">{value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
