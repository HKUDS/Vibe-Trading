import { Link } from "react-router-dom";
import { ArrowRight, Bot, BarChart3, Zap, UserCircle2 } from "lucide-react";
import { copy } from "@/i18n/display";

export function Home() {
  const { features } = copy.home;
  const FEATURES = [
    { icon: Bot, ...features[0] },
    { icon: BarChart3, ...features[1] },
    { icon: Zap, ...features[2] },
    { icon: UserCircle2, ...features[3] },
  ];

  return (
    <div className="flex flex-col items-center justify-center min-h-screen p-8">
      <div className="max-w-2xl text-center space-y-6">
        <h1 className="text-4xl font-bold tracking-tight">{copy.home.title}</h1>
        <p className="text-lg text-muted-foreground">{copy.home.subtitle}</p>
        <Link
          to="/agent"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-primary text-primary-foreground font-medium hover:opacity-90 transition"
        >
          {copy.home.start} <ArrowRight className="h-4 w-4" />
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
