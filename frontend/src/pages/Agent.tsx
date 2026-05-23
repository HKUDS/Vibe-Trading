import { useEffect, useRef, useState, useMemo, useCallback, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Send, Loader2, ArrowDown, Square, Download, Plus, Paperclip, X, Users, Target, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { useAgentStore } from "@/stores/agent";
import { useSSE } from "@/hooks/useSSE";
import { ApiError, api, type GoalSnapshot } from "@/lib/api";
import { isReportWorthyRun } from "@/lib/runReports";
import type { AgentMessage, ToolCallEntry } from "@/types/agent";
import { AgentAvatar } from "@/components/chat/AgentAvatar";
import { WelcomeScreen } from "@/components/chat/WelcomeScreen";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { ThinkingTimeline } from "@/components/chat/ThinkingTimeline";
import { ConversationTimeline } from "@/components/chat/ConversationTimeline";
import { ToolProgressIndicator } from "@/components/chat/ToolProgressIndicator";

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

function isCriterionStatusMet(status: string): boolean {
  return !["", "pending", "open", "unsatisfied"].includes(status.toLowerCase());
}

function getGoalProgress(snapshot: GoalSnapshot | null): {
  met: number;
  total: number;
  label: string;
  metLabel: string;
  evidenceTotal: number;
} {
  const total = snapshot?.criteria.length ?? 0;
  const met = snapshot?.criteria.filter((item) => isCriterionStatusMet(item.status)).length ?? 0;
  const evidenceTotal = snapshot?.evidence_count ?? 0;
  return {
    met,
    total,
    label: total > 0 ? `${met}/${total}` : "",
    metLabel: total > 0 ? `${met}/${total} met` : "",
    evidenceTotal,
  };
}

function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

function criterionIndexLabel(index: number): string {
  return String(index + 1);
}

function criterionEvidenceCount(snapshot: GoalSnapshot, criterionId: string): number {
  return snapshot.evidence.filter((item) => item.criterion_id === criterionId).length;
}

function latestGoalEvidence(snapshot: GoalSnapshot) {
  return [...snapshot.evidence]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 2);
}

/* ---------- Component ---------- */
export function Agent() {
  const [input, setInput] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sseSessionRef = useRef<string | null>(null);
  const prevSseStatusRef = useRef<string>("disconnected");
  const genRef = useRef(0);
  const pendingGoalSessionRef = useRef<string | null>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const lastEventRef = useRef(0);

  /* tool_progress coalescing — keep latest payload per-tool, flush once per rAF. */
  const pendingProgressRef = useRef<Map<string, NonNullable<ToolCallEntry["progress"]>>>(new Map());
  const progressRafRef = useRef(0);

  const [attachment, setAttachment] = useState<{ filename: string; filePath: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [showUploadMenu, setShowUploadMenu] = useState(false);
  const uploadMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [swarmPreset, setSwarmPreset] = useState<{ name: string; title: string } | null>(null);
  const [goalComposerActive, setGoalComposerActive] = useState(false);
  const [goalDetailsOpen, setGoalDetailsOpen] = useState(false);
  const [goalSnapshot, setGoalSnapshot] = useState<GoalSnapshot | null>(null);

  const messages = useAgentStore(s => s.messages);
  const streamingText = useAgentStore(s => s.streamingText);
  const status = useAgentStore(s => s.status);
  const sessionId = useAgentStore(s => s.sessionId);
  const toolCalls = useAgentStore(s => s.toolCalls);
  const sessionLoading = useAgentStore(s => s.sessionLoading);

  const { connect, disconnect, onStatusChange } = useSSE();

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
      if (s === "reconnecting" && prevSseStatusRef.current === "connected") toast.warning("Connection lost, reconnecting…");
      else if (s === "connected" && prevSseStatusRef.current === "reconnecting") toast.success("Connection restored");
      prevSseStatusRef.current = s;
    });
  }, [onStatusChange]);

  const doDisconnect = useCallback(() => {
    disconnect();
    sseSessionRef.current = null;
  }, [disconnect]);

  const loadGoalSnapshot = useCallback(async (sid?: string | null) => {
    const targetSession = sid || act().sessionId;
    if (!targetSession) {
      setGoalSnapshot(null);
      setGoalDetailsOpen(false);
      return;
    }
    try {
      const snapshot = await api.getGoal(targetSession);
      if (act().sessionId !== targetSession) return;
      setGoalSnapshot(snapshot);
    } catch (error) {
      if (act().sessionId !== targetSession) return;
      if (error instanceof ApiError && error.status === 404) {
        setGoalSnapshot(null);
        setGoalDetailsOpen(false);
      } else {
        toast.error(error instanceof Error ? error.message : "Failed to load goal.");
      }
    }
  }, []);

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
          if (metrics && Object.keys(metrics).length > 0) {
            agentMsgs.push({ id: m.message_id, type: "run_complete", content: "", runId, metrics, timestamp: ts + 1 });
          } else {
            try {
              const runData = await api.getRun(runId);
              if (isReportWorthyRun(runData)) {
                agentMsgs.push({
                  id: m.message_id,
                  type: "run_complete",
                  content: "",
                  runId,
                  metrics: runData.metrics,
                  equityCurve: runData.equity_curve?.map((e) => ({ time: e.time, equity: e.equity })),
                  timestamp: ts + 1,
                });
              }
            } catch { /* ignore non-report attempt directories */ }
          }
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

    connect(api.sseUrl(sid, { replay: "active" }), {
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
        const toolName = String(d.tool || "");
        // Drop any in-flight coalesced progress for this tool.
        pendingProgressRef.current.delete(toolName);
        // Only update tracker (no message creation during streaming)
        act().updateToolCall(toolName, {
          status: d.status === "ok" ? "ok" : "error",
          preview: String(d.preview || ""),
          elapsed_ms: Number(d.elapsed_ms || 0),
          elapsed_s: undefined,
          progress: undefined,
        });
      },

      tool_heartbeat: (d) => {
        touch();
        const toolName = String(d.tool || "");
        if (!toolName) return;
        act().updateToolCall(toolName, {
          elapsed_s: Number(d.elapsed_s || 0),
        });
      },

      tool_progress: (d) => {
        touch();
        const toolName = String(d.tool || "");
        if (!toolName) return;
        const payload: NonNullable<ToolCallEntry["progress"]> = {};
        if (typeof d.stage === "string" && d.stage) payload.stage = d.stage;
        if (typeof d.message === "string" && d.message) payload.message = d.message;
        if (typeof d.current === "number") payload.current = d.current;
        if (typeof d.total === "number") payload.total = d.total;
        // Coalesce: keep latest payload per tool, flush once per animation frame.
        pendingProgressRef.current.set(toolName, payload);
        if (progressRafRef.current) return;
        progressRafRef.current = requestAnimationFrame(() => {
          progressRafRef.current = 0;
          const pending = pendingProgressRef.current;
          if (pending.size === 0) return;
          const store = act();
          for (const [tool, progress] of pending) {
            store.updateToolCall(tool, { progress });
          }
          pending.clear();
        });
      },

      compact: () => { touch(); },

      "attempt.completed": async (d) => {
        touch();
        const s = act();
        // Build ThinkingTimeline summary from accumulated toolCalls
        const completedTools = s.toolCalls;
        if (completedTools.length > 0) {
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
            const hasReport = isReportWorthyRun(runData);
            if (hasReport || shadowId) {
              s.addMessage({
                id: "", type: "run_complete", content: "", runId,
                metrics: hasReport ? runData.metrics : undefined,
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
        // Clear stale toolCalls so the next turn's running indicator doesn't
        // briefly show the previous turn's progress before fresh events land.
        useAgentStore.setState({ toolCalls: [] });
        scrollToBottom();
      },

      "goal.created": () => {
        touch();
        loadGoalSnapshot(sid);
      },

      "goal.evidence": () => {
        touch();
        loadGoalSnapshot(sid);
      },

      heartbeat: () => {},
      reconnect: (d) => { act().setSseStatus("reconnecting", Number(d.attempt ?? 0)); },
    });
  }, [connect, disconnect, loadGoalSnapshot, scrollToBottom]);

  useEffect(() => {
    const { sessionId: curSid, messages: curMsgs, cacheSession, reset, getCachedSession, switchSession } = act();

    if (urlSessionId && urlSessionId !== curSid) {
      const gen = genRef.current + 1;
      genRef.current = gen;
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
      genRef.current += 1;
      doDisconnect();
      if (curSid && curMsgs.length > 0) cacheSession(curSid, curMsgs);
      reset();
    }
  }, [urlSessionId, doDisconnect, loadSessionMessages, setupSSE, forceScrollToBottom]);

  useEffect(() => {
    if (!sessionId) {
      setGoalSnapshot(null);
      setGoalDetailsOpen(false);
      return;
    }
    if (pendingGoalSessionRef.current === sessionId) {
      pendingGoalSessionRef.current = null;
      return;
    }
    loadGoalSnapshot(sessionId);
  }, [sessionId, loadGoalSnapshot]);

  useEffect(() => () => doDisconnect(), [doDisconnect]);

  /* Safety timeout: if streaming but no SSE event for 90s, reset to idle */
  useEffect(() => {
    if (status !== "streaming") return;
    const timer = setInterval(() => {
      if (lastEventRef.current && Date.now() - lastEventRef.current > 90_000 && act().status === "streaming") {
        act().setStatus("idle");
        toast.warning("Execution timed out, automatically stopped");
      }
    }, 10_000);
    return () => clearInterval(timer);
  }, [status]);

  const runPrompt = async (prompt: string) => {
    if (!prompt.trim() || status === "streaming") return;

    if (goalComposerActive) {
      setInput("");
      inputRef.current?.focus();
      try {
        const sid = await ensureGoalSession(prompt);
        const snapshot = await api.createGoal(sid, { objective: prompt });
        setGoalSnapshot(snapshot);
        setGoalComposerActive(false);
        setGoalDetailsOpen(true);
        toast.success("Research goal attached");
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to start goal.");
      }
      return;
    }

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
      toast.error("Failed to send message, please retry.");
      act().addMessage({ id: "", type: "error", content: "Failed to send message, please retry.", timestamp: Date.now() });
    }
  };

  const ensureGoalSession = useCallback(async (title: string): Promise<string> => {
    let sid = act().sessionId;
    if (sid) return sid;
    const session = await api.createSession(title.slice(0, 50));
    sid = session.session_id;
    pendingGoalSessionRef.current = sid;
    act().setSessionId(sid);
    setSearchParams({ session: sid }, { replace: true });
    setupSSE(sid);
    return sid;
  }, [setSearchParams, setupSSE]);

  const handleSubmit = (e: FormEvent) => { e.preventDefault(); runPrompt(input.trim()); };

  const handleCancel = async () => {
    if (!sessionId) {
      act().setStatus("idle");
      return;
    }
    try {
      await api.cancelSession(sessionId);
      act().setStatus("idle");
      act().clearStreaming();
      useAgentStore.setState({ toolCalls: [] });
      toast.info("Cancel request sent");
    } catch {
      toast.error("Cancel failed");
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
    const lines: string[] = [`# Chat Export`, ``, `Export time: ${new Date().toLocaleString()}`, ``];
    for (const msg of messages) {
      const time = new Date(msg.timestamp).toLocaleString();
      if (msg.type === "user") {
        lines.push(`## User (${time})`, ``, msg.content, ``);
      } else if (msg.type === "answer") {
        lines.push(`## Assistant (${time})`, ``, msg.content, ``);
      } else if (msg.type === "error") {
        lines.push(`## Error (${time})`, ``, msg.content, ``);
      } else if (msg.type === "tool_call") {
        lines.push(`> Tool call: ${msg.tool || "unknown"}`, ``);
      } else if (msg.type === "run_complete") {
        lines.push(`> Backtest complete: ${msg.runId || ""}`, ``);
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
      toast.error("Executables and archives are not allowed");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      toast.error("File size exceeds 50 MB limit");
      return;
    }
    setUploading(true);
    setShowUploadMenu(false);
    try {
      const result = await api.uploadFile(file);
      setAttachment({ filename: result.filename, filePath: result.file_path });
      toast.success(`Uploaded: ${result.filename}`);
    } catch (err) {
      toast.error(`Upload failed: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setUploading(false);
    }
  }, []);

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
  const goalProgress = useMemo(() => getGoalProgress(goalSnapshot), [goalSnapshot]);

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
            return (
              <div key={g.msg.id || g.msg.timestamp} data-msg-idx={msgIdx}>
                <MessageBubble msg={g.msg} onRetry={g.msg.type === "error" ? handleRetry : undefined} />
              </div>
            );
          })}

          {/* Pre-stream placeholder: visible after Send, before first SSE event */}
          {status === "streaming" && !streamingText && toolCalls.length === 0 && (
            <div className="flex gap-3">
              <AgentAvatar />
              <div className="flex-1 min-w-0 flex items-center gap-2 text-xs text-muted-foreground pt-1">
                <Loader2 className="h-3 w-3 animate-spin text-primary shrink-0" />
                <span>Thinking…</span>
              </div>
            </div>
          )}

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
                {status === "streaming" && toolCalls.length > 0 && (
                  <ToolProgressIndicator toolCalls={toolCalls} />
                )}
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
            <ArrowDown className="h-3 w-3" /> New messages
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
          {goalComposerActive && (
            <div className="flex items-center gap-1">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-primary/10 text-primary text-xs font-medium">
                <Target className="h-3 w-3" />
                New Research Goal
                <button type="button" onClick={() => setGoalComposerActive(false)} className="hover:text-destructive transition-colors">
                  <X className="h-3 w-3" />
                </button>
              </span>
            </div>
          )}
          {goalSnapshot && !goalComposerActive && (
            <div className="grid gap-2">
              <button
                type="button"
                onClick={() => setGoalDetailsOpen((open) => !open)}
                className="inline-flex max-w-full items-center gap-1.5 justify-self-start rounded-lg bg-primary/10 px-2.5 py-1 text-left text-xs font-medium text-primary transition-colors hover:bg-primary/15"
                title={goalSnapshot.goal.objective}
                aria-label="Active research goal"
                aria-expanded={goalDetailsOpen}
              >
                <Target className="h-3 w-3 shrink-0" />
                <span className="shrink-0">Goal</span>
                <span className="truncate text-muted-foreground">
                  {goalSnapshot.goal.ui_summary || goalSnapshot.goal.objective}
                </span>
                {goalProgress.metLabel && (
                  <span className="shrink-0 font-mono text-[11px] text-emerald-600 dark:text-emerald-400">
                    {goalProgress.metLabel}
                  </span>
                )}
                {goalProgress.evidenceTotal > 0 && (
                  <span className="shrink-0 rounded bg-background px-1 font-mono text-[10px] text-primary">
                    {goalProgress.evidenceTotal} ev
                  </span>
                )}
                <ChevronDown
                  className={[
                    "h-3 w-3 shrink-0 transition-transform",
                    goalDetailsOpen ? "rotate-180" : "",
                  ].join(" ")}
                  aria-hidden="true"
                />
              </button>
              {goalDetailsOpen && (
                <div className="grid gap-3 rounded-xl border border-primary/20 bg-background/95 p-3 text-xs shadow-sm">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded-lg border bg-muted/20 p-2.5">
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        Criteria
                      </div>
                      <div className="mt-1 font-mono text-base font-semibold text-foreground">
                        {goalProgress.label || "0/0"}
                      </div>
                    </div>
                    <div className="rounded-lg border bg-muted/20 p-2.5">
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        Evidence
                      </div>
                      <div className="mt-1 font-mono text-base font-semibold text-foreground">
                        {goalProgress.evidenceTotal}
                      </div>
                    </div>
                  </div>
                  <div className="grid gap-1.5">
                    {goalSnapshot.criteria.map((criterion, index) => {
                      const evidenceCount = criterionEvidenceCount(goalSnapshot, criterion.criterion_id);
                      return (
                        <div
                          key={criterion.criterion_id}
                          className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-start gap-2 rounded-lg border bg-muted/20 p-2"
                        >
                          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-[10px] text-muted-foreground">
                            {criterionIndexLabel(index)}
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate font-medium text-foreground">{criterion.text}</span>
                            <span className="block text-[11px] text-muted-foreground">
                              {statusLabel(criterion.status)}
                            </span>
                          </span>
                          <span className="rounded-full border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                            {evidenceCount} ev
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  {goalSnapshot.evidence.length > 0 && (
                    <div className="grid gap-1.5 border-t pt-2">
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        Recent Evidence
                      </div>
                      {latestGoalEvidence(goalSnapshot).map((item) => (
                        <div key={item.evidence_id} className="rounded-lg bg-muted/20 px-2 py-1.5">
                          <div className="mb-0.5 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                            <span className="truncate">{item.source_provider || "evidence"}</span>
                            <span>{statusLabel(item.verification_status)}</span>
                          </div>
                          <div className="line-clamp-2 text-[11px] leading-relaxed text-foreground">
                            {item.text}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
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
              Uploading...
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
                title="More options"
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
                    Upload PDF document
                  </button>
                  <div className="border-t my-1" />
                  <button
                    type="button"
                    onClick={() => {
                      setShowUploadMenu(false);
                      setSwarmPreset(null);
                      setGoalComposerActive(true);
                      inputRef.current?.focus();
                    }}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors flex items-center gap-2"
                  >
                    <Target className="h-4 w-4" />
                    Research Goal
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowUploadMenu(false);
                      setGoalComposerActive(false);
                      setSwarmPreset({ name: "auto", title: "Agent Swarm" });
                      inputRef.current?.focus();
                    }}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors flex items-center gap-2"
                  >
                    <Users className="h-4 w-4" />
                    Agent Swarm
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
              placeholder={
                goalComposerActive
                  ? "Describe the research goal to attach to this session"
                  : "e.g. Create a dual MA crossover strategy for 000001.SZ, backtest 2024"
              }
              className="flex-1 px-4 py-2.5 rounded-xl border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 transition-shadow resize-none max-h-32 overflow-y-auto"
              disabled={status === "streaming"}
            />
            {messages.length > 0 && (
              <button
                type="button"
                onClick={handleExport}
                className="px-3 py-2.5 rounded-xl border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                title="Export chat"
              >
                <Download className="h-4 w-4" />
              </button>
            )}
            {status === "streaming" ? (
              <button
                type="button"
                onClick={handleCancel}
                className="px-4 py-2.5 rounded-xl bg-destructive text-destructive-foreground text-sm font-medium hover:opacity-90 transition-opacity"
                title="Stop generation"
              >
                <Square className="h-4 w-4" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={goalComposerActive ? !input.trim() : (!input.trim() && !attachment)}
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
