import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import { Check, Crown, Plus, Shield, Target, UserRound } from "lucide-react";
import { cn } from "@/lib/utils";

type AgentStatus = "idle" | "busy" | "waiting";
type AgentRank = "Operator" | "Senior" | "Lead";

type OfficeAgent = {
  id: string;
  name: string;
  title: string;
  room: string;
  status: AgentStatus;
  rank: AgentRank;
  speciality: string;
  color: string;
};

type OfficeTask = {
  id: string;
  title: string;
  detail: string;
  priority: "Low" | "Normal" | "High";
  assignee: string;
  status: "Queued" | "In progress" | "Completed";
};

const INITIAL_AGENTS: OfficeAgent[] = [
  { id: "research-analyst", name: "Research Analyst", title: "Market Research", room: "Research desk", status: "idle", rank: "Lead", speciality: "Macro, equity, crypto and news", color: "#f59e0b" },
  { id: "risk-guard", name: "Risk Guard", title: "Risk Management", room: "Risk control", status: "idle", rank: "Senior", speciality: "Drawdown, exposure and execution risk", color: "#38bdf8" },
  { id: "execution-agent", name: "Execution Agent", title: "Trade Operations", room: "Execution desk", status: "idle", rank: "Senior", speciality: "Broker routing and paper orders", color: "#a78bfa" },
];

const INITIAL_TASKS: OfficeTask[] = [
  { id: "office-welcome", title: "Set up today's trading brief", detail: "Review overnight market context and list the top risks.", priority: "Normal", assignee: "research-analyst", status: "Queued" },
];

const statusLabel: Record<AgentStatus, string> = {
  idle: "Available",
  busy: "Working",
  waiting: "Waiting",
};

function PixelCharacter({ color, status }: Pick<OfficeAgent, "color" | "status">) {
  return (
    <div className="pixel-character" style={{ "--pixel-color": color } as CSSProperties} aria-label={`${statusLabel[status]} pixel agent`}>
      <div className="pixel-character__shadow" />
      <div className="pixel-character__body">
        <span className="pixel-character__head" />
        <span className="pixel-character__torso" />
        <span className="pixel-character__arm pixel-character__arm--left" />
        <span className="pixel-character__arm pixel-character__arm--right" />
        <span className="pixel-character__leg pixel-character__leg--left" />
        <span className="pixel-character__leg pixel-character__leg--right" />
      </div>
      {status === "busy" && <span className="pixel-character__typing" aria-hidden="true">...</span>}
    </div>
  );
}

export function PixelOffice() {
  const [agents, setAgents] = useState<OfficeAgent[]>(() => {
    try {
      const stored = window.localStorage.getItem("vibe-pixel-office-agents");
      return stored ? JSON.parse(stored) as OfficeAgent[] : INITIAL_AGENTS;
    } catch {
      return INITIAL_AGENTS;
    }
  });
  const [tasks, setTasks] = useState<OfficeTask[]>(() => {
    try {
      const stored = window.localStorage.getItem("vibe-pixel-office-tasks");
      return stored ? JSON.parse(stored) as OfficeTask[] : INITIAL_TASKS;
    } catch {
      return INITIAL_TASKS;
    }
  });
  const [selectedAgent, setSelectedAgent] = useState(INITIAL_AGENTS[0].id);
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDetail, setTaskDetail] = useState("");
  const [taskPriority, setTaskPriority] = useState<OfficeTask["priority"]>("Normal");

  const workload = useMemo(() => agents.map((agent) => ({
    ...agent,
    tasks: tasks.filter((task) => task.assignee === agent.id && task.status !== "Completed"),
  })), [agents, tasks]);

  useEffect(() => {
    window.localStorage.setItem("vibe-pixel-office-agents", JSON.stringify(agents));
  }, [agents]);

  useEffect(() => {
    window.localStorage.setItem("vibe-pixel-office-tasks", JSON.stringify(tasks));
  }, [tasks]);

  const assignTask = (event: FormEvent) => {
    event.preventDefault();
    if (!taskTitle.trim()) return;
    const id = `task-${Date.now()}`;
    setTasks((current) => [...current, {
      id,
      title: taskTitle.trim(),
      detail: taskDetail.trim() || "No extra instructions.",
      priority: taskPriority,
      assignee: selectedAgent,
      status: "Queued",
    }]);
    setAgents((current) => current.map((agent) => agent.id === selectedAgent ? { ...agent, status: "busy" } : agent));
    setTaskTitle("");
    setTaskDetail("");
  };

  const completeTask = (taskId: string) => {
    const task = tasks.find((item) => item.id === taskId);
    if (!task) return;
    setTasks((current) => current.map((item) => item.id === taskId ? { ...item, status: "Completed" } : item));
    const hasOtherWork = tasks.some((item) => item.id !== taskId && item.assignee === task.assignee && item.status !== "Completed");
    if (!hasOtherWork) {
      setAgents((current) => current.map((agent) => agent.id === task.assignee ? { ...agent, status: "idle" } : agent));
    }
  };

  return (
    <main className="h-full overflow-y-auto bg-background px-4 py-5 sm:px-6">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Pixel Agents</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">Trading Office</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              Görevleri agent'lara dağıt, rütbelerini yönet ve trading operasyonunu tek ofisten izle.
              Agent isimleri sabittir; yalnızca rütbe ve görevleri yönetilebilir.
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            Office online
            <span className="mx-1 text-border">|</span>
            {agents.filter((agent) => agent.status === "busy").length} working
          </div>
        </header>

        <section className="pixel-office-floor rounded-xl border border-border/80 p-4 shadow-sm sm:p-6" aria-label="Pixel Agents office">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="font-semibold">Office floor</h2>
              <p className="text-xs text-muted-foreground">Pixel karakterler görev durumuna göre hareket eder.</p>
            </div>
            <span className="rounded-full bg-background/70 px-3 py-1 text-xs text-muted-foreground">Trading HQ</span>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            {workload.map((agent) => (
              <button
                type="button"
                key={agent.id}
                onClick={() => setSelectedAgent(agent.id)}
                className={cn("pixel-desk rounded-lg border p-4 text-left transition-all", selectedAgent === agent.id ? "border-primary ring-2 ring-primary/20" : "border-border/70")}
              >
                <div className="flex items-start justify-between gap-3">
                  <PixelCharacter color={agent.color} status={agent.status} />
                  <span className={cn("rounded-full px-2 py-1 text-[10px] font-medium", agent.status === "busy" ? "bg-amber-500/15 text-amber-600" : "bg-emerald-500/15 text-emerald-600")}>
                    {statusLabel[agent.status]}
                  </span>
                </div>
                <div className="mt-3">
                  <div className="flex items-center gap-2 font-semibold">{agent.name}<span className="text-xs font-normal text-muted-foreground">· {agent.rank}</span></div>
                  <p className="text-xs text-muted-foreground">{agent.title} · {agent.room}</p>
                  <p className="mt-2 text-xs text-muted-foreground">{agent.speciality}</p>
                </div>
                {agent.tasks.length > 0 && <p className="mt-3 text-xs text-primary">{agent.tasks.length} active task{agent.tasks.length > 1 ? "s" : ""}</p>}
              </button>
            ))}
          </div>
        </section>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="font-semibold">Task board</h2>
                <p className="text-xs text-muted-foreground">Atanan işler burada izlenir.</p>
              </div>
              <Target className="h-4 w-4 text-primary" />
            </div>
            <div className="space-y-2">
              {tasks.map((task) => {
                const owner = agents.find((agent) => agent.id === task.assignee);
                return (
                  <div key={task.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/70 p-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-medium">{task.title}</p>
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px]">{task.priority}</span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{task.detail}</p>
                      <p className="mt-2 text-xs text-primary">{owner?.name} · {task.status}</p>
                    </div>
                    {task.status !== "Completed" ? (
                      <button type="button" onClick={() => completeTask(task.id)} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs hover:bg-muted">
                        <Check className="h-3.5 w-3.5" /> Complete
                      </button>
                    ) : <span className="inline-flex items-center gap-1 text-xs text-emerald-600"><Check className="h-3.5 w-3.5" /> Done</span>}
                  </div>
                );
              })}
              {tasks.length === 0 && <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">No tasks yet.</p>}
            </div>
          </section>

          <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <Plus className="h-4 w-4 text-primary" />
              <div>
                <h2 className="font-semibold">Assign a mission</h2>
                <p className="text-xs text-muted-foreground">İsimler sabit, görev ve rütbe yönetilebilir.</p>
              </div>
            </div>
            <form className="space-y-3" onSubmit={assignTask}>
              <label className="block text-xs font-medium">Agent
                <select value={selectedAgent} onChange={(event) => setSelectedAgent(event.target.value)} className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm">
                  {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
                </select>
              </label>
              <label className="block text-xs font-medium">Mission
                <input value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} placeholder="Örn. BTC risk analizi" className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm" />
              </label>
              <label className="block text-xs font-medium">Instructions
                <textarea value={taskDetail} onChange={(event) => setTaskDetail(event.target.value)} placeholder="Agent'ın teslim etmesini istediğin çıktı..." rows={3} className="mt-1 w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm" />
              </label>
              <label className="block text-xs font-medium">Priority
                <select value={taskPriority} onChange={(event) => setTaskPriority(event.target.value as OfficeTask["priority"])} className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm">
                  <option>Low</option><option>Normal</option><option>High</option>
                </select>
              </label>
              <button type="submit" className="w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">Assign mission</button>
            </form>
          </section>
        </div>

        <section className="rounded-xl border border-border bg-card p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2"><Crown className="h-4 w-4 text-primary" /><h2 className="font-semibold">Rank & permissions</h2></div>
          <div className="grid gap-3 md:grid-cols-3">
            {agents.map((agent) => (
              <div key={agent.id} className="flex items-center gap-3 rounded-lg border border-border/70 p-3">
                <UserRound className="h-4 w-4 text-muted-foreground" />
                <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{agent.name}</p><p className="text-xs text-muted-foreground">{agent.title}</p></div>
                <select aria-label={`${agent.name} rank`} value={agent.rank} onChange={(event) => setAgents((current) => current.map((item) => item.id === agent.id ? { ...item, rank: event.target.value as AgentRank } : item))} className="rounded-md border border-border bg-background px-2 py-1 text-xs">
                  <option>Operator</option><option>Senior</option><option>Lead</option>
                </select>
                <Shield className="h-4 w-4 text-primary" />
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
