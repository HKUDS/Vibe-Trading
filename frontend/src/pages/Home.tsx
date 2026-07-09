import { Link } from "react-router-dom";
import { ArrowRight, Bot, BarChart3, Zap, UserCircle2, MessageSquarePlus, SearchCode, LineChart, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

export function Home() {
  const { t } = useTranslation();

  const FEATURES = [
    { icon: Bot, title: t("home.featureAgent"), desc: t("home.featureAgentDesc") },
    { icon: BarChart3, title: t("home.featureBacktest"), desc: t("home.featureBacktestDesc") },
    { icon: Zap, title: t("home.featureStreaming"), desc: t("home.featureStreamingDesc") },
    { icon: UserCircle2, title: t("home.featureReplay"), desc: t("home.featureReplayDesc") },
  ];

  const STEPS = [
    { icon: MessageSquarePlus, title: t("home.step1Title"), desc: t("home.step1Desc") },
    { icon: SearchCode, title: t("home.step2Title"), desc: t("home.step2Desc") },
    { icon: LineChart, title: t("home.step3Title"), desc: t("home.step3Desc") },
    { icon: ShieldCheck, title: t("home.step4Title"), desc: t("home.step4Desc") },
  ];

  return (
    <div className="flex flex-col items-center justify-center min-h-screen p-8">
      <div className="max-w-2xl text-center space-y-6">
        <h1 className="text-4xl font-bold tracking-tight">{t("home.title")}</h1>
        <p className="text-lg text-muted-foreground">{t("home.subtitle")}</p>
        <Link
          to="/agent"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-primary text-primary-foreground font-medium hover:opacity-90 transition"
        >
          {t("home.startResearch")} <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      <div className="mt-16 max-w-5xl w-full">
        <h2 className="text-center text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {t("home.howItWorksTitle")}
        </h2>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-4">
          {STEPS.map(({ icon: Icon, title, desc }, index) => (
            <div key={title} className="relative rounded-lg border bg-card p-4 space-y-2">
              <div className="flex items-center gap-2 min-w-0">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <h3 className="min-w-0 text-sm font-semibold">{title}</h3>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">{desc}</p>
              {index < STEPS.length - 1 && (
                <ArrowRight className="hidden md:block absolute top-1/2 -right-6 h-4 w-4 -translate-y-1/2 text-muted-foreground/40" />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mt-12 max-w-5xl w-full">
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
