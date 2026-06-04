import { Bot, TrendingUp, Globe, Sparkles, Users, UserCircle2, NotebookPen, Landmark } from "lucide-react";
import { copy } from "@/i18n/display";

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

const CATEGORY_UI: Array<Pick<Category, "icon" | "color">> = [
  { icon: <TrendingUp className="h-4 w-4" />, color: "text-red-400 border-red-500/30 hover:border-red-500/60 hover:bg-red-500/5" },
  { icon: <Sparkles className="h-4 w-4" />, color: "text-amber-400 border-amber-500/30 hover:border-amber-500/60 hover:bg-amber-500/5" },
  { icon: <Users className="h-4 w-4" />, color: "text-violet-400 border-violet-500/30 hover:border-violet-500/60 hover:bg-violet-500/5" },
  { icon: <Globe className="h-4 w-4" />, color: "text-blue-400 border-blue-500/30 hover:border-blue-500/60 hover:bg-blue-500/5" },
  { icon: <NotebookPen className="h-4 w-4" />, color: "text-orange-400 border-orange-500/30 hover:border-orange-500/60 hover:bg-orange-500/5" },
  { icon: <Landmark className="h-4 w-4" />, color: "text-cyan-400 border-cyan-500/30 hover:border-cyan-500/60 hover:bg-cyan-500/5" },
  { icon: <UserCircle2 className="h-4 w-4" />, color: "text-emerald-400 border-emerald-500/30 hover:border-emerald-500/60 hover:bg-emerald-500/5" },
];

const CATEGORIES: Category[] = copy.welcome.categories.map((category, index) => {
  const ui = CATEGORY_UI[index] ?? CATEGORY_UI[0]!;
  return {
    ...category,
    icon: ui.icon,
    color: ui.color,
  };
});

const CAPABILITY_CHIPS = copy.welcome.chips;

interface Props {
  onExample: (s: string) => void;
}

export function WelcomeScreen({ onExample }: Props) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-8 text-center">
      {/* Header */}
      <div className="space-y-3">
        <div className="h-16 w-16 mx-auto rounded-2xl bg-gradient-to-br from-primary/80 to-info/80 flex items-center justify-center shadow-lg">
          <Bot className="h-8 w-8 text-white" />
        </div>
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Vibe-Trading</h2>
          <p className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto leading-relaxed">
            {copy.welcome.subtitle}
          </p>
          <p className="text-sm text-muted-foreground mt-2 max-w-md leading-relaxed mx-auto">
            {copy.welcome.helper}
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
        <p className="text-xs text-muted-foreground px-1">{copy.welcome.tryExample}</p>
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
