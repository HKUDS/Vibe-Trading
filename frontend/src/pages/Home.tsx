import { Link } from "react-router-dom";
import { ArrowRight, Bot, BarChart3, Zap, UserCircle2 } from "lucide-react";

export function Home() {
  const FEATURES = [
    { icon: Bot, title: "AI Agent", desc: "Natural language strategy generation with ReAct reasoning" },
    { icon: BarChart3, title: "Built-in Backtest", desc: "7 data sources across A-shares, US/HK & Crypto" },
    { icon: Zap, title: "Real-time Streaming", desc: "Watch the agent think, call tools, and iterate" },
    { icon: UserCircle2, title: "Strategy Replay", desc: "Trade journal analyzer + Shadow Account — extract your rules, backtest them, attribute PnL delta" },
  ];

  return (
    <div className="flex flex-col items-center justify-center min-h-screen p-8">
      <div className="max-w-2xl text-center space-y-6">
        <h1 className="text-4xl font-bold tracking-tight">AI-Powered Quant Strategy Research</h1>
        <p className="text-lg text-muted-foreground">Describe a trading strategy in natural language. The agent generates code, runs backtests, and optimizes — all in real time.</p>
        <Link
          to="/agent"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-primary text-primary-foreground font-medium hover:opacity-90 transition"
        >
          Start Research <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mt-16 max-w-5xl w-full">
        {FEATURES.map(({ icon: Icon, title, desc }) => (
          <div key={title} className="border rounded-lg p-6 space-y-3">
            <Icon className="h-8 w-8 text-primary" />
            <h3 className="font-semibold">{title}</h3>
            <p className="text-sm text-muted-foreground">{desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
