import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUpRight, ChevronDown, TrendingUp, Globe, Sparkles, Users, UserCircle2, NotebookPen, Landmark, Gem, Search, WalletCards } from "lucide-react";
import { BrandMark } from "@/components/common/BrandMark";

interface Example {
  titleKey: string;
  descKey: string;
  promptKey: string;
}

interface Category {
  labelKey: string;
  icon: React.ReactNode;
  examples: Example[];
}

const CATEGORIES: Category[] = [
  {
    labelKey: "welcome.categories.multiMarketBacktest",
    icon: <TrendingUp className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.adaptStrategy",
        descKey: "welcome.examples.adaptStrategyDesc",
        promptKey: "welcome.examples.adaptStrategyPrompt",
      },
      {
        titleKey: "welcome.examples.crossMarketPortfolio",
        descKey: "welcome.examples.crossMarketPortfolioDesc",
        promptKey: "welcome.examples.crossMarketPortfolioPrompt",
      },
      {
        titleKey: "welcome.examples.btcMacd",
        descKey: "welcome.examples.btcMacdDesc",
        promptKey: "welcome.examples.btcMacdPrompt",
      },
      {
        titleKey: "welcome.examples.usTechMaxDiv",
        descKey: "welcome.examples.usTechMaxDivDesc",
        promptKey: "welcome.examples.usTechMaxDivPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.researchAnalysis",
    icon: <Sparkles className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.multiFactorAlpha",
        descKey: "welcome.examples.multiFactorAlphaDesc",
        promptKey: "welcome.examples.multiFactorAlphaPrompt",
      },
      {
        titleKey: "welcome.examples.optionsGreeks",
        descKey: "welcome.examples.optionsGreeksDesc",
        promptKey: "welcome.examples.optionsGreeksPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.valueInvesting",
    icon: <Gem className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.valueCommittee",
        descKey: "welcome.examples.valueCommitteeDesc",
        promptKey: "welcome.examples.valueCommitteePrompt",
      },
      {
        titleKey: "welcome.examples.bottleneckHunter",
        descKey: "welcome.examples.bottleneckHunterDesc",
        promptKey: "welcome.examples.bottleneckHunterPrompt",
      },
      {
        titleKey: "welcome.examples.thesisTracker",
        descKey: "welcome.examples.thesisTrackerDesc",
        promptKey: "welcome.examples.thesisTrackerPrompt",
      },
      {
        titleKey: "welcome.examples.valuationCheck",
        descKey: "welcome.examples.valuationCheckDesc",
        promptKey: "welcome.examples.valuationCheckPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.swarmTeams",
    icon: <Users className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.investmentCommittee",
        descKey: "welcome.examples.investmentCommitteeDesc",
        promptKey: "welcome.examples.investmentCommitteePrompt",
      },
      {
        titleKey: "welcome.examples.quantStrategyDesk",
        descKey: "welcome.examples.quantStrategyDeskDesc",
        promptKey: "welcome.examples.quantStrategyDeskPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.docWebResearch",
    icon: <Globe className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.earningsReport",
        descKey: "welcome.examples.earningsReportDesc",
        promptKey: "welcome.examples.earningsReportPrompt",
      },
      {
        titleKey: "welcome.examples.macroResearch",
        descKey: "welcome.examples.macroResearchDesc",
        promptKey: "welcome.examples.macroResearchPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.tradeJournal",
    icon: <NotebookPen className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.analyzeBrokerExport",
        descKey: "welcome.examples.analyzeBrokerExportDesc",
        promptKey: "welcome.examples.analyzeBrokerExportPrompt",
      },
      {
        titleKey: "welcome.examples.diagnoseBehavior",
        descKey: "welcome.examples.diagnoseBehaviorDesc",
        promptKey: "welcome.examples.diagnoseBehaviorPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.tradingConnectors",
    icon: <Landmark className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.checkConnector",
        descKey: "welcome.examples.checkConnectorDesc",
        promptKey: "welcome.examples.checkConnectorPrompt",
      },
      {
        titleKey: "welcome.examples.analyzePortfolio",
        descKey: "welcome.examples.analyzePortfolioDesc",
        promptKey: "welcome.examples.analyzePortfolioPrompt",
      },
      {
        titleKey: "welcome.examples.quoteTrend",
        descKey: "welcome.examples.quoteTrendDesc",
        promptKey: "welcome.examples.quoteTrendPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.shadowAccount",
    icon: <UserCircle2 className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.trainShadow",
        descKey: "welcome.examples.trainShadowDesc",
        promptKey: "welcome.examples.trainShadowPrompt",
      },
      {
        titleKey: "welcome.examples.shadowDelta",
        descKey: "welcome.examples.shadowDeltaDesc",
        promptKey: "welcome.examples.shadowDeltaPrompt",
      },
      {
        titleKey: "welcome.examples.shadowReport",
        descKey: "welcome.examples.shadowReportDesc",
        promptKey: "welcome.examples.shadowReportPrompt",
      },
    ],
  },
];

const FEATURED_EXAMPLE_KEYS = [
  "welcome.examples.earningsReport",
  "welcome.examples.crossMarketPortfolio",
  "welcome.examples.thesisTracker",
] as const;

// Resolved from the library so a featured card always carries its own
// category label and prompt; a key that drifts out of CATEGORIES fails loudly.
const FEATURED_EXAMPLES = FEATURED_EXAMPLE_KEYS.map((titleKey) => {
  const category = CATEGORIES.find((cat) => cat.examples.some((ex) => ex.titleKey === titleKey));
  const example = category?.examples.find((ex) => ex.titleKey === titleKey);
  if (!category || !example) {
    throw new Error(`Featured example ${titleKey} is not in the example library`);
  }
  return { category, example };
});

const GREETING_KEYS = {
  morning: [
    "welcome.greetings.morning1",
    "welcome.greetings.morning2",
    "welcome.greetings.morning3",
  ],
  afternoon: [
    "welcome.greetings.afternoon1",
    "welcome.greetings.afternoon2",
    "welcome.greetings.afternoon3",
  ],
  evening: [
    "welcome.greetings.evening1",
    "welcome.greetings.evening2",
    "welcome.greetings.evening3",
  ],
  night: [
    "welcome.greetings.night1",
    "welcome.greetings.night2",
    "welcome.greetings.night3",
  ],
} as const;

const QUICK_ACTIONS = [
  {
    titleKey: "welcome.tasks.research",
    promptKey: "welcome.tasks.researchPrompt",
    icon: <Search className="h-4 w-4" aria-hidden="true" />,
  },
  {
    titleKey: "welcome.tasks.backtest",
    promptKey: "welcome.tasks.backtestPrompt",
    icon: <TrendingUp className="h-4 w-4" aria-hidden="true" />,
  },
  {
    titleKey: "welcome.tasks.portfolio",
    promptKey: "welcome.tasks.portfolioPrompt",
    icon: <WalletCards className="h-4 w-4" aria-hidden="true" />,
  },
] as const;

function pickGreetingKey(): string {
  const hour = new Date().getHours();
  const bucket =
    hour >= 5 && hour < 12
      ? "morning"
      : hour >= 12 && hour < 17
        ? "afternoon"
        : hour >= 17 && hour < 22
          ? "evening"
          : "night";
  const variants = GREETING_KEYS[bucket];
  return variants[Math.floor(Math.random() * variants.length)] ?? variants[0];
}

interface Props {
  onExample: (s: string) => void;
}

export function WelcomeScreen({ onExample }: Props) {
  const { t } = useTranslation();
  const [greetingKey] = useState(() => pickGreetingKey());
  const [isExamplesOpen, setIsExamplesOpen] = useState(false);
  const [activeCategory, setActiveCategory] = useState(0);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const examplesTriggerRef = useRef<HTMLButtonElement>(null);

  return (
    <div className="w-full px-4 pb-14 pt-6 text-start">
      <BrandMark className="mb-8 h-6 w-6" />

      <h1 className="font-serif text-[38px] font-normal leading-[1.08] tracking-[-0.025em] sm:text-[52px]">
        {t(greetingKey as any)}
      </h1>
      <p className="mt-4 text-base leading-7 text-muted-foreground sm:text-lg">
        {t("welcome.taskSubtitle" as any)}
      </p>

      <div className="mt-10 border-y border-border/70 py-5">
        <span className="mb-3 block text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {t("welcome.quickActions" as any)}
        </span>
        <div
          className="grid grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] gap-2"
          role="group"
          aria-label={t("welcome.quickActions" as any)}
        >
          {QUICK_ACTIONS.map((action) => {
            const isActive = action.titleKey === activeAction;
            return (
              <button
                key={action.titleKey}
                type="button"
                aria-pressed={isActive}
                onClick={() => {
                  setActiveAction(action.titleKey);
                  onExample(t(action.promptKey as any));
                }}
                className={
                  isActive
                    ? "group flex min-h-24 items-center justify-between rounded-xl border border-primary/35 bg-primary/[0.08] px-4 py-3 text-start text-primary shadow-sm transition-all hover:border-primary/50 hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    : "group flex min-h-24 items-center justify-between rounded-xl border border-border/70 bg-card/70 px-4 py-3 text-start transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                }
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted/70 text-muted-foreground transition-colors group-hover:text-primary">
                    {action.icon}
                  </span>
                  {t(action.titleKey as any)}
                </span>
                <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 rtl:-scale-x-100 rtl:group-hover:-translate-x-0.5" aria-hidden="true" />
              </button>
            );
          })}
        </div>
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          {t("welcome.tasks.hint")}
        </p>
      </div>

      <section aria-labelledby="welcome-featured-heading" className="mt-8">
        <h2
          id="welcome-featured-heading"
          className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground"
        >
          {t("welcome.featured" as any)}
        </h2>
        <ul className="grid grid-cols-[repeat(auto-fit,minmax(12rem,1fr))] gap-2">
          {FEATURED_EXAMPLES.map(({ category, example }) => (
            <li key={example.titleKey} className="flex">
              <button
                type="button"
                onClick={() => onExample(t(example.promptKey as any))}
                className="group flex w-full flex-col rounded-xl border border-border/70 bg-card/50 p-4 text-start transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
              >
                <span className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground/70">{t(category.labelKey as any)}</span>
                <span className="mt-1.5 text-sm font-medium leading-6 transition-colors group-hover:text-primary">{t(example.titleKey as any)}</span>
                <span className="mt-1 text-xs leading-5 text-muted-foreground">{t(example.descKey as any)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <div className="mt-8">
        <button
          ref={examplesTriggerRef}
          type="button"
          aria-expanded={isExamplesOpen}
          aria-controls="welcome-example-library"
          onClick={() => setIsExamplesOpen((open) => !open)}
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <span>{t("welcome.browseAllExamples" as any)}</span>
          <ChevronDown
            className={`h-4 w-4 transition-transform duration-300 ${isExamplesOpen ? "rotate-180" : ""}`}
            aria-hidden="true"
          />
        </button>

        <div
          id="welcome-example-library"
          aria-hidden={!isExamplesOpen}
          onKeyDown={(event) => {
            if (event.key !== "Escape" || !isExamplesOpen) return;
            event.preventDefault();
            event.stopPropagation();
            setIsExamplesOpen(false);
            examplesTriggerRef.current?.focus();
          }}
          className={`grid text-start transition-[grid-template-rows,opacity] duration-300 ease-out ${
            isExamplesOpen
              ? "mt-5 grid-rows-[1fr] opacity-100"
              : "grid-rows-[0fr] opacity-0"
          }`}
        >
          <div className="min-h-0 overflow-hidden">
            <div className="border-t border-border/70 pt-5">
              <div
                className="flex flex-wrap gap-1.5"
                role="tablist"
                aria-label={t("welcome.browseAllExamples" as any)}
              >
                {CATEGORIES.map((cat, index) => (
                  <button
                    key={cat.labelKey}
                    type="button"
                    role="tab"
                    aria-selected={index === activeCategory}
                    tabIndex={isExamplesOpen ? 0 : -1}
                    onClick={() => setActiveCategory(index)}
                    className={
                      index === activeCategory
                        ? "inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary"
                        : "inline-flex items-center gap-1.5 rounded-full border border-transparent px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-border/60 hover:text-foreground"
                    }
                  >
                    {cat.icon}
                    <span>{t(cat.labelKey as any)}</span>
                  </button>
                ))}
              </div>
              <div role="tabpanel" className="mt-4 grid gap-2 text-start sm:grid-cols-2">
                {CATEGORIES[activeCategory].examples.map((ex) => (
                  <button
                    key={ex.titleKey}
                    type="button"
                    tabIndex={isExamplesOpen ? 0 : -1}
                    onClick={() => onExample(t(ex.promptKey as any))}
                    className="block w-full rounded-xl border border-border/60 px-3 py-2.5 text-start transition-colors hover:border-primary/40 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  >
                    <span className="text-sm font-medium leading-snug text-foreground">{t(ex.titleKey as any)}</span>
                    <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">{t(ex.descKey as any)}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
