import { Link } from "react-router-dom";
import { ArrowRight, Bot, BarChart3, Zap, UserCircle2 } from "lucide-react";
import { useI18n } from "@/lib/i18n";

export function Home() {
  const { t } = useI18n();

  const FEATURES = [
    { icon: Bot, title: t.feat1, desc: t.feat1d },
    { icon: BarChart3, title: t.feat2, desc: t.feat2d },
    { icon: Zap, title: t.feat3, desc: t.feat3d },
    { icon: UserCircle2, title: t.feat4, desc: t.feat4d },
  ];


  return (
    <div className="flex flex-col items-center justify-center min-h-screen p-8">
      <div className="max-w-2xl text-center space-y-6">
        <h1 className="text-4xl font-bold tracking-tight">{t.heroTitle}</h1>
        <p className="text-lg text-muted-foreground">{t.heroDesc}</p>
        <Link
          to="/agent"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-primary text-primary-foreground font-medium hover:opacity-90 transition"
        >
          {t.startResearch} <ArrowRight className="h-4 w-4" />
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
