import { Bot, TrendingUp, Bitcoin, Globe, Sparkles, Users, UserCircle2, NotebookPen } from "lucide-react";
import { useI18n } from "@/lib/i18n";

interface Example {
  title: string;
  desc: string;
  prompt: string;
}

interface Category {
  label: string;
  icon: React.ReactNode;
  color: string;
  examples: Example[];
}

interface Props {
  onExample: (s: string) => void;
}

export function WelcomeScreen({ onExample }: Props) {
  const { t } = useI18n();

  const CATEGORIES: Category[] = [
    {
      label: t.welcomeCatBacktest,
      icon: <TrendingUp className="h-4 w-4" />,
      color: "text-red-400 border-red-500/30 hover:border-red-500/60 hover:bg-red-500/5",
      examples: [
        { title: t.welcomeExample1Title, desc: t.welcomeExample1Desc, prompt: t.welcomeExample1Prompt },
        { title: t.welcomeExample2Title, desc: t.welcomeExample2Desc, prompt: t.welcomeExample2Prompt },
        { title: t.welcomeExample3Title, desc: t.welcomeExample3Desc, prompt: t.welcomeExample3Prompt },
      ],
    },
    {
      label: t.welcomeCatResearch,
      icon: <Sparkles className="h-4 w-4" />,
      color: "text-amber-400 border-amber-500/30 hover:border-amber-500/60 hover:bg-amber-500/5",
      examples: [
        { title: t.welcomeExample4Title, desc: t.welcomeExample4Desc, prompt: t.welcomeExample4Prompt },
        { title: t.welcomeExample5Title, desc: t.welcomeExample5Desc, prompt: t.welcomeExample5Prompt },
      ],
    },
    {
      label: t.welcomeCatSwarm,
      icon: <Users className="h-4 w-4" />,
      color: "text-violet-400 border-violet-500/30 hover:border-violet-500/60 hover:bg-violet-500/5",
      examples: [
        { title: t.welcomeExample6Title, desc: t.welcomeExample6Desc, prompt: t.welcomeExample6Prompt },
        { title: t.welcomeExample7Title, desc: t.welcomeExample7Desc, prompt: t.welcomeExample7Prompt },
      ],
    },
    {
      label: t.welcomeCatDoc,
      icon: <Globe className="h-4 w-4" />,
      color: "text-blue-400 border-blue-500/30 hover:border-blue-500/60 hover:bg-blue-500/5",
      examples: [
        { title: t.welcomeExample8Title, desc: t.welcomeExample8Desc, prompt: t.welcomeExample8Prompt },
        { title: t.welcomeExample9Title, desc: t.welcomeExample9Desc, prompt: t.welcomeExample9Prompt },
      ],
    },
    {
      label: t.welcomeCatJournal,
      icon: <NotebookPen className="h-4 w-4" />,
      color: "text-orange-400 border-orange-500/30 hover:border-orange-500/60 hover:bg-orange-500/5",
      examples: [
        { title: t.welcomeExample10Title, desc: t.welcomeExample10Desc, prompt: t.welcomeExample10Prompt },
        { title: t.welcomeExample11Title, desc: t.welcomeExample11Desc, prompt: t.welcomeExample11Prompt },
      ],
    },
    {
      label: t.welcomeCatShadow,
      icon: <UserCircle2 className="h-4 w-4" />,
      color: "text-emerald-400 border-emerald-500/30 hover:border-emerald-500/60 hover:bg-emerald-500/5",
      examples: [
        { title: t.welcomeExample12Title, desc: t.welcomeExample12Desc, prompt: t.welcomeExample12Prompt },
        { title: t.welcomeExample13Title, desc: t.welcomeExample13Desc, prompt: t.welcomeExample13Prompt },
        { title: t.welcomeExample14Title, desc: t.welcomeExample14Desc, prompt: t.welcomeExample14Prompt },
      ],
    },
  ];

  const CAPABILITY_CHIPS = [
    t.welcomeChip1, t.welcomeChip2, t.welcomeChip3, t.welcomeChip4,
    t.welcomeChip5, t.welcomeChip6, t.welcomeChip7, t.welcomeChip8,
    t.welcomeChip9, t.welcomeChip10, t.welcomeChip11, t.welcomeChip12,
    t.welcomeChip13, t.welcomeChip14,
  ];

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-8 text-center">
      {/* Header */}
      <div className="space-y-3">
        <div className="h-16 w-16 mx-auto rounded-2xl bg-gradient-to-br from-primary/80 to-info/80 flex items-center justify-center shadow-lg">
          <Bot className="h-8 w-8 text-white" />
        </div>
        <div>
          <h2 className="text-2xl font-bold tracking-tight">{t.appBrandName}</h2>
          <p className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto leading-relaxed">
            {t.welcomeTagline}
          </p>
          <p className="text-sm text-muted-foreground mt-2 max-w-md leading-relaxed mx-auto">
            {t.describeStrategy}
          </p>
        </div>
      </div>

      {/* Capability chips */}
      <div className="flex flex-wrap justify-center gap-2 max-w-lg">
        {CAPABILITY_CHIPS.map((chip) => (
          <span
            key={chip}
            className="px-2.5 py-1 text-xs rounded-full border border-border/60 text-muted-foreground bg-muted/30"
          >
            {chip}
          </span>
        ))}
      </div>

      {/* Example categories grid */}
      <div className="w-full max-w-2xl text-left space-y-4">
        <p className="text-xs text-muted-foreground px-1">{t.examples}</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {CATEGORIES.map((cat) => (
            <div key={cat.label} className="space-y-2">
              <div className={`flex items-center gap-1.5 text-xs font-medium px-1 ${cat.color.split(" ").filter(c => c.startsWith("text-")).join(" ")}`}>
                {cat.icon}
                <span>{cat.label}</span>
              </div>
              <div className="space-y-1.5">
                {cat.examples.map((ex) => (
                  <button
                    key={ex.title}
                    onClick={() => onExample(ex.prompt)}
                    className={`block w-full text-left px-3 py-2.5 rounded-xl border transition-colors ${cat.color}`}
                  >
                    <span className="text-sm font-medium text-foreground leading-snug">
                      {ex.title}
                    </span>
                    <span className="block text-xs text-muted-foreground mt-0.5 leading-snug">
                      {ex.desc}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
