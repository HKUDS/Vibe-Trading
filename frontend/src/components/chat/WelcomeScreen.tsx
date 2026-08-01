import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, TrendingUp, Globe, Sparkles, Users, UserCircle2, NotebookPen, Landmark, Gem } from "lucide-react";
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
    titleKey: "welcome.examples.valuationCheck",
    promptKey: "welcome.examples.valuationCheckPrompt",
    icon: <Gem className="h-4 w-4" aria-hidden="true" />,
  },
  {
    titleKey: "welcome.examples.optionsGreeks",
    promptKey: "welcome.examples.optionsGreeksPrompt",
    icon: <Sparkles className="h-4 w-4" aria-hidden="true" />,
  },
  {
    titleKey: "welcome.examples.crossMarketPortfolio",
    promptKey: "welcome.examples.crossMarketPortfolioPrompt",
    icon: <TrendingUp className="h-4 w-4" aria-hidden="true" />,
  },
  {
    titleKey: "welcome.examples.investmentCommittee",
    promptKey: "welcome.examples.investmentCommitteePrompt",
    icon: <Users className="h-4 w-4" aria-hidden="true" />,
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
  const examplesTriggerRef = useRef<HTMLButtonElement>(null);

  return (
    <div className="flex w-full flex-col items-center px-4 pb-14 text-center">
      <div className="w-full max-w-3xl">
        <div className="mx-auto max-w-2xl">
          <div className="flex items-center justify-center gap-3">
            <BrandMark className="h-9 w-9 shrink-0" />
            <h1 className="font-serif text-[34px] font-normal leading-tight sm:text-[40px]">
              {t(greetingKey as any)}
            </h1>
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            {t("welcome.taskSubtitle" as any)}
          </p>
        </div>

        <div
          className="mt-8 flex flex-wrap justify-center gap-2"
          role="group"
          aria-label={t("welcome.quickActions" as any)}
        >
          {QUICK_ACTIONS.map((action, index) => (
            <button
              key={action.titleKey}
              type="button"
              onClick={() => onExample(t(action.promptKey as any))}
              className={
                index === 0
                  ? "inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/[0.08] px-4 py-2 text-sm text-primary transition-colors hover:border-primary/50 hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  : "inline-flex items-center gap-2 rounded-full border border-border/60 bg-card px-4 py-2 text-sm transition-colors hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
              }
            >
              {action.icon}
              <span>{t(action.titleKey as any)}</span>
            </button>
          ))}
        </div>

        <button
          ref={examplesTriggerRef}
          type="button"
          aria-expanded={isExamplesOpen}
          aria-controls="welcome-example-library"
          onClick={() => setIsExamplesOpen((open) => !open)}
          className="mt-10 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
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
          className={`grid text-left transition-[grid-template-rows,opacity] duration-300 ease-out ${
            isExamplesOpen
              ? "grid-rows-[1fr] opacity-100"
              : "grid-rows-[0fr] opacity-0"
          }`}
        >
          <div className="min-h-0 overflow-hidden">
            {/* One category at a time: a chip tab bar + that category's cards.
                Rendering all 8 categories at once (grid or masonry) reads as
                an unstructured wall — categories have uneven card counts. */}
            <div className="pt-6">
              <div
                className="flex flex-wrap justify-center gap-1.5"
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
              <div role="tabpanel" className="mt-4 grid gap-2 text-left sm:grid-cols-2">
                {CATEGORIES[activeCategory].examples.map((ex) => (
                  <button
                    key={ex.titleKey}
                    type="button"
                    tabIndex={isExamplesOpen ? 0 : -1}
                    onClick={() => onExample(t(ex.promptKey as any))}
                    className="block w-full rounded-xl border border-border/60 px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  >
                    <span className="text-sm font-medium leading-snug text-foreground">
                      {t(ex.titleKey as any)}
                    </span>
                    <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">
                      {t(ex.descKey as any)}
                    </span>
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
