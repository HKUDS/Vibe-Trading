import i18n from '@/i18n';
import { memo, useState, useCallback } from "react";
import { User, XCircle, RefreshCw, Copy, Check, ChevronDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { formatTimestamp } from "@/lib/formatters";
import type { AgentMessage } from "@/types/agent";
import { AgentAvatar } from "./AgentAvatar";
import { RunCompleteCard } from "./RunCompleteCard";

const remarkPlugins = [remarkGfm];
const rehypePlugins = [rehypeHighlight];

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [text]);
  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 p-1.5 rounded-md bg-muted/80 hover:bg-muted text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity"
      title={copied ? i18n.t("messageBubble.copied") : i18n.t("messageBubble.copy")}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

function summarizeError(content: string): string {
  const lower = content.toLowerCase();
  if (lower.includes("ollama") || lower.includes("connection refused")) return "The local intelligence model is not currently reachable. Confirm that ollama serve is running and try again.";
  if (lower.includes("qwen2.5") || lower.includes("model") && lower.includes("not found")) return "The configured model qwen2.5:1.5b may not be installed. Pull the model in Ollama and retry.";
  if (lower.includes("auth") || lower.includes("unauthorized") || lower.includes("api key")) return "Enter the API authentication key in Intelligence Settings to access protected endpoints.";
  if (lower.includes("timeout") || lower.includes("timed out")) return "The analysis request timed out before a complete response was returned.";
  if (lower.includes("session")) return "This analysis session could not be loaded or continued.";
  return "TradeCoreFX could not complete this analysis request.";
}

function getRetryHint(content: string): string {
  const lower = content.toLowerCase();
  if (lower.includes("timeout") || lower.includes("timed out")) {
    return i18n.t("messageBubble.timeoutHint");
  }
  if (lower.includes("api") || lower.includes("rate limit") || lower.includes("429") || lower.includes("500") || lower.includes("502") || lower.includes("503")) {
    return i18n.t("messageBubble.apiFailedHint");
  }
  return i18n.t("messageBubble.executionFailedHint");
}

interface Props {
  msg: AgentMessage;
  onRetry?: (msg: AgentMessage) => void;
}

export const MessageBubble = memo(function MessageBubble({ msg, onRetry }: Props) {
  const ts = msg.timestamp ? formatTimestamp(msg.timestamp) : null;

  if (msg.type === "user") {
    return (
      <div className="flex justify-end gap-3 group">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm border bg-primary text-primary-foreground px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap shadow-sm">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] opacity-70">Analysis Request</div>
          {msg.content}
          {ts && <span className="block text-[9px] opacity-50 text-right mt-1">{ts}</span>}
        </div>
        <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center shrink-0 mt-0.5">
          <User className="h-4 w-4 text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (msg.type === "answer") {
    return (
      <div className="flex gap-3 group">
        <AgentAvatar />
        <div className="flex-1 min-w-0 relative">
          <CopyButton text={msg.content} />
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">TradeCoreFX Intelligence</div><div className="rounded-2xl border bg-card p-4 prose prose-sm dark:prose-invert max-w-none leading-relaxed prose-table:border prose-table:border-border/50 prose-th:bg-muted/30 prose-th:px-3 prose-th:py-1.5 prose-td:px-3 prose-td:py-1.5 prose-th:text-left prose-th:text-xs prose-th:font-medium prose-td:text-xs prose-hr:hidden">
            <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>{msg.content}</ReactMarkdown>
          </div>
          {ts && <span className="text-[9px] text-muted-foreground/30 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">{ts}</span>}
        </div>
      </div>
    );
  }

  if (msg.type === "run_complete" && msg.runId) {
    return <RunCompleteCard msg={msg} />;
  }

  if (msg.type === "error") {
    const hint = getRetryHint(msg.content);
    const summary = summarizeError(msg.content);
    const [detailsOpen, setDetailsOpen] = useState(false);
    return (
      <div className="flex gap-3">
        <AgentAvatar />
        <div className="space-y-2">
          <div className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger/5 px-4 py-3">
            <XCircle className="h-4 w-4 text-danger shrink-0 mt-0.5" />
            <div className="min-w-0"><p className="text-sm font-medium text-danger leading-relaxed">{summary}</p><button type="button" onClick={() => setDetailsOpen((open) => !open)} className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" aria-expanded={detailsOpen}><ChevronDown className="h-3 w-3" />Technical details</button>{detailsOpen && <p className="mt-2 whitespace-pre-wrap break-words text-xs text-muted-foreground">{msg.content}</p>}</div>
          </div>
          {onRetry && (
            <button
              onClick={() => onRetry(msg)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-muted-foreground hover:text-foreground hover:bg-muted/80 border border-transparent hover:border-border transition-all"
              title={hint}
            >
              <RefreshCw className="h-3 w-3" />
              <span>{hint}</span>
            </button>
          )}
        </div>
      </div>
    );
  }

  // Fallback: show content for any unhandled message type
  if (msg.content) {
    return (
      <div className="flex gap-3">
        <AgentAvatar />
        <p className="text-sm text-muted-foreground leading-relaxed">{msg.content}</p>
      </div>
    );
  }

  return null;
});
