import { useEffect, useRef, useState, useMemo, useCallback, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Send, Loader2, ArrowDown, CheckCircle2, Square, Download, Plus, Paperclip, X, Users } from "lucide-react";
import { toast } from "sonner";
import { useAgentStore } from "@/stores/agent";
import { useSSE } from "@/hooks/useSSE";
import { useI18n } from "@/lib/i18n";
import { api } from "@/lib/api";
import type { AgentMessage, ToolCallEntry } from "@/types/agent";
import { AgentAvatar } from "@/components/chat/AgentAvatar";
import { WelcomeScreen } from "@/components/chat/WelcomeScreen";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { ThinkingTimeline } from "@/components/chat/ThinkingTimeline";
import { ConversationTimeline } from "@/components/chat/ConversationTimeline";
import { SwarmDashboard, type SwarmAgent, type SwarmDashboardProps } from "@/components/chat/SwarmDashboard";

/* ---------- Message grouping ---------- */
type MsgGroup =
  | { kind: "single"; msg: AgentMessage }
  | { kind: "timeline"; msgs: AgentMessage[] };

function groupMessages(msgs: AgentMessage[]): MsgGroup[] {
  const out: MsgGroup[] = [];
  let buf: AgentMessage[] = [];
  const flush = () => { if (buf.length) { out.push({ kind: "timeline", msgs: [...buf] }); buf = []; } };
  for (const m of msgs) {
    if (["thinking", "tool_call", "tool_result", "compact"].includes(m.type)) {
      buf.push(m);
    } else {
      flush();
      out.push({ kind: "single", msg: m });
    }
  }
  flush();
  return out;
}

const act = () => useAgentStore.getState();

/* ---------- Component ---------- */
export function Agent() {
  const [input, setInput] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sseSessionRef = useRef<string | null>(null);
  const prevSseStatusRef = useRef<string>("disconnected");
  const genRef = useRef(0);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const lastEventRef = useRef(0);

  const [attachment, setAttachment] = useState<{ filename: string; filePath: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [showUploadMenu, setShowUploadMenu] = useState(false);
  const uploadMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [swarmPreset, setSwarmPreset] = useState<{ name: string; title: string } | null>(null);
  const swarmCancelRef = useRef(false);
  const [swarmDash, setSwarmDash] = useState<SwarmDashboardProps | null>(null);
  const swarmDashRef = useRef<SwarmDashboardProps | null>(null);

  const messages = useAgentStore(s => s.messages);
  const streamingText = useAgentStore(s => s.streamingText);
  const status = useAgentStore(s => s.status);
  const sessionId = useAgentStore(s => s.sessionId);
  const toolCalls = useAgentStore(s => s.toolCalls);
  const sessionLoading = useAgentStore(s => s.sessionLoading);

  const { connect, disconnect, onStatusChange } = useSSE();
  const { t } = useI18n();

  const urlSessionId = searchParams.get("session");

  /* Smart scroll — only auto-scroll when near bottom */
  const isNearBottom = useCallback(() => {
    const el = listRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 100;
  }, []);

  const rafRef = useRef(0);
  const scrollToBottom = useCallback(() => {
    if (!isNearBottom()) {
      setShowScrollBtn(true);
      return;
    }
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
    });
  }, [isNearBottom]);

  const forceScrollToBottom = useCallback(() => {
    setShowScrollBtn(false);
    requestAnimationFrame(() => {
      if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
    });
  }, []);

  /* Track scroll position to show/hide scroll button */
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const onScroll = () => {
      if (isNearBottom()) setShowScrollBtn(false);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [isNearBottom]);

  useEffect(() => {
    onStatusChange((s) => {
      act().setSseStatus(s);
      if (s === "reconnecting" && prevSseStatusRef.current === "connected") toast.warning(t.reconnecting);
      else if (s === "connected" && prevSseStatusRef.current === "reconnecting") toast.success(t.connected);
      prevSseStatusRef.current = s;
    });
  }, [onStatusChange, t]);

  const doDisconnect = useCallback(() => {
    disconnect();
    sseSessionRef.current = null;
  }, [disconnect]);

  const loadSessionMessages = useCallback(async (sid: string, gen: number) => {
    try {
      const msgs = await api.getSessionMessages(sid);
      if (genRef.current !== gen) return;
      const agentMsgs: AgentMessage[] = [];
      for (const m of msgs) {
        const meta = m.metadata as Record<string, unknown> | undefined;
        const runId = meta?.run_id as string | undefined;
        const metrics = meta?.metrics as Record<string, number> | undefined;
        const ts = new Date(m.created_at).getTime();
        if (m.role === "user") {
          agentMsgs.push({ id: m.message_id, type: "user", content: m.content, timestamp: ts });
        } else if (runId) {
          // Show text answer first (if non-empty), then chart card
          if (m.content && m.content !== "Strategy execution completed.") {
            agentMsgs.push({ id: m.message_id + "_ans", type: "answer", content: m.content, timestamp: ts });
          }
          agentMsgs.push({ id: m.message_id, type: "run_complete", content: "", runId, metrics, timestamp: ts + 1 });
        } else {
          agentMsgs.push({ id: m.message_id, type: "answer", content: m.content, timestamp: ts });
        }
      }
      if (genRef.current !== gen) return;
      act().loadHistory(agentMsgs);
      act().setSessionLoading(false);
      act().cacheSession(sid, agentMsgs);
      setTimeout(() => forceScrollToBottom(), 50);
    } catch {
      act().setSessionLoading(false);
    }
  }, [forceScrollToBottom]);

  const setupSSE = useCallback((sid: string) => {
    if (sseSessionRef.current === sid) return;
    disconnect();
    sseSessionRef.current = sid;

    const touch = () => { lastEventRef.current = Date.now(); };

    connect(api.sseUrl(sid), {
      text_delta: (d) => { touch(); act().appendDelta(String(d.delta || "")); scrollToBottom(); },
      thinking_done: () => { touch(); /* don't flush — keep streaming text visible */ },

      tool_call: (d) => {
        touch();
        const toolName = String(d.tool || "");
        // Only update toolCalls tracker (no message creation during streaming)
        act().addToolCall({
          id: toolName, tool: toolName,
          arguments: (d.arguments as Record<string, string>) ?? {},
          status: "running", timestamp: Date.now(),
        });
        scrollToBottom();
      },

      tool_result: (d) => {
        touch();
        // Only update tracker (no message creation during streaming)
        act().updateToolCall(String(d.tool || ""), {
          status: d.status === "ok" ? "ok" : "error",
          preview: String(d.preview || ""),
          elapsed_ms: Number(d.elapsed_ms || 0),
        });
      },

      compact: () => { touch(); },

      "attempt.completed": async (d) => {
        touch();
        const s = act();
        // Build ThinkingTimeline summary from accumulated toolCalls
        const completedTools = s.toolCalls;
        if (completedTools.length > 0) {
          const totalMs = completedTools.reduce((a, tc) => a + (tc.elapsed_ms || 0), 0);
          for (const tc of completedTools) {
            s.addMessage({ id: tc.id + "_call", type: "tool_call", content: "", tool: tc.tool, args: tc.arguments, status: tc.status || "ok", timestamp: tc.timestamp });
            if (tc.elapsed_ms != null) {
              s.addMessage({ id: "", type: "tool_result", content: tc.preview || "", tool: tc.tool, status: tc.status || "ok", elapsed_ms: tc.elapsed_ms, timestamp: tc.timestamp + 1 });
            }
          }
        }

        // Clear streaming text (don't create thinking message)
        s.clearStreaming();

        // Add final answer
        const runDir = String(d.run_dir || "");
        const runId = runDir ? runDir.split(/[/\\]/).pop() : undefined;
        const summary = String(d.summary || "");
        if (summary) s.addMessage({ id: "", type: "answer", content: summary, timestamp: Date.now() });

        // Detect Shadow Account id if render_shadow_report fired successfully this turn
        const shadowCall = completedTools.find(
          (tc) => tc.tool === "render_shadow_report" && (tc.status || "ok") === "ok",
        );
        const shadowMatch = shadowCall?.preview?.match(/"shadow_id"\s*:\s*"(shadow_[A-Za-z0-9_]+)"/);
        const shadowId = shadowMatch?.[1];

        // Show RunCompleteCard when the turn produced backtest metrics or a shadow report
        if (runId) {
          try {
            const runData = await api.getRun(runId);
            const hasMetrics = runData.metrics && Object.keys(runData.metrics).length > 0;
            if (hasMetrics || shadowId) {
              s.addMessage({
                id: "", type: "run_complete", content: "", runId,
                metrics: hasMetrics ? runData.metrics : undefined,
                equityCurve: runData.equity_curve?.map(e => ({ time: e.time, equity: e.equity })),
                shadowId,
                timestamp: Date.now(),
              });
            }
          } catch { /* ignore */ }
        } else if (shadowId) {
          s.addMessage({ id: "", type: "run_complete", content: "", shadowId, timestamp: Date.now() });
        }

        // Reset
        s.setStatus("idle");
        useAgentStore.setState({ toolCalls: [] });
        scrollToBottom();
      },

      "attempt.failed": (d) => {
        touch();
        act().clearStreaming();
        act().addMessage({ id: "", type: "error", content: String(d.error || "Execution failed"), timestamp: Date.now() });
        act().setStatus("idle");
        scrollToBottom();
      },

      heartbeat: () => {},
      reconnect: (d) => { act().setSseStatus("reconnecting", Number(d.attempt ?? 0)); },
    });
  }, [connect, disconnect, scrollToBottom]);

  useEffect(() => {
    const gen = ++genRef.current;
    const { sessionId: curSid, messages: curMsgs, cacheSession, reset, getCachedSession, switchSession } = act();

    if (urlSessionId && urlSessionId !== curSid) {
      doDisconnect();
      if (curSid && curMsgs.length > 0) cacheSession(curSid, curMsgs);

      // Atomic switch: cache hit = instant, cache miss = show loading skeleton
      const cached = getCachedSession(urlSessionId);
      switchSession(urlSessionId, cached);
      if (cached) {
        setTimeout(() => forceScrollToBottom(), 50);
      } else {
        loadSessionMessages(urlSessionId, gen);
      }
      setupSSE(urlSessionId);
    } else if (!urlSessionId && curSid) {
      doDisconnect();
      if (curMsgs.length > 0) cacheSession(curSid, curMsgs);
      reset();
    }
  }, [urlSessionId, doDisconnect, loadSessionMessages, setupSSE, forceScrollToBottom]);

  useEffect(() => () => doDisconnect(), [doDisconnect]);

  /* Safety timeout: if streaming but no SSE event for 90s, reset to idle */
  useEffect(() => {
    if (status !== "streaming") return;
    const timer = setInterval(() => {
      if (lastEventRef.current && Date.now() - lastEventRef.current > 90_000 && act().status === "streaming") {
        act().setStatus("idle");
        toast.warning(t.executionTimeout);
      }
    }, 10_000);
    return () => clearInterval(timer);
  }, [status, t]);

  const runSwarm = async (presetName: string, presetTitle: string, prompt: string) => {
    let sid = act().sessionId;
    if (!sid) {
      try {
        const session = await api.createSession(`[Swarm] ${presetTitle}: ${prompt.slice(0, 30)}`);
        sid = session.session_id;
        act().setSessionId(sid);
        setSearchParams({ session: sid }, { replace: true });
      } catch { /* continue without session */ }
    }

    act().addMessage({ id: "", type: "user", content: `[${presetTitle}] ${prompt}`, timestamp: Date.now() });
    act().setStatus("streaming");
    // Add a placeholder swarm-progress message (rendered as SwarmDashboard)
    act().addMessage({ id: "swarm-progress", type: "answer", content: "", timestamp: Date.now() });
    forceScrollToBottom();
    swarmCancelRef.current = false;

    // Initialize dashboard state
    const dash: SwarmDashboardProps = {
      preset: presetTitle,
      agents: {},
      agentOrder: [],
      currentLayer: 0,
      finished: false,
      finalStatus: "",
      startTime: Date.now(),
      completedSummaries: [],
      finalReport: "",
    };
    swarmDashRef.current = dash;
    setSwarmDash({ ...dash });

    const ensureAgent = (agentId: string): SwarmAgent => {
      if (!dash.agents[agentId]) {
        dash.agents[agentId] = {
          id: agentId, status: "waiting", tool: "", iters: 0,
          startedAt: 0, elapsed: 0, lastText: "", summary: "",
        };
        dash.agentOrder.push(agentId);
      }
      return dash.agents[agentId];
    };

    const flush = () => { lastEventRef.current = Date.now(); swarmDashRef.current = dash; setSwarmDash({ ...dash }); scrollToBottom(); };

    try {
      const result = await api.createSwarmRun(presetName, { goal: prompt });
      const runId = result.id;
      const sseUrl = `/swarm/runs/${runId}/events`;
      const evtSource = new EventSource(sseUrl);
      let sseFinished = false;

      evtSource.addEventListener("layer_started", (e) => {
        try {
          const d = JSON.parse(e.data);
          dash.currentLayer = d.data?.layer ?? 0;
          flush();
        } catch {}
      });

      evtSource.addEventListener("task_started", (e) => {
        try {
          const d = JSON.parse(e.data);
          const agentId = d.agent_id || "";
          if (agentId) {
            const a = ensureAgent(agentId);
            a.status = "running";
            a.startedAt = Date.now();
            flush();
          }
        } catch {}
      });

      evtSource.addEventListener("worker_text", (e) => {
        try {
          const d = JSON.parse(e.data);
          const agentId = d.agent_id || "";
          const content = (d.data?.content || "").trim();
          if (agentId && content) {
            const a = ensureAgent(agentId);
            const lastLine = content.split("\n").pop()?.trim() || "";
            if (lastLine) a.lastText = lastLine.slice(0, 60);
            flush();
          }
        } catch {}
      });

      evtSource.addEventListener("tool_call", (e) => {
        try {
          const d = JSON.parse(e.data);
          const agentId = d.agent_id || "";
          const tool = d.data?.tool || "";
          if (agentId && tool) {
            const a = ensureAgent(agentId);
            a.tool = tool;
            a.iters++;
            flush();
          }
        } catch {}
      });

      evtSource.addEventListener("tool_result", (e) => {
        try {
          const d = JSON.parse(e.data);
          const agentId = d.agent_id || "";
          if (agentId) {
            const a = ensureAgent(agentId);
            const ok = (d.data?.status || "ok") === "ok";
            a.tool = `${a.tool} ${ok ? "\u2713" : "\u2717"}`;
            a.elapsed = a.startedAt ? Date.now() - a.startedAt : 0;
            flush();
          }
        } catch {}
      });

      evtSource.addEventListener("task_completed", (e) => {
        try {
          const d = JSON.parse(e.data);
          const agentId = d.agent_id || "";
          if (agentId) {
            const a = ensureAgent(agentId);
            a.status = "done";
            a.elapsed = a.startedAt ? Date.now() - a.startedAt : 0;
            a.iters = d.data?.iterations ?? a.iters;
            const summary = d.data?.summary || "";
            if (summary) {
              a.summary = summary;
              dash.completedSummaries.push({ agentId, summary });
            }
            flush();
          }
        } catch {}
      });

      evtSource.addEventListener("task_failed", (e) => {
        try {
          const d = JSON.parse(e.data);
          const agentId = d.agent_id || "";
          if (agentId) {
            const a = ensureAgent(agentId);
            a.status = "failed";
            a.elapsed = a.startedAt ? Date.now() - a.startedAt : 0;
            const error = (d.data?.error || "").slice(0, 80);
            dash.completedSummaries.push({ agentId, summary: `FAILED: ${error}` });
            flush();
          }
        } catch {}
      });

      evtSource.addEventListener("task_retry", (e) => {
        try {
          const d = JSON.parse(e.data);
          const agentId = d.agent_id || "";
          if (agentId) { ensureAgent(agentId).status = "retry"; flush(); }
        } catch {}
      });

      evtSource.addEventListener("done", () => { sseFinished = true; evtSource.close(); });
      evtSource.onerror = () => { if (!sseFinished) evtSource.close(); };

      // Poll for completion
      for (let i = 0; i < 720; i++) {
        await new Promise(r => setTimeout(r, 2500));
        if (swarmCancelRef.current) { evtSource.close(); break; }
        try {
          const run = await api.getSwarmRun(runId);
          const rs = String(run.status || "");
          if (["completed", "failed", "cancelled"].includes(rs)) {
            evtSource.close();
            dash.finished = true;
            dash.finalStatus = rs;
            const report = String(run.final_report || "");
            if (!report) {
              const tasks = (run.tasks || []) as Array<{ agent_id: string; summary?: string }>;
              dash.finalReport = tasks
                .filter(t => t.summary && !t.summary.startsWith("Worker hit iteration limit"))
                .map(t => `### ${t.agent_id}\n${t.summary}`)
                .join("\n\n") || "Swarm completed.";
            } else {
              dash.finalReport = report;
            }
            flush();
            act().setStatus("idle");
            return;
          }
        } catch {}
      }
      evtSource.close();
      act().addMessage({ id: "", type: "error", content: "Swarm timed out", timestamp: Date.now() });
      act().setStatus("idle");
    } catch (err) {
      act().setStatus("error");
      act().addMessage({ id: "", type: "error", content: `Swarm failed: ${err instanceof Error ? err.message : "Unknown"}`, timestamp: Date.now() });
    }
  };

  const runPrompt = async (prompt: string) => {
    if (!prompt.trim() || status === "streaming") return;

    let finalPrompt = prompt;

    // Swarm mode: let agent auto-select the right preset
    if (swarmPreset) {
      setSwarmPreset(null);
      finalPrompt = `[Swarm Team Mode] Use the swarm tool to assemble the best specialist team for this task. Auto-select the most appropriate preset.\n\n${prompt}`;
    }

    if (attachment) {
      finalPrompt = `[Uploaded file: ${attachment.filename}, path: ${attachment.filePath}]\n\n${finalPrompt}`;
      setAttachment(null);
    }
    setInput("");
    act().addMessage({ id: "", type: "user", content: finalPrompt, timestamp: Date.now() });
    act().setStatus("streaming");
    forceScrollToBottom();
    inputRef.current?.focus();

    try {
      let sid = act().sessionId;
      if (!sid) {
        const session = await api.createSession(prompt.slice(0, 50));
        sid = session.session_id;
        act().setSessionId(sid);
        setSearchParams({ session: sid }, { replace: true });
      }
      setupSSE(sid);
      await api.sendMessage(sid, finalPrompt);
    } catch {
      act().setStatus("error");
      toast.error(t.sendFailed);
      act().addMessage({ id: "", type: "error", content: t.sendFailed, timestamp: Date.now() });
    }
  };

  const handleSubmit = (e: FormEvent) => { e.preventDefault(); runPrompt(input.trim()); };

  const handleCancel = async () => {
    swarmCancelRef.current = true;
    if (!sessionId) {
      act().setStatus("idle");
      return;
    }
    try {
      await api.cancelSession(sessionId);
      act().setStatus("idle");
      act().clearStreaming();
      useAgentStore.setState({ toolCalls: [] });
      toast.info(t.cancelSent);
    } catch {
      toast.error(t.cancelFailed);
    }
  };

  const handleRetry = useCallback((errorMsg: AgentMessage) => {
    if (status === "streaming") return;
    const msgs = act().messages;
    const errorIdx = msgs.findIndex(m => m.id === errorMsg.id);
    if (errorIdx === -1) return;
    // Find the most recent user message before this error
    let userContent: string | null = null;
    for (let i = errorIdx - 1; i >= 0; i--) {
      if (msgs[i].type === "user") {
        userContent = msgs[i].content;
        break;
      }
    }
    if (!userContent) return;
    runPrompt(userContent);
  }, [status]);

  const handleExport = () => {
    if (messages.length === 0) return;
    const lines: string[] = [t.exportTitle, ``, `${t.exportTime}: ${new Date().toLocaleString()}`, ``];
    for (const msg of messages) {
      const time = new Date(msg.timestamp).toLocaleString();
      if (msg.type === "user") {
        lines.push(`${t.exportUser} (${time})`, ``, msg.content, ``);
      } else if (msg.type === "answer") {
        lines.push(`${t.exportAssistant} (${time})`, ``, msg.content, ``);
      } else if (msg.type === "error") {
        lines.push(`${t.exportError} (${time})`, ``, msg.content, ``);
      } else if (msg.type === "tool_call") {
        lines.push(`${t.exportToolCall}: ${msg.tool || t.unknownError}`, ``);
      } else if (msg.type === "run_complete") {
        lines.push(`${t.exportRunComplete}: ${msg.runId || ""}`, ``);
      }
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chat_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    const blockedExts = [
      ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".app", ".dmg",
      ".so", ".dll", ".dylib",
      ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
    ];
    const lowered = file.name.toLowerCase();
    if (blockedExts.some((ext) => lowered.endsWith(ext))) {
      toast.error(t.executablesBlocked);
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      toast.error(t.fileSizeExceeded);
      return;
    }
    setUploading(true);
    setShowUploadMenu(false);
    try {
      const result = await api.uploadFile(file);
      setAttachment({ filename: result.filename, filePath: result.file_path });
      toast.success(t.uploaded.replace("{name}", result.filename));
    } catch (err) {
      toast.error(t.uploadFailed.replace("{error}", err instanceof Error ? err.message : t.unknownError));
    } finally {
      setUploading(false);
    }
  }, [t]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (uploadMenuRef.current && !uploadMenuRef.current.contains(e.target as Node)) {
        setShowUploadMenu(false);
      }
    };
    if (showUploadMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showUploadMenu]);

  const groups = useMemo(() => groupMessages(messages), [messages]);

  return (
    <div className="flex flex-col flex-1 min-w-0 overflow-hidden h-full">
      <div ref={listRef} className="flex-1 overflow-auto p-6 scroll-smooth relative">
        <div className="max-w-3xl mx-auto space-y-4">
          {sessionLoading && (
            <div className="space-y-4 py-4">
              {[1, 2, 3].map(i => (
                <div key={i} className="flex gap-3 animate-pulse">
                  <div className="h-8 w-8 rounded-full bg-muted shrink-0" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 bg-muted rounded w-3/4" />
                    <div className="h-3 bg-muted/60 rounded w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          )}
          {!sessionLoading && messages.length === 0 && <WelcomeScreen onExample={runPrompt} />}

          {groups.map((g, i) => {
            if (g.kind === "timeline") {
              return (
                <ThinkingTimeline
                  key={g.msgs[0].id || g.msgs[0].timestamp}
                  messages={g.msgs}
                  isLatest={i === groups.length - 1 && status === "streaming"}
                />
              );
            }
            const msgIdx = messages.indexOf(g.msg);
            // Render swarm-progress as SwarmDashboard
            if (g.msg.id === "swarm-progress" && swarmDash) {
              return (
                <div key="swarm-dash" className="flex gap-3">
                  <AgentAvatar />
                  <div className="flex-1 min-w-0">
                    <SwarmDashboard {...swarmDash} />
                  </div>
                </div>
              );
            }
            return (
              <div key={g.msg.id || g.msg.timestamp} data-msg-idx={msgIdx}>
                <MessageBubble msg={g.msg} onRetry={g.msg.type === "error" ? handleRetry : undefined} />
              </div>
            );
          })}

          {/* Live streaming area: text + tool status */}
          {(streamingText || (status === "streaming" && toolCalls.length > 0)) && (
            <div className="flex gap-3">
              <AgentAvatar />
              <div className="flex-1 min-w-0 space-y-1.5">
                {streamingText && (
                  <div className="prose prose-sm dark:prose-invert max-w-none leading-relaxed">
                    {streamingText}
                    <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 animate-pulse align-middle" />
                  </div>
                )}
                {status === "streaming" && toolCalls.length > 0 && (() => {
                  const latest = toolCalls[toolCalls.length - 1];
                  const running = latest.status === "running";
                  return (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      {running
                        ? <Loader2 className="h-3 w-3 animate-spin text-primary shrink-0" />
                        : <CheckCircle2 className="h-3 w-3 text-success/60 shrink-0" />}
                      <span>{t.step} {toolCalls.length} · {latest.tool}</span>
                    </div>
                  );
                })()}
              </div>
            </div>
          )}

        </div>

        {/* Scroll to bottom button */}
        {showScrollBtn && (
          <button
            onClick={forceScrollToBottom}
            className="sticky bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1 px-3 py-1.5 rounded-full bg-primary text-primary-foreground text-xs font-medium shadow-lg hover:opacity-90 transition-opacity z-10"
          >
            <ArrowDown className="h-3 w-3" /> {t.newMessages}
          </button>
        )}
        <ConversationTimeline messages={messages} containerRef={listRef} />
      </div>

      <form onSubmit={handleSubmit} className="border-t p-4 bg-background/80 backdrop-blur-sm">
        <div className="max-w-3xl mx-auto space-y-2">
          {/* Swarm preset badge */}
          {swarmPreset && (
            <div className="flex items-center gap-1">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-violet-500/10 text-violet-600 dark:text-violet-400 text-xs font-medium">
                <Users className="h-3 w-3" />
                {swarmPreset.title}
                <button type="button" onClick={() => setSwarmPreset(null)} className="hover:text-destructive transition-colors">
                  <X className="h-3 w-3" />
                </button>
              </span>
            </div>
          )}
          {/* Attachment badge */}
          {attachment && (
            <div className="flex items-center gap-1">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-primary/10 text-primary text-xs font-medium">
                <Paperclip className="h-3 w-3" />
                {attachment.filename}
                <button type="button" onClick={() => setAttachment(null)} className="hover:text-destructive transition-colors">
                  <X className="h-3 w-3" />
                </button>
              </span>
            </div>
          )}
          {/* Uploading indicator */}
          {uploading && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              {t.uploading}
            </div>
          )}
          <div className="flex gap-2 items-end">
            {/* "+" menu: PDF upload + Swarm presets */}
            <div className="relative" ref={uploadMenuRef}>
              <button
                type="button"
                onClick={() => setShowUploadMenu(prev => !prev)}
                disabled={status === "streaming" || uploading}
                className="w-9 h-9 rounded-full border flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40 shrink-0"
                title={t.moreOptions}
              >
                <Plus className="h-4 w-4" />
              </button>
              {showUploadMenu && (
                <div className="absolute bottom-full left-0 mb-2 w-52 rounded-xl border bg-background/95 backdrop-blur-sm shadow-lg py-1 z-50">
                  <button
                    type="button"
                    onClick={() => { fileInputRef.current?.click(); setShowUploadMenu(false); }}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors flex items-center gap-2"
                  >
                    <Paperclip className="h-4 w-4" />
                    {t.uploadPdf}
                  </button>
                  <div className="border-t my-1" />
                  <button
                    type="button"
                    onClick={() => {
                      setShowUploadMenu(false);
                      setSwarmPreset({ name: "auto", title: "Agent Swarm" });
                      inputRef.current?.focus();
                    }}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors flex items-center gap-2"
                  >
                    <Users className="h-4 w-4" />
                    {t.agentSwarm}
                  </button>
                </div>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.xlsx,.xls,.pptx,.csv,.tsv,.txt,.md,.log,.json,.yaml,.yml,.toml,.html,.xml,.rst,.png,.jpg,.jpeg,.gif,.bmp,.webp,.tiff"
              onChange={handleFileSelect}
              className="hidden"
            />
            <textarea
              ref={inputRef}
              value={input}
              rows={1}
              onChange={(e) => setInput(e.target.value)}
              onInput={(e) => {
                const el = e.target as HTMLTextAreaElement;
                el.style.height = "auto";
                el.style.height = el.scrollHeight + "px";
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  runPrompt(input.trim());
                }
              }}
              placeholder={t.prompt}
              className="flex-1 px-4 py-2.5 rounded-xl border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 transition-shadow resize-none max-h-32 overflow-y-auto"
              disabled={status === "streaming"}
            />
            {messages.length > 0 && (
              <button
                type="button"
                onClick={handleExport}
                className="px-3 py-2.5 rounded-xl border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                title={t.exportChat}
              >
                <Download className="h-4 w-4" />
              </button>
            )}
            {status === "streaming" ? (
              <button
                type="button"
                onClick={handleCancel}
                className="px-4 py-2.5 rounded-xl bg-destructive text-destructive-foreground text-sm font-medium hover:opacity-90 transition-opacity"
                title={t.stopGeneration}
              >
                <Square className="h-4 w-4" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim() && !attachment}
                className="px-4 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium disabled:opacity-40 hover:opacity-90 transition-opacity"
              >
                <Send className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
